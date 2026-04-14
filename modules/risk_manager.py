"""
Risk Manager v2 — Professional-grade risk controls
New in v2:
  1. Kelly Criterion position sizing (replaces flat 1% rule)
  2. Correlation matrix check (cluster risk prevention)
  3. Black Swan circuit breaker (VIX + regime triggered)
  4. Strategy jail system (auto-ban losing strategies)
  5. Losing streak analysis trigger
"""

import json
import math
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple


TRADES_PATH  = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades.json')
PNL_PATH     = os.path.join(os.path.dirname(__file__), '..', 'data', 'pnl.json')
JAIL_PATH    = os.path.join(os.path.dirname(__file__), '..', 'data', 'strategy_jail.json')

# Sector map for correlation check
SECTOR_MAP = {
    'RELIANCE':   'energy',    'ONGC':       'energy',
    'TCS':        'it',        'INFY':       'it',
    'WIPRO':      'it',        'HCLTECH':    'it',      'TECHM': 'it',
    'HDFCBANK':   'banking',   'ICICIBANK':  'banking', 'SBIN':  'banking',
    'AXISBANK':   'banking',   'KOTAKBANK':  'banking', 'INDUSINDBK': 'banking',
    'BAJFINANCE': 'finance',
    'TATAMOTORS': 'auto',      'MARUTI':     'auto',    'M&M':   'auto',
    'TATASTEEL':  'metal',     'HINDALCO':   'metal',   'JSWSTEEL': 'metal',
    'SUNPHARMA':  'pharma',    'DRREDDY':    'pharma',
    'LT':         'infra',     'POWERGRID':  'infra',   'NTPC':  'infra',
    'ADANIENT':   'conglomerate','ADANIPORTS':'infra',
    'ULTRACEMCO': 'cement',    'GRASIM':     'cement',
    'BHARTIARTL': 'telecom',
}


