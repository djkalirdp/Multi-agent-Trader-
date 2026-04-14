"""
Claude Connector v2
Fixes:
  - Empty API key check before making request
  - Detailed error messages
  - Model name validation
  - Logger integration
"""

import logging
logger = logging.getLogger('claude_connector')

VALID_MODELS = [
    'claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5',
    'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20251020',
    'claude-haiku-4-5-20251001',
]


class ClaudeConnector:
    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-5'):
        self.api_key = (api_key or '').strip()
        self.model   = model or 'claude-sonnet-4-5'
        self._client = None

    def _get_client(self):
        if not self._client:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def test_connection(self) -> dict:
        if not self.api_key:
            return {
                'success': False,
                'message': 'Claude API key is empty. Get your key at: console.anthropic.com → API Keys'
            }
        if not self.api_key.startswith('sk-ant-'):
            return {
                'success': False,
                'message': (
                    f'Invalid key format (got: {self.api_key[:10]}...). '
                    'Claude API keys start with "sk-ant-api03-...". '
                    'Get a valid key at console.anthropic.com → API Keys.'
                )
            }
        try:
            import anthropic
            client  = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return {
                'success': True,
                'message': f'Claude API connected! Model: {self.model}',
                'details': {'model': self.model}
            }
        except Exception as e:
            err = str(e)
            if 'authentication' in err.lower() or '401' in err:
                return {'success': False, 'message': f'Invalid API key — authentication failed. Check your key at console.anthropic.com'}
            if 'rate' in err.lower() or '429' in err:
                return {'success': False, 'message': 'Rate limited — key is valid but too many requests. Try again in a moment.'}
            if 'model' in err.lower():
                return {'success': False, 'message': f'Model "{self.model}" not found. Valid models: {", ".join(VALID_MODELS[:3])}'}
            if 'credit' in err.lower() or 'billing' in err.lower():
                return {'success': False, 'message': 'Billing issue — check your Anthropic account credits at console.anthropic.com'}
            logger.error(f'Claude test error: {err}')
            return {'success': False, 'message': f'Connection error: {err[:200]}'}

    def chat(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        import anthropic
        message = self._get_client().messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        return message.content[0].text
