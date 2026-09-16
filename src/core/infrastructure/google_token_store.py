import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("tac.core.infrastructure.google_token_store")


class GoogleTokenStore:
    """Infrastructure: persists Google OAuth tokens per linked account email.

    Mirrors the trust level of config.json (local file, not encrypted) but is
    kept in a separate file so it can be excluded from version control.
    """

    def __init__(self, token_file: str):
        self.token_file = token_file
        self._lock = threading.Lock()
        self._tokens: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(self.token_file):
            return {}
        try:
            with open(self.token_file, "r") as f:
                return json.load(f)
        except Exception:
            logger.warning("failed to read google token store", exc_info=True)
            return {}

    def _save(self):
        with open(self.token_file, "w") as f:
            json.dump(self._tokens, f, indent=2)

    def all_emails(self) -> List[str]:
        with self._lock:
            return list(self._tokens.keys())

    def get(self, email: str) -> Optional[dict]:
        with self._lock:
            return self._tokens.get(email)

    def save_tokens(
        self,
        email: str,
        access_token: str,
        refresh_token: str = None,
        expires_in: int = 3600,
    ):
        with self._lock:
            existing = self._tokens.get(email, {})
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
            self._tokens[email] = {
                "access_token": access_token,
                "refresh_token": refresh_token or existing.get("refresh_token"),
                "expires_at": expires_at,
            }
            self._save()

    def is_access_token_expired(self, email: str) -> bool:
        entry = self.get(email)
        if not entry:
            return True
        expires_at = datetime.fromisoformat(entry["expires_at"])
        return datetime.now(timezone.utc) >= expires_at - timedelta(seconds=60)

    def remove(self, email: str):
        with self._lock:
            if email in self._tokens:
                del self._tokens[email]
                self._save()
