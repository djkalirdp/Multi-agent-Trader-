"""
Module 4: Risk Manager
- 1% max loss per trade enforcement
- Daily kill switch (halt on daily loss limit breach)
- Position size calculator
- Trade log & P&L tracker
"""

import json
import os
from datetime import datetime, date
from typing import Dict, List, Optional


TRADES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trades.json')
PNL_PATH    = os.path.join(os.path.dirname(__file__), '..', 'data', 'pnl.json')


class RiskManager:
    def __init__(self, config: Dict):
        self.config          = config
        self.total_capital   = float(config.get('total_capital', 100000))
        self.max_trade_risk  = float(config.get('max_loss_per_trade_pct', 1.0)) / 100
        self.daily_limit_pct = float(config.get('daily_loss_limit_pct', 3.0))  / 100
        self.max_per_trade   = float(config.get('max_capital_per_trade', 10000))
        self.max_positions   = int(config.get('max_open_positions', 3))

        os.makedirs(os.path.dirname(TRADES_PATH), exist_ok=True)
        self._load_state()

    # ─── STATE ────────────────────────────────────────────────
    def _load_state(self):
        today = date.today().isoformat()
        try:
            with open(PNL_PATH, 'r') as f:
                state = json.load(f)
            if state.get('date') != today:
                self._reset_daily(today)
            else:
                self.daily_pnl       = float(state.get('daily_pnl', 0))
                self.daily_trades    = int(state.get('daily_trades', 0))
                self.kill_switch_on  = bool(state.get('kill_switch_on', False))
                self.open_positions  = state.get('open_positions', [])
        except Exception:
            self._reset_daily(today)

    def _reset_daily(self, today: str):
        self.daily_pnl      = 0.0
        self.daily_trades   = 0
        self.kill_switch_on = False
        self.open_positions = []
        self._save_state(today)

    def _save_state(self, today: str = None):
        today = today or date.today().isoformat()
        state = {
            'date':           today,
            'daily_pnl':      self.daily_pnl,
            'daily_trades':   self.daily_trades,
            'kill_switch_on': self.kill_switch_on,
            'open_positions': self.open_positions,
        }
        with open(PNL_PATH, 'w') as f:
            json.dump(state, f, indent=2)

    # ─── KILL SWITCH ──────────────────────────────────────────
    def is_trading_allowed(self) -> Dict:
        """Check if agent is allowed to place new trades."""
        self._load_state()

        if self.kill_switch_on:
            return {
                'allowed': False,
                'reason':  f'KILL SWITCH ACTIVE — Daily loss limit breached. '
                           f'P&L today: ₹{self.daily_pnl:,.0f}. Resume tomorrow.'
            }

        daily_loss_limit = self.total_capital * self.daily_limit_pct
        if self.daily_pnl <= -daily_loss_limit:
            self.kill_switch_on = True
            self._save_state()
            return {
                'allowed': False,
                'reason':  f'KILL SWITCH TRIGGERED — Daily loss limit ₹{daily_loss_limit:,.0f} reached. '
                           f'All trading halted for today.'
            }

        if len(self.open_positions) >= self.max_positions:
            return {
                'allowed': False,
                'reason':  f'Max open positions ({self.max_positions}) reached.'
            }

        market_open  = datetime.now().replace(hour=9,  minute=15, second=0)
        market_close = datetime.now().replace(hour=15, minute=15, second=0)
        now          = datetime.now()
        if not (market_open <= now <= market_close):
            return {'allowed': False, 'reason': 'Market is closed. NSE hours: 9:15 AM – 3:15 PM IST'}

        return {'allowed': True, 'reason': 'All risk checks passed'}

    def force_kill_switch(self):
        """Manually activate kill switch."""
        self.kill_switch_on = True
        self._save_state()

    def reset_kill_switch(self):
        """Manually reset kill switch (use with caution)."""
        self.kill_switch_on = False
        self._save_state()

    # ─── POSITION SIZING ──────────────────────────────────────
    def calculate_position_size(self, entry: float, stop_loss: float) -> Dict:
        """
        Calculate quantity so that loss at SL = max 1% of total capital.
        Also respects max_capital_per_trade limit.
        """
        risk_per_share = abs(entry - stop_loss)
        if risk_per_share <= 0:
            return {'quantity': 0, 'error': 'Invalid entry/stop levels'}

        max_risk_amount = self.total_capital * self.max_trade_risk
        qty_by_risk     = int(max_risk_amount / risk_per_share)

        # Also cap by max capital per trade
        qty_by_capital  = int(self.max_per_trade / entry)
        quantity        = min(qty_by_risk, qty_by_capital)

        if quantity <= 0:
            return {'quantity': 0, 'error': 'Position size too small after risk calculation'}

        return {
            'quantity':         quantity,
            'capital_used':     round(quantity * entry, 2),
            'max_loss':         round(quantity * risk_per_share, 2),
            'risk_pct':         round((quantity * risk_per_share / self.total_capital) * 100, 2),
            'error':            None,
        }

    # ─── TRADE LOGGING ────────────────────────────────────────
    def log_trade_entry(self, trade: Dict) -> str:
        """Log a new trade entry. Returns trade_id."""
        trade_id = f"TRD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{trade['symbol']}"
        record = {
            'trade_id':    trade_id,
            'symbol':      trade['symbol'],
            'security_id': trade.get('security_id', ''),
            'side':        trade.get('position_side', 'BUY'),
            'quantity':    trade.get('quantity', 0),
            'entry_price': trade.get('entry_price', 0),
            'stop_loss':   trade.get('stop_loss', 0),
            'target_1':    trade.get('target_1', 0),
            'target_2':    trade.get('target_2', 0),
            'strategy':    trade.get('strategy_name', ''),
            'conviction':  trade.get('conviction_score', 0),
            'status':      'OPEN',
            'entry_time':  datetime.now().isoformat(),
            'exit_price':  None,
            'exit_time':   None,
            'pnl':         None,
            'mode':        self.config.get('trading_mode', 'paper'),
        }

        # Add to open positions
        self.open_positions.append({'trade_id': trade_id, 'symbol': trade['symbol']})
        self.daily_trades += 1
        self._save_state()

        # Write to trades log
        trades = self._load_trades()
        trades.append(record)
        self._save_trades(trades)

        return trade_id

    def log_trade_exit(self, trade_id: str, exit_price: float, exit_reason: str) -> Dict:
        """Log trade exit and update P&L."""
        trades = self._load_trades()
        for t in trades:
            if t['trade_id'] == trade_id and t['status'] == 'OPEN':
                qty   = t['quantity']
                entry = t['entry_price']
                side  = t['side']

                pnl = (exit_price - entry) * qty if side == 'BUY' else (entry - exit_price) * qty
                pnl = round(pnl, 2)

                t['exit_price']  = exit_price
                t['exit_time']   = datetime.now().isoformat()
                t['pnl']         = pnl
                t['exit_reason'] = exit_reason
                t['status']      = 'CLOSED'

                self.daily_pnl      += pnl
                self.open_positions  = [p for p in self.open_positions if p['trade_id'] != trade_id]
                self._save_state()
                self._save_trades(trades)

                return {'success': True, 'pnl': pnl, 'daily_pnl': self.daily_pnl}

        return {'success': False, 'error': 'Trade not found or already closed'}

    # ─── P&L SUMMARY ──────────────────────────────────────────
    def get_summary(self) -> Dict:
        self._load_state()
        trades  = self._load_trades()
        today   = date.today().isoformat()
        t_today = [t for t in trades if t['entry_time'][:10] == today]
        closed  = [t for t in t_today if t['status'] == 'CLOSED']
        wins    = [t for t in closed if (t['pnl'] or 0) > 0]
        losses  = [t for t in closed if (t['pnl'] or 0) < 0]

        daily_loss_limit = self.total_capital * self.daily_limit_pct

        return {
            'daily_pnl':          round(self.daily_pnl, 2),
            'daily_pnl_pct':      round((self.daily_pnl / self.total_capital) * 100, 2),
            'daily_trades':       self.daily_trades,
            'open_positions':     len(self.open_positions),
            'open_symbols':       [p['symbol'] for p in self.open_positions],
            'closed_trades':      len(closed),
            'wins':               len(wins),
            'losses':             len(losses),
            'win_rate':           round(len(wins)/len(closed)*100, 1) if closed else 0,
            'kill_switch_on':     self.kill_switch_on,
            'daily_loss_limit':   round(daily_loss_limit, 2),
            'loss_limit_used_pct':round((abs(min(self.daily_pnl,0)) / daily_loss_limit) * 100, 1) if daily_loss_limit else 0,
            'total_capital':      self.total_capital,
            'recent_trades':      t_today[-5:],
        }

    # ─── HELPERS ──────────────────────────────────────────────
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
