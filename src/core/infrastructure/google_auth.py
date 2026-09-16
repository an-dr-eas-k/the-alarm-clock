import json
import logging
import os
import urllib.parse

from tornado.httpclient import HTTPClient, HTTPError, HTTPRequest

logger = logging.getLogger("tac.core.infrastructure.google_auth")

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# openid+email+profile to identify the user (incl. profile picture),
# calendar.readonly to read their events.
DEFAULT_SCOPE = "openid email profile https://www.googleapis.com/auth/calendar.readonly"


class GoogleAuthError(Exception):
    pass


class AuthorizationPending(GoogleAuthError):
    """The user has not yet completed the login on google.com/device."""


class SlowDown(GoogleAuthError):
    """We are polling too fast, back off."""


class AuthorizationExpired(GoogleAuthError):
    """The device_code expired before the user completed login."""


class AccessDenied(GoogleAuthError):
    """The user explicitly declined the consent screen."""


def load_client_credentials(secret_file: str) -> tuple[str, str] | tuple[None, None]:
    """Reads client_id/client_secret from a local secrets file.

    Accepts both a flat {"client_id": ..., "client_secret": ...} file and the
    raw JSON Google Cloud Console lets you download for an OAuth client,
    which nests the fields under an "installed" or "web" key, e.g.:
    {"installed": {"client_id": ..., "client_secret": ..., ...}}

    Returns (None, None) if the file does not exist or does not contain both
    fields, so the feature can stay disabled until an operator provides real
    credentials.
    """
    if not os.path.exists(secret_file):
        logger.warning(
            "google oauth secret file not found at %s - Google login is disabled",
            secret_file,
        )
        return None, None
    with open(secret_file, "r") as f:
        data = json.load(f)
    for nested_key in ("installed", "web"):
        if nested_key in data:
            data = data[nested_key]
            break
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    if not client_id or not client_secret:
        logger.warning(
            "google oauth secret file %s is missing client_id/client_secret - "
            "Google login is disabled",
            secret_file,
        )
        return None, None
    return client_id, client_secret


class GoogleDeviceAuthClient:
    """Infrastructure: talks to Google's OAuth 2.0 Device Authorization endpoints.

    This uses the "TV and Limited Input devices" flow: it requires no reachable
    redirect URI at all, which fits a device (like a Raspberry Pi) that has no
    stable public hostname. The user completes the login on any other device
    (phone/laptop) by visiting a short URL and typing in a code.
    """

    def __init__(self, client_id: str, client_secret: str, scope: str = DEFAULT_SCOPE):
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope

    def _post(self, url: str, body: dict) -> dict:
        client = HTTPClient()
        try:
            request = HTTPRequest(
                url,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=urllib.parse.urlencode(body),
                request_timeout=15,
            )
            response = client.fetch(request)
            return json.loads(response.body)
        except HTTPError as e:
            if e.response is not None and e.response.body:
                try:
                    return json.loads(e.response.body)
                except ValueError:
                    pass
            raise
        finally:
            client.close()

    def request_device_code(self) -> dict:
        return self._post(
            DEVICE_CODE_URL, {"client_id": self.client_id, "scope": self.scope}
        )

    def poll_for_token(self, device_code: str) -> dict:
        result = self._post(
            TOKEN_URL,
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        error = result.get("error")
        if error == "authorization_pending":
            raise AuthorizationPending()
        if error == "slow_down":
            raise SlowDown()
        if error == "expired_token":
            raise AuthorizationExpired()
        if error == "access_denied":
            raise AccessDenied()
        if error:
            raise GoogleAuthError(result.get("error_description", error))
        return result

    def refresh_access_token(self, refresh_token: str) -> dict:
        result = self._post(
            TOKEN_URL,
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if result.get("error"):
            raise GoogleAuthError(result.get("error_description", result.get("error")))
        return result

    def get_userinfo(self, access_token: str) -> dict:
        client = HTTPClient()
        try:
            request = HTTPRequest(
                USERINFO_URL,
                method="GET",
                headers={"Authorization": f"Bearer {access_token}"},
                request_timeout=15,
            )
            response = client.fetch(request)
            return json.loads(response.body)
        finally:
            client.close()

    def revoke(self, token: str):
        client = HTTPClient()
        try:
            request = HTTPRequest(
                REVOKE_URL,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=urllib.parse.urlencode({"token": token}),
                request_timeout=15,
            )
            client.fetch(request)
        except Exception:
            logger.warning("failed to revoke google token", exc_info=True)
        finally:
            client.close()
