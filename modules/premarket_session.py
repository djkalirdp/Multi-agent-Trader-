"""
Feature 4 — After-Market + Pre-Market Session Manager

After-Market  (3:30 PM – 9:00 PM):
  - No time pressure → use Gemini Pro for deep OSINT
  - Scan all 180 F&O for next day candidates
  - Score each with fundamental + technical + news context
  - Save watchlist_tomorrow.json

Pre-Market    (8:45 AM – 9:15 AM):
  - Load yesterday's watchlist
  - Check overnight news (US markets, SGX Nifty, Asian indices)
  - Rescore top 5 candidates
  - Warm up agent — market open pe reaction time = near zero

Both sessions run as separate background threads.
Market session loop untouched.
"""

import json
import os
import threading
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

WATCHLIST_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'watchlist_tomorrow.json')
PREMARKET_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'premarket_brief.json')


class PreMarketSession:
    """
    After-market + Pre-market background worker.
    Runs independently of the main trading loop.
    """

    def __init__(self, config_mgr, memory, socketio=None):
        self.config_mgr = config_mgr
        self.memory     = memory
        self.socketio   = socketio
        self._thread    = None
        self._running   = False
        os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)

    # ─── PUBLIC ───────────────────────────────────────────────

    def start_background(self):
        """Start the after/pre-market monitor thread."""
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop_background(self):
        self._running = False

    def get_todays_watchlist(self) -> Dict:
        """Load today's pre-computed watchlist (used by market scanner at 9:30 AM)."""
        try:
            if os.path.exists(WATCHLIST_PATH):
                with open(WATCHLIST_PATH) as f:
                    wl = json.load(f)
                # Only valid if generated today or yesterday evening
                gen_date = wl.get('generated_date', '')
                today    = date.today().isoformat()
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                if gen_date in (today, yesterday):
                    return wl
        except Exception:
            pass
        return {}

    def get_premarket_brief(self) -> Dict:
        """Load this morning's pre-market brief."""
        try:
            if os.path.exists(PREMARKET_PATH):
                with open(PREMARKET_PATH) as f:
                    brief = json.load(f)
                if brief.get('date') == date.today().isoformat():
                    return brief
        except Exception:
            pass
        return {}

    # ─── MONITOR LOOP ─────────────────────────────────────────

    def _monitor_loop(self):
        """
        Checks current time every minute.
        Triggers after-market or pre-market job at the right window.
        """
        after_market_done  = False
        pre_market_done    = False
        last_check_date    = None

        while self._running:
            try:
                now        = datetime.now()
                today_str  = date.today().isoformat()
                hour, minute = now.hour, now.minute

                # Reset daily flags at midnight
                if last_check_date != today_str:
                    after_market_done = False
                    pre_market_done   = False
                    last_check_date   = today_str

                # After-market window: 3:30 PM – 9:00 PM
                if (15, 30) <= (hour, minute) <= (21, 0) and not after_market_done:
                    self._log('INFO', '🌙 After-market session starting...')
                    self._run_after_market()
                    after_market_done = True
                    self._log('SUCCESS', '✅ After-market complete — watchlist_tomorrow.json saved')

                # Pre-market window: 8:45 AM – 9:15 AM
                elif (8, 45) <= (hour, minute) <= (9, 15) and not pre_market_done:
                    self._log('INFO', '🌅 Pre-market session starting...')
                    self._run_pre_market()
                    pre_market_done = True
                    self._log('SUCCESS', '✅ Pre-market brief ready — agent prepared for open')

            except Exception as e:
                self._log('ERROR', f'PreMarket loop error: {e}')

            time.sleep(60)   # check every minute

    # ─── AFTER-MARKET SESSION ─────────────────────────────────

    def _run_after_market(self):
        """
        Deep analysis after market close.
        Uses Gemini Pro (no time pressure).
        Builds watchlist_tomorrow.json.
        """
        cfg = self.config_mgr.load()

        self._broadcast('premarket_update', {
            'session': 'after_market',
            'status':  'RUNNING',
            'message': 'After-market deep scan started — building tomorrow\'s watchlist...',
            'time':    datetime.now().strftime('%H:%M:%S'),
        })

        try:
            from modules.market_scanner import MarketScanner, NSE_FO_UNIVERSE
            from modules.osint_gatherer import OSINTGatherer

            # Quick quote scan — use full universe
            scanner     = MarketScanner(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg)
            scan_result = scanner.scan()
            candidates  = scan_result.get('candidates', [])

            if not candidates:
                self._log('WARN', 'After-market: no candidates from scan')
                return

            # Deep OSINT for all candidates — use Pro model (time = no constraint)
            osint = OSINTGatherer(cfg)
            self._log('INFO', f'After-market: deep OSINT for {len(candidates)} candidates (Gemini Pro)...')

            # Override: use Pro for all in after-market
            osint_data = {}
            for i, c in enumerate(candidates):
                try:
                    intel = osint.gather(c['symbol'], atr=c.get('atr', 0), use_pro_model=True)
                    osint_data[c['symbol']] = intel
                    time.sleep(2.0)   # generous delay — no hurry
                    self._log('INFO', f'  [{i+1}/{len(candidates)}] {c["symbol"]}: {intel.get("sentiment","?")} ({intel.get("sentiment_score",5)}/10)')
                except Exception as e:
                    osint_data[c['symbol']] = {'sentiment': 'NEUTRAL', 'sentiment_score': 5, 'error': str(e)}

            # Build scored watchlist
            watchlist = self._build_watchlist(candidates, osint_data)

            # Enrich with memory context
            for item in watchlist:
                sym         = item['symbol']
                sym_history = self.memory.get_symbol_history(sym)
                if sym_history:
                    wins  = sum(1 for t in sym_history if (t.get('pnl') or 0) > 0)
                    total = len(sym_history)
                    item['historical_wr']   = round(wins/total*100, 1) if total > 0 else None
                    item['historical_trades'] = total

            # Save to disk
            payload = {
                'generated_date':    date.today().isoformat(),
                'generated_time':    datetime.now().strftime('%H:%M:%S'),
                'session':           'after_market',
                'watchlist':         watchlist,
                'scan_meta':         scan_result.get('scan_meta', {}),
                'total_candidates':  len(candidates),
            }
            with open(WATCHLIST_PATH, 'w') as f:
                json.dump(payload, f, indent=2)

            self._broadcast('premarket_update', {
                'session':   'after_market',
                'status':    'COMPLETE',
                'watchlist': watchlist[:10],
                'message':   f'Watchlist ready: {len(watchlist)} stocks scored for tomorrow',
                'time':      datetime.now().strftime('%H:%M:%S'),
            })

            # Save to memory
            self.memory.add_lesson(
                f"After-market {date.today()}: {len(watchlist)} candidates. "
                f"Top pick: {watchlist[0]['symbol']} (score {watchlist[0]['composite_score']:.1f}) "
                f"if available.",
                category='after_market'
            )

        except Exception as e:
            self._log('ERROR', f'After-market session error: {e}')

    def _build_watchlist(self, candidates: List[Dict],
                          osint_data: Dict) -> List[Dict]:
        """
        Score each candidate with composite score:
        tech_score(40%) + sentiment_score(30%) + historical_wr(30%)
        """
        scored = []
        for c in candidates:
            sym    = c['symbol']
            intel  = osint_data.get(sym, {})
            s_score = float(intel.get('sentiment_score', 5))
            t_score = float(c.get('tech_score', 5))

            # Composite: weighted average
            composite = (t_score * 0.40 + s_score * 0.30 + 5.0 * 0.30)

            # Divergence penalty
            div = intel.get('divergence', {})
            if div.get('type') == 'BEARISH_TRAP':
                composite -= 1.5
            elif div.get('type') == 'BULLISH_HIDDEN':
                composite += 0.5

            scored.append({
                'symbol':          sym,
                'tech_score':      round(t_score, 2),
                'sentiment_score': round(s_score, 2),
                'sentiment':       intel.get('sentiment', 'NEUTRAL'),
                'composite_score': round(composite, 2),
                'sector':          c.get('sector', 'unknown'),
                'atr':             c.get('atr', 0),
                'gap_pct':         c.get('gap_pct', 0),
                'rvol':            c.get('rvol', 0),
                'news_summary':    intel.get('summary', ''),
                'divergence':      div,
                'watch_reason':    f"Tech:{t_score:.1f} | Sent:{s_score:.1f} | {intel.get('sentiment','?')}",
            })

        scored.sort(key=lambda x: x['composite_score'], reverse=True)
        return scored

    # ─── PRE-MARKET SESSION ───────────────────────────────────

    def _run_pre_market(self):
        """
        Pre-market brief: 8:45 AM – 9:15 AM
        - Load yesterday's watchlist
        - Check overnight news + SGX Nifty
        - Rescore top 5
        - Save premarket_brief.json
        """
        cfg = self.config_mgr.load()

        self._broadcast('premarket_update', {
            'session': 'pre_market',
            'status':  'RUNNING',
            'message': 'Pre-market session — loading watchlist and checking overnight news...',
            'time':    datetime.now().strftime('%H:%M:%S'),
        })

        try:
            # Load yesterday's watchlist
            watchlist = self.get_todays_watchlist()
            top5      = watchlist.get('watchlist', [])[:5]

            if not top5:
                self._log('WARN', 'Pre-market: no watchlist found. Run after-market session first.')
                return

            # Overnight OSINT check for top 5
            from modules.osint_gatherer import OSINTGatherer
            osint       = OSINTGatherer(cfg)
            global_sig  = osint._fetch_global_signals()

            # Check SGX Nifty direction
            sgx    = global_sig.get('SGX', global_sig.get('NIFTY', {}))
            sgx_pct = sgx.get('change_pct', 0) if sgx else 0
            market_bias = 'BULLISH' if sgx_pct > 0.3 else 'BEARISH' if sgx_pct < -0.3 else 'NEUTRAL'

            self._log('INFO', f'Pre-market: SGX/Nifty overnight: {sgx_pct:+.2f}% → bias {market_bias}')

            # Quick overnight news for top 5
            rescored = []
            for item in top5:
                try:
                    intel = osint.gather(item['symbol'], atr=item.get('atr', 0), use_pro_model=False)
                    time.sleep(1.5)

                    # Adjust score with overnight news
                    new_score = (item['composite_score'] * 0.6 + float(intel.get('sentiment_score', 5)) * 0.4)
                    if market_bias == 'BEARISH':
                        new_score -= 0.5
                    elif market_bias == 'BULLISH':
                        new_score += 0.3

                    rescored.append({
                        **item,
                        'overnight_sentiment':   intel.get('sentiment', 'NEUTRAL'),
                        'overnight_news':        intel.get('summary', ''),
                        'rescored_composite':    round(new_score, 2),
                        'premarket_confidence':  'HIGH' if new_score >= 7 else 'MED' if new_score >= 5 else 'LOW',
                    })
                    self._log('INFO', f'  Pre-market: {item["symbol"]} → score {new_score:.1f} | {intel.get("sentiment","?")}')
                except Exception as e:
                    rescored.append({**item, 'error': str(e)})

            rescored.sort(key=lambda x: x.get('rescored_composite', 0), reverse=True)

            brief = {
                'date':             date.today().isoformat(),
                'generated_time':   datetime.now().strftime('%H:%M:%S'),
                'session':          'pre_market',
                'market_bias':      market_bias,
                'sgx_change_pct':   sgx_pct,
                'global_signals':   global_sig,
                'top5':             rescored,
                'ready_to_trade':   [s['symbol'] for s in rescored if s.get('premarket_confidence') == 'HIGH'],
                'memory_context':   self.memory.get_context_for_prompt()[:500],
            }

            with open(PREMARKET_PATH, 'w') as f:
                json.dump(brief, f, indent=2)

            self._broadcast('premarket_update', {
                'session':       'pre_market',
                'status':        'COMPLETE',
                'market_bias':   market_bias,
                'sgx_pct':       sgx_pct,
                'top5':          rescored,
                'ready_to_trade':brief['ready_to_trade'],
                'message':       f'Pre-market ready. Bias: {market_bias}. Hot stocks: {", ".join(brief["ready_to_trade"][:3])}',
                'time':          datetime.now().strftime('%H:%M:%S'),
            })

        except Exception as e:
            self._log('ERROR', f'Pre-market session error: {e}')

    # ─── HELPERS ──────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        self._broadcast('agent_log', {
            'level':   level,
            'message': f'[PRE/POST] {msg}',
            'time':    datetime.now().strftime('%H:%M:%S'),
        })

    def _broadcast(self, event: str, data: Dict):
        if self.socketio:
            try: self.socketio.emit(event, data)
            except Exception: pass
