"""
Multi-AI Router
Agent 1 (Research): Gemini / Ollama — data gathering, summarization
Agent 2 (Reasoning): Claude / DeepSeek — analysis, trade decision
Agent 3 (Fallback): Any available model

Architecture:
  Gemini → gathers news, fundamentals, sentiment → JSON
  Claude  → receives Gemini's research + technical data → trade decision
  Ollama  → offline fallback when no API available
"""

import json
import requests
from datetime import datetime
from typing import Dict, Optional, List


# ─────────────────────────────────────────────────────────────
#  BASE AI ADAPTER
# ─────────────────────────────────────────────────────────────

class BaseAIAdapter:
    name = "base"

    def chat(self, system: str, user: str, max_tokens: int = 2000) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────
#  CLAUDE ADAPTER
# ─────────────────────────────────────────────────────────────

class ClaudeAdapter(BaseAIAdapter):
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-opus-4-5"):
        self.api_key = api_key
        self.model   = model
        self._client = None

    def _get_client(self):
        if not self._client:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def chat(self, system: str, user: str, max_tokens: int = 2000) -> str:
        msg = self._get_client().messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        return msg.content[0].text

    def is_available(self) -> bool:
        try:
            self._get_client().messages.create(
                model=self.model, max_tokens=5,
                messages=[{"role": "user", "content": "ping"}]
            )
            return True
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
#  GEMINI ADAPTER
# ─────────────────────────────────────────────────────────────

class GeminiAdapter(BaseAIAdapter):
    name = "gemini"
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        self.api_key = api_key
        self.model   = model

    def chat(self, system: str, user: str, max_tokens: int = 2000) -> str:
        url     = self.GEMINI_URL.format(model=self.model) + f"?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def is_available(self) -> bool:
        try:
            self.chat("You are a test assistant.", "Reply: OK", max_tokens=5)
            return True
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
#  OLLAMA ADAPTER (offline local AI)
# ─────────────────────────────────────────────────────────────

class OllamaAdapter(BaseAIAdapter):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip('/')
        self.model    = model

    def chat(self, system: str, user: str, max_tokens: int = 2000) -> str:
        payload = {
            "model":  self.model,
            "prompt": f"System: {system}\n\nUser: {user}",
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "")

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            data = resp.json()
            return [m['name'] for m in data.get('models', [])]
        except Exception:
            return []


# ─────────────────────────────────────────────────────────────
#  MULTI-AI ORCHESTRATOR — The Core of the Multi-Agent System
# ─────────────────────────────────────────────────────────────

