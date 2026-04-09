# Intraday Trading Agent — v4

> "A robust system survives when it's wrong. A perfect system dies on the first unexpected move."

Autonomous AI-powered intraday trading agent for NSE India.
Gemini (research) → Claude (decision) → DhanHQ (execution).

---

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000 → Settings → Dashboard → START
# PAPER MODE FIRST. Always.
```

---

## Project Structure

```
trading_agent/
├── app.py                      Flask app + all API routes
├── requirements.txt
├── README.md
├── .gitignore
│
├── modules/
│   ├── config_manager.py       Settings (data/config.json)
│   ├── dhan_connector.py       DhanHQ auth
│   ├── claude_connector.py     Claude API auth
│   ├── market_scanner.py       180 F&O → top 80 → 15 candidates  [v4]
│   ├── osint_gatherer.py       feedparser + trafilatura + Gemini parallel  [v4]
│   ├── regime_detector.py      TRENDING/SIDEWAYS/VOLATILE/PANIC detection
│   ├── multi_ai.py             Gemini (research) → Claude (decision) pipeline
│   ├── claude_selector.py      20-strategy library + trade params
│   ├── risk_manager.py         Kelly + jail + slippage + black swan  [v4]
│   ├── order_executor.py       DhanHQ bracket orders (paper + live)
│   ├── memory_manager.py       Persistent memory → Memory.md
│   └── agent_brain.py          Full autonomous loop — all stages  [v4]
│
├── templates/
│   ├── settings.html
│   ├── dashboard.html
│   └── memory.html
│
└── data/                       Auto-created, gitignored
    ├── config.json             API keys (never commit)
    ├── trades.json
    ├── pnl.json
    ├── strategy_jail.json
    └── memory/
        ├── agent_memory.json
        └── Memory.md           Human-readable (auto-generated)
```

---

## API Keys Required

| Key | Source | Cost |
|-----|--------|------|
| DhanHQ Client ID | dhanhq.co → Profile | Free |
| DhanHQ Access Token | dhanhq.co → Developer | Free |
| Claude API Key | console.anthropic.com | Pay per use |
| Gemini API Key | aistudio.google.com | Free tier available |
| Telegram API ID + Hash | my.telegram.org | Free, optional |
| NewsAPI Key | newsapi.org | Optional, free 100/day |
| Alpha Vantage Key | alphavantage.co | Optional, free tier |

Minimum required: DhanHQ + Claude. Gemini strongly recommended.

---

## v4 Agent Loop (9:30 AM – 3:15 PM IST)

```
STAGE 1 — MARKET SCAN
  180 NSE F&O universe
  Stage 1a: prev-day volume → top 80
  Stage 1b: RVOL + ATR + Gap% → top 15 candidates
  Sector multiplier: 1.0x / 0.75x / 0.0x (weak sector dropped)
  Tech score: RVOL(40%) + ATR(30%) + Gap%(30%)
  scan_price + scan_timestamp saved for stale check

STAGE 2 — OSINT
  feedparser  → ET Markets, MoneyControl, Business Standard RSS
  trafilatura → full text top 3 articles
  Telegram    → whitelisted official channels only
  NSE API     → corporate announcements
  Yahoo       → Nifty + global signals
  Gemini Pro + Flash parallel (5s timeout, CancelledError clean)
  ATR-normalized divergence (anchor = LTP at news fetch time)

STAGE 2b — CONFLICT GATE (saves Multi-AI tokens)
  BEARISH_TRAP divergence  → DROP
  Sentiment delta > 6      → DROP
  Sentiment multiplier: 7-10→1.0x | 5-6→0.75x | 3-4→0.5x | 0-2→0.25x

STAGE 3 — REGIME DETECTION + BLACK SWAN
  TRENDING_UP / TRENDING_DOWN / SIDEWAYS / VOLATILE / BEARISH_PANIC
  Black Swan (VIX>25 / Panic / >80% daily loss / 4+ consec losses)
    → square_off_all() IMMEDIATELY [Bug 1 fixed]

STAGE 4 — MULTI-AI DECISION
  Agent 1 (Gemini): research passed candidates
  Agent 2 (Claude): research + technicals + memory → trade decisions

STAGE 5 — PER-STOCK EXECUTION
  Strategy jail (5 losses → regime stable 3 loops → auto-release) [Bug 2]
  Regime fit check (recommended/neutral/avoid)
  Sector correlation (max 1 per sector, 30+ sectors mapped)
  Stale check: age > 60s OR drift > 0.6% → ABORT [Bug 15]
  Kelly × Sentiment × Sector × Regime multiplier
  Slippage: entry +0.3%, stop-loss -0.3% [Bug 10]
  Bracket order placed

STAGE 6 — LEARN
  Memory updated, Memory.md regenerated
  Auto-learn patterns every 5 cycles
```

---

## Scoring & Size Logic

```
Tech Score = RVOL(40%) + ATR(30%) + Gap%(30%)  [0-10 normalized]

Multipliers (stacked):
  Kelly    = f*(win_rate, odds) × 0.5 safety  [0.25%–2% capital]
  Sentiment = 1.00x / 0.75x / 0.50x / 0.25x
  Sector    = 1.00x / 0.75x / skip
  Regime    = 1.00x / 0.80x / 0.70x / 0.00x (panic)

