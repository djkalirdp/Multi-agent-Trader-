"""
Agent Brain v4 — All bugs fixed
  Bug 1:  Black Swan now calls square_off_all() (CRITICAL)
  Bug 4:  Sentiment multiplier (not gate) — 1.0/0.75/0.50/0.25x
  Bug 9:  Conflict Gate moved to Stage 2b (before Multi-AI — saves tokens)
  Bug 11: 9:15-9:30 noise window blocked (effective window 9:30-15:15)
  Bug 15: Stale price check before execution (>60s or >2x drift → ABORT)

v4 loop order:
  Stage 1 — Scan (180 F&O → top 80 → 15 candidates)
  Stage 2 — OSINT + ATR-normalized divergence
  Stage 2b— Conflict Gate (sentiment/sector multipliers, BEARISH_TRAP drop)
  Stage 3 — Regime Detection + Black Swan → EXIT ALL
  Stage 4 — Multi-AI (only Stage-2b passing stocks)
  Stage 5 — Per-stock: Jail/Regime/Correlation/Stale/Kelly/Execute
  Stage 6 — Learn + Memory
"""

import threading
import time
import json
from datetime import datetime, date, time as dtime
from typing import Dict, List, Optional

from modules.config_manager   import ConfigManager
from modules.market_scanner   import MarketScanner
from modules.claude_selector  import ClaudeSelector
from modules.risk_manager     import RiskManager
from modules.order_executor   import OrderExecutor
from modules.memory_manager   import MemoryManager
from modules.multi_ai         import MultiAIOrchestrator
from modules.osint_gatherer   import OSINTGatherer
from modules.regime_detector  import MarketRegimeDetector
from modules.premarket_session import PreMarketSession
from modules.logger          import get_logger

SLIPPAGE_BUFFER = 0.003   # 0.3% — Bug 10


