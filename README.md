# Intraday Trading Agent — Setup & Run Guide

## 📁 Project Structure

```
trading_agent/
├── app.py                          ← Flask app (all routes)
├── requirements.txt                ← pip dependencies
├── README.md
├── .gitignore
│
├── modules/
│   ├── config_manager.py           ← Settings read/write (data/config.json)
│   ├── dhan_connector.py           ← DhanHQ API connection
│   ├── claude_connector.py         ← Claude API connection
│   ├── market_scanner.py           ← Module 1: Market Scanner
│   ├── claude_selector.py          ← Module 2+3: Stock Selector + Strategy Engine
│   ├── risk_manager.py             ← Module 4: Risk Management
│   ├── order_executor.py           ← Module 5: Order Execution
│   └── agent_brain.py              ← Autonomous Loop (Scan→Select→Execute)
│
├── templates/
│   ├── settings.html               ← Settings page
│   └── dashboard.html              ← Live trading dashboard
│
└── data/                           ← Auto-created, gitignored
    ├── config.json                 ← Your API keys (never commit this)
    ├── trades.json                 ← Trade log
    └── pnl.json                    ← Daily P&L state
```

---

## ⚡ Quick Start

### Step 1 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 2 — Run the server
```bash
python app.py
```

### Step 3 — Open browser
```
http://localhost:5000
```
You'll be redirected to Settings. Fill in your API keys and save.

### Step 4 — Go to Dashboard
Click Dashboard → Press **START AGENT**

---

## 🔑 API Keys You Need

| Key | Where to Get |
|-----|--------------|
| DhanHQ Client ID | dhanhq.co → Profile |
| DhanHQ Access Token | dhanhq.co → Developer → Generate Token |
| Claude API Key | console.anthropic.com → API Keys |

---

## 🔄 Agent Loop (Autonomous)

```
Every N minutes (configurable):
  1. MarketScanner  → Scan 30 NSE stocks
  2. ClaudeSelector → Evaluate candidates, get Conviction Scores
  3. ClaudeSelector → Select strategy for top stocks
  4. ClaudeSelector → Generate entry/SL/target levels
  5. RiskManager    → Validate position size (max 1% loss)
  6. OrderExecutor  → Place bracket order (paper or live)
  7. RiskManager    → Update P&L, check kill switch
```

---

## ⚠️ Risk Controls

- **Max Loss Per Trade**: 1% of capital (configurable)
- **Daily Loss Limit**: 3% (configurable) → kill switch auto-activates
- **Kill Switch**: Stops agent + halts trading for the day
- **Square Off All**: Emergency close all positions at market
- **Max Open Positions**: 1-5 (configurable)
- **Market Hours**: 9:15 AM – 3:15 PM IST (no trades outside)

---

## 🧪 Paper Trading First!

**Always test in PAPER mode before switching to LIVE.**
Paper mode simulates all orders without touching real money.

---

## 📊 Dashboard Features

- **Scanner Tab**: Real-time filtered candidates with RVOL, ATR, Gap%
- **AI Picks Tab**: Claude's top 3 selections with conviction scores
- **Trades Tab**: Full trade log with P&L per trade
- **Agent Log Tab**: Real-time agent thought process

---

## ⚙️ Customization

Edit `modules/market_scanner.py` → `STOCK_UNIVERSE` to change the stocks scanned.
Currently includes 30 high-liquidity NSE F&O stocks.
