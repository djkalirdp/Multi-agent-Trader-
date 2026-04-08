"""
Claude Connector
Handles authentication and communication with the Anthropic Claude API.
"""

import anthropic


class ClaudeConnector:
    def __init__(self, api_key: str, model: str = "claude-opus-4-5"):
        self.api_key = api_key
        self.model   = model
        self.client  = anthropic.Anthropic(api_key=api_key)

    def test_connection(self) -> dict:
        """
        Send a minimal ping message to verify the API key is valid.
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=50,
                messages=[
                    {"role": "user", "content": "Respond with: API_OK"}
                ]
            )
            reply = message.content[0].text.strip()
            return {
                'success': True,
                'message': f'Claude API connected! Model: {self.model}',
                'details': {'response': reply, 'model': self.model}
            }
        except anthropic.AuthenticationError:
            return {'success': False, 'message': 'Invalid Claude API key – authentication failed.'}
        except anthropic.RateLimitError:
            return {'success': False, 'message': 'Claude API rate limit hit – key is valid but rate-limited.'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def chat(self, system_prompt: str, user_message: str, max_tokens: int = 2048) -> str:
        """General-purpose chat completion."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        return message.content[0].text