class AgentBrain:
    def __init__(self, socketio=None):
        self.socketio        = socketio
        self.config_mgr      = ConfigManager()
        self.memory          = MemoryManager()
        self._running        = False
        self._thread         = None
        self._cycle_count    = 0
        self.last_scan       = None
        self.last_selections = []
        self.last_regime     = None
        self.active_trades   = {}
        self._session_start  = None
        # Feature 4: after-market + pre-market session
        self.premarket       = PreMarketSession(self.config_mgr, self.memory, socketio=socketio)
        self._flog           = get_logger("agent_brain")
        self.premarket.start_background()

    # ─── START / STOP ──────────────────────────────────────────
    def start(self):
        if self._running:
            return {'success': False, 'message': 'Agent already running'}
        cfg = self.config_mgr.load()
        if not cfg.get('is_configured'):
            return {'success': False, 'message': 'Agent not configured. Go to Settings first.'}
        self._running       = True
        self._session_start = datetime.now()
        self._thread        = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._broadcast('agent_status', {'status': 'RUNNING',
            'message': 'Agent v4 started — Bug16 fixed. Pre/After-market sessions running.'})
        return {'success': True, 'message': 'Agent v4 started'}

    def stop(self):
        self._running = False
        self._end_session()
        self._broadcast('agent_status', {'status': 'STOPPED',
            'message': 'Agent stopped. Session saved to memory.'})
        return {'success': True, 'message': 'Agent stopped'}

    def is_running(self) -> bool:
        return self._running

    # ─── MAIN LOOP ─────────────────────────────────────────────
    def _loop(self):
        while self._running:
            try:
                self._cycle_count += 1
                cfg  = self.config_mgr.load()
                risk = RiskManager(cfg)

                self._log('INFO', f'═══ Cycle #{self._cycle_count} [{datetime.now().strftime("%H:%M:%S")}] ═══')

                # ── PRE-CHECK + BUG 16 HARD EXIT ──────────────
                # Hard exit at 3:10 PM before broker auto-sq-off at 3:20 PM
                if risk.is_hard_exit_time():
                    self._log('ERROR', '⏰ 3:10 PM — HARD EXIT: squaring off all positions before broker auto-sq-off')
                    executor = OrderExecutor(
                        cfg['dhan_client_id'], cfg['dhan_access_token'],
                        cfg.get('trading_mode', 'paper')
                    )
                    sq = executor.square_off_all()
                    self._log('ERROR', f'🚨 Hard exit complete: {sq.get("squared_off",0)} positions closed')
                    self._broadcast('hard_exit', {'message': '3:10 PM hard exit — all intraday positions closed before broker sq-off'})
                    self._broadcast('risk_update', risk.get_summary())
                    self._sleep_interval(cfg)
                    continue

                check = risk.is_trading_allowed()
                if not check['allowed']:
                    self._log('WARN', f'⛔ {check["reason"]}')
                    self._broadcast('risk_update', risk.get_summary())
                    time.sleep(60)
                    continue

                # ── STAGE 1: SCAN ──────────────────────────────
                self._log('INFO', '🔍 [Stage 1] Market scan (180 F&O → top 80 → candidates)...')
                scanner     = MarketScanner(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg)
                scan_result = scanner.scan()
                self.last_scan = scan_result
                candidates     = scan_result.get('candidates', [])

                self._broadcast('scan_update', {
                    'candidates': candidates,
                    'meta':       scan_result.get('scan_meta', {}),
                    'time':       datetime.now().strftime('%H:%M:%S'),
                })
                self._log('SUCCESS',
                    f'✅ Scan: {len(candidates)} candidates from '
                    f'{scan_result["scan_meta"].get("total_fo_universe",0)} F&O universe '
                    f'(scanned top {scan_result["scan_meta"].get("total_scanned",0)})')

                if not candidates:
                    self._log('WARN', '⚠️ No candidates. Waiting...')
                    self._sleep_interval(cfg)
                    continue

                # ── STAGE 2: OSINT ─────────────────────────────
                self._log('INFO', f'🕵️ [Stage 2] OSINT for {min(len(candidates),5)} stocks...')
                osint_gatherer = OSINTGatherer(cfg)
                symbols        = [c['symbol'] for c in candidates[:5]]
                osint_data     = osint_gatherer.gather_batch(symbols, candidates)

                for sym, intel in osint_data.items():
                    self.memory.remember_osint(sym, {
                        'sentiment':       intel.get('sentiment'),
                        'sentiment_score': intel.get('sentiment_score'),
                        'news_summary':    intel.get('summary'),
                    })
                    self._broadcast('osint_update', {
                        'symbol':    sym,
                        'sentiment': intel.get('sentiment'),
                        'score':     intel.get('sentiment_score'),
                        'summary':   intel.get('summary'),
                        'divergence':intel.get('divergence', {}),
                    })

                self._log('SUCCESS', '✅ OSINT done: ' +
                    ' | '.join(f"{s}:{osint_data.get(s,{}).get('sentiment','?')}" for s in symbols))

                # ── STAGE 2b: CONFLICT GATE ────────────────────
                # Bug 9: moved before Multi-AI to save tokens
                # Bug 4: sentiment = size multiplier, not hard gate (except delta>6)
                passed_candidates = []
                for c in candidates:
                    sym     = c['symbol']
                    intel   = osint_data.get(sym, {})
                    div     = intel.get('divergence', {})
                    s_score = float(intel.get('sentiment_score', 5))
                    t_score = float(c.get('tech_score', 5))
                    delta   = abs(t_score - s_score)

                    # Drop on BEARISH_TRAP divergence
                    if div.get('divergence') and div.get('type') == 'BEARISH_TRAP':
                        self._log('WARN', f'🚫 {sym}: BEARISH_TRAP — {div.get("signal","")} → DROP')
                        continue

                    # Extreme conflict → hard skip (Bug 4)
                    if delta > 6:
                        self._log('WARN', f'⚡ {sym}: Extreme conflict delta={delta:.1f} (tech={t_score:.1f}, sentiment={s_score:.1f}) → DROP')
                        continue

                    # Sentiment multiplier: 1.0 / 0.75 / 0.50 / 0.25 (Bug 4)
                    if   s_score >= 7: sent_mult = 1.00
                    elif s_score >= 5: sent_mult = 0.75
                    elif s_score >= 3: sent_mult = 0.50
                    else:              sent_mult = 0.25

                    c['sentiment_score']    = s_score
                    c['sentiment_mult']     = sent_mult
                    c['conflict_delta']     = round(delta, 1)
                    passed_candidates.append(c)

                drop_count = len(candidates) - len(passed_candidates)
                self._log('INFO',
                    f'[Stage 2b] Conflict Gate: {len(passed_candidates)} passed, '
                    f'{drop_count} dropped. Token saving: {drop_count/max(len(candidates),1)*100:.0f}%')

                if not passed_candidates:
                    self._log('WARN', '⚠️ All candidates dropped at Conflict Gate.')
                    self._sleep_interval(cfg)
                    continue

                # ── STAGE 3: REGIME + BLACK SWAN ──────────────
                self._log('INFO', '📊 [Stage 3] Regime detection...')
                detector = MarketRegimeDetector(cfg)
                regime   = detector.detect(passed_candidates)
                self.last_regime = regime
                self._broadcast('regime_update', regime)
                self._log('SUCCESS' if regime['trading_allowed'] else 'WARN',
                    f'🌡️ Regime: {regime["regime"]} ({regime["confidence"]}%) — {regime["description"]}')

                # BLACK SWAN — Bug 1 FIXED: square_off_all() before sleep
                bs_check = risk.check_black_swan(regime)
                if bs_check['activated']:
                    self._log('ERROR', bs_check['message'])
                    self._broadcast('black_swan', bs_check)
                    # BUG 1 FIX: Emergency square off all open positions
                    executor = OrderExecutor(
                        cfg['dhan_client_id'], cfg['dhan_access_token'],
                        cfg.get('trading_mode', 'paper')
                    )
                    sq = executor.square_off_all()
                    self._log('ERROR', f'🚨 Emergency square off: closed={sq.get("squared_off",0)} errors={sq.get("errors",[])}')
                    self._broadcast('risk_update', risk.get_summary())
                    self._sleep_interval(cfg)
                    continue

                if not regime['trading_allowed']:
                    self._log('WARN', f'🚫 Trading blocked: {regime["regime"]}')
                    self._sleep_interval(cfg)
                    continue

                # Losing streak check
                streak_analysis    = risk.analyze_losing_streak()
                dynamic_conviction = cfg.get('conviction_threshold', 7)
                if streak_analysis:
                    self._log('WARN',
                        f'📉 Losing streak: {streak_analysis["streak_count"]} losses '
                        f'(₹{streak_analysis["total_loss"]:,.0f})')
                    self.memory.learn_from_losing_streak(streak_analysis)
                    self._broadcast('streak_alert', streak_analysis)
                    dynamic_conviction += min(streak_analysis['streak_count'], 2)
                    self._log('WARN', f'⬆️ Conviction threshold → {dynamic_conviction}/10 (streak protection)')

                # ── STAGE 4: MULTI-AI DECISION ─────────────────
                # Only passed_candidates go to AI — token saving (Bug 9)
                memory_context = self.memory.get_context_for_prompt()
                regime_context = (
                    f"\nCURRENT REGIME: {regime['regime']} ({regime['confidence']}% confidence)\n"
                    f"Description: {regime['description']}\n"
                    f"RECOMMENDED: {', '.join(regime['recommended_strategies'])}\n"
                    f"AVOID: {', '.join(regime['avoid_strategies'])}\n"
                )
                if streak_analysis:
                    regime_context += f"\nLOSING STREAK: {streak_analysis['analysis_text']}\n"

                self._log('INFO',
                    f'🤖 [Stage 4] Multi-AI [{cfg.get("researcher_model","gemini").upper()} → '
                    f'{cfg.get("decision_model","claude").upper()}] on {len(passed_candidates)} stocks...')

                orchestrator = MultiAIOrchestrator(cfg)
                research     = orchestrator.research_stocks(passed_candidates, osint_data,
                                                             memory_context + regime_context)
                decision     = orchestrator.make_trade_decision(passed_candidates, research,
                                                                 memory_context + regime_context)

                if not decision.get('selections'):
                    self._log('WARN', '⚠️ Multi-AI failed — Claude fallback...')
                    selector = ClaudeSelector(cfg['claude_api_key'], cfg.get('claude_model','claude-opus-4-5'))
                    decision = selector.select_stocks(passed_candidates)

                selections          = decision.get('selections', [])
                self.last_selections= selections
                self._broadcast('selection_update', {
                    'selections':   selections,
                    'market_bias':  decision.get('market_bias', 'NEUTRAL'),
                    'analyst_note': decision.get('analyst_note', ''),
                    'reasoning':    decision.get('reasoning', ''),
                    'regime':       regime['regime'],
                    'time':         datetime.now().strftime('%H:%M:%S'),
                })
                self._log('SUCCESS',
                    f'🎯 {len(selections)} stocks selected | Bias: {decision.get("market_bias","?")} | '
                    f'Regime: {regime["regime"]}')

                # ── STAGE 5: PER-STOCK EXECUTION ───────────────
                selector = ClaudeSelector(cfg['claude_api_key'], cfg.get('claude_model','claude-opus-4-5'))

                for stock in selections:
                    if not self._running: break

                    symbol     = stock.get('symbol', '')
                    conviction = stock.get('conviction_score', 0)
                    self._log('INFO', f'─── {symbol} (conviction {conviction}/10) ───')

                    if symbol in [t['symbol'] for t in self.active_trades.values()]:
                        self._log('WARN', f'⏭ {symbol}: position already open'); continue

                    if conviction < dynamic_conviction:
                        self._log('WARN', f'⏭ {symbol}: conviction {conviction} < {dynamic_conviction}'); continue

                    check2 = risk.is_trading_allowed()
                    if not check2['allowed']:
                        self._log('WARN', f'⛔ {check2["reason"]}'); break

                    # Strategy selection
                    strategy_result = selector.select_strategy(stock)
                    if strategy_result.get('error'):
                        self._log('ERROR', f'❌ Strategy error: {strategy_result["error"]}'); continue

                    strategy_key  = strategy_result.get('strategy_key', '')
                    strategy_name = strategy_result.get('strategy_name', '')
                    stock['strategy_name'] = strategy_name

                    # Jail check (Bug 2: regime-stable 3-loop release)
                    jail_check = risk.is_strategy_jailed(strategy_name, regime['regime'])
                    if jail_check.get('jailed'):
                        self._log('WARN', f'⛓ {symbol}: "{strategy_name}" JAILED — {jail_check.get("reason","")}')
                        self._broadcast('jail_alert', {'symbol': symbol, 'strategy': strategy_name,
                                                        'reason': jail_check.get('reason','')})
                        continue

                    # Regime fit
                    regime_fit = detector.filter_strategies_for_regime(strategy_key, regime['regime'])
                    if regime_fit['fit'] == 'AVOID':
                        self._log('WARN', f'🚫 {symbol}: "{strategy_name}" AVOID for {regime["regime"]}'); continue

                    adjusted_conviction = conviction + regime_fit['score_boost']
                    self._log('SUCCESS', f'📐 {symbol}: {strategy_name} | Fit: {regime_fit["fit"]}')

                    # Correlation check
                    open_syms = [t['symbol'] for t in self.active_trades.values()]
                    corr      = risk.check_correlation_risk(symbol, open_syms)
                    if not corr['allowed']:
                        self._log('WARN', f'🔗 {symbol}: {corr["reason"]}'); continue

                    # Trade parameters
                    capital      = cfg.get('max_capital_per_trade', 10000)
                    trade_params = selector.generate_trade_params(stock, strategy_result, capital)
                    if trade_params.get('error'):
                        self._log('ERROR', f'❌ Trade params: {trade_params["error"]}'); continue

                    # Bug 15: Stale price check
                    stale_ok, stale_reason = self._is_price_still_valid(
                        stock, trade_params.get('entry_price', 0)
                    )
                    if not stale_ok:
                        self._log('WARN', f'⏱ {symbol}: {stale_reason} — ABORT'); continue

                    # Kelly × Sentiment × Sector × Regime multipliers
                    c_data       = next((c for c in passed_candidates if c['symbol'] == symbol), {})
                    sent_mult    = c_data.get('sentiment_mult', 1.0)
                    sector_mult  = c_data.get('sector_multiplier', 1.0)
                    combined_mult = sent_mult * sector_mult * regime.get('risk_multiplier', 1.0)

                    risk_size = risk.calculate_position_size(
                        trade_params.get('entry_price', 0),
                        trade_params.get('stop_loss', 0),
                        strategy_name=strategy_name,
                        regime_multiplier=combined_mult,
                    )
                    if risk_size.get('error'):
                        self._log('WARN', f'⚠️ {symbol}: {risk_size["error"]}'); continue

                    trade_params.update({
                        'quantity':          risk_size['quantity'],
                        'conviction_score':  adjusted_conviction,
                        'symbol':            symbol,
                        'strategy_name':     strategy_name,
                        'strategy':          strategy_name,
                    })

                    self._log('INFO',
                        f'💰 {symbol} | Kelly {risk_size.get("kelly_fraction","?")}% | '
                        f'Sent×{sent_mult} Sect×{sector_mult} Reg×{regime.get("risk_multiplier",1)} | '
                        f'Entry ₹{trade_params.get("entry_price")} SL ₹{trade_params.get("stop_loss")} '
                        f'T1 ₹{trade_params.get("target_1")} Qty:{trade_params.get("quantity")} '
                        f'MaxLoss:₹{risk_size.get("max_loss","?")}')

                    executor     = OrderExecutor(
                        cfg['dhan_client_id'], cfg['dhan_access_token'],
                        cfg.get('trading_mode', 'paper')
                    )
                    order_result = executor.place_bracket_order(trade_params)

                    if order_result['success']:
                        trade_id = risk.log_trade_entry(trade_params)
                        self.active_trades[trade_id] = {
                            'symbol': symbol, 'order_id': order_result.get('order_id',''),
                            'trade_id': trade_id, 'params': trade_params,
                            'strategy': strategy_result, 'regime': regime['regime'],
                        }
                        self.memory.remember_trade({
                            **trade_params,
                            'side':     trade_params.get('position_side', 'BUY'),
                            'strategy': strategy_name,
                        })
                        self._log('TRADE',
                            f'✅ ORDER [{cfg.get("trading_mode","paper").upper()}] {order_result.get("message","")}')
                        self._broadcast('trade_placed', {
                            'trade_id':     trade_id,
                            'order_result': order_result,
                            'trade_params': trade_params,
                            'strategy':     strategy_result,
                            'regime':       regime['regime'],
                            'kelly_info':   risk_size,
                            'multipliers':  {'sentiment': sent_mult, 'sector': sector_mult,
                                             'regime': regime.get('risk_multiplier',1), 'combined': combined_mult},
                            'time':         datetime.now().strftime('%H:%M:%S'),
                        })
                    else:
                        self._log('ERROR', f'❌ Order failed {symbol}: {order_result.get("message","")}')

                # ── STAGE 6: LEARN ─────────────────────────────
                summary = risk.get_summary()
                self._broadcast('risk_update', summary)
                if self._cycle_count % 5 == 0:
                    self.memory.auto_learn_from_trades()
                    self._log('SUCCESS', '🧠 Auto-learned from patterns')
                self.memory.export_markdown()

                jailed = summary.get('jailed_strategies', [])
                if jailed:
                    self._log('WARN', f'⛓ Jailed: {", ".join(jailed)}')

                self._log('INFO',
                    f'💹 P&L: ₹{summary["daily_pnl"]:+,.0f} | WR: {summary["win_rate"]}% | '
                    f'Streak: {summary["consecutive_losses"]} | Regime: {regime["regime"]}')

            except Exception as e:
                import traceback
                self._log('ERROR', f'💥 Loop error: {e}')
                self._log('ERROR', traceback.format_exc()[:400])

            self._sleep_interval(self.config_mgr.load())

    # ─── BUG 15: STALE PRICE CHECK ─────────────────────────────
    def _is_price_still_valid(self, stock: Dict, proposed_entry: float) -> tuple:
        """
        Check if scan data is still fresh and price hasn't drifted too much.
        Returns (valid: bool, reason: str)
        """
        scan_ts_str = stock.get('scan_timestamp', '')
        if not scan_ts_str:
            return True, 'No timestamp — allowing'

        try:
            scan_ts  = datetime.fromisoformat(scan_ts_str)
            age_secs = (datetime.now() - scan_ts).total_seconds()
            if age_secs > 60:
                return False, f'Scan data {age_secs:.0f}s old (>60s limit)'
        except Exception:
            pass

        scan_price = stock.get('scan_price', 0)
        if scan_price > 0 and proposed_entry > 0:
            drift = abs(proposed_entry - scan_price) / scan_price
            if drift > SLIPPAGE_BUFFER * 2:
                return False, f'Price drifted {drift*100:.2f}% from scan (>{SLIPPAGE_BUFFER*200:.1f}% limit)'

        return True, 'Price valid'

    # ─── SESSION END ───────────────────────────────────────────
    def _end_session(self):
        try:
            cfg     = self.config_mgr.load()
            risk    = RiskManager(cfg)
            summary = risk.get_summary()
            self.memory.remember_session({
                **summary,
                'market_bias': self.last_regime['regime'] if self.last_regime else 'UNKNOWN',
                'notes': (f'Cycles: {self._cycle_count} | '
                          f'Regime: {self.last_regime["regime"] if self.last_regime else "?"} | '
                          f'Models: {cfg.get("researcher_model","?")} → {cfg.get("decision_model","?")}'),
            })
            self.memory.auto_learn_from_trades()
            self.memory.export_markdown()
        except Exception:
            pass

    # ─── HELPERS ───────────────────────────────────────────────
    def _log(self, level: str, message: str):
        self._broadcast('agent_log', {
            'level':   level,
            'message': message,
            'time':    datetime.now().strftime('%H:%M:%S'),
        })
        # Also write to file log
        _lvl = {'INFO': self._flog.info, 'SUCCESS': self._flog.info,
                'WARN': self._flog.warning, 'ERROR': self._flog.error,
                'TRADE': self._flog.info}.get(level, self._flog.debug)
        _lvl(message)

    def _sleep_interval(self, cfg: Dict):
        mins = int(cfg.get('scan_interval_min', 5))
        self._log('INFO', f'⏳ Next cycle in {mins} min...')
        for _ in range(mins * 60):
            if not self._running: break
            time.sleep(1)

    def _broadcast(self, event: str, data: Dict):
        if self.socketio:
            try: self.socketio.emit(event, data)
            except Exception: pass

    def get_state(self) -> Dict:
        cfg  = self.config_mgr.load()
        risk = RiskManager(cfg)
        return {
            'running':        self._running,
            'cycle_count':    self._cycle_count,
            'trading_mode':   cfg.get('trading_mode', 'paper'),
            'last_scan_time': self.last_scan['timestamp'] if self.last_scan else None,
            'candidates':     self.last_scan['candidates'] if self.last_scan else [],
            'selections':     self.last_selections,
            'active_trades':  list(self.active_trades.values()),
            'risk_summary':   risk.get_summary(),
            'regime':         self.last_regime,
            'memory_summary': {
                'lessons_count':  len(self.memory.get_lessons()),
                'sessions_count': len(self.memory.get_sessions()),
            },
        }

    def get_memory(self) -> Dict:
        return {
            'sessions':       self.memory.get_sessions(10),
            'lessons':        self.memory.get_lessons(),
            'strategy_stats': self.memory.get_strategy_stats(),
        }

    def release_strategy(self, strategy_name: str):
        cfg  = self.config_mgr.load()
        risk = RiskManager(cfg)
        risk.release_strategy(strategy_name)
        return {'success': True, 'message': f'Strategy "{strategy_name}" released from jail'}
