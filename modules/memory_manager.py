"""
Memory Manager
Agent ki persistent memory — har session, trade, pattern, aur lesson yaad rakhta hai.
Memory.md file mein human-readable format, JSON mein machine-readable format.
"""

import json
import os
from datetime import datetime, date
from typing import Dict, List, Optional

MEMORY_DIR  = os.path.join(os.path.dirname(__file__), '..', 'data', 'memory')
MEMORY_JSON = os.path.join(MEMORY_DIR, 'agent_memory.json')
MEMORY_MD   = os.path.join(MEMORY_DIR, 'Memory.md')


class MemoryManager:
    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self._mem = self._load_json()

    # ─────────────────────────────────────────────────────────
    #  PUBLIC API
    # ─────────────────────────────────────────────────────────

    def remember_trade(self, trade: Dict):
        """Log a completed trade into long-term memory."""
        self._ensure_keys()
        entry = {
            'date':         date.today().isoformat(),
            'time':         datetime.now().strftime('%H:%M'),
            'symbol':       trade.get('symbol'),
            'side':         trade.get('side', 'BUY'),
            'strategy':     trade.get('strategy', ''),
            'entry':        trade.get('entry_price', 0),
            'exit':         trade.get('exit_price'),
            'stop_loss':    trade.get('stop_loss', 0),
            'target':       trade.get('target_1', 0),
            'quantity':     trade.get('quantity', 0),
            'pnl':          trade.get('pnl'),
            'pnl_pct':      trade.get('pnl_pct'),
            'conviction':   trade.get('conviction_score', 0),
            'exit_reason':  trade.get('exit_reason', ''),
            'mode':         trade.get('mode', 'paper'),
        }
        self._mem['trades'].append(entry)
        self._update_strategy_stats(entry)
        self._update_symbol_stats(entry)
        self._save()

    def remember_session(self, session: Dict):
        """Log end-of-day session summary."""
        self._ensure_keys()
        entry = {
            'date':           date.today().isoformat(),
            'total_trades':   session.get('daily_trades', 0),
            'wins':           session.get('wins', 0),
            'losses':         session.get('losses', 0),
            'win_rate':       session.get('win_rate', 0),
            'daily_pnl':      session.get('daily_pnl', 0),
            'daily_pnl_pct':  session.get('daily_pnl_pct', 0),
            'market_bias':    session.get('market_bias', 'NEUTRAL'),
            'best_trade':     session.get('best_trade'),
            'worst_trade':    session.get('worst_trade'),
            'notes':          session.get('notes', ''),
        }
        # Replace if same date already exists
        self._mem['sessions'] = [s for s in self._mem['sessions'] if s['date'] != entry['date']]
        self._mem['sessions'].append(entry)
        self._mem['sessions'] = sorted(self._mem['sessions'], key=lambda x: x['date'], reverse=True)[:90]
        self._save()

    def remember_osint(self, symbol: str, osint_data: Dict):
        """Store OSINT / news intelligence for a symbol."""
        self._ensure_keys()
        key = symbol.upper()
        if key not in self._mem['osint_cache']:
            self._mem['osint_cache'][key] = []
        entry = {
            'timestamp': datetime.now().isoformat(),
            'date':      date.today().isoformat(),
            **osint_data,
        }
        self._mem['osint_cache'][key].append(entry)
        # Keep last 20 per symbol
        self._mem['osint_cache'][key] = self._mem['osint_cache'][key][-20:]
        self._save()

    def add_lesson(self, lesson: str, category: str = 'general'):
        """Agent ne kuch seekha — permanently save karo."""
        self._ensure_keys()
        self._mem['lessons'].append({
            'date':     date.today().isoformat(),
            'category': category,
            'lesson':   lesson,
        })
        self._save()

    def get_context_for_prompt(self) -> str:
        """
        Agent ke liye memory context string banao jo Claude/Gemini prompt mein inject ho.
        Yeh function agent ke reasoning ko history-aware banata hai.
        """
        self._ensure_keys()
        lines = ["=== AGENT MEMORY CONTEXT ===\n"]

        # Last 5 sessions
        sessions = self._mem['sessions'][:5]
        if sessions:
            lines.append("RECENT SESSIONS (last 5 days):")
            for s in sessions:
                lines.append(
                    f"  {s['date']}: P&L ₹{s['daily_pnl']:+,.0f} ({s['daily_pnl_pct']:+.1f}%) | "
                    f"W/L {s['wins']}/{s['losses']} | WinRate {s['win_rate']}% | Bias: {s['market_bias']}"
                )
            lines.append("")

        # Strategy performance
        strat_stats = self._mem.get('strategy_stats', {})
        if strat_stats:
            lines.append("STRATEGY PERFORMANCE (all time):")
            sorted_strats = sorted(strat_stats.items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
            for name, stats in sorted_strats[:5]:
                lines.append(
                    f"  {name[:30]}: {stats.get('trades',0)} trades | "
                    f"WR {stats.get('win_rate',0):.0f}% | "
                    f"Avg P&L ₹{stats.get('avg_pnl',0):+.0f}"
                )
            lines.append("")

        # Symbol stats
        sym_stats = self._mem.get('symbol_stats', {})
        if sym_stats:
            lines.append("TOP SYMBOLS (by win rate):")
            sorted_syms = sorted(sym_stats.items(), key=lambda x: x[1].get('win_rate', 0), reverse=True)
            for sym, stats in sorted_syms[:5]:
                lines.append(
                    f"  {sym}: {stats.get('trades',0)} trades | "
                    f"WR {stats.get('win_rate',0):.0f}% | "
                    f"Avg P&L ₹{stats.get('avg_pnl',0):+.0f}"
                )
            lines.append("")

        # Lessons learned
        lessons = self._mem['lessons'][-5:]
        if lessons:
            lines.append("LESSONS LEARNED:")
            for l in lessons:
                lines.append(f"  [{l['category'].upper()}] {l['lesson']}")
            lines.append("")

        lines.append("=== END MEMORY ===")
        return "\n".join(lines)

    def get_symbol_history(self, symbol: str) -> List[Dict]:
        """Get all trades for a specific symbol."""
        return [t for t in self._mem.get('trades', []) if t.get('symbol') == symbol]

    def get_strategy_stats(self) -> Dict:
        return self._mem.get('strategy_stats', {})

    def get_lessons(self) -> List[Dict]:
        return self._mem.get('lessons', [])

    def get_sessions(self, limit: int = 30) -> List[Dict]:
        return self._mem.get('sessions', [])[:limit]

    def get_full_memory(self) -> Dict:
        return self._mem

    def auto_learn_from_trades(self):
        """Automatically generate lessons from trade patterns."""
        trades = self._mem.get('trades', [])
        if len(trades) < 5:
            return

        recent = trades[-20:]
        wins   = [t for t in recent if (t.get('pnl') or 0) > 0]

        # Pattern: Losing strategies
        strat_stats = self._mem.get('strategy_stats', {})
        for strat, stats in strat_stats.items():
            if stats.get('trades', 0) >= 3 and stats.get('win_rate', 100) < 30:
                lesson = (f"Strategy '{strat}' has only {stats['win_rate']:.0f}% win rate "
                          f"over {stats['trades']} trades. Avoid or reduce conviction threshold.")
                existing = [l['lesson'] for l in self._mem.get('lessons', [])]
                if lesson not in existing:
                    self.add_lesson(lesson, 'strategy')

        # Pattern: Best trading time
        if len(wins) >= 3:
            win_times = [t.get('time', '') for t in wins if t.get('time')]
            if win_times:
                morning   = [t for t in win_times if t < '11:00']
                afternoon = [t for t in win_times if t >= '13:00']
                if len(morning) > len(afternoon) * 2:
                    self.add_lesson("Most wins occur in morning session (9:15–11:00). Prioritize early trades.", 'timing')

        self._save()

    def learn_from_losing_streak(self, analysis: Dict):
        """
        Feature 6: Store losing streak analysis as an actionable lesson.
        Called by agent_brain when RiskManager detects 3+ consecutive losses.
        """
        if not analysis:
            return
        self._ensure_keys()
        lesson = analysis.get('analysis_text', '')
        if not lesson:
            return

        # Store as high-priority lesson
        self._mem['lessons'].append({
            'date':     date.today().isoformat(),
            'category': 'losing_streak',
            'lesson':   lesson,
            'streak':   analysis.get('streak_count', 0),
            'loss':     analysis.get('total_loss', 0),
        })

        # Also store structured streak data for dashboard
        self._mem.setdefault('losing_streaks', []).append({
            'date':           date.today().isoformat(),
            'time':           datetime.now().strftime('%H:%M'),
            **analysis,
        })
        # Keep last 30 streaks
        self._mem['losing_streaks'] = self._mem['losing_streaks'][-30:]
        self._save()

    # ─────────────────────────────────────────────────────────
    #  MARKDOWN EXPORT
    # ─────────────────────────────────────────────────────────

    def export_markdown(self):
        """Write human-readable Memory.md file."""
        self._ensure_keys()
        lines = [
            "# 🤖 Trading Agent Memory",
            f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "---",
            "",
            "## 📊 Overall Statistics",
        ]

        trades   = self._mem.get('trades', [])
        closed   = [t for t in trades if t.get('pnl') is not None]
        wins     = [t for t in closed if t.get('pnl', 0) > 0]
        total_pnl= sum(t.get('pnl', 0) for t in closed)

        lines += [
            f"- **Total Trades**: {len(closed)}",
            f"- **Win Rate**: {len(wins)/len(closed)*100:.1f}%" if closed else "- **Win Rate**: N/A",
            f"- **Total P&L**: ₹{total_pnl:+,.0f}",
            f"- **Avg P&L/Trade**: ₹{total_pnl/len(closed):+.0f}" if closed else "- **Avg P&L/Trade**: N/A",
            "",
            "---",
            "",
            "## 📅 Recent Sessions (Last 10)",
            "",
            "| Date | P&L | W/L | Win Rate | Market Bias | Notes |",
            "|------|-----|-----|----------|-------------|-------|",
        ]
        for s in self._mem['sessions'][:10]:
            pnl_str = f"₹{s['daily_pnl']:+,.0f}"
            lines.append(
                f"| {s['date']} | {pnl_str} | {s['wins']}/{s['losses']} | "
                f"{s['win_rate']}% | {s['market_bias']} | {s.get('notes','')} |"
            )

        lines += [
            "",
            "---",
            "",
            "## 🎯 Strategy Performance",
            "",
            "| Strategy | Trades | Win Rate | Avg P&L | Total P&L |",
            "|----------|--------|----------|---------|-----------|",
        ]
        for strat, stats in sorted(
            self._mem.get('strategy_stats', {}).items(),
            key=lambda x: x[1].get('total_pnl', 0), reverse=True
        ):
            lines.append(
                f"| {strat[:35]} | {stats.get('trades',0)} | "
                f"{stats.get('win_rate',0):.0f}% | "
                f"₹{stats.get('avg_pnl',0):+.0f} | "
                f"₹{stats.get('total_pnl',0):+,.0f} |"
            )

        lines += [
            "",
            "---",
            "",
            "## 📈 Symbol Statistics",
            "",
            "| Symbol | Trades | Win Rate | Avg P&L |",
            "|--------|--------|----------|---------|",
        ]
        for sym, stats in sorted(
            self._mem.get('symbol_stats', {}).items(),
            key=lambda x: x[1].get('total_pnl', 0), reverse=True
        ):
            lines.append(
                f"| {sym} | {stats.get('trades',0)} | "
                f"{stats.get('win_rate',0):.0f}% | "
                f"₹{stats.get('avg_pnl',0):+.0f} |"
            )

        lines += [
            "",
            "---",
            "",
            "## 💡 Lessons Learned",
            "",
        ]
        for lesson in reversed(self._mem.get('lessons', [])):
            lines.append(f"- **[{lesson['category'].upper()}]** ({lesson['date']}) {lesson['lesson']}")

        lines += [
            "",
            "---",
            "",
            "## 🕵️ Recent OSINT Cache",
            "",
        ]
        for sym, entries in self._mem.get('osint_cache', {}).items():
            if entries:
                latest = entries[-1]
                lines.append(f"### {sym}")
                lines.append(f"*Last updated: {latest.get('timestamp','')}*")
                if latest.get('news_summary'):
                    lines.append(f"- News: {latest['news_summary']}")
                if latest.get('sentiment'):
                    lines.append(f"- Sentiment: {latest['sentiment']}")
                lines.append("")

        with open(MEMORY_MD, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    # ─────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────

    def _ensure_keys(self):
        self._mem.setdefault('trades', [])
        self._mem.setdefault('sessions', [])
        self._mem.setdefault('lessons', [])
        self._mem.setdefault('osint_cache', {})
        self._mem.setdefault('strategy_stats', {})
        self._mem.setdefault('symbol_stats', {})
        self._mem.setdefault('meta', {'created': date.today().isoformat(), 'version': '2.0'})

    def _update_strategy_stats(self, trade: Dict):
        strat = trade.get('strategy', 'Unknown')
        pnl   = trade.get('pnl') or 0
        if not strat:
            return
        s = self._mem['strategy_stats'].setdefault(strat, {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0, 'avg_pnl': 0, 'win_rate': 0
        })
        s['trades']    += 1
        s['total_pnl'] += pnl
        if pnl > 0:
            s['wins'] += 1
        elif pnl < 0:
            s['losses'] += 1
        s['avg_pnl']  = s['total_pnl'] / s['trades']
        s['win_rate'] = (s['wins'] / s['trades']) * 100 if s['trades'] > 0 else 0

    def _update_symbol_stats(self, trade: Dict):
        sym = trade.get('symbol', '')
        pnl = trade.get('pnl') or 0
        if not sym:
            return
        s = self._mem['symbol_stats'].setdefault(sym, {
            'trades': 0, 'wins': 0, 'total_pnl': 0, 'avg_pnl': 0, 'win_rate': 0
        })
        s['trades']    += 1
        s['total_pnl'] += pnl
        if pnl > 0:
            s['wins'] += 1
        s['avg_pnl']  = s['total_pnl'] / s['trades']
        s['win_rate'] = (s['wins'] / s['trades']) * 100 if s['trades'] > 0 else 0

    def _load_json(self) -> Dict:
        if not os.path.exists(MEMORY_JSON):
            return {}
        try:
            with open(MEMORY_JSON, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        self._ensure_keys()
        with open(MEMORY_JSON, 'w', encoding='utf-8') as f:
            json.dump(self._mem, f, indent=2, ensure_ascii=False)
        self.export_markdown()