Final Size = Kelly × Sentiment × Sector × Regime
```

---

## Risk Controls

| Control | Value | Bug Fixed |
|---------|-------|-----------|
| Position Sizing | Kelly Criterion (half-Kelly) | — |
| Slippage Buffer | 0.3% on entry + SL | #10 |
| Daily Loss Limit | 3% → kill switch | — |
| Strategy Jail | 5 losses → 3-loop regime release | #2 |
| Sentiment Gate | Multiplier 0.25x–1.0x | #4 |
| Sector Limit | Max 1 position/sector | — |
| Conflict Gate | Delta > 6 → DROP | #9 |
| Black Swan | EXIT ALL immediately | #1 |
| Noise Window | 9:15–9:30 blocked | #11 |
| Trading Hours | 9:30 AM – 3:15 PM | #11 |
| Stale Data | >60s or >0.6% drift → ABORT | #15 |

---

## Bug Tracker — v4 (All 15 Fixed)

| # | Bug | Severity | Status |
|---|-----|----------|--------|
| 1 | Black Swan exits positions | CRITICAL | ✅ square_off_all() on activation |
| 2 | Strategy jail regime churn | Medium | ✅ 3-loop stability counter |
| 3 | Keyword sentiment unreliable | Medium | ✅ Gemini AI extraction |
| 4 | Sentiment hard gate wrong | Medium | ✅ 0.25x–1.0x multiplier |
| 5 | 30-stock universe too small | Low | ✅ 180 F&O universe |
| 6 | Telegram pump & dump risk | Medium | ✅ Whitelist-only |
| 7 | Gemini ghost connections | Medium | ✅ CancelledError clean close |
| 8 | requirements.txt incomplete | Low | ✅ feedparser, trafilatura, genai |
| 9 | Conflict Gate after Multi-AI | Medium | ✅ Moved to Stage 2b |
| 10 | Slippage not accounted | Medium | ✅ 0.3% buffer added |
| 11 | 9:15–9:30 not filtered | Medium | ✅ Hard block |
| 12 | Sector rotation blind | Low | ✅ Live sector scores from gaps |
| 13 | Divergence 0.2% hardcoded | Medium | ✅ ATR-normalized + anchor |
| 14 | Sector boost flat +0.5 wrong | Medium | ✅ Multiplier not addition |
| 15 | Stale scan data | Medium | ✅ 60s age + 0.6% drift check |

---

## REST API Reference

```
Agent Control:
  POST /api/agent/start         start autonomous loop
  POST /api/agent/stop          stop + save session
  GET  /api/agent/status        full state
  POST /api/agent/kill-switch   emergency stop
  POST /api/agent/square-off    close all positions

Settings:
  POST /api/settings/save
  GET  /api/settings/load       (secrets masked)
  POST /api/settings/test-dhan
  POST /api/settings/test-claude
  POST /api/settings/reset

Data:
  GET  /api/risk/summary        today P&L, win rate
  GET  /api/trades              last 50 trades
  POST /api/scan/run            manual scan
  GET  /api/regime              current regime
  GET  /api/jail                jailed strategies
  POST /api/jail/release        {strategy: "name"}

Memory:
  GET  /api/memory              full memory
  GET  /api/memory/sessions     last 30 sessions
  GET  /api/memory/stats        strategy stats + lessons
  POST /api/memory/add-lesson   {lesson, category}

AI Models:
  GET  /api/ai/models           available models
  POST /api/ai/test-gemini
  POST /api/ai/test-ollama

OSINT:
  GET  /api/osint/<SYMBOL>      full OSINT sweep
  POST /api/osint/batch         {symbols: [...]}
```

---

## WebSocket Events (Server → Client)

| Event | Payload |
|-------|---------|
| `agent_status` | `{status, message}` |
| `scan_update` | `{candidates[], meta}` |
| `osint_update` | `{symbol, sentiment, score, divergence}` |
| `regime_update` | `{regime, confidence, recommended_strategies[]}` |
| `selection_update` | `{selections[], market_bias, reasoning, regime}` |
| `trade_placed` | `{trade_params, kelly_info, multipliers{}}` |
| `risk_update` | `{daily_pnl, win_rate, jailed_strategies[], black_swan_mode}` |
| `black_swan` | `{triggers[], message}` |
| `jail_alert` | `{symbol, strategy, reason}` |
| `streak_alert` | `{streak_count, total_loss}` |
| `correlation_alert` | `{symbol, sector}` |
| `agent_log` | `{level, message, time}` |

---

## Dashboard Pages

| URL | Contents |
|-----|----------|
| `/` | Redirect → settings (first run) or dashboard |
| `/settings` | API keys, trading mode, risk, AI config, OSINT keys |
| `/dashboard` | P&L, regime panel, scanner, AI picks, trades, log, jail panel |
| `/memory` | Sessions, strategy performance, lessons learned |

---

## Stable Modules (Not Changed in v4)

These are production-stable and require no changes:
`order_executor.py`, `regime_detector.py`, `multi_ai.py`,
`claude_selector.py`, `dhan_connector.py`, `claude_connector.py`

---

## Paper Trading Checklist (Before Going Live)

- [ ] Minimum 2 weeks paper trading
- [ ] Win rate >= 45%
- [ ] No single day loss > 3%
- [ ] Black Swan tested (manually trigger high VIX scenario)
- [ ] Kill switch tested
- [ ] Strategy jail triggered + auto-released correctly
- [ ] Memory.md shows progressive lessons over sessions
- [ ] At least 30 paper trades logged

---

*Key insight: Never hardcode percentages in trading algorithms. Always normalize against ATR.*
*Bug #1 confirmed: square_off_all() existed but was never called on Black Swan. Fixed in v4.*
