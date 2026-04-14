"""
DhanHQ Connector v2
Fixes:
  - 503 Sandbox detection: sandbox tokens return 503 on /fundlimit
  - Try multiple endpoints for test connection
  - Clear error messages per status code
  - client-id header added (required in v2 API)
"""

import requests
import logging

logger = logging.getLogger('dhan_connector')

# DhanHQ Sandbox uses same base URL but different token format
DHAN_BASE   = "https://api.dhan.co"
# Endpoints to try for connection test (sandbox may block some)
TEST_ENDPOINTS = [
    "/fundlimit",           # live account fund limits
    "/v2/portfolio/",       # portfolio holdings
    "/userdetail",          # basic user info
]


class DhanConnector:
    def __init__(self, client_id: str, access_token: str):
        self.client_id    = (client_id    or '').strip()
        self.access_token = (access_token or '').strip()
        self.headers = {
            "access-token": self.access_token,
            "client-id":    self.client_id,     # required for v2
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }

    def test_connection(self) -> dict:
        """
        Test DhanHQ connection — tries multiple endpoints.
        Handles sandbox (503), live (200/401/429) correctly.
        """
        if not self.client_id or not self.access_token:
            return {
                'success': False,
                'message': 'Client ID or Access Token is empty. Please fill both fields in Settings.'
            }

        last_error = ''
        for endpoint in TEST_ENDPOINTS:
            try:
                resp = requests.get(
                    f"{DHAN_BASE}{endpoint}",
                    headers=self.headers,
                    timeout=10
                )
                code = resp.status_code

                if code == 200:
                    data = {}
                    try:    data = resp.json()
                    except: pass
                    details = {}
                    if 'availabelBalance' in data:
                        details['available_balance'] = data['availabelBalance']
                    if 'utilizedAmount' in data:
                        details['used_margin'] = data['utilizedAmount']
                    return {
                        'success': True,
                        'message': f'DhanHQ connected! (endpoint: {endpoint})',
                        'details': details or {'endpoint_tested': endpoint}
                    }

                elif code == 401:
                    return {
                        'success': False,
                        'message': (
                            '401 Unauthorized — Invalid Access Token.\n'
                            'Steps: Go to dhanhq.co → Developer → API Access → Generate new token.\n'
                            'Note: Tokens expire periodically and must be regenerated.'
                        )
                    }

                elif code == 403:
                    return {
                        'success': False,
                        'message': (
                            '403 Forbidden — API access not enabled.\n'
                            'Go to dhanhq.co → Developer → Enable API Access for your account.'
                        )
                    }

                elif code == 429:
                    return {
                        'success': False,
                        'message': '429 Rate Limited — Too many requests. Wait 60 seconds and try again.'
                    }

                elif code == 503:
                    # Common with sandbox/test accounts
                    last_error = (
                        f'503 Service Unavailable on {endpoint}. '
                        'This usually means you are using a Sandbox/Test token. '
                        'Sandbox tokens have restricted API access. '
                        'For full functionality, use a Live account token from dhanhq.co → Developer.'
                    )
                    continue  # try next endpoint

                else:
                    last_error = f'{code} on {endpoint}: {resp.text[:150]}'
                    continue

            except requests.exceptions.ConnectionError:
                return {'success': False, 'message': 'Network error — cannot reach api.dhan.co. Check internet connection.'}
            except requests.exceptions.Timeout:
                last_error = f'Timeout on {endpoint}'
                continue
            except Exception as e:
                last_error = str(e)
                continue

        # All endpoints failed
        return {
            'success': False,
            'message': (
                f'All test endpoints failed. Last error: {last_error}\n\n'
                'If using Sandbox token: Sandbox API has limited access. '
                'Live account token is needed for full features.\n'
                'Get a live token: dhanhq.co → Developer → Generate Access Token'
            )
        }

    def get_fund_limits(self) -> dict:
        resp = requests.get(f"{DHAN_BASE}/fundlimit", headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
