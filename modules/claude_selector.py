"""
Module 2 & 3: Claude AI Stock Selector + Strategy Engine
Claude API ko structured prompts bhejta hai:
  - Stock selection with Conviction Score (1-10)
  - Dynamic strategy selection from 20-strategy library
"""

import json
import anthropic
from datetime import datetime
from typing import List, Dict, Optional


# ─── 20-STRATEGY LIBRARY ─────────────────────────────────────────────────────
STRATEGY_LIBRARY = {
    "VWAP_CROSSOVER": {
        "name":        "VWAP Crossover & Pullbacks",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "medium",
        "timeframe":   "5-15 min",
        "description": "Trade pullbacks to VWAP after a confirmed crossover. Long above VWAP, short below.",
        "entry_rule":  "Price pulls back to VWAP after crossover, candle closes in trend direction",
        "stop_rule":   "Below VWAP (long) / Above VWAP (short), 0.5% buffer",
        "target_rule": "1.5x-2x risk reward, or next pivot",
    },
    "ORB": {
        "name":        "Opening Range Breakout (ORB)",
        "best_for":    ["uptrend", "downtrend", "volatile"],
        "volatility":  "high",
        "timeframe":   "15-30 min ORB",
        "description": "Trade breakout of first 15/30-min candle high or low with volume confirmation.",
        "entry_rule":  "Price closes above/below opening range with 1.5x average volume",
        "stop_rule":   "Opposite side of opening range",
        "target_rule": "1x opening range width as target",
    },
    "MEAN_REVERSION": {
        "name":        "Mean Reversion (Bollinger Band Snaps)",
        "best_for":    ["ranging", "volatile"],
        "volatility":  "high",
        "timeframe":   "5-15 min",
        "description": "Fade extreme moves when price touches outer Bollinger Bands with RSI divergence.",
        "entry_rule":  "Price touches 2SD band + RSI > 70 or < 30 + reversal candle",
        "stop_rule":   "Beyond band by 0.3%",
        "target_rule": "VWAP or middle band",
    },
    "GAP_AND_GO": {
        "name":        "Gap and Go Momentum",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "high",
        "timeframe":   "First 30 min",
        "description": "Trade in the direction of the pre-market gap after a brief consolidation/pullback.",
        "entry_rule":  "Gap > 2%, first 5-min pullback to VWAP or prev resistance, then new high",
        "stop_rule":   "Below the pullback low",
        "target_rule": "Gap fill or 2x ATR extension",
    },
    "PIVOT_REVERSALS": {
        "name":        "Standard Pivot Point Reversals",
        "best_for":    ["ranging", "neutral"],
        "volatility":  "medium",
        "timeframe":   "15-30 min",
        "description": "Trade reversals at daily pivot, R1, R2, S1, S2 levels.",
        "entry_rule":  "Price reaches pivot level + rejection candle pattern",
        "stop_rule":   "Beyond next pivot level",
        "target_rule": "Next pivot level in direction",
    },
    "RSI_DIVERGENCE": {
        "name":        "RSI Divergence (Hidden & Regular)",
        "best_for":    ["uptrend", "downtrend", "neutral"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Trade regular divergence for reversals, hidden divergence for trend continuation.",
        "entry_rule":  "RSI divergence confirmed + volume spike on signal candle",
        "stop_rule":   "Beyond the divergence swing point",
        "target_rule": "1:2 R/R minimum",
    },
    "MA_RIBBON": {
        "name":        "Moving Average Ribbon Expansions",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Enter when MA ribbon (8/21/50 EMA) expands in one direction after compression.",
        "entry_rule":  "All EMAs aligned + ribbon expanding + price above/below all EMAs",
        "stop_rule":   "Below 8 EMA (long) / Above 8 EMA (short)",
        "target_rule": "Ribbon contraction or 2x ATR",
    },
    "MACD_HISTOGRAM": {
        "name":        "MACD Histogram Crossovers",
        "best_for":    ["uptrend", "downtrend", "neutral"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Trade MACD line crossing signal line with expanding histogram.",
        "entry_rule":  "Histogram crosses zero line + MACD cross above/below signal",
        "stop_rule":   "Previous swing low/high",
        "target_rule": "1:1.5 R/R",
    },
    "FIBONACCI_BOUNCE": {
        "name":        "Fibonacci Retracement Intraday Bounces",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "medium",
        "timeframe":   "15-30 min",
        "description": "Buy/short at key Fibonacci retracement levels (38.2%, 50%, 61.8%) within a trend.",
        "entry_rule":  "Price pulls back to Fib level + bullish/bearish engulfing candle",
        "stop_rule":   "Below next Fib level",
        "target_rule": "Previous swing high/low (100% extension)",
    },
    "SUPERTREND": {
        "name":        "Supertrend Indicator Pullbacks",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Trade pullbacks to the Supertrend line in a trending market.",
        "entry_rule":  "Price touches Supertrend line from trend side + small rejection candle",
        "stop_rule":   "Supertrend line flip (opposite side)",
        "target_rule": "ATR-based target (2x ATR)",
    },
    "INSIDE_BAR_NR7": {
        "name":        "Inside Bar / NR7 Breakouts",
        "best_for":    ["neutral", "ranging"],
        "volatility":  "low",
        "timeframe":   "15-30 min",
        "description": "Trade breakout of Inside Bar or Narrowest Range 7-day candle with volume.",
        "entry_rule":  "NR7 identified + breakout candle with 2x volume",
        "stop_rule":   "Below/Above the NR7 candle",
        "target_rule": "2x the NR7 range",
    },
    "CUP_HANDLE": {
        "name":        "Intraday Cup and Handle Breakouts",
        "best_for":    ["uptrend"],
        "volatility":  "medium",
        "timeframe":   "15-30 min",
        "description": "Trade the handle breakout of an intraday cup formation above VWAP.",
        "entry_rule":  "Cup + handle formed above VWAP, handle breakout with volume",
        "stop_rule":   "Bottom of handle",
        "target_rule": "Cup depth projected from breakout",
    },
    "CAMARILLA": {
        "name":        "Camarilla Equation Pivot Trading",
        "best_for":    ["ranging", "volatile"],
        "volatility":  "high",
        "timeframe":   "5-15 min",
        "description": "Trade reversals at Camarilla H3/L3 levels, breakouts at H4/L4.",
        "entry_rule":  "Price reaches H3/L3 + reversal signal, or breaks H4/L4 with momentum",
        "stop_rule":   "H4/L4 levels respectively",
        "target_rule": "Opposite Camarilla level",
    },
    "DONCHIAN_BREAKOUT": {
        "name":        "Donchian Channel Breakouts",
        "best_for":    ["uptrend", "downtrend", "volatile"],
        "volatility":  "high",
        "timeframe":   "15 min",
        "description": "Trade breakouts of 20-period Donchian Channel with volume confirmation.",
        "entry_rule":  "Price breaks 20-period high/low + volume 1.5x average",
        "stop_rule":   "Mid-channel line",
        "target_rule": "Channel width projected",
    },
    "VPT_BREAKOUT": {
        "name":        "Volume Price Trend (VPT) Breakouts",
        "best_for":    ["uptrend", "downtrend"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Trade when VPT breaks out of consolidation, confirming price breakout.",
        "entry_rule":  "VPT rising/falling strongly while price breaks key level",
        "stop_rule":   "Below breakout candle low",
        "target_rule": "1:2 R/R minimum",
    },
    "VSA": {
        "name":        "Volume Spread Analysis (VSA)",
        "best_for":    ["uptrend", "downtrend", "neutral"],
        "volatility":  "medium",
        "timeframe":   "5-15 min",
        "description": "Read institutional activity through volume and spread relationships.",
        "entry_rule":  "High-volume narrow spread (absorption) or ultra-high volume reversal bar",
        "stop_rule":   "Below the high-volume bar",
        "target_rule": "Previous high/low or 1.5x risk",
    },
    "INSTITUTIONAL_SR": {
        "name":        "Institutional Support/Resistance Bounces",
        "best_for":    ["ranging", "neutral"],
        "volatility":  "medium",
        "timeframe":   "15-30 min",
        "description": "Trade bounces from round numbers and high-volume nodes (HVN).",
        "entry_rule":  "Price tests S/R level 2nd+ time + volume drops at test + reversal candle",
        "stop_rule":   "Beyond S/R by 0.5%",
        "target_rule": "Next major S/R level",
    },
    "ORDER_FLOW_SCALP": {
        "name":        "Order Flow / Tape Reading Scalps",
        "best_for":    ["uptrend", "downtrend", "volatile"],
        "volatility":  "very_high",
        "timeframe":   "1-5 min",
        "description": "Read bid-ask imbalances and large order absorption for quick scalps.",
        "entry_rule":  "Large bid/ask stacking + market orders clearing one side",
        "stop_rule":   "Tight: 3-5 ticks",
        "target_rule": "5-10 ticks or momentum exhaustion",
    },
    "TIME_OF_DAY": {
        "name":        "Time-of-Day Momentum (2:00 PM Breakouts)",
        "best_for":    ["neutral", "ranging"],
        "volatility":  "medium",
        "timeframe":   "Specific time windows",
        "description": "Trade the 9:15-9:45 AM opening momentum and 1:30-2:30 PM afternoon breakouts.",
        "entry_rule":  "Strong directional move at key time window with above-average volume",
        "stop_rule":   "Below/above the 5-min candle that triggered",
        "target_rule": "ATR extension",
    },
    "MACD_FULL": {
        "name":        "MACD Full Signal",
        "best_for":    ["uptrend", "downtrend", "neutral"],
        "volatility":  "medium",
        "timeframe":   "15 min",
        "description": "Classic MACD crossover with zero-line respect for trend confirmation.",
        "entry_rule":  "MACD crosses signal above/below zero line",
        "stop_rule":   "Swing point before signal",
        "target_rule": "Previous major high/low",
    },
}


class ClaudeSelector:
    def __init__(self, api_key: str, model: str = "claude-opus-4-5"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model  = model

    # ─── STOCK SELECTION ─────────────────────────────────────
    def select_stocks(self, candidates: List[Dict], market_context: Dict = None) -> Dict:
        """
        Claude ko candidates bhejo, woh top 3 stocks + conviction scores return karega.
        """
        if not candidates:
            return {"error": "No candidates to evaluate", "selections": []}

        prompt = self._build_selection_prompt(candidates, market_context)
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=self._selection_system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            raw = message.content[0].text
            return self._parse_selection_response(raw, candidates)
        except Exception as e:
            return {"error": str(e), "selections": []}

    # ─── STRATEGY SELECTION ───────────────────────────────────
    def select_strategy(self, stock: Dict) -> Dict:
        """
        Given a selected stock, Claude chooses the best strategy from the library.
        """
        prompt = self._build_strategy_prompt(stock)
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=self._strategy_system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            raw = message.content[0].text
            return self._parse_strategy_response(raw, stock)
        except Exception as e:
            return {"error": str(e), "strategy": None}

    # ─── TRADE PARAMETERS ─────────────────────────────────────
    def generate_trade_params(self, stock: Dict, strategy: Dict, capital: float) -> Dict:
        """
        Final step: Claude generates exact entry, SL, target levels.
        """
        prompt = self._build_trade_prompt(stock, strategy, capital)
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=self._trade_system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            raw = message.content[0].text
            return self._parse_trade_params(raw, stock)
        except Exception as e:
            return {"error": str(e)}

    # ─── PROMPT BUILDERS ──────────────────────────────────────

    def _selection_system_prompt(self) -> str:
        return """You are an elite intraday trading analyst specializing in Indian equity markets (NSE).
Your job is to evaluate a list of stock candidates and select the TOP 3 with the highest probability of a profitable intraday trade today.

You MUST respond in this exact JSON format and nothing else:
{
  "selections": [
    {
      "rank": 1,
      "symbol": "SYMBOL",
      "conviction_score": 8,
      "direction": "LONG",
      "primary_reason": "One clear sentence why this stock",
      "key_levels": {"support": 0.0, "resistance": 0.0, "vwap": 0.0},
      "risk_note": "One sentence on main risk"
    }
  ],
  "market_bias": "BULLISH/BEARISH/NEUTRAL",
  "analyst_note": "One overall market comment"
}

Conviction score 1-10 where 7+ means trade it, below 7 means skip.
Direction must be LONG or SHORT based on trend and setup.
Be precise with key levels — use the actual price data provided."""

    def _build_selection_prompt(self, candidates: List[Dict], market_context: Dict) -> str:
        time_now = datetime.now().strftime("%H:%M")
        day      = datetime.now().strftime("%A, %d %B %Y")

        lines = [
            f"DATE: {day}  TIME: {time_now} IST",
            f"MARKET SESSION: {'Opening (9:15-10:30)' if datetime.now().hour < 10 else 'Mid-session' if datetime.now().hour < 13 else 'Afternoon'}",
            "",
            "SCANNED CANDIDATES (filtered by RVOL, ATR, liquidity):",
            ""
        ]
        for c in candidates:
            lines.append(
                f"STOCK: {c['symbol']}\n"
                f"  LTP: ₹{c['ltp']}  |  Open: ₹{c['open']}  |  High: ₹{c['high']}  |  Low: ₹{c['low']}\n"
                f"  Prev Close: ₹{c['prev_close']}  |  Gap: {c['gap_pct']:+.2f}%\n"
                f"  Volume: {c['volume']:,}  |  Avg Volume: {c['avg_volume']:,}  |  RVOL: {c['rvol']}x\n"
                f"  ATR: ₹{c['atr']}  |  VWAP: ₹{c.get('vwap','N/A')}  |  RSI: {c.get('rsi','N/A')}\n"
                f"  Trend Classification: {c['trend'].upper()}\n"
            )

        if market_context:
            lines.append(f"\nMARKET CONTEXT:\n{json.dumps(market_context, indent=2)}")

        lines.append("\nAnalyze all candidates. Select the best 3. Respond ONLY in the required JSON format.")
        return "\n".join(lines)

    def _strategy_system_prompt(self) -> str:
        strategy_names = "\n".join([f"- {k}: {v['name']}" for k, v in STRATEGY_LIBRARY.items()])
        return f"""You are a quantitative strategy selector for intraday trading on NSE India.
Given a stock's current market behavior, select the SINGLE best strategy from this library:

{strategy_names}

Respond ONLY in this exact JSON format:
{{
  "strategy_key": "STRATEGY_KEY_FROM_LIBRARY",
  "strategy_name": "Full strategy name",
  "reasoning": "2-3 sentences explaining why this strategy fits this stock right now",
  "setup_conditions": ["condition 1", "condition 2", "condition 3"],
  "confirmation_needed": "What price action to wait for before entering",
  "time_validity": "How long this setup is valid (e.g., next 30 minutes)"
}}"""

    def _build_strategy_prompt(self, stock: Dict) -> str:
        return f"""Select the best intraday strategy for this stock:

SYMBOL: {stock['symbol']}
LTP: ₹{stock['ltp']}
Trend: {stock.get('trend', 'unknown').upper()}
Gap: {stock.get('gap_pct', 0):+.2f}%
RVOL: {stock.get('rvol', 0)}x
ATR: ₹{stock.get('atr', 0)}
RSI: {stock.get('rsi', 'N/A')}
VWAP: ₹{stock.get('vwap', 'N/A')}
Direction: {stock.get('direction', 'LONG')}
Time: {datetime.now().strftime('%H:%M')} IST

Conviction Score: {stock.get('conviction_score', 7)}/10

Choose the mathematically best strategy. Respond ONLY in required JSON format."""

    def _trade_system_prompt(self) -> str:
        return """You are a precision trade execution planner for Indian equity markets.
Generate exact trade parameters with specific price levels.

Respond ONLY in this exact JSON format:
{
  "entry_price": 0.0,
  "entry_type": "LIMIT/MARKET/STOP_LIMIT",
  "stop_loss": 0.0,
  "target_1": 0.0,
  "target_2": 0.0,
  "quantity": 0,
  "risk_amount": 0.0,
  "reward_amount": 0.0,
  "rr_ratio": 0.0,
  "position_side": "BUY/SELL",
  "order_notes": "Any specific execution notes"
}
All prices in INR. Quantity must be a whole number. Be precise."""

    def _build_trade_prompt(self, stock: Dict, strategy: Dict, capital: float) -> str:
        strat_info = STRATEGY_LIBRARY.get(strategy.get("strategy_key", ""), {})
        return f"""Generate exact trade parameters:

STOCK: {stock['symbol']}
LTP: ₹{stock['ltp']}
High: ₹{stock.get('high', 0)}  Low: ₹{stock.get('low', 0)}
VWAP: ₹{stock.get('vwap', 'N/A')}
ATR: ₹{stock.get('atr', 0)}
Direction: {stock.get('direction', 'LONG')}
Support: ₹{stock.get('key_levels', {}).get('support', 0)}
Resistance: ₹{stock.get('key_levels', {}).get('resistance', 0)}

STRATEGY: {strategy.get('strategy_name', '')}
Entry Rule: {strat_info.get('entry_rule', '')}
Stop Rule: {strat_info.get('stop_rule', '')}
Target Rule: {strat_info.get('target_rule', '')}
Confirmation needed: {strategy.get('confirmation_needed', '')}

CAPITAL AVAILABLE: ₹{capital:,.0f}
MAX RISK PER TRADE: 1% of capital = ₹{capital * 0.01:,.0f}

Calculate quantity so that if stop loss is hit, loss ≤ ₹{capital * 0.01:,.0f}
Respond ONLY in required JSON format."""

    # ─── RESPONSE PARSERS ──────────────────────────────────────

    def _parse_selection_response(self, raw: str, candidates: List[Dict]) -> Dict:
        try:
            # Strip any markdown fences
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = "\n".join(clean.split("\n")[:-1])
            data = json.loads(clean.strip())

            # Enrich selections with original candidate data
            for sel in data.get("selections", []):
                orig = next((c for c in candidates if c["symbol"] == sel["symbol"]), {})
                sel.update({k: v for k, v in orig.items() if k not in sel})

            return data
        except Exception as e:
            return {
                "error": f"Parse error: {e}. Raw: {raw[:200]}",
                "selections": [],
                "market_bias": "NEUTRAL",
                "analyst_note": "Parse error occurred"
            }

    def _parse_strategy_response(self, raw: str, stock: Dict) -> Dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = "\n".join(clean.split("\n")[:-1])
            data = json.loads(clean.strip())

            # Attach full strategy details from library
            sk = data.get("strategy_key", "")
            if sk in STRATEGY_LIBRARY:
                data["strategy_details"] = STRATEGY_LIBRARY[sk]

            return data
        except Exception as e:
            return {"error": f"Parse error: {e}", "strategy_key": None}

    def _parse_trade_params(self, raw: str, stock: Dict) -> Dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = "\n".join(clean.split("\n")[:-1])
            data = json.loads(clean.strip())
            data["symbol"]      = stock["symbol"]
            data["security_id"] = stock.get("security_id", "")
            data["generated_at"] = datetime.now().isoformat()
            return data
        except Exception as e:
            return {"error": f"Parse error: {e}"}
