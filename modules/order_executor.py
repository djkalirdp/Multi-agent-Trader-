"""
Module 5: Order Executor
DhanHQ API ke through actual/paper orders place karta hai.
Paper mode mein orders simulate hote hain, live mein real orders jaate hain.
"""

import requests
import json
from datetime import datetime
from typing import Dict, Optional


DHAN_BASE = "https://api.dhan.co"


class OrderExecutor:
    def __init__(self, client_id: str, access_token: str, trading_mode: str = 'paper'):
        self.client_id    = client_id
        self.access_token = access_token
        self.mode         = trading_mode   # 'paper' or 'live'
        self.headers = {
            "access-token": access_token,
            "client-id":    client_id,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }

    # ─── MAIN ENTRY POINT ─────────────────────────────────────
    def place_order(self, trade_params: Dict) -> Dict:
        """
        Place an order based on trade parameters from Claude.
        Paper mode: simulate. Live mode: real DhanHQ order.
        """
        if self.mode == 'paper':
            return self._simulate_order(trade_params)
        else:
            return self._place_live_order(trade_params)

    def place_bracket_order(self, trade_params: Dict) -> Dict:
        """Place bracket order with built-in SL and target."""
        if self.mode == 'paper':
            return self._simulate_bracket_order(trade_params)
        else:
            return self._place_live_bracket_order(trade_params)

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an open order."""
        if self.mode == 'paper':
            return {'success': True, 'message': f'[PAPER] Order {order_id} cancelled.', 'order_id': order_id}

        try:
            resp = requests.delete(
                f"{DHAN_BASE}/v2/orders/{order_id}",
                headers=self.headers,
                timeout=10
            )
            resp.raise_for_status()
            return {'success': True, 'message': 'Order cancelled.', 'order_id': order_id}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_positions(self) -> Dict:
        """Fetch all open positions from DhanHQ."""
        if self.mode == 'paper':
            return {'success': True, 'positions': [], 'mode': 'paper'}

        try:
            resp = requests.get(
                f"{DHAN_BASE}/v2/positions",
                headers=self.headers,
                timeout=10
            )
            resp.raise_for_status()
            return {'success': True, 'positions': resp.json(), 'mode': 'live'}
        except Exception as e:
            return {'success': False, 'message': str(e), 'positions': []}

    def get_order_status(self, order_id: str) -> Dict:
        """Check status of a specific order."""
        if self.mode == 'paper':
            return {'success': True, 'status': 'TRADED', 'order_id': order_id, 'mode': 'paper'}

        try:
            resp = requests.get(
                f"{DHAN_BASE}/v2/orders/{order_id}",
                headers=self.headers,
                timeout=10
            )
            resp.raise_for_status()
            return {'success': True, **resp.json(), 'mode': 'live'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def square_off_all(self) -> Dict:
        """Emergency: square off all open positions (kill switch)."""
        if self.mode == 'paper':
            return {'success': True, 'message': '[PAPER] All positions squared off.', 'count': 0}

        try:
            # Fetch all positions
            pos_resp = self.get_positions()
            positions = pos_resp.get('positions', [])
            squared   = 0
            errors    = []

            for pos in positions:
                qty = abs(int(pos.get('netQty', 0)))
                if qty == 0:
                    continue
                side = 'SELL' if pos.get('netQty', 0) > 0 else 'BUY'
                try:
                    order = {
                        'security_id':      pos.get('securityId'),
                        'quantity':         qty,
                        'position_side':    side,
                        'entry_type':       'MARKET',
                        'entry_price':      0,
                        'exchange_segment': pos.get('exchangeSegment', 'NSE_EQ'),
                    }
                    self._place_live_order(order)
                    squared += 1
                except Exception as e:
                    errors.append(str(e))

            return {
                'success': len(errors) == 0,
                'squared_off': squared,
                'errors': errors,
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ─── PAPER TRADING ────────────────────────────────────────
    def _simulate_order(self, params: Dict) -> Dict:
        fake_id = f"PAPER_{datetime.now().strftime('%H%M%S')}_{params.get('symbol','')}"
        return {
            'success':   True,
            'mode':      'paper',
            'order_id':  fake_id,
            'symbol':    params.get('symbol'),
            'side':      params.get('position_side', 'BUY'),
            'quantity':  params.get('quantity', 0),
            'price':     params.get('entry_price', 0),
            'order_type':params.get('entry_type', 'LIMIT'),
            'status':    'SIMULATED',
            'message':   f"[PAPER] Order simulated: {params.get('position_side','BUY')} "
                         f"{params.get('quantity',0)} {params.get('symbol','')} @ "
                         f"₹{params.get('entry_price',0)}",
            'timestamp': datetime.now().isoformat(),
        }

    def _simulate_bracket_order(self, params: Dict) -> Dict:
        fake_id  = f"PAPER_BO_{datetime.now().strftime('%H%M%S')}_{params.get('symbol','')}"
        return {
            'success':     True,
            'mode':        'paper',
            'order_id':    fake_id,
            'symbol':      params.get('symbol'),
            'side':        params.get('position_side', 'BUY'),
            'quantity':    params.get('quantity', 0),
            'entry_price': params.get('entry_price', 0),
            'stop_loss':   params.get('stop_loss', 0),
            'target_1':    params.get('target_1', 0),
            'status':      'SIMULATED_BRACKET',
            'message':     f"[PAPER BRACKET] {params.get('position_side','BUY')} "
                           f"{params.get('quantity',0)} {params.get('symbol','')} | "
                           f"Entry: ₹{params.get('entry_price',0)} | "
                           f"SL: ₹{params.get('stop_loss',0)} | "
                           f"Target: ₹{params.get('target_1',0)}",
            'timestamp':   datetime.now().isoformat(),
        }

    # ─── LIVE ORDER PLACEMENT ─────────────────────────────────
    def _place_live_order(self, params: Dict) -> Dict:
        """
        Place a real order via DhanHQ v2 Orders API.
        https://dhanhq.co/docs/v2/orders/
        """
        order_type = params.get('entry_type', 'LIMIT').upper()
        payload = {
            "dhanClientId":     self.client_id,
            "transactionType":  params.get('position_side', 'BUY'),   # BUY or SELL
            "exchangeSegment":  params.get('exchange_segment', 'NSE_EQ'),
            "productType":      "INTRADAY",
            "orderType":        order_type,   # LIMIT / MARKET / STOP_LIMIT
            "validity":         "DAY",
            "securityId":       str(params.get('security_id', '')),
            "quantity":         int(params.get('quantity', 0)),
            "price":            float(params.get('entry_price', 0)),
            "triggerPrice":     float(params.get('trigger_price', 0)),
            "disclosedQuantity":0,
            "afterMarketOrder": False,
            "amoTime":          "OPEN",
        }

        try:
            resp = requests.post(
                f"{DHAN_BASE}/v2/orders",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            data = resp.json()

            if resp.status_code in (200, 201):
                return {
                    'success':  True,
                    'mode':     'live',
                    'order_id': data.get('orderId', ''),
                    'status':   data.get('orderStatus', ''),
                    'message':  f"Live order placed: {data.get('orderId','')}",
                    'raw':      data,
                }
            else:
                return {
                    'success': False,
                    'mode':    'live',
                    'message': data.get('remarks', resp.text[:200]),
                    'raw':     data,
                }
        except Exception as e:
            return {'success': False, 'mode': 'live', 'message': str(e)}

    def _place_live_bracket_order(self, params: Dict) -> Dict:
        """
        DhanHQ bracket-order (Super Order) with auto SL and target.
        """
        entry  = float(params.get('entry_price', 0))
        sl     = float(params.get('stop_loss', 0))
        tgt    = float(params.get('target_1', 0))
        side   = params.get('position_side', 'BUY')

        sl_offset  = abs(entry - sl)
        tgt_offset = abs(tgt  - entry)

        payload = {
            "dhanClientId":     self.client_id,
            "transactionType":  side,
            "exchangeSegment":  params.get('exchange_segment', 'NSE_EQ'),
            "productType":      "BO",
            "orderType":        "LIMIT",
            "validity":         "DAY",
            "securityId":       str(params.get('security_id', '')),
            "quantity":         int(params.get('quantity', 0)),
            "price":            entry,
            "triggerPrice":     0,
            "disclosedQuantity":0,
            "afterMarketOrder": False,
            "amoTime":          "OPEN",
            "boProfitValue":    round(tgt_offset, 2),
            "boStopLossValue":  round(sl_offset, 2),
        }

        try:
            resp = requests.post(
                f"{DHAN_BASE}/v2/orders",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                return {'success': True, 'mode': 'live', 'order_id': data.get('orderId',''), 'raw': data}
            else:
                return {'success': False, 'mode': 'live', 'message': data.get('remarks', resp.text[:200])}
        except Exception as e:
            return {'success': False, 'mode': 'live', 'message': str(e)}
