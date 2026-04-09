"""
Config Manager v2 — supports Multi-AI (Gemini, Claude, Ollama) + OSINT keys
"""
import json, os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'config.json')

DEFAULT_CONFIG = {
    # DhanHQ
    'dhan_client_id': '', 'dhan_access_token': '',
    # Claude
    'claude_api_key': '', 'claude_model': 'claude-opus-4-5',
    # Gemini (NEW)
    'gemini_api_key': '', 'gemini_model': 'gemini-1.5-pro',
    # Ollama (NEW)
    'ollama_enabled': False, 'ollama_base_url': 'http://localhost:11434', 'ollama_model': 'llama3',
    # Multi-AI routing (NEW)
    'researcher_model': 'gemini',   # gemini | ollama | claude
    'decision_model':   'claude',   # claude | gemini | ollama
    # OSINT API keys (NEW)
    'newsapi_key': '', 'alphavantage_key': '',
    # Telegram (NEW v4)
    'telegram_api_id': '', 'telegram_api_hash': '',
    # Trading
    'trading_mode': 'paper', 'trading_style': 'swing_intraday',
    # Risk
    'max_loss_per_trade_pct': 1.0, 'daily_loss_limit_pct': 3.0,
    'max_capital_per_trade': 10000.0, 'total_capital': 100000.0, 'max_open_positions': 3,
    # Scanner
    'rvol_threshold': 1.5, 'min_gap_pct': 2.0, 'min_atr': 5.0, 'min_market_cap': 500.0,
    # Agent
    'autonomous_mode': True, 'scan_interval_min': 5, 'conviction_threshold': 7,
    # Notifications
    'enable_notifications': False, 'notification_email': '',
    'is_configured': False,
}

class ConfigManager:
    def __init__(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

    def load(self) -> dict:
        if not os.path.exists(CONFIG_PATH):
            return DEFAULT_CONFIG.copy()
        try:
            with open(CONFIG_PATH, 'r') as f:
                stored = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(stored)
            return merged
        except Exception:
            return DEFAULT_CONFIG.copy()

    def save(self, config: dict) -> None:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)

    def reset(self) -> None:
        self.save(DEFAULT_CONFIG.copy())

    def get(self, key: str, default=None):
        return self.load().get(key, default)
