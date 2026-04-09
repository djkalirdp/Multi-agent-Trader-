"""
Market Regime Detector
Detect karta hai market ka current character:
  TRENDING_UP   → Strong uptrend, momentum strategies kaam karti hain
  TRENDING_DOWN → Strong downtrend, short strategies / mean reversion
  SIDEWAYS      → Range-bound, pivot/mean-reversion strategies best
  VOLATILE      → High volatility, tight stops, ORB/breakout strategies
  BEARISH_PANIC → VIX spike + broad selloff → Black Swan mode

Har regime mein alag strategies recommended hain.
"""

import math
import statistics
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ─── REGIME DEFINITIONS ──────────────────────────────────────────────────────
REGIME_STRATEGIES = {
    "TRENDING_UP": {
        "recommended":    ["VWAP_CROSSOVER", "GAP_AND_GO", "MA_RIBBON", "SUPERTREND", "ORB"],
        "avoid":          ["MEAN_REVERSION", "CAMARILLA", "PIVOT_REVERSALS"],
        "description":    "Market is trending up. Trade with momentum, buy pullbacks.",
        "color":          "green",
        "risk_multiplier": 1.0,   # normal risk
    },
    "TRENDING_DOWN": {
        "recommended":    ["VWAP_CROSSOVER", "DONCHIAN_BREAKOUT", "MA_RIBBON", "MACD_HISTOGRAM"],
        "avoid":          ["GAP_AND_GO", "CUP_HANDLE"],
        "description":    "Market is trending down. Short setups preferred, avoid longs.",
        "color":          "red",
        "risk_multiplier": 0.8,   # slightly reduced risk
    },
    "SIDEWAYS": {
        "recommended":    ["MEAN_REVERSION", "PIVOT_REVERSALS", "CAMARILLA", "INSIDE_BAR_NR7", "INSTITUTIONAL_SR"],
        "avoid":          ["GAP_AND_GO", "DONCHIAN_BREAKOUT", "MA_RIBBON"],
        "description":    "Market is range-bound. Fade extremes, trade pivot bounces.",
        "color":          "amber",
        "risk_multiplier": 0.9,
    },
    "VOLATILE": {
        "recommended":    ["ORB", "MEAN_REVERSION", "ORDER_FLOW_SCALP", "DONCHIAN_BREAKOUT"],
        "avoid":          ["MA_RIBBON", "FIBONACCI_BOUNCE", "TIME_OF_DAY"],
        "description":    "Market is highly volatile. Use wider stops, ORB setups only.",
        "color":          "purple",
        "risk_multiplier": 0.7,   # reduced risk in volatile conditions
    },
    "BEARISH_PANIC": {
        "recommended":    [],      # no new trades in panic
        "avoid":          ["ALL"],
        "description":    "PANIC MODE: VIX spike / circuit-breaker conditions. NO NEW TRADES.",
        "color":          "red",
        "risk_multiplier": 0.0,   # ZERO — no new trades
    },
    "UNKNOWN": {
        "recommended":    ["VWAP_CROSSOVER", "ORB"],
        "avoid":          [],
        "description":    "Insufficient data to determine regime. Using conservative defaults.",
        "color":          "text3",
        "risk_multiplier": 0.8,
    },
}


