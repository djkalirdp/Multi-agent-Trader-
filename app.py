"""
Intraday Trading Agent — Flask Application (Complete)
All routes: Settings, Dashboard, Agent Control, P&L API
"""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit

from modules.config_manager import ConfigManager
from modules.agent_brain    import AgentBrain
from modules.risk_manager   import RiskManager

app        = Flask(__name__)
app.secret_key = os.urandom(24)
socketio   = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

config_mgr = ConfigManager()
agent      = AgentBrain(socketio=socketio)


# PAGE ROUTES
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


# SETTINGS API
@app.route('/api/settings/save', methods=['POST'])
def save_settings():
    try:
        data = request.get_json()
        required = ['dhan_client_id', 'dhan_access_token', 'claude_api_key']
        missing  = [f for f in required if not data.get(f,'').strip()]
        if missing:
            return jsonify({'success': False, 'message': f'Missing: {", ".join(missing)}'}), 400
        config = {
            'dhan_client_id': data.get('dhan_client_id','').strip(),
            'dhan_access_token': data.get('dhan_access_token','').strip(),
            'claude_api_key': data.get('claude_api_key','').strip(),
            'claude_model': data.get('claude_model','claude-opus-4-5'),
            'trading_mode': data.get('trading_mode','paper'),
            'trading_style': data.get('trading_style','swing_intraday'),
            'max_loss_per_trade_pct': float(data.get('max_loss_per_trade_pct',1.0)),
            'daily_loss_limit_pct': float(data.get('daily_loss_limit_pct',3.0)),
            'max_capital_per_trade': float(data.get('max_capital_per_trade',10000)),
            'total_capital': float(data.get('total_capital',100000)),
            'max_open_positions': int(data.get('max_open_positions',3)),
            'rvol_threshold': float(data.get('rvol_threshold',1.5)),
            'min_gap_pct': float(data.get('min_gap_pct',2.0)),
            'min_atr': float(data.get('min_atr',5.0)),
            'min_market_cap': float(data.get('min_market_cap',500)),
            'autonomous_mode': data.get('autonomous_mode',True),
            'scan_interval_min': int(data.get('scan_interval_min',5)),
            'conviction_threshold': int(data.get('conviction_threshold',7)),
            'enable_notifications': data.get('enable_notifications',False),
            'notification_email': data.get('notification_email',''),
            'is_configured': True,
        }
        config_mgr.save(config)
        return jsonify({'success': True, 'message': 'Settings saved!'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings/load', methods=['GET'])
def load_settings():
    cfg = config_mgr.load()
    safe = cfg.copy()
    for f in ['dhan_access_token','claude_api_key']:
        v = safe.get(f,'')
        if v: safe[f] = v[:4]+'........'+v[-4:] if len(v)>8 else '........'
    return jsonify({'success': True, 'config': safe})

@app.route('/api/settings/test-dhan', methods=['POST'])
def test_dhan():
    from modules.dhan_connector import DhanConnector
    d = request.get_json()
    return jsonify(DhanConnector(d.get('dhan_client_id'), d.get('dhan_access_token')).test_connection())

@app.route('/api/settings/test-claude', methods=['POST'])
def test_claude():
    from modules.claude_connector import ClaudeConnector
    d = request.get_json()
    return jsonify(ClaudeConnector(d.get('claude_api_key'), d.get('claude_model','claude-opus-4-5')).test_connection())

@app.route('/api/settings/reset', methods=['POST'])
def reset_settings():
    config_mgr.reset()
    return jsonify({'success': True, 'message': 'Settings reset.'})


# AGENT CONTROL API
@app.route('/api/agent/start', methods=['POST'])
def agent_start():
    return jsonify(agent.start())

@app.route('/api/agent/stop', methods=['POST'])
def agent_stop():
    return jsonify(agent.stop())

@app.route('/api/agent/status', methods=['GET'])
def agent_status():
    return jsonify({'running': agent.is_running(), **agent.get_state()})

@app.route('/api/agent/kill-switch', methods=['POST'])
def agent_kill_switch():
    cfg = config_mgr.load()
    risk = RiskManager(cfg)
    agent.stop()
    risk.force_kill_switch()
    return jsonify({'success': True, 'message': 'Kill switch activated.'})

@app.route('/api/agent/reset-kill-switch', methods=['POST'])
def reset_kill_switch():
    cfg = config_mgr.load()
    RiskManager(cfg).reset_kill_switch()
    return jsonify({'success': True, 'message': 'Kill switch reset.'})

@app.route('/api/agent/square-off', methods=['POST'])
def square_off():
    cfg = config_mgr.load()
    from modules.order_executor import OrderExecutor
    executor = OrderExecutor(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg.get('trading_mode','paper'))
    result = executor.square_off_all()
    agent.stop()
    return jsonify(result)


# DATA API
@app.route('/api/risk/summary', methods=['GET'])
def risk_summary():
    cfg = config_mgr.load()
    return jsonify(RiskManager(cfg).get_summary())

@app.route('/api/trades', methods=['GET'])
def get_trades():
    from modules.risk_manager import TRADES_PATH
    import json as _json
    if not os.path.exists(TRADES_PATH):
        return jsonify({'trades': []})
    with open(TRADES_PATH) as f:
        trades = _json.load(f)
    return jsonify({'trades': trades[-50:]})

@app.route('/api/scan/run', methods=['POST'])
def manual_scan():
    cfg = config_mgr.load()
    from modules.market_scanner import MarketScanner
    scanner = MarketScanner(cfg['dhan_client_id'], cfg['dhan_access_token'], cfg)
    return jsonify(scanner.scan())


# WEBSOCKET
@socketio.on('connect')
def on_connect():
    emit('agent_status', {'status': 'RUNNING' if agent.is_running() else 'STOPPED',
                          'message': 'Connected to Trading Agent'})

@socketio.on('disconnect')
def on_disconnect():
    pass

@socketio.on('request_state')
def on_request_state():
    emit('full_state', agent.get_state())


if __name__ == '__main__':
    print("\n" + "="*60)
    print("  Intraday Trading Agent - Full System")
    print("  Dashboard: http://localhost:5000")
    print("  Settings:  http://localhost:5000/settings")
    print("="*60 + "\n")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, use_reloader=False)


# ═══════════════════════════════════════════════════════════════
#  MEMORY API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/memory', methods=['GET'])
def get_memory():
    return jsonify(agent.get_memory())

@app.route('/api/memory/lessons', methods=['GET'])
def get_lessons():
    from modules.memory_manager import MemoryManager
    return jsonify({'lessons': MemoryManager().get_lessons()})

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


# ═══════════════════════════════════════════════════════════════
#  OSINT API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/osint/<symbol>', methods=['GET'])
def get_osint(symbol):
    cfg = config_mgr.load()
    from modules.osint_gatherer import OSINTGatherer
    gatherer = OSINTGatherer(cfg)
    return jsonify(gatherer.gather(symbol.upper()))

@app.route('/api/osint/batch', methods=['POST'])
def osint_batch():
    cfg = config_mgr.load()
    from modules.osint_gatherer import OSINTGatherer
    symbols = request.get_json().get('symbols', [])
    gatherer = OSINTGatherer(cfg)
    return jsonify(gatherer.gather_batch(symbols))


# ═══════════════════════════════════════════════════════════════
#  MULTI-AI STATUS API
# ═══════════════════════════════════════════════════════════════

@app.route('/api/ai/models', methods=['GET'])
def get_ai_models():
    cfg = config_mgr.load()
    from modules.multi_ai import MultiAIOrchestrator
    orch = MultiAIOrchestrator(cfg)
    return jsonify({
        'models':           orch.get_available_models(),
        'researcher_model': cfg.get('researcher_model','gemini'),
        'decision_model':   cfg.get('decision_model','claude'),
    })

@app.route('/api/ai/test-gemini', methods=['POST'])
def test_gemini():
    data = request.get_json()
    from modules.multi_ai import GeminiAdapter
    try:
        g = GeminiAdapter(data.get('gemini_api_key',''), data.get('gemini_model','gemini-1.5-pro'))
        r = g.chat("You are a test.", "Reply: GEMINI_OK", max_tokens=10)
        return jsonify({'success': True, 'message': f'Gemini connected! Response: {r.strip()}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/ai/test-ollama', methods=['POST'])
def test_ollama():
    data = request.get_json()
    from modules.multi_ai import OllamaAdapter
    try:
        o = OllamaAdapter(data.get('ollama_base_url','http://localhost:11434'), data.get('ollama_model','llama3'))
        available = o.is_available()
        models    = o.list_models()
        if available:
            return jsonify({'success': True, 'message': f'Ollama running! Models: {", ".join(models[:5])}'})
        else:
            return jsonify({'success': False, 'message': 'Ollama not running. Start with: ollama serve'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
