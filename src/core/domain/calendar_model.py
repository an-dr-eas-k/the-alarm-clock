from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class CalendarEvent:
    """Value Object: a single calendar entry read from a linked Google account.

    Pure domain data - no Google API / HTTP concerns here.
    """

    event_id: str
    account_email: str
    summary: str
    start: datetime
    end: datetime
    is_all_day: bool = False
    response_status: str = "accepted"
    html_link: Optional[str] = None

    def is_accepted(self) -> bool:
        return self.response_status in ("accepted", None)

    def starts_within(self, reference: datetime, window: timedelta) -> bool:
        """Whether this event starts between `reference` and `reference + window`."""
        if self.is_all_day:
            return False
        return reference <= self.start <= reference + window

    def seconds_until_start(self, reference: datetime) -> float:
        return (self.start - reference).total_seconds()

    def __str__(self):
        return f"'{self.summary}' at {self.start} ({self.response_status})"


@dataclass
class GoogleAccountLink:
    """Entity: an allowed Google account and whether it has linked calendar access."""

    email: str
    is_linked: bool = False
    display_name: Optional[str] = None
