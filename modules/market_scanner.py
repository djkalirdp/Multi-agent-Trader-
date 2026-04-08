"""
Module 1: Market Scanner
DhanHQ API se live market data fetch karta hai aur intraday candidates filter karta hai.
Filters: High RVOL, Pre-Market Gappers, High ATR, Liquidity
"""

import requests
import json
import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional


DHAN_BASE   = "https://api.dhan.co"
DHAN_DATA   = "https://api.dhan.co/v2"

# NSE F&O stocks — high liquidity intraday universe
STOCK_UNIVERSE = [
    {"symbol": "RELIANCE",  "security_id": "2885",  "exchange": "NSE"},
    {"symbol": "TCS",       "security_id": "11536", "exchange": "NSE"},
    {"symbol": "INFY",      "security_id": "1594",  "exchange": "NSE"},
    {"symbol": "HDFCBANK",  "security_id": "1333",  "exchange": "NSE"},
    {"symbol": "ICICIBANK", "security_id": "4963",  "exchange": "NSE"},
    {"symbol": "SBIN",      "security_id": "3045",  "exchange": "NSE"},
    {"symbol": "AXISBANK",  "security_id": "5900",  "exchange": "NSE"},
    {"symbol": "KOTAKBANK", "security_id": "1922",  "exchange": "NSE"},
    {"symbol": "BAJFINANCE","security_id": "317",   "exchange": "NSE"},
    {"symbol": "WIPRO",     "security_id": "3787",  "exchange": "NSE"},
    {"symbol": "HCLTECH",   "security_id": "1348",  "exchange": "NSE"},
    {"symbol": "LT",        "security_id": "11483", "exchange": "NSE"},
    {"symbol": "TATAMOTORS","security_id": "3456",  "exchange": "NSE"},
    {"symbol": "TATASTEEL", "security_id": "3499",  "exchange": "NSE"},
    {"symbol": "MARUTI",    "security_id": "10999", "exchange": "NSE"},
    {"symbol": "SUNPHARMA", "security_id": "3351",  "exchange": "NSE"},
    {"symbol": "DRREDDY",   "security_id": "881",   "exchange": "NSE"},
    {"symbol": "HINDALCO",  "security_id": "1363",  "exchange": "NSE"},
    {"symbol": "JSWSTEEL",  "security_id": "11723", "exchange": "NSE"},
    {"symbol": "ONGC",      "security_id": "2475",  "exchange": "NSE"},
    {"symbol": "NTPC",      "security_id": "11630", "exchange": "NSE"},
    {"symbol": "POWERGRID", "security_id": "14977", "exchange": "NSE"},
    {"symbol": "ADANIENT",  "security_id": "25",    "exchange": "NSE"},
    {"symbol": "ADANIPORTS","security_id": "15083", "exchange": "NSE"},
    {"symbol": "ULTRACEMCO","security_id": "11532", "exchange": "NSE"},
    {"symbol": "GRASIM",    "security_id": "1232",  "exchange": "NSE"},
    {"symbol": "BHARTIARTL","security_id": "10604", "exchange": "NSE"},
    {"symbol": "INDUSINDBK","security_id": "5258",  "exchange": "NSE"},
    {"symbol": "M&M",       "security_id": "2031",  "exchange": "NSE"},
    {"symbol": "TECHM",     "security_id": "13538", "exchange": "NSE"},
]