class MultiAIOrchestrator:
    """
    2-Agent Pipeline:

    Agent 1 (Researcher): Gemini / Ollama
      → Given stock candidates + OSINT data
      → Returns structured research JSON

    Agent 2 (Decision Maker): Claude / Ollama
      → Given research JSON + technical data + memory context
      → Returns trade decision JSON

    If primary unavailable, falls back to next available.
    """

    def __init__(self, config: Dict):
        self.config = config
        self._agents = self._build_agents()

    def _build_agents(self) -> Dict[str, Optional[BaseAIAdapter]]:
        cfg = self.config
        agents = {}

        # Claude
        if cfg.get('claude_api_key'):
            agents['claude'] = ClaudeAdapter(
                cfg['claude_api_key'],
                cfg.get('claude_model', 'claude-opus-4-5')
            )

        # Gemini
        if cfg.get('gemini_api_key'):
            agents['gemini'] = GeminiAdapter(
                cfg['gemini_api_key'],
                cfg.get('gemini_model', 'gemini-1.5-pro')
            )

        # Ollama (offline)
        if cfg.get('ollama_enabled', False):
            agents['ollama'] = OllamaAdapter(
                cfg.get('ollama_base_url', 'http://localhost:11434'),
                cfg.get('ollama_model', 'llama3')
            )

        return agents

    def get_researcher(self) -> Optional[BaseAIAdapter]:
        """
        Agent 1 — Research role.
        Priority: gemini → ollama → claude (last resort)
        """
        preferred = self.config.get('researcher_model', 'gemini')
        order = [preferred, 'gemini', 'ollama', 'claude']
        for name in order:
            agent = self._agents.get(name)
            if agent:
                return agent
        return None

    def get_decision_maker(self) -> Optional[BaseAIAdapter]:
        """
        Agent 2 — Decision/Reasoning role.
        Priority: claude → gemini → ollama
        """
        preferred = self.config.get('decision_model', 'claude')
        order = [preferred, 'claude', 'gemini', 'ollama']
        for name in order:
            agent = self._agents.get(name)
            if agent:
                return agent
        return None

    def research_stocks(self, candidates: List[Dict], osint_data: Dict, memory_context: str) -> Dict:
        """
        Agent 1 task: Research all candidates, return structured analysis.
        """
        researcher = self.get_researcher()
        if not researcher:
            return {"error": "No research AI available", "research": {}}

        system = """You are a financial research specialist for Indian equity markets (NSE/BSE).
Your job is to analyze stock candidates using provided market data, news, and sentiment.
You MUST respond ONLY in this exact JSON format:
{
  "research": {
    "SYMBOL": {
      "fundamental_score": 7,
      "sentiment_score": 8,
      "news_summary": "One clear sentence about recent news",
      "key_catalyst": "Main reason this stock is moving today",
      "risk_factors": ["risk 1", "risk 2"],
      "recommended_for_analysis": true
    }
  },
  "market_overview": "One sentence about overall market today",
  "sector_alerts": ["any sector-specific alerts"]
}
Be factual, data-driven. Score 1-10. Mark recommended_for_analysis=true only if strong setup."""

        # Build context
        cand_text = json.dumps(candidates, indent=2)
        osint_text = json.dumps(osint_data, indent=2) if osint_data else "No OSINT data available."

        user = f"""Analyze these NSE stock candidates:

CANDIDATES FROM SCANNER:
{cand_text}

OSINT / NEWS DATA:
{osint_text}

AGENT MEMORY CONTEXT:
{memory_context}

Current time: {datetime.now().strftime('%H:%M')} IST
Date: {datetime.now().strftime('%Y-%m-%d')}

Analyze each candidate. Respond ONLY in required JSON format."""

        try:
            raw    = researcher.chat(system, user, max_tokens=2000)
            return self._parse_json_response(raw)
        except Exception as e:
            return {"error": str(e), "research": {}, "researcher_used": researcher.name}

    def _parse_json_response(self, raw: str) -> dict:
        """
        Robust JSON extractor — handles markdown fences, extra text, etc.
        Tries multiple strategies before giving up.
        """
        # Strategy 1: strip markdown fences
        clean = raw.strip()
        for fence in ['```json', '```JSON', '```']:
            if clean.startswith(fence):
                clean = clean[len(fence):]
                break
        if clean.endswith('```'):
            clean = clean[:-3]
        clean = clean.strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # Strategy 2: find first { ... } block
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response (length={len(raw)})")

    def make_trade_decision(self, candidates: List[Dict], research: Dict,
                             memory_context: str) -> Dict:
        """
        Agent 2 task: Take research + technical data → final trade decision.
        """
        decision_maker = self.get_decision_maker()
        if not decision_maker:
            return {"error": "No decision AI available", "selections": []}

        system = f"""You are a Senior Quantitative Analyst and Portfolio Manager for Indian equity markets.
You receive research from a data-gathering AI and must make final trade decisions.

AGENT MEMORY (learn from past):
{memory_context}

You MUST respond ONLY in this exact JSON format:
{{
  "selections": [
    {{
      "rank": 1,
      "symbol": "SYMBOL",
      "conviction_score": 8,
      "direction": "LONG",
      "primary_reason": "Clear reasoning combining research + technicals",
      "key_levels": {{"support": 0.0, "resistance": 0.0, "vwap": 0.0}},
      "risk_note": "Main risk",
      "research_alignment": "How research supports this trade"
    }}
  ],
  "market_bias": "BULLISH/BEARISH/NEUTRAL",
  "analyst_note": "Overall market comment",
  "reasoning": "Your chain-of-thought before reaching conclusion"
}}
Select max 3 stocks. Conviction score 7+ to trade. Be disciplined."""

        enriched = []
        for c in candidates:
            sym = c.get('symbol', '')
            enriched.append({**c, 'research': research.get('research', {}).get(sym, {})})

        user = f"""Make final trade decisions:

TECHNICAL DATA + RESEARCH (merged):
{json.dumps(enriched, indent=2)}

MARKET OVERVIEW FROM RESEARCHER:
{research.get('market_overview', 'Not available')}

SECTOR ALERTS:
{json.dumps(research.get('sector_alerts', []))}

Time: {datetime.now().strftime('%H:%M')} IST

Apply your 20-strategy knowledge and memory context. Respond ONLY in required JSON format."""

        try:
            raw    = decision_maker.chat(system, user, max_tokens=2500)
            result = self._parse_json_response(raw)
            result['decision_model_used'] = decision_maker.name
            result['research_model_used'] = (
                self.get_researcher().name if self.get_researcher() else 'none'
            )
            return result
        except Exception as e:
            return {
                "error": str(e),
                "selections": [],
                "decision_model_used": decision_maker.name if decision_maker else 'none'
            }

    def get_available_models(self) -> Dict:
        """Check which AI models are configured and available."""
        status = {}
        for name, agent in self._agents.items():
            status[name] = {
                'configured': True,
                'model': getattr(agent, 'model', 'unknown'),
                'role': 'researcher' if name in ['gemini','ollama'] else 'decision_maker',
            }

        # Check Ollama models if available
        ollama = self._agents.get('ollama')
        if ollama and isinstance(ollama, OllamaAdapter):
            status['ollama']['available_models'] = ollama.list_models()

        return status