class MarketRegimeDetector:
    """
    Detects market regime using:
    1. ADX (Average Directional Index)  → trend strength
    2. ATR relative to price             → volatility level
    3. Price vs EMAs                     → direction
    4. India VIX (fetched from NSE)      → fear/panic gauge
    5. Breadth (advance/decline ratio)   → market-wide direction
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}

    # ─── MAIN DETECTION METHOD ────────────────────────────────
    def detect(self, candidates: List[Dict], nifty_data: Optional[Dict] = None) -> Dict:
        """
        Main entry point. Takes scan candidates + optional Nifty data.
        Returns full regime analysis dict.
        """
        if not candidates:
            return self._build_result("UNKNOWN", 50, {}, "No market data available")

        # Compute metrics from candidates
        metrics = self._compute_market_metrics(candidates)

        # Get India VIX if available
        vix_value = self._fetch_india_vix()
        metrics['india_vix'] = vix_value

        # Detect regime
        regime, confidence, signals = self._classify_regime(metrics)

        result = self._build_result(regime, confidence, metrics, signals)
        result['timestamp'] = datetime.now().isoformat()
        return result

    # ─── METRICS COMPUTATION ──────────────────────────────────
    def _compute_market_metrics(self, candidates: List[Dict]) -> Dict:
        """Compute aggregate market metrics from scan candidates."""
        ltps       = [c.get('ltp', 0) for c in candidates if c.get('ltp', 0) > 0]
        vwaps      = [c.get('vwap', 0) for c in candidates if c.get('vwap', 0) > 0]
        atrs       = [c.get('atr', 0) for c in candidates if c.get('atr', 0) > 0]
        gaps       = [c.get('gap_pct', 0) for c in candidates]
        rsis       = [c.get('rsi', 50) for c in candidates if c.get('rsi') is not None]
        rvols      = [c.get('rvol', 1) for c in candidates]
        trends     = [c.get('trend', 'neutral') for c in candidates]

        # Above/below VWAP ratio
        above_vwap = sum(1 for c in candidates
                        if c.get('ltp', 0) > (c.get('vwap', 0) or c.get('ltp', 0)))
        below_vwap = len(candidates) - above_vwap

        # ATR as % of price (relative volatility)
        rel_atrs = []
        for c in candidates:
            if c.get('ltp', 0) > 0 and c.get('atr', 0) > 0:
                rel_atrs.append(c['atr'] / c['ltp'] * 100)

        # Trend distribution
        uptrends   = trends.count('uptrend')
        downtrends = trends.count('downtrend')
        volatile_c = trends.count('volatile')
        ranging_c  = trends.count('ranging')

        # Average gap (market-wide momentum)
        avg_gap     = statistics.mean(gaps) if gaps else 0
        avg_rsi     = statistics.mean(rsis) if rsis else 50
        avg_rel_atr = statistics.mean(rel_atrs) if rel_atrs else 0
        avg_rvol    = statistics.mean(rvols) if rvols else 1.0

        return {
            'total_stocks':    len(candidates),
            'above_vwap':      above_vwap,
            'below_vwap':      below_vwap,
            'vwap_ratio':      above_vwap / len(candidates) if candidates else 0.5,
            'avg_gap_pct':     round(avg_gap, 2),
            'avg_rsi':         round(avg_rsi, 1),
            'avg_rel_atr':     round(avg_rel_atr, 2),   # % ATR
            'avg_rvol':        round(avg_rvol, 2),
            'uptrend_count':   uptrends,
            'downtrend_count': downtrends,
            'volatile_count':  volatile_c,
            'ranging_count':   ranging_c,
        }

    # ─── INDIA VIX ────────────────────────────────────────────
    def _fetch_india_vix(self) -> Optional[float]:
        """Fetch India VIX from NSE (free, no auth needed)."""
        try:
            import requests
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
                'Referer': 'https://www.nseindia.com',
            }
            session = requests.Session()
            # Warm up session with cookies
            session.get('https://www.nseindia.com', headers=headers, timeout=5)
            resp = session.get(
                'https://www.nseindia.com/api/allIndices',
                headers=headers, timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                for idx in data.get('data', []):
                    if 'VIX' in idx.get('index', '').upper():
                        return float(idx.get('last', 15.0))
        except Exception:
            pass
        return None   # None means unavailable

    # ─── REGIME CLASSIFICATION ────────────────────────────────
    def _classify_regime(self, m: Dict) -> Tuple[str, float, str]:
        """
        Core classification logic.
        Returns (regime_name, confidence_pct, signal_description)
        """
        vix       = m.get('india_vix')
        vwap_r    = m.get('vwap_ratio', 0.5)
        avg_gap   = m.get('avg_gap_pct', 0)
        avg_rsi   = m.get('avg_rsi', 50)
        rel_atr   = m.get('avg_rel_atr', 1.0)
        up_count  = m.get('uptrend_count', 0)
        dn_count  = m.get('downtrend_count', 0)
        vol_count = m.get('volatile_count', 0)
        total     = max(m.get('total_stocks', 1), 1)

        signals = []

        # ── CHECK 1: BLACK SWAN / PANIC ──────────────────────
        if vix and vix > 25:
            signals.append(f"India VIX={vix:.1f} (DANGER > 25)")
            return "BEARISH_PANIC", 95, " | ".join(signals)

        if rel_atr > 3.5 and vwap_r < 0.25:
            signals.append(f"Extreme volatility (ATR={rel_atr:.1f}%) + broad selloff")
            return "BEARISH_PANIC", 88, " | ".join(signals)

        # ── CHECK 2: HIGH VOLATILITY ─────────────────────────
        if rel_atr > 2.5 or vol_count / total > 0.4:
            signals.append(f"High ATR ({rel_atr:.1f}%), volatile stocks={vol_count}/{total}")
            if vwap_r > 0.5:
                signals.append("Bullish tilt")
                return "VOLATILE", 75, " | ".join(signals)
            else:
                return "VOLATILE", 70, " | ".join(signals)

        # ── CHECK 3: STRONG UPTREND ──────────────────────────
        if (vwap_r >= 0.70 and avg_rsi >= 55 and avg_gap >= 0.5
                and up_count / total >= 0.4):
            confidence = min(95, int(vwap_r * 100 + avg_rsi / 10))
            signals.append(f"VWAP ratio={vwap_r:.0%}, RSI={avg_rsi:.0f}, Gap={avg_gap:+.1f}%")
            signals.append(f"Uptrend stocks={up_count}/{total}")
            return "TRENDING_UP", confidence, " | ".join(signals)

        # ── CHECK 4: STRONG DOWNTREND ────────────────────────
        if (vwap_r <= 0.30 and avg_rsi <= 45 and avg_gap <= -0.5
                and dn_count / total >= 0.4):
            confidence = min(95, int((1 - vwap_r) * 100 + (50 - avg_rsi)))
            signals.append(f"VWAP ratio={vwap_r:.0%}, RSI={avg_rsi:.0f}, Gap={avg_gap:+.1f}%")
            signals.append(f"Downtrend stocks={dn_count}/{total}")
            return "TRENDING_DOWN", confidence, " | ".join(signals)

        # ── CHECK 5: SIDEWAYS / RANGING ──────────────────────
        if (0.35 <= vwap_r <= 0.65 and 40 <= avg_rsi <= 60):
            signals.append(f"VWAP ratio={vwap_r:.0%} (balanced), RSI={avg_rsi:.0f} (neutral)")
            return "SIDEWAYS", 70, " | ".join(signals)

        # ── DEFAULT: MILD TREND ──────────────────────────────
        if vwap_r > 0.55:
            signals.append(f"Mild bullish bias: VWAP={vwap_r:.0%}")
            return "TRENDING_UP", 55, " | ".join(signals)
        elif vwap_r < 0.45:
            signals.append(f"Mild bearish bias: VWAP={vwap_r:.0%}")
            return "TRENDING_DOWN", 55, " | ".join(signals)

        signals.append("No clear regime signal")
        return "UNKNOWN", 40, " | ".join(signals)

    # ─── BUILD RESULT ──────────────────────────────────────────
    def _build_result(self, regime: str, confidence: float,
                      metrics: Dict, signals: str) -> Dict:
        info = REGIME_STRATEGIES.get(regime, REGIME_STRATEGIES["UNKNOWN"])
        return {
            'regime':           regime,
            'confidence':       confidence,
            'description':      info['description'],
            'color':            info['color'],
            'recommended_strategies': info['recommended'],
            'avoid_strategies': info['avoid'],
            'risk_multiplier':  info['risk_multiplier'],
            'signals':          signals,
            'metrics':          metrics,
            'trading_allowed':  regime != "BEARISH_PANIC",
        }

    # ─── STRATEGY FILTER ──────────────────────────────────────
    def filter_strategies_for_regime(self, strategy_key: str, regime: str) -> Dict:
        """
        Given a strategy key and current regime,
        return whether it's recommended, neutral, or avoid.
        """
        info = REGIME_STRATEGIES.get(regime, REGIME_STRATEGIES["UNKNOWN"])
        if strategy_key in info['recommended']:
            return {'fit': 'RECOMMENDED', 'score_boost': 1}
        elif 'ALL' in info['avoid'] or strategy_key in info['avoid']:
            return {'fit': 'AVOID', 'score_boost': -2}
        return {'fit': 'NEUTRAL', 'score_boost': 0}