class MarketScanner:
    def __init__(self, client_id: str, access_token: str, config: dict):
        self.client_id    = client_id
        self.access_token = access_token
        self.config       = config
        self.headers = {
            "access-token": access_token,
            "client-id":    client_id,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }

    # ─── PUBLIC MAIN METHOD ──────────────────────────────────
    def scan(self) -> Dict:
        """
        Full scan pipeline.
        Returns dict with 'candidates' list and 'scan_meta' info.
        """
        result = {
            "timestamp":  datetime.now().isoformat(),
            "candidates": [],
            "scan_meta":  {},
            "errors":     [],
        }

        try:
            quotes = self._fetch_quotes_batch()
            if not quotes:
                result["errors"].append("Could not fetch market quotes")
                return result

            candles_map = self._fetch_candles_batch()
            enriched    = self._enrich_and_filter(quotes, candles_map)

            result["candidates"]       = enriched
            result["scan_meta"]["total_scanned"] = len(STOCK_UNIVERSE)
            result["scan_meta"]["passed_filter"] = len(enriched)
            result["scan_meta"]["scan_time"]     = datetime.now().strftime("%H:%M:%S")

        except Exception as e:
            result["errors"].append(str(e))

        return result

    # ─── STEP 1: FETCH LIVE QUOTES ───────────────────────────
    def _fetch_quotes_batch(self) -> List[Dict]:
        """Fetch live LTP + OHLCV for all universe stocks."""
        payload = {
            "NSE_EQ": [s["security_id"] for s in STOCK_UNIVERSE]
        }
        try:
            resp = requests.post(
                f"{DHAN_BASE}/v2/marketfeed/ltp",
                headers=self.headers,
                json=payload,
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            quotes = []
            nse_data = data.get("data", {}).get("NSE_EQ", {})
            for stock in STOCK_UNIVERSE:
                sid  = stock["security_id"]
                info = nse_data.get(sid, {})
                if info:
                    quotes.append({
                        "symbol":      stock["symbol"],
                        "security_id": sid,
                        "exchange":    stock["exchange"],
                        "ltp":         float(info.get("last_price", 0)),
                        "open":        float(info.get("open_price", 0)),
                        "high":        float(info.get("high_price", 0)),
                        "low":         float(info.get("low_price", 0)),
                        "close":       float(info.get("close_price", 0)),
                        "volume":      int(info.get("volume", 0)),
                    })
            return quotes
        except Exception as e:
            return []

    # ─── STEP 2: FETCH HISTORICAL CANDLES (for ATR/RVOL) ─────
    def _fetch_candles_batch(self) -> Dict[str, List]:
        """
        Fetch 15-min candles for last 10 days for each stock.
        Used to compute ATR and average volume.
        """
        candles_map = {}
        today       = datetime.now()
        from_date   = (today - timedelta(days=15)).strftime("%Y-%m-%d")
        to_date     = today.strftime("%Y-%m-%d")

        for stock in STOCK_UNIVERSE:
            try:
                payload = {
                    "securityId":  stock["security_id"],
                    "exchangeSegment": "NSE_EQ",
                    "instrument":  "EQUITY",
                    "interval":    "15",
                    "oi_flag":     "0",
                    "from_date":   from_date,
                    "to_date":     to_date,
                }
                resp = requests.post(
                    f"{DHAN_BASE}/v2/charts/intraday",
                    headers=self.headers,
                    json=payload,
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candles_map[stock["symbol"]] = data.get("data", [])
                time.sleep(0.1)   # rate limit courtesy
            except Exception:
                continue

        return candles_map

    # ─── STEP 3: ENRICH + FILTER ─────────────────────────────
    def _enrich_and_filter(self, quotes: List[Dict], candles_map: Dict) -> List[Dict]:
        """Apply all scanner filters and return passing candidates."""
        candidates = []
        cfg = self.config

        for q in quotes:
            sym = q["symbol"]
            try:
                candles  = candles_map.get(sym, [])
                atr      = self._calculate_atr(candles)
                avg_vol  = self._calculate_avg_volume(candles)
                rvol     = (q["volume"] / avg_vol) if avg_vol > 0 else 0
                gap_pct  = self._calculate_gap(q["open"], q["close"])
                vwap     = self._calculate_vwap(candles)
                rsi      = self._calculate_rsi(candles)

                # ── FILTER CHECKS ──
                passes_rvol = rvol >= cfg.get("rvol_threshold", 1.5)
                passes_atr  = atr  >= cfg.get("min_atr", 5.0)
                passes_gap  = abs(gap_pct) >= cfg.get("min_gap_pct", 2.0)
                passes_liq  = q["ltp"] > 50   # avoid penny stocks

                # Must pass RVOL + ATR; gap is bonus signal
                if not (passes_rvol and passes_atr and passes_liq):
                    continue

                trend = self._determine_trend(q, vwap, candles)

                candidates.append({
                    "symbol":      sym,
                    "security_id": q["security_id"],
                    "ltp":         round(q["ltp"], 2),
                    "open":        round(q["open"], 2),
                    "high":        round(q["high"], 2),
                    "low":         round(q["low"], 2),
                    "prev_close":  round(q["close"], 2),
                    "volume":      q["volume"],
                    "avg_volume":  int(avg_vol),
                    "rvol":        round(rvol, 2),
                    "atr":         round(atr, 2),
                    "gap_pct":     round(gap_pct, 2),
                    "vwap":        round(vwap, 2) if vwap else None,
                    "rsi":         round(rsi, 1) if rsi else None,
                    "trend":       trend,
                    "gap_flag":    passes_gap,
                    "scan_time":   datetime.now().strftime("%H:%M:%S"),
                })

            except Exception:
                continue

        # Sort by RVOL descending
        candidates.sort(key=lambda x: x["rvol"], reverse=True)
        return candidates[:10]   # top 10 for Claude to evaluate

    # ─── INDICATOR CALCULATIONS ──────────────────────────────

    def _calculate_atr(self, candles: List, period: int = 14) -> float:
        """Average True Range from OHLC candles."""
        if len(candles) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(candles)):
            c = candles[i]
            p = candles[i-1]
            high  = float(c.get("high", 0))
            low   = float(c.get("low",  0))
            close = float(p.get("close", 0))
            tr = max(high - low, abs(high - close), abs(low - close))
            trs.append(tr)
        return sum(trs[-period:]) / period

    def _calculate_avg_volume(self, candles: List, period: int = 20) -> float:
        """Average volume over last N candles."""
        if not candles:
            return 1
        vols = [float(c.get("volume", 0)) for c in candles[-period:]]
        return sum(vols) / len(vols) if vols else 1

    def _calculate_gap(self, open_price: float, prev_close: float) -> float:
        """Gap percentage from prev close to today's open."""
        if prev_close == 0:
            return 0.0
        return ((open_price - prev_close) / prev_close) * 100

    def _calculate_vwap(self, candles: List) -> Optional[float]:
        """Simple VWAP from candle data."""
        if not candles:
            return None
        total_pv = sum(
            ((float(c.get("high",0)) + float(c.get("low",0)) + float(c.get("close",0))) / 3)
            * float(c.get("volume", 0))
            for c in candles
        )
        total_v = sum(float(c.get("volume", 0)) for c in candles)
        return total_pv / total_v if total_v > 0 else None

    def _calculate_rsi(self, candles: List, period: int = 14) -> Optional[float]:
        """RSI calculation."""
        closes = [float(c.get("close", 0)) for c in candles]
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _determine_trend(self, q: Dict, vwap: Optional[float], candles: List) -> str:
        """Simple trend classification for strategy selection."""
        if not vwap or not candles:
            return "unknown"
        ltp   = q["ltp"]
        opens = [float(c.get("open",0)) for c in candles[-5:]]
        closes= [float(c.get("close",0)) for c in candles[-5:]]

        higher_highs = all(closes[i] > closes[i-1] for i in range(1, len(closes))) if closes else False
        lower_lows   = all(closes[i] < closes[i-1] for i in range(1, len(closes))) if closes else False

        if ltp > vwap and higher_highs:
            return "uptrend"
        elif ltp < vwap and lower_lows:
            return "downtrend"
        elif abs(ltp - vwap) / vwap < 0.005:
            return "ranging"
        elif q["high"] - q["low"] > 2 * (sum(closes)/len(closes) * 0.02 if closes else 1):
            return "volatile"
        return "neutral"