class RiskManager:
    def __init__(self, config: Dict):
        self.config          = config
        self.total_capital   = float(config.get('total_capital', 100000))
        self.max_trade_risk  = float(config.get('max_loss_per_trade_pct', 1.0)) / 100
        self.daily_limit_pct = float(config.get('daily_loss_limit_pct', 3.0)) / 100
        self.max_per_trade   = float(config.get('max_capital_per_trade', 10000))
        self.max_positions   = int(config.get('max_open_positions', 3))

        os.makedirs(os.path.dirname(TRADES_PATH), exist_ok=True)
        self._load_state()

    # ═══════════════════════════════════════════════════════════
    #  STATE MANAGEMENT
    # ═══════════════════════════════════════════════════════════

    def _load_state(self):
        today = date.today().isoformat()
        try:
            with open(PNL_PATH, 'r') as f:
                state = json.load(f)
            if state.get('date') != today:
                self._reset_daily(today)
            else:
                self.daily_pnl        = float(state.get('daily_pnl', 0))
                self.daily_trades     = int(state.get('daily_trades', 0))
                self.kill_switch_on   = bool(state.get('kill_switch_on', False))
                self.open_positions   = state.get('open_positions', [])
                self.consecutive_losses = int(state.get('consecutive_losses', 0))
                self.black_swan_mode  = bool(state.get('black_swan_mode', False))
        except Exception:
            self._reset_daily(today)

    def _reset_daily(self, today: str):
        self.daily_pnl          = 0.0
        self.daily_trades       = 0
        self.kill_switch_on     = False
        self.open_positions     = []
        self.consecutive_losses = 0
        self.black_swan_mode    = False
        self._save_state(today)

    def _save_state(self, today: str = None):
        today = today or date.today().isoformat()
        with open(PNL_PATH, 'w') as f:
            json.dump({
                'date':               today,
                'daily_pnl':          self.daily_pnl,
                'daily_trades':       self.daily_trades,
                'kill_switch_on':     self.kill_switch_on,
                'open_positions':     self.open_positions,
                'consecutive_losses': self.consecutive_losses,
                'black_swan_mode':    self.black_swan_mode,
            }, f, indent=2)

    # ═══════════════════════════════════════════════════════════
    #  KILL SWITCH & TRADING PERMISSION
    # ═══════════════════════════════════════════════════════════

    def is_trading_allowed(self) -> Dict:
        self._load_state()

        if self.black_swan_mode:
            return {'allowed': False, 'reason': '🦢 BLACK SWAN MODE ACTIVE — Market panic detected. All trading halted.'}

        if self.kill_switch_on:
            return {'allowed': False, 'reason': f'☠ KILL SWITCH ACTIVE — P&L: ₹{self.daily_pnl:,.0f}. Resume tomorrow.'}

        daily_loss_limit = self.total_capital * self.daily_limit_pct
        if self.daily_pnl <= -daily_loss_limit:
            self.kill_switch_on = True
            self._save_state()
            return {'allowed': False, 'reason': f'KILL SWITCH TRIGGERED — Daily loss ₹{daily_loss_limit:,.0f} reached.'}

        if len(self.open_positions) >= self.max_positions:
            return {'allowed': False, 'reason': f'Max open positions ({self.max_positions}) reached.'}

        now = datetime.now()
        # Bug 11: 9:15-9:30 noise window
        # Bug 16: ENTRY_CUTOFF 2:45 PM + HARD_EXIT_TIME 3:10 PM (broker auto-sq-off trap)
        market_open    = now.replace(hour=9,  minute=15, second=0, microsecond=0)
        noise_end      = now.replace(hour=9,  minute=30, second=0, microsecond=0)
        entry_cutoff   = now.replace(hour=14, minute=45, second=0, microsecond=0)
        hard_exit_time = now.replace(hour=15, minute=10, second=0, microsecond=0)
        market_close   = now.replace(hour=15, minute=15, second=0, microsecond=0)

        if not (market_open <= now <= market_close):
            return {'allowed': False, 'reason': 'Market closed. Trading: 9:30 AM – 3:15 PM IST'}
        if now < noise_end:
            return {'allowed': False, 'reason': '⏳ 9:15–9:30 noise window — waiting for price discovery'}
        if now >= hard_exit_time:
            return {'allowed': False, 'reason': '⏰ 3:10 PM hard exit zone — no new trades. Broker sq-off at 3:20 PM.', 'hard_exit': True}
        if now >= entry_cutoff:
            return {'allowed': False, 'reason': '🕑 2:45 PM entry cutoff — no new positions. Too close to broker sq-off.', 'entry_cutoff': True}

        return {'allowed': True, 'reason': 'All risk checks passed ✓'}

    def is_hard_exit_time(self) -> bool:
        """Returns True when agent must square off all open intraday positions (3:10 PM)."""
        now = datetime.now()
        t   = now.replace(hour=15, minute=10, second=0, microsecond=0)
        return now >= t and now.hour < 16

    def force_kill_switch(self):
        self.kill_switch_on = True
        self._save_state()

    def reset_kill_switch(self):
        self.kill_switch_on  = False
        self.black_swan_mode = False
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    #  FEATURE 3: KELLY CRITERION POSITION SIZING
    # ═══════════════════════════════════════════════════════════

    def calculate_position_size(self, entry: float, stop_loss: float,
                                 strategy_name: str = '',
                                 regime_multiplier: float = 1.0) -> Dict:
        """
        Kelly Criterion + slippage-adjusted position sizing.
        Bug 10: adjusted_entry = entry * (1 + slippage), adjusted_sl = sl * (1 - slippage)
        """
        SLIPPAGE = 0.003   # 0.3%
        adjusted_entry = entry * (1 + SLIPPAGE)
        adjusted_sl    = stop_loss * (1 - SLIPPAGE)
        risk_per_share = abs(adjusted_entry - adjusted_sl)
        if risk_per_share <= 0 or entry <= 0:
            return {'quantity': 0, 'error': 'Invalid entry/stop levels', 'method': 'error'}

        # Get strategy stats from memory for Kelly calculation
        kelly_fraction = self._get_kelly_fraction(strategy_name)
        kelly_fraction *= regime_multiplier   # scale by market regime

        # Method 1: Kelly-based risk amount
        kelly_risk_amount = self.total_capital * kelly_fraction
        qty_kelly         = int(kelly_risk_amount / risk_per_share)

        # Method 2: Fixed 1% risk (safety floor)
        fixed_risk_amount = self.total_capital * self.max_trade_risk
        qty_fixed         = int(fixed_risk_amount / risk_per_share)

        # Method 3: Max capital per trade cap
        qty_capital_cap   = int(self.max_per_trade / entry)

        # Take the MOST conservative of Kelly vs Fixed, then cap by capital
        qty_risk = min(qty_kelly, qty_fixed) if qty_kelly > 0 else qty_fixed
        quantity = min(qty_risk, qty_capital_cap)

        if quantity <= 0:
            return {'quantity': 0, 'error': 'Position size too small after Kelly adjustment', 'method': 'kelly'}

        actual_risk = quantity * risk_per_share
        return {
            'quantity':         quantity,
            'capital_used':     round(quantity * entry, 2),
            'max_loss':         round(actual_risk, 2),
            'risk_pct':         round((actual_risk / self.total_capital) * 100, 2),
            'kelly_fraction':   round(kelly_fraction * 100, 2),
            'regime_multiplier':regime_multiplier,
            'method':           'kelly_criterion',
            'error':            None,
        }

    def _get_kelly_fraction(self, strategy_name: str) -> float:
        """
        Calculate Kelly fraction from historical trade data.
        Falls back to conservative 0.5% if insufficient history.
        """
        if not strategy_name:
            return self.max_trade_risk * 0.5   # half of max risk when no history

        trades = self._load_trades()
        strat_trades = [t for t in trades
                        if t.get('strategy', '') == strategy_name
                        and t.get('pnl') is not None
                        and t.get('status') == 'CLOSED']

        if len(strat_trades) < 5:
            # Not enough data → use conservative fixed fraction
            return self.max_trade_risk

        wins   = [t for t in strat_trades if t['pnl'] > 0]
        losses = [t for t in strat_trades if t['pnl'] <= 0]

        p = len(wins) / len(strat_trades)   # win rate
        q = 1 - p

        if not wins or not losses:
            return self.max_trade_risk

        avg_win  = sum(t['pnl'] for t in wins) / len(wins)
        avg_loss = abs(sum(t['pnl'] for t in losses) / len(losses))

        if avg_loss <= 0:
            return self.max_trade_risk

        b = avg_win / avg_loss   # win/loss ratio

        # Kelly formula: f* = (p*b - q) / b
        kelly_f = (p * b - q) / b

        # Apply Kelly fraction limits:
        # • Negative Kelly = skip trade (but we return 0 risk to let caller decide)
        # • Cap at 2% max (even if Kelly says more — safety first)
        # • Minimum 0.25% floor (always take some position if Kelly is positive)
        if kelly_f <= 0:
            return 0.001   # minimal size — Kelly says don't trade
        return max(0.0025, min(kelly_f * 0.5, 0.02))   # half-kelly, capped at 2%

    # ═══════════════════════════════════════════════════════════
    #  FEATURE 4: CORRELATION / CLUSTER RISK CHECK
    # ═══════════════════════════════════════════════════════════

    def check_correlation_risk(self, new_symbol: str, open_symbols: List[str]) -> Dict:
        """
        Prevent trading same sector twice.
        If we already have 2 positions in the same sector, block the 3rd.
        """
        if not open_symbols:
            return {'allowed': True, 'reason': 'No existing positions', 'sector': SECTOR_MAP.get(new_symbol, 'unknown')}

        new_sector = SECTOR_MAP.get(new_symbol.upper(), 'unknown')
        if new_sector == 'unknown':
            return {'allowed': True, 'reason': 'Sector unknown — allowing', 'sector': 'unknown'}

        # Count same-sector positions
        same_sector = [s for s in open_symbols if SECTOR_MAP.get(s.upper(), '') == new_sector]
        max_per_sector = self.config.get('max_positions_per_sector', 1)

        if len(same_sector) >= max_per_sector:
            return {
                'allowed': False,
                'reason':  f'Cluster risk: Already have {len(same_sector)} {new_sector.upper()} position(s): {same_sector}. Max {max_per_sector} per sector.',
                'sector':  new_sector,
                'conflicting': same_sector,
            }

        return {
            'allowed': True,
            'reason':  f'Sector {new_sector.upper()} — no cluster risk',
            'sector':  new_sector,
        }

    # ═══════════════════════════════════════════════════════════
    #  FEATURE 5: BLACK SWAN CIRCUIT BREAKER
    # ═══════════════════════════════════════════════════════════

    def check_black_swan(self, regime_data: Dict) -> Dict:
        """
        Activate Black Swan mode if:
          1. India VIX > 25 (extreme fear)
          2. Regime = BEARISH_PANIC
          3. Daily loss > 80% of limit (near kill-switch territory)
          4. 4+ consecutive losses today
        """
        self._load_state()
        triggers = []

        # Check 1: Regime
        if regime_data.get('regime') == 'BEARISH_PANIC':
            triggers.append(f"Market regime: BEARISH_PANIC (confidence {regime_data.get('confidence',0)}%)")

        # Check 2: India VIX
        vix = regime_data.get('metrics', {}).get('india_vix')
        if vix and vix > 25:
            triggers.append(f"India VIX = {vix:.1f} (extreme fear > 25)")

        # Check 3: Near daily loss limit
        daily_limit  = self.total_capital * self.daily_limit_pct
        loss_used_pct = abs(min(self.daily_pnl, 0)) / daily_limit * 100 if daily_limit else 0
        if loss_used_pct >= 80:
            triggers.append(f"Daily loss {loss_used_pct:.0f}% of limit reached")

        # Check 4: Consecutive losses
        if self.consecutive_losses >= 4:
            triggers.append(f"{self.consecutive_losses} consecutive losses today")

        if triggers:
            self.black_swan_mode = True
            self._save_state()
            return {
                'activated':  True,
                'triggers':   triggers,
                'message':    '🦢 BLACK SWAN CIRCUIT BREAKER ACTIVATED — ' + ' | '.join(triggers),
            }

        return {'activated': False, 'triggers': [], 'message': 'No black swan conditions'}

    def reset_black_swan(self):
        self.black_swan_mode = False
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    #  FEATURE 2: STRATEGY JAIL SYSTEM
    # ═══════════════════════════════════════════════════════════

    def jail_strategy(self, strategy_name: str, reason: str, current_regime: str = ''):
        """Put a strategy in jail — released after regime is stable for 3 loops."""
        jail = self._load_jail()
        jail[strategy_name] = {
            'jailed_at':          datetime.now().isoformat(),
            'reason':             reason,
            'jailed_in_regime':   current_regime,
            'new_regime_loop_count': 0,
        }
        self._save_jail(jail)

    def release_strategy(self, strategy_name: str):
        jail = self._load_jail()
        if strategy_name in jail:
            del jail[strategy_name]
            self._save_jail(jail)

    def is_strategy_jailed(self, strategy_name: str, current_regime: str = '') -> Dict:
        """
        Bug 2 fix: Regime-stable 3-loop auto-release.
        If market regime has changed and stayed stable for 3 loops → auto-release.
        Prevents permanent ban and regime-churn oscillation.
        """
        jail = self._load_jail()
        if strategy_name not in jail:
            return {'jailed': False}

        entry = jail[strategy_name]

        if current_regime and entry.get('jailed_in_regime') != current_regime:
            # Regime has changed — increment stability counter
            count = entry.get('new_regime_loop_count', 0) + 1
            entry['new_regime_loop_count'] = count
            jail[strategy_name] = entry
            self._save_jail(jail)

            if count >= 3:
                # Regime stable for 3 loops in new regime → auto-release
                del jail[strategy_name]
                self._save_jail(jail)
                return {
                    'jailed': False,
                    'reason': f'Auto-released: regime stable {count} loops in {current_regime}'
                }
            return {
                'jailed': True,
                'reason': f'{entry["reason"]} (regime change {count}/3 loops to auto-release)'
            }
        else:
            # Same regime — reset counter, strategy stays jailed
            if entry.get('new_regime_loop_count', 0) != 0:
                entry['new_regime_loop_count'] = 0
                jail[strategy_name] = entry
                self._save_jail(jail)
            return {'jailed': True, **entry}

    def get_jailed_strategies(self) -> Dict:
        return self._load_jail()

    def auto_jail_check(self, strategy_name: str) -> Dict:
        """
        After each trade, check if this strategy should be jailed.
        Jail if: 5+ consecutive losses with this strategy.
        """
        if not strategy_name:
            return {'jailed': False}

        trades = self._load_trades()
        strat_trades = [t for t in trades
                        if t.get('strategy') == strategy_name
                        and t.get('status') == 'CLOSED'
                        and t.get('pnl') is not None]

        if len(strat_trades) < 5:
            return {'jailed': False}

        # Last 5 trades with this strategy
        last_5 = strat_trades[-5:]
        all_losses = all(t['pnl'] < 0 for t in last_5)

        if all_losses:
            reason = f"5 consecutive losses. Losses: {[round(t['pnl'],0) for t in last_5]}"
            self.jail_strategy(strategy_name, reason)
            return {
                'jailed':   True,
                'strategy': strategy_name,
                'reason':   reason,
                'message':  f"⛓ Strategy '{strategy_name}' JAILED — {reason}",
            }

        return {'jailed': False}

    def _load_jail(self) -> Dict:
        if not os.path.exists(JAIL_PATH):
            return {}
        try:
            with open(JAIL_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_jail(self, jail: Dict):
        with open(JAIL_PATH, 'w') as f:
            json.dump(jail, f, indent=2)

    # ═══════════════════════════════════════════════════════════
    #  FEATURE 6: LOSING STREAK ANALYSIS
    # ═══════════════════════════════════════════════════════════

    def analyze_losing_streak(self) -> Optional[Dict]:
        """
        After 3+ consecutive losses, generate a structured analysis
        that gets injected into the next AI prompt as a lesson.
        Returns None if no streak detected.
        """
        self._load_state()
        if self.consecutive_losses < 3:
            return None

        trades = self._load_trades()
        today  = date.today().isoformat()
        today_closed = [t for t in trades
                        if t.get('entry_time', '')[:10] == today
                        and t.get('status') == 'CLOSED'
                        and t.get('pnl') is not None]

        recent_losses = [t for t in today_closed[-self.consecutive_losses:]
                         if t['pnl'] < 0]
        if not recent_losses:
            return None

        # Find patterns in losses
        strategies_used = list(set(t.get('strategy', '') for t in recent_losses))
        symbols_used    = list(set(t.get('symbol', '') for t in recent_losses))
        entry_times     = [t.get('entry_time', '')[-8:-3] for t in recent_losses]
        total_loss      = sum(t['pnl'] for t in recent_losses)
        avg_loss        = total_loss / len(recent_losses)

        analysis = {
            'streak_count':    self.consecutive_losses,
            'total_loss':      round(total_loss, 2),
            'avg_loss':        round(avg_loss, 2),
            'strategies_used': strategies_used,
            'symbols_lost_on': symbols_used,
            'entry_times':     entry_times,
            'analysis_text': (
                f"LOSING STREAK DETECTED: {self.consecutive_losses} consecutive losses. "
                f"Total loss: ₹{total_loss:,.0f}. "
                f"Strategies used: {', '.join(strategies_used)}. "
                f"Symbols: {', '.join(symbols_used)}. "
                f"Entry times: {', '.join(entry_times)}. "
                f"ACTION: Reduce position size, increase conviction threshold, "
                f"consider avoiding {strategies_used[0] if strategies_used else 'these strategies'} today."
            ),
        }
        return analysis

    # ═══════════════════════════════════════════════════════════
    #  TRADE LOGGING
    # ═══════════════════════════════════════════════════════════

    def log_trade_entry(self, trade: Dict) -> str:
        trade_id = f"TRD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{trade['symbol']}"
        record   = {
            'trade_id':    trade_id,
            'symbol':      trade['symbol'],
            'security_id': trade.get('security_id', ''),
            'side':        trade.get('position_side', 'BUY'),
            'quantity':    trade.get('quantity', 0),
            'entry_price': trade.get('entry_price', 0),
            'stop_loss':   trade.get('stop_loss', 0),
            'target_1':    trade.get('target_1', 0),
            'target_2':    trade.get('target_2', 0),
            'strategy':    trade.get('strategy_name', trade.get('strategy', '')),
            'conviction':  trade.get('conviction_score', 0),
            'status':      'OPEN',
            'entry_time':  datetime.now().isoformat(),
            'exit_price':  None,
            'exit_time':   None,
            'pnl':         None,
            'mode':        self.config.get('trading_mode', 'paper'),
        }
        self.open_positions.append({'trade_id': trade_id, 'symbol': trade['symbol']})
        self.daily_trades += 1
        self._save_state()

        trades = self._load_trades()
        trades.append(record)
        self._save_trades(trades)
        return trade_id

    def log_trade_exit(self, trade_id: str, exit_price: float, exit_reason: str) -> Dict:
        trades = self._load_trades()
        for t in trades:
            if t['trade_id'] == trade_id and t['status'] == 'OPEN':
                qty   = t['quantity']
                entry = t['entry_price']
                side  = t['side']
                pnl   = round((exit_price - entry) * qty if side == 'BUY'
                              else (entry - exit_price) * qty, 2)

                t.update({'exit_price': exit_price, 'exit_time': datetime.now().isoformat(),
                           'pnl': pnl, 'exit_reason': exit_reason, 'status': 'CLOSED'})

                self.daily_pnl     += pnl
                self.open_positions = [p for p in self.open_positions if p['trade_id'] != trade_id]

                # Update consecutive losses counter
                if pnl < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0   # reset on win

                self._save_state()
                self._save_trades(trades)

                # Auto-jail check after every exit
                strategy_name = t.get('strategy', '')
                jail_result   = self.auto_jail_check(strategy_name)

                return {'success': True, 'pnl': pnl, 'daily_pnl': self.daily_pnl,
                        'jail_result': jail_result}

        return {'success': False, 'error': 'Trade not found or already closed'}

    # ═══════════════════════════════════════════════════════════
    #  P&L SUMMARY
    # ═══════════════════════════════════════════════════════════

    def get_summary(self) -> Dict:
        self._load_state()
        trades      = self._load_trades()
        today       = date.today().isoformat()
        t_today     = [t for t in trades if t.get('entry_time', '')[:10] == today]
        closed      = [t for t in t_today if t['status'] == 'CLOSED']
        wins        = [t for t in closed if (t['pnl'] or 0) > 0]
        losses      = [t for t in closed if (t['pnl'] or 0) < 0]
        daily_limit = self.total_capital * self.daily_limit_pct

        return {
            'daily_pnl':           round(self.daily_pnl, 2),
            'daily_pnl_pct':       round((self.daily_pnl / self.total_capital) * 100, 2),
            'daily_trades':        self.daily_trades,
            'open_positions':      len(self.open_positions),
            'open_symbols':        [p['symbol'] for p in self.open_positions],
            'closed_trades':       len(closed),
            'wins':                len(wins),
            'losses':              len(losses),
            'win_rate':            round(len(wins) / len(closed) * 100, 1) if closed else 0,
            'kill_switch_on':      self.kill_switch_on,
            'black_swan_mode':     self.black_swan_mode,
            'consecutive_losses':  self.consecutive_losses,
            'daily_loss_limit':    round(daily_limit, 2),
            'loss_limit_used_pct': round(abs(min(self.daily_pnl, 0)) / daily_limit * 100, 1) if daily_limit else 0,
            'total_capital':       self.total_capital,
            'jailed_strategies':   list(self._load_jail().keys()),
            'recent_trades':       t_today[-5:],
        }

    # ═══════════════════════════════════════════════════════════
    #  HELPERS
    # ═══════════════════════════════════════════════════════════

    def _load_trades(self) -> List[Dict]:
        if not os.path.exists(TRADES_PATH):
            return []
        try:
            with open(TRADES_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return []

    def _save_trades(self, trades: List[Dict]):
        with open(TRADES_PATH, 'w') as f:
            json.dump(trades, f, indent=2)
