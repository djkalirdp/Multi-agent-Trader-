"""
Intraday Trading Agent — Flask Application v4.3
FIXES:
  1. ALL routes now defined BEFORE if __name__ == '__main__'
     (routes after socketio.run() are never registered — that was the /premarket bug)
  2. /api/scan/run — market hours check REMOVED for manual scans
  3. Logging system integrated (data/logs/agent.log)
  4. DhanHQ 503 sandbox better handling
  5. /api/logs endpoint for log viewer
  6. /premarket page route now correctly registered
  7. [v4.3] World Monitor + OSINT routes MOVED before __main__ block (were dead before!)
  8. [v4.3] Gemini test — 60s cooldown per key to avoid quota burn during testing
"""

import os
import json as _json
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit

from modules.config_manager import ConfigManager
from modules.agent_brain    import AgentBrain
from modules.risk_manager   import RiskManager, TRADES_PATH
from modules.logger         import get_logger, read_log_tail

# ─── App setup ────────────────────────────────────────────────
app        = Flask(__name__)
app.secret_key = os.urandom(24)
socketio   = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

config_mgr = ConfigManager()
agent      = AgentBrain(socketio=socketio)
log        = get_logger('app')

# Gemini test cooldown cache: {api_key_prefix: last_test_timestamp}
_gemini_test_cache: dict = {}
GEMINI_TEST_COOLDOWN_SEC = 60  # 60 seconds between real API tests for same key

log.info("=" * 50)
log.info("Trading Agent v4.3 initializing...")
log.info("=" * 50)


# ═══════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    cfg = config_mgr.load()
    return redirect(url_for('settings') if not cfg.get('is_configured') else url_for('dashboard'))

@app.route('/settings')
def settings():
    return render_template('settings.html', config=config_mgr.load())

@app.route('/dashboard')
def dashboard():
    cfg = config_mgr.load()
    if not cfg.get('is_configured'):
        return redirect(url_for('settings'))
    return render_template('dashboard.html', config=cfg)

@app.route('/memory')
def memory_page():
    from modules.memory_manager import MemoryManager
    mem = MemoryManager()
    return render_template('memory.html',
        sessions=mem.get_sessions(30),
        lessons=mem.get_lessons(),
        strategy_stats=mem.get_strategy_stats(),
        config=config_mgr.load()
    )

@app.route('/premarket')
def premarket_page():
    """Pre/after-market watchlist page."""
    wl    = agent.premarket.get_todays_watchlist()
    brief = agent.premarket.get_premarket_brief()
    return render_template('premarket.html',
        watchlist=wl.get('watchlist', []),
        brief=brief,
        config=config_mgr.load()
    )

@app.route('/logs')
def logs_page():
    """Live log viewer."""
    lines = read_log_tail(300)
    return render_template('logs.html', lines=lines, config=config_mgr.load())

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'agent_running': agent.is_running(),
                    'timestamp': datetime.now().isoformat()})


