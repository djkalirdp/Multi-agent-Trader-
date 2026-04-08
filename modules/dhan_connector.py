"""
DhanHQ Connector
Handles authentication and basic connectivity test with the DhanHQ API.
Full market-data and order methods will be added in later modules.
"""

import requests


DHAN_BASE_URL = "https://api.dhan.co"


class DhanConnector:
    def __init__(self, client_id: str, access_token: str):
        self.client_id    = client_id
        self.access_token = access_token
        self.headers = {
            "access-token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def test_connection(self) -> dict:
        """
        Ping the DhanHQ profile/fund endpoint to verify credentials.
        Returns a dict with 'success' and 'message' keys.
        """
        try:
            response = requests.get(
                f"{DHAN_BASE_URL}/fundlimit",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'message': 'DhanHQ connection successful!',
                    'details': {
                        'available_balance': data.get('availabelBalance', 'N/A'),
                        'used_margin':       data.get('utilizedAmount', 'N/A'),
                    }
                }
            elif response.status_code == 401:
                return {'success': False, 'message': 'Invalid credentials – check Client ID and Access Token.'}
            else:
                return {
                    'success': False,
                    'message': f"DhanHQ returned status {response.status_code}: {response.text[:200]}"
                }
        except requests.exceptions.ConnectionError:
            return {'success': False, 'message': 'Network error – could not reach DhanHQ servers.'}
        except requests.exceptions.Timeout:
            return {'success': False, 'message': 'Request timed out – DhanHQ did not respond.'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_fund_limits(self) -> dict:
        """Fetch available fund limits (used by risk manager)."""
        response = requests.get(f"{DHAN_BASE_URL}/fundlimit", headers=self.headers, timeout=10)
        response.raise_for_status()
        return response.json()
