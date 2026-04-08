"""
Agent Brain v2 — Multi-Agent Autonomous Trading Loop
New features:
  1. Memory — persistent memory across sessions
  2. Multi-AI — Gemini (research) + Claude (decision) pipeline
  3. OSINT — news, sentiment, fundamentals gathering
  4. Learn — auto-learns from past trades each session

Loop: Scan → OSINT → Multi-AI Research → Multi-AI Decision → Risk → Execute → Remember
"""

import threading
import time
import json
from datetime import datetime, date
from typing import Dict, Optional

from modules.config_manager  import ConfigManager
from modules.market_scanner  import MarketScanner
from modules.claude_selector import ClaudeSelector
from modules.risk_manager    import RiskManager
from modules.order_executor  import OrderExecutor
from modules.memory_manager  import MemoryManager
from modules.multi_ai        import MultiAIOrchestrator
from modules.osint_gatherer  import OSINTGatherer


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
        self.active_trades   = {}
        self._session_start  = None

    # ─── START / STOP ──────────────────────────────────────────
    def start(self):
        if self._running:
            return {'success': False, 'message': 'Agent already running'}
        cfg = self.config_mgr.load()
        if not cfg.get('is_configured'):
            return {'success': False, 'message': 'Agent not configured. Go to Settings first.'}

        self._running     = True
        self._session_start = datetime.now()
        self._thread      = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._broadcast('agent_status', {'status': 'RUNNING', 'message': 'Agent v2 started — Multi-AI + Memory + OSINT active'})
        return {'success': True, 'message': 'Agent v2 started'}

    def stop(self):
        self._running = False
        self._end_session()
        self._broadcast('agent_status', {'status': 'STOPPED', 'message': 'Agent stopped. Session saved to memory.'})
        return {'success': True, 'message': 'Agent stopped'}

    def is_running(self) -> bool:
        return self._running

    # ─── MAIN LOOP ─────────────────────────────────────────────
    def _loop(self):
        while self._running:
            try:
                self._cycle_count += 1
                cfg = self.config_mgr.load()

                self._log('INFO', f'═══ Cycle #{self._cycle_count} [{datetime.now().strftime("%H:%M:%S")}] ═══')
                self._log('INFO', f'🧠 Mode: {cfg.get("trading_mode","paper").upper()} | '
                                  f'AI: {cfg.get("researcher_model","gemini").upper()} → {cfg.get("decision_model","claude").upper()}')

                risk  = RiskManager(cfg)
                check = risk.is_trading_allowed()
                if not check['allowed']:
                    self._log('WARN', f'⛔ {check["reason"]}')
                    self._broadcast('risk_update', risk.get_summary())
                    time.sleep(60)
                    continue

                # ── STEP 1: MARKET SCAN ───────────────────────
                self._log('INFO', '🔍 Step 1/6 — Running market scan...')
                scanner     = MarketScanner(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg)
                scan_result = scanner.scan()
                self.last_scan  = scan_result
                candidates      = scan_result.get('candidates', [])

                self._broadcast('scan_update', {
                    'candidates': candidates,
                    'meta':       scan_result.get('scan_meta', {}),
                    'time':       datetime.now().strftime("%H:%M:%S"),
                })
                self._log('SUCCESS', f'✅ Scan: {len(candidates)} candidates '
                                     f'(from {scan_result["scan_meta"].get("total_scanned",0)} stocks)')

                if not candidates:
                    self._log('WARN', '⚠️ No candidates passed filters. Waiting...')
                    self._sleep_interval(cfg)
                    continue

                # ── STEP 2: OSINT INTELLIGENCE ─────────────────
                self._log('INFO', f'🕵️ Step 2/6 — Gathering OSINT for {len(candidates)} stocks...')
                osint_gatherer = OSINTGatherer(cfg)
                symbols        = [c['symbol'] for c in candidates[:5]]  # top 5 only
                osint_data     = {}

                for sym in symbols:
                    self._log('INFO', f'  📰 OSINT: {sym}...')
                    intel = osint_gatherer.gather(sym)
                    osint_data[sym] = intel
                    self.memory.remember_osint(sym, {
                        'sentiment':     intel.get('sentiment'),
                        'sentiment_score': intel.get('sentiment_score'),
                        'news_summary':  intel.get('summary'),
                        'news_count':    len(intel.get('news', [])),
                    })
                    self._broadcast('osint_update', {
                        'symbol':    sym,
                        'sentiment': intel.get('sentiment'),
                        'score':     intel.get('sentiment_score'),
                        'summary':   intel.get('summary'),
                        'news':      intel.get('news', [])[:3],
                    })

                self._log('SUCCESS', f'✅ OSINT gathered. Sentiment: ' +
                    ', '.join([f"{s}: {osint_data[s].get('sentiment','?')}" for s in symbols]))

                # ── STEP 3: MULTI-AI RESEARCH (Agent 1) ────────
                self._log('INFO', '🤖 Step 3/6 — Agent 1 (Researcher) analyzing...')
                orchestrator   = MultiAIOrchestrator(cfg)
                memory_context = self.memory.get_context_for_prompt()
                research       = orchestrator.research_stocks(candidates, osint_data, memory_context)

                if 'error' in research and not research.get('research'):
                    self._log('WARN', f'⚠️ Research agent error: {research["error"]}. Falling back to direct Claude...')
                    research = {'research': {}, 'market_overview': 'Research unavailable'}
                else:
                    researcher_name = research.get('researcher_used', orchestrator.get_researcher().name if orchestrator.get_researcher() else '?')
                    self._log('SUCCESS', f'✅ Research complete [{researcher_name.upper()}]: {research.get("market_overview","")}')

                self._broadcast('research_update', {
                    'research':        research.get('research', {}),
                    'market_overview': research.get('market_overview', ''),
                    'sector_alerts':   research.get('sector_alerts', []),
                    'time':            datetime.now().strftime("%H:%M:%S"),
                })

                # ── STEP 4: MULTI-AI DECISION (Agent 2) ────────
                self._log('INFO', '🧠 Step 4/6 — Agent 2 (Decision Maker) reasoning...')
                decision = orchestrator.make_trade_decision(candidates, research, memory_context)

                if 'error' in decision and not decision.get('selections'):
                    # Fallback to original Claude selector
                    self._log('WARN', f'⚠️ Decision agent failed. Using fallback Claude selector...')
                    selector        = ClaudeSelector(cfg['claude_api_key'], cfg.get('claude_model','claude-opus-4-5'))
                    fallback_result = selector.select_stocks(candidates)
                    decision        = fallback_result

                selections = decision.get('selections', [])
                self.last_selections = selections
                decision_model  = decision.get('decision_model_used', 'claude')
                research_model  = decision.get('research_model_used', 'gemini')

                self._broadcast('selection_update', {
                    'selections':    selections,
                    'market_bias':   decision.get('market_bias', 'NEUTRAL'),
                    'analyst_note':  decision.get('analyst_note', ''),
                    'reasoning':     decision.get('reasoning', ''),
                    'models_used':   f'{research_model.upper()} → {decision_model.upper()}',
                    'time':          datetime.now().strftime("%H:%M:%S"),
                })
                self._log('SUCCESS', f'🎯 [{research_model.upper()} → {decision_model.upper()}] '
                                     f'{len(selections)} stocks selected. '
                                     f'Bias: {decision.get("market_bias","?")}')

                # ── STEP 5: EXECUTE EACH SELECTION ─────────────
                min_conviction = cfg.get('conviction_threshold', 7)
                selector       = ClaudeSelector(cfg['claude_api_key'], cfg.get('claude_model','claude-opus-4-5'))

                for stock in selections:
                    if not self._running:
                        break

                    symbol     = stock.get('symbol', '')
                    conviction = stock.get('conviction_score', 0)

                    if symbol in [t['symbol'] for t in self.active_trades.values()]:
                        self._log('WARN', f'⏭️ {symbol}: position already open')
                        continue

                    if conviction < min_conviction:
                        self._log('WARN', f'⏭️ {symbol}: conviction {conviction}/10 < threshold {min_conviction}')
                        continue

                    check2 = risk.is_trading_allowed()
                    if not check2['allowed']:
                        self._log('WARN', f'⛔ {check2["reason"]}')
                        break

                    self._log('INFO', f'📊 Step 5/6 — {symbol} (conviction {conviction}/10) → strategy selection...')

                    # Strategy selection (always Claude for precision)
                    strategy_result = selector.select_strategy(stock)
                    if strategy_result.get('error'):
                        self._log('ERROR', f'❌ Strategy error {symbol}: {strategy_result["error"]}')
                        continue

                    stock['strategy_name'] = strategy_result.get('strategy_name', '')
                    self._log('SUCCESS', f'📐 {symbol}: {strategy_result.get("strategy_name","")}')
                    self._broadcast('strategy_update', {
                        'symbol':   symbol,
                        'strategy': strategy_result,
                        'time':     datetime.now().strftime("%H:%M:%S"),
                    })

                    # Trade parameters
                    capital      = cfg.get('max_capital_per_trade', 10000)
                    trade_params = selector.generate_trade_params(stock, strategy_result, capital)
                    if trade_params.get('error'):
                        self._log('ERROR', f'❌ Trade params error: {trade_params["error"]}')
                        continue

                    # Risk size validation
                    risk_size = risk.calculate_position_size(
                        trade_params.get('entry_price', 0),
                        trade_params.get('stop_loss', 0)
                    )
                    if risk_size.get('error'):
                        self._log('WARN', f'⚠️ {symbol}: {risk_size["error"]}')
                        continue

                    trade_params.update({
                        'quantity':        risk_size['quantity'],
                        'conviction_score': conviction,
                        'symbol':          symbol,
                        'strategy':        stock.get('strategy_name', ''),
                    })

                    self._log('INFO',
                        f'💰 {symbol}: Entry ₹{trade_params.get("entry_price")} | '
                        f'SL ₹{trade_params.get("stop_loss")} | '
                        f'T1 ₹{trade_params.get("target_1")} | '
                        f'Qty: {trade_params.get("quantity")} | '
                        f'Max loss: ₹{risk_size.get("max_loss","?")}')

                    # Execute
                    executor     = OrderExecutor(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg.get('trading_mode','paper'))
                    order_result = executor.place_bracket_order(trade_params)

                    if order_result['success']:
                        trade_id = risk.log_trade_entry(trade_params)
                        self.active_trades[trade_id] = {
                            'symbol':   symbol,
                            'order_id': order_result.get('order_id',''),
                            'trade_id': trade_id,
                            'params':   trade_params,
                            'strategy': strategy_result,
                        }
                        # Save to memory immediately
                        self.memory.remember_trade({
                            **trade_params,
                            'side':     trade_params.get('position_side', 'BUY'),
                            'strategy': stock.get('strategy_name', ''),
                        })
                        self._log('TRADE', f'✅ ORDER [{cfg.get("trading_mode","paper").upper()}] — {order_result.get("message","")}')
                        self._broadcast('trade_placed', {
                            'trade_id':    trade_id,
                            'order_result':order_result,
                            'trade_params':trade_params,
                            'strategy':    strategy_result,
                            'time':        datetime.now().strftime("%H:%M:%S"),
                        })
                    else:
                        self._log('ERROR', f'❌ Order failed {symbol}: {order_result.get("message","")}')

                # ── STEP 6: LEARN + UPDATE MEMORY ──────────────
                self._log('INFO', '📚 Step 6/6 — Updating memory & learning...')
                summary = risk.get_summary()
                self._broadcast('risk_update', summary)

                # Auto-learn patterns every 5 cycles
                if self._cycle_count % 5 == 0:
                    self.memory.auto_learn_from_trades()
                    self._log('SUCCESS', '🧠 Memory updated — auto-learned from recent patterns')

                self.memory.export_markdown()

                self._log('INFO',
                    f'💹 P&L: ₹{summary["daily_pnl"]:+,.0f} | '
                    f'Trades: {summary["daily_trades"]} | '
                    f'WinRate: {summary["win_rate"]}% | '
                    f'Open: {summary["open_positions"]}')

            except Exception as e:
                self._log('ERROR', f'💥 Loop error: {str(e)}')
                import traceback
                self._log('ERROR', traceback.format_exc()[:300])

            self._sleep_interval(self.config_mgr.load())

    # ─── SESSION END ──────────────────────────────────────────
    def _end_session(self):
        """Save session summary to memory when agent stops."""
        try:
            cfg     = self.config_mgr.load()
            risk    = RiskManager(cfg)
            summary = risk.get_summary()
            self.memory.remember_session({
                **summary,
                'notes': f'Session ran {self._cycle_count} cycles. '
                         f'Models: {cfg.get("researcher_model","?")} → {cfg.get("decision_model","?")}',
            })
            self.memory.auto_learn_from_trades()
            self.memory.export_markdown()
        except Exception:
            pass

    # ─── HELPERS ──────────────────────────────────────────────
    def _log(self, level: str, message: str):
        self._broadcast('agent_log', {
            'level':   level,
            'message': message,
            'time':    datetime.now().strftime("%H:%M:%S"),
        })

    def _sleep_interval(self, cfg: Dict):
        mins = int(cfg.get('scan_interval_min', 5))
        self._log('INFO', f'⏳ Next cycle in {mins} min...')
        for _ in range(mins * 60):
            if not self._running:
                break
            time.sleep(1)

    def _broadcast(self, event: str, data: Dict):
        if self.socketio:
            try:
                self.socketio.emit(event, data)
            except Exception:
                pass

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
            'memory_summary': {
                'total_trades':   len(self.memory.get_sessions()),
                'lessons_count':  len(self.memory.get_lessons()),
                'sessions_count': len(self.memory.get_sessions()),
            },
        }

    def get_memory(self) -> Dict:
        return {
            'sessions':       self.memory.get_sessions(10),
            'lessons':        self.memory.get_lessons(),
            'strategy_stats': self.memory.get_strategy_stats(),
            'full':           self.memory.get_full_memory(),
        }