# ═══════════════════════════════════════════════════════════════
#  SETTINGS API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/settings/save', methods=['POST'])
def save_settings():
    try:
        data    = request.get_json()
        required = ['dhan_client_id', 'dhan_access_token', 'claude_api_key']
        missing  = [f for f in required if not data.get(f, '').strip()]
        if missing:
            return jsonify({'success': False, 'message': f'Missing: {", ".join(missing)}'}), 400
        config = {
            'dhan_client_id':          data.get('dhan_client_id','').strip(),
            'dhan_access_token':       data.get('dhan_access_token','').strip(),
            'claude_api_key':          data.get('claude_api_key','').strip(),
            'claude_model':            data.get('claude_model','claude-sonnet-4-5'),
            'gemini_api_key':          data.get('gemini_api_key','').strip(),
            'gemini_model':            data.get('gemini_model','gemini-1.5-flash'),
            'ollama_enabled':          bool(data.get('ollama_enabled',False)),
            'ollama_base_url':         data.get('ollama_base_url','http://localhost:11434').strip(),
            'ollama_model':            data.get('ollama_model','llama3').strip(),
            'researcher_model':        data.get('researcher_model','gemini'),
            'decision_model':          data.get('decision_model','claude'),
            'newsapi_key':             data.get('newsapi_key','').strip(),
            'alphavantage_key':        data.get('alphavantage_key','').strip(),
            'telegram_api_id':         data.get('telegram_api_id','').strip(),
            'telegram_api_hash':       data.get('telegram_api_hash','').strip(),
            'trading_mode':            data.get('trading_mode','paper'),
            'trading_style':           data.get('trading_style','swing_intraday'),
            'max_loss_per_trade_pct':  float(data.get('max_loss_per_trade_pct',1.0)),
            'daily_loss_limit_pct':    float(data.get('daily_loss_limit_pct',3.0)),
            'max_capital_per_trade':   float(data.get('max_capital_per_trade',10000)),
            'total_capital':           float(data.get('total_capital',100000)),
            'max_open_positions':      int(data.get('max_open_positions',3)),
            'max_positions_per_sector':int(data.get('max_positions_per_sector',1)),
            'rvol_threshold':          float(data.get('rvol_threshold',1.5)),
            'min_gap_pct':             float(data.get('min_gap_pct',2.0)),
            'min_atr':                 float(data.get('min_atr',5.0)),
            'min_market_cap':          float(data.get('min_market_cap',500)),
            'autonomous_mode':         bool(data.get('autonomous_mode',True)),
            'scan_interval_min':       int(data.get('scan_interval_min',5)),
            'conviction_threshold':    int(data.get('conviction_threshold',7)),
            'enable_notifications':    bool(data.get('enable_notifications',False)),
            'notification_email':      data.get('notification_email','').strip(),
            'is_configured':           True,
        }
        config_mgr.save(config)
        log.info(f"Settings saved by user. Mode: {config['trading_mode']}")
        return jsonify({'success': True, 'message': 'Settings saved!'})
    except Exception as e:
        log.error(f"save_settings error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings/load', methods=['GET'])
def load_settings():
    cfg  = config_mgr.load()
    safe = cfg.copy()
    for f in ['dhan_access_token','claude_api_key','gemini_api_key','newsapi_key','alphavantage_key']:
        v = safe.get(f,'')
        if v: safe[f] = v[:4]+'••••••••'+v[-4:] if len(v)>8 else '••••••••'
    return jsonify({'success': True, 'config': safe})

@app.route('/api/settings/test-dhan', methods=['POST'])
def test_dhan():
    from modules.dhan_connector import DhanConnector
    d      = request.get_json()
    result = DhanConnector(d.get('dhan_client_id',''), d.get('dhan_access_token','')).test_connection()
    log.info(f"DhanHQ test: {'OK' if result['success'] else 'FAIL'} — {result['message'][:80]}")
    return jsonify(result)

@app.route('/api/settings/test-claude', methods=['POST'])
def test_claude():
    from modules.claude_connector import ClaudeConnector
    d      = request.get_json()
    result = ClaudeConnector(d.get('claude_api_key',''), d.get('claude_model','claude-sonnet-4-5')).test_connection()
    log.info(f"Claude test: {'OK' if result['success'] else 'FAIL'} — {result['message'][:80]}")
    return jsonify(result)

@app.route('/api/settings/reset', methods=['POST'])
def reset_settings():
    config_mgr.reset()
    log.warning("Settings reset to defaults")
    return jsonify({'success': True, 'message': 'Settings reset.'})


# ═══════════════════════════════════════════════════════════════
#  AGENT CONTROL API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/agent/start', methods=['POST'])
def agent_start():
    result = agent.start()
    log.info(f"Agent start: {result['message']}")
    return jsonify(result)

@app.route('/api/agent/stop', methods=['POST'])
def agent_stop():
    result = agent.stop()
    log.info(f"Agent stop: {result['message']}")
    return jsonify(result)

@app.route('/api/agent/status', methods=['GET'])
def agent_status():
    return jsonify({'running': agent.is_running(), **agent.get_state()})

@app.route('/api/agent/kill-switch', methods=['POST'])
def agent_kill_switch():
    cfg  = config_mgr.load()
    risk = RiskManager(cfg)
    agent.stop()
    risk.force_kill_switch()
    log.warning("KILL SWITCH activated by user")
    return jsonify({'success': True, 'message': 'Kill switch activated. Agent stopped.'})

@app.route('/api/agent/reset-kill-switch', methods=['POST'])
def reset_kill_switch():
    RiskManager(config_mgr.load()).reset_kill_switch()
    log.info("Kill switch reset by user")
    return jsonify({'success': True, 'message': 'Kill switch reset.'})

@app.route('/api/agent/reset-black-swan', methods=['POST'])
def reset_black_swan():
    RiskManager(config_mgr.load()).reset_black_swan()
    log.info("Black Swan mode reset by user")
    return jsonify({'success': True, 'message': 'Black Swan mode reset.'})

@app.route('/api/agent/square-off', methods=['POST'])
def square_off():
    cfg  = config_mgr.load()
    from modules.order_executor import OrderExecutor
    result = OrderExecutor(cfg['dhan_client_id'], cfg['dhan_access_token'],
                           cfg.get('trading_mode','paper')).square_off_all()
    agent.stop()
    log.warning(f"Square off all: {result}")
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════
#  DATA API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/risk/summary', methods=['GET'])
def risk_summary():
    return jsonify(RiskManager(config_mgr.load()).get_summary())

@app.route('/api/trades', methods=['GET'])
def get_trades():
    if not os.path.exists(TRADES_PATH):
        return jsonify({'trades': []})
    try:
        with open(TRADES_PATH) as f:
            trades = _json.load(f)
        return jsonify({'trades': trades[-50:]})
    except Exception:
        return jsonify({'trades': []})

@app.route('/api/scan/run', methods=['POST'])
def manual_scan():
    """
    Manual scan — NO market hours check.
    User can scan anytime to test API and see candidates.
    Only the autonomous agent loop respects market hours.
    """
    cfg = config_mgr.load()
    if not cfg.get('dhan_client_id') or not cfg.get('dhan_access_token'):
        return jsonify({
            'candidates': [], 'scan_meta': {},
            'errors': ['DhanHQ credentials not set. Go to Settings and save your Client ID and Access Token.']
        })
    try:
        from modules.market_scanner import MarketScanner
        scanner = MarketScanner(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg)
        result  = scanner.scan()
        n = len(result.get('candidates',[]))
        log.info(f"Manual scan: {n} candidates found")
        return jsonify(result)
    except Exception as e:
        log.error(f"Manual scan error: {e}", exc_info=True)
        return jsonify({'candidates':[], 'scan_meta':{}, 'errors':[str(e)]})


# ═══════════════════════════════════════════════════════════════
#  MEMORY API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/memory', methods=['GET'])
def get_memory():
    return jsonify(agent.get_memory())

@app.route('/api/memory/sessions', methods=['GET'])
def get_sessions():
    from modules.memory_manager import MemoryManager
    return jsonify({'sessions': MemoryManager().get_sessions(30)})

@app.route('/api/memory/stats', methods=['GET'])
def get_memory_stats():
    from modules.memory_manager import MemoryManager
    mem = MemoryManager()
    return jsonify({
        'strategy_stats': mem.get_strategy_stats(),
        'sessions':       mem.get_sessions(5),
        'lessons':        mem.get_lessons()[-10:],
    })

@app.route('/api/memory/add-lesson', methods=['POST'])
def add_lesson():
    from modules.memory_manager import MemoryManager
    data = request.get_json()
    MemoryManager().add_lesson(data.get('lesson',''), data.get('category','manual'))
    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════════
#  OSINT API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/osint/<symbol>', methods=['GET'])
def get_osint(symbol):
    from modules.osint_gatherer import OSINTGatherer
    return jsonify(OSINTGatherer(config_mgr.load()).gather(symbol.upper()))

@app.route('/api/osint/batch', methods=['POST'])
def osint_batch():
    symbols = request.get_json().get('symbols', [])
    from modules.osint_gatherer import OSINTGatherer
    return jsonify(OSINTGatherer(config_mgr.load()).gather_batch(symbols))


# ═══════════════════════════════════════════════════════════════
#  MULTI-AI API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/ai/models', methods=['GET'])
def get_ai_models():
    from modules.multi_ai import MultiAIOrchestrator
    cfg  = config_mgr.load()
    orch = MultiAIOrchestrator(cfg)
    return jsonify({'models': orch.get_available_models(),
                    'researcher_model': cfg.get('researcher_model','gemini'),
                    'decision_model':   cfg.get('decision_model','claude')})

@app.route('/api/ai/test-gemini', methods=['POST'])
def test_gemini():
    """
    Test Gemini API key.
    COOLDOWN: Same key tested within 60s → return cached result (no real API call).
    Prevents quota burn during repeated testing in Settings page.
    """
    from modules.multi_ai import GeminiAdapter
    d     = request.get_json()
    key   = d.get('gemini_api_key','').strip()
    model = d.get('gemini_model','gemini-1.5-flash')

    if not key:
        return jsonify({'success': False, 'message': 'Gemini API key is empty. Get it free at aistudio.google.com → Get API Key'})
    if not key.startswith('AIza'):
        return jsonify({'success': False, 'message': f'Invalid Gemini key format (got: {key[:8]}...). Gemini keys start with "AIza..."'})

    # ── Cooldown check ──────────────────────────────────────────
    cache_key = key[:12]  # Use key prefix as cache identifier
    now = time.time()
    cached = _gemini_test_cache.get(cache_key)
    if cached:
        elapsed = now - cached['ts']
        if elapsed < GEMINI_TEST_COOLDOWN_SEC:
            wait = int(GEMINI_TEST_COOLDOWN_SEC - elapsed)
            log.info(f"Gemini test CACHED ({int(elapsed)}s ago): {cached['result']['message'][:60]}")
            result = cached['result'].copy()
            if result['success']:
                result['message'] += f' [Cached — retesting in {wait}s]'
            else:
                result['message'] += f' [Cached — retesting in {wait}s]'
            return jsonify(result)
    # ── Real API call ────────────────────────────────────────────
    try:
        g = GeminiAdapter(key, model)
        r = g.chat("You are a test.", "Reply: GEMINI_OK", max_tokens=10)
        log.info(f"Gemini test OK: {model}")
        result = {'success': True, 'message': f'Gemini connected! Model: {model}'}
    except Exception as e:
        err = str(e)
        log.warning(f"Gemini test fail: {err[:80]}")
        if '429' in err or 'quota' in err.lower():
            result = {'success': False, 'message': 'Rate limited (429). Your key is valid but hit the free quota. Wait 1 minute and try again.'}
        elif '403' in err or 'permission' in err.lower():
            result = {'success': False, 'message': 'Permission denied (403). Enable Generative Language API at console.cloud.google.com'}
        elif '400' in err:
            result = {'success': False, 'message': f'Bad request: {err[:150]}. Check model name.'}
        else:
            result = {'success': False, 'message': err[:200]}

    # Cache the result regardless of success/fail
    _gemini_test_cache[cache_key] = {'ts': now, 'result': result}
    return jsonify(result)

@app.route('/api/ai/test-ollama', methods=['POST'])
def test_ollama():
    from modules.multi_ai import OllamaAdapter
    d = request.get_json()
    try:
        o = OllamaAdapter(d.get('ollama_base_url','http://localhost:11434'), d.get('ollama_model','llama3'))
        if o.is_available():
            return jsonify({'success': True, 'message': f'Ollama running! Models: {", ".join(o.list_models()[:5])}'})
        return jsonify({'success': False, 'message': 'Ollama not running. Start with: ollama serve'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ═══════════════════════════════════════════════════════════════
#  REGIME + JAIL API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/regime', methods=['GET'])
def get_regime():
    return jsonify(agent.last_regime or {'regime':'UNKNOWN','confidence':0,'trading_allowed':True})

@app.route('/api/jail', methods=['GET'])
def get_jail():
    return jsonify({'jailed': RiskManager(config_mgr.load()).get_jailed_strategies()})

@app.route('/api/jail/release', methods=['POST'])
def release_from_jail():
    strategy = request.get_json().get('strategy','')
    if not strategy: return jsonify({'success':False,'message':'strategy required'}),400
    return jsonify(agent.release_strategy(strategy))

@app.route('/api/jail/add', methods=['POST'])
def jail_manually():
    data = request.get_json()
    RiskManager(config_mgr.load()).jail_strategy(data.get('strategy',''), data.get('reason','Manual jail'))
    return jsonify({'success': True})

@app.route('/api/risk/kelly-preview', methods=['POST'])
def kelly_preview():
    data = request.get_json()
    risk = RiskManager(config_mgr.load())
    return jsonify(risk.calculate_position_size(
        float(data.get('entry',0)), float(data.get('stop_loss',0)),
        data.get('strategy',''), float(data.get('regime_multiplier',1.0))
    ))


# ═══════════════════════════════════════════════════════════════
#  PRE/AFTER-MARKET API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/premarket/watchlist', methods=['GET'])
def get_watchlist():
    wl = agent.premarket.get_todays_watchlist()
    return jsonify(wl if wl else {'message':'No watchlist yet. Runs at 3:30 PM after market close.'})

@app.route('/api/premarket/brief', methods=['GET'])
def get_premarket_brief():
    brief = agent.premarket.get_premarket_brief()
    return jsonify(brief if brief else {'message':'No pre-market brief yet. Runs at 8:45 AM.'})

@app.route('/api/premarket/run-aftermarket', methods=['POST'])
def run_aftermarket_now():
    threading.Thread(target=agent.premarket._run_after_market, daemon=True).start()
    log.info("After-market scan triggered manually")
    return jsonify({'success':True,'message':'After-market scan started. Check /premarket page.'})

@app.route('/api/premarket/run-premarket', methods=['POST'])
def run_premarket_now():
    threading.Thread(target=agent.premarket._run_pre_market, daemon=True).start()
    log.info("Pre-market brief triggered manually")
    return jsonify({'success':True,'message':'Pre-market brief started. Check /premarket page.'})


# ═══════════════════════════════════════════════════════════════
#  LOGS API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/logs', methods=['GET'])
def get_logs():
    n = int(request.args.get('n', 200))
    return jsonify({'lines': read_log_tail(n)})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    from modules.logger import LOG_DIR
    try:
        log_file = os.path.join(LOG_DIR, 'agent.log')
        open(log_file, 'w').close()
        log.info("Log file cleared by user")
        return jsonify({'success': True, 'message': 'Log cleared.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ═══════════════════════════════════════════════════════════════
#  WORLD MONITOR + OSINT STATUS API
#  !! MUST BE BEFORE if __name__ == '__main__' !!
#  (Routes defined after socketio.run() are NEVER registered)
# ═══════════════════════════════════════════════════════════════

def _classify_news(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ['india','nse','bse','nifty','sensex','rupee','rbi']):
        return 'india'
    if any(w in text for w in ['fed','dollar','nasdaq','s&p','dow','wall street','usa','treasury']):
        return 'usa'
    if any(w in text for w in ['china','yuan','hang seng','shanghai']):
        return 'asia'
    if any(w in text for w in ['europe','ecb','euro','ftse','dax','france','germany']):
        return 'europe'
    if any(w in text for w in ['oil','crude','gold','silver','commodity','metal']):
        return 'commodities'
    if any(w in text for w in ['crypto','bitcoin','ethereum','btc','eth']):
        return 'crypto'
    return 'global'


@app.route('/api/world-news', methods=['GET'])
def world_news():
    """
    Fetch global financial news from multiple free RSS feeds.
    No API key required. Used by World Monitor tab.
    """
    import re
    import requests as req

    WORLD_FEEDS = [
        ('Reuters Markets',   'https://feeds.reuters.com/reuters/businessNews'),
        ('Bloomberg Markets', 'https://feeds.bloomberg.com/markets/news.rss'),
        ('CNBC Finance',      'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664'),
        ('ET Markets',        'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms'),
        ('Moneycontrol',      'https://www.moneycontrol.com/rss/business.xml'),
        ('Business Standard', 'https://www.business-standard.com/rss/markets-106.rss'),
        ('Yahoo Finance',     'https://finance.yahoo.com/news/rssindex'),
        ('Seeking Alpha',     'https://seekingalpha.com/market_currents.xml'),
        ('FT Markets',        'https://www.ft.com/markets?format=rss'),
        ('WSJ Markets',       'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'),
    ]

    all_articles = []
    feeds_ok  = 0
    feeds_err = 0

    for source_name, url in WORLD_FEEDS:
        try:
            r = req.get(url, timeout=5,
                        headers={'User-Agent':'Mozilla/5.0 (TradingAgent/4.3)'})
            if r.status_code != 200:
                log.warning(f"WorldMonitor feed {source_name}: HTTP {r.status_code}")
                feeds_err += 1
                continue
            items = re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL)
            for item in items[:4]:
                title   = re.search(r'<title[^>]*>(.*?)</title>', item, re.DOTALL)
                link    = re.search(r'<link>(.*?)</link>', item)
                pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
                desc    = re.search(r'<description[^>]*>(.*?)</description>', item, re.DOTALL)
                if title:
                    t = re.sub(r'<[^>]+>','', title.group(1)).strip()
                    d = re.sub(r'<[^>]+>','', desc.group(1) if desc else '').strip()[:200]
                    all_articles.append({
                        'title':       t,
                        'source':      source_name,
                        'url':         link.group(1).strip() if link else '',
                        'published':   pubdate.group(1).strip() if pubdate else '',
                        'description': d,
                        'fetched_at':  datetime.now().strftime('%H:%M:%S'),
                        'category':    _classify_news(t + ' ' + d),
                    })
            feeds_ok += 1
        except Exception as e:
            log.warning(f"WorldMonitor feed {source_name} error: {e}")
            feeds_err += 1
            all_articles.append({
                'title': f'[{source_name}] Feed unavailable',
                'source': source_name,
                'error': str(e)[:80],
                'category': 'error',
            })

    log.info(f"WorldMonitor: {feeds_ok} feeds OK, {feeds_err} failed, {len(all_articles)} articles")
    return jsonify({
        'articles':   all_articles,
        'total':      len(all_articles),
        'feeds_ok':   feeds_ok,
        'feeds_err':  feeds_err,
        'fetched_at': datetime.now().isoformat(),
    })


@app.route('/api/osint/status', methods=['GET'])
def osint_status():
    """
    Run OSINT for all current scan candidates and return full details.
    Used by OSINT Monitor tab — manual trigger.
    """
    cfg = config_mgr.load()
    state = agent.get_state()
    candidates = state.get('candidates', [])
    if not candidates:
        return jsonify({'error': 'No scan candidates. Run SCAN first.', 'results': {}})

    symbols = [c['symbol'] for c in candidates[:8]]
    log.info(f"OSINT status requested for: {symbols}")
    try:
        from modules.osint_gatherer import OSINTGatherer
        gatherer = OSINTGatherer(cfg)
        results  = gatherer.gather_batch(symbols, candidates)
        return jsonify({
            'results':    results,
            'symbols':    symbols,
            'fetched_at': datetime.now().isoformat(),
        })
    except Exception as e:
        log.error(f"OSINT status error: {e}", exc_info=True)
        return jsonify({'error': str(e), 'results': {}})


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET
# ═══════════════════════════════════════════════════════════════

@socketio.on('connect')
def on_connect():
    emit('agent_status', {'status':'RUNNING' if agent.is_running() else 'STOPPED',
                           'message':'Connected to Trading Agent v4.3'})

@socketio.on('disconnect')
def on_disconnect():
    pass

@socketio.on('request_state')
def on_request_state():
    emit('full_state', agent.get_state())


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT  ← ALL ROUTES MUST BE ABOVE THIS LINE
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  Trading Agent v4.3")
    print("  Dashboard  : http://localhost:5000/dashboard")
    print("  Settings   : http://localhost:5000/settings")
    print("  Memory     : http://localhost:5000/memory")
    print("  Pre/Post   : http://localhost:5000/premarket")
    print("  Logs       : http://localhost:5000/logs")
    print("  Health     : http://localhost:5000/health")
    print("=" * 60 + "\n")
    socketio.run(app, debug=False, host='0.0.0.0', port=5000, use_reloader=False)
