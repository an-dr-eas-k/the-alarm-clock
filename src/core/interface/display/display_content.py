from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.job import Job

from core.domain.model import (
    AlarmClockContext,
    Mode,
    RoomBrightness,
    Weather,
)

if TYPE_CHECKING:
    from core.infrastructure.event_bus import EventBus
    from core.domain.model import PlaybackContent

from core.domain.events import (
    AudioStreamChangedEvent,
    ForcedDisplayUpdateEvent,
    VolumeChangedEvent,
)

import logging

logger = logging.getLogger("tac.interface.display")


class NextAlarmInfo:
    """
    Value Object: Information about the next scheduled alarm.

    Encapsulates alarm timing without exposing scheduler infrastructure.
    This bridges between the Infrastructure layer (APScheduler) and
    the Interface layer (DisplayContent).
    """

    def __init__(self, next_run_time: datetime = None):
        self._next_run_time = next_run_time

    @property
    def next_run_time(self) -> datetime:
        return self._next_run_time

    def has_alarm(self) -> bool:
        return self._next_run_time is not None

    def get_timedelta_to_alarm(self) -> timedelta:
        if not self.has_alarm():
            return timedelta.max
        return self._calculate_time_delta()

    def _calculate_time_delta(self) -> timedelta:
        """Calculate time delta to alarm time."""
        from utils.geolocation import GeoLocation

        now = GeoLocation().now()
        return self._next_run_time - now

    def minutes_until_alarm(self) -> int:
        return int(self.get_timedelta_to_alarm().total_seconds() / 60)


class DisplayContent:
    """
    ViewModel (MVVM Pattern): Aggregates all data needed for display presentation.

    This is the Interface Layer component that serves the View (Presenter).
    It owns presentation state and coordinates data from multiple domain aggregates.

    Responsibilities:
    - Owns presentation state (brightness, blinking, scrolling)
    - Aggregates data from domain (alarms, weather, playback)
    - Provides convenient accessors for the View layer
    - Handles presentation-related events

    DDD Pattern: Anti-Corruption Layer between Domain and View
    MVVM Pattern: ViewModel
    """

    # ========== Presentation State (ViewModel owns this) ==========
    show_volume_meter: bool = False
    next_alarm_info: NextAlarmInfo = None
    show_blink_segment: bool = True
    room_brightness: RoomBrightness = None
    is_scrolling: bool = False

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        playback_content: "PlaybackContent",
        event_bus: "EventBus" = None,
    ):
        """
        Initialize the ViewModel.

        Args:
            alarm_clock_context: Domain aggregate root
            playback_content: Playback state (should also be moved to interface layer)
            event_bus: Event infrastructure for reactive updates
        """
        self.alarm_clock_context = alarm_clock_context
        self.playback_content = playback_content
        self.event_bus = event_bus
        self.next_alarm_info = NextAlarmInfo()
        self.room_brightness = RoomBrightness(1.0)

        # Subscribe to presentation-relevant events
        self.event_bus.on(AudioStreamChangedEvent)(self._audio_stream_changed)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

    # ========== Event Handlers ==========

    def _audio_stream_changed(self, event: AudioStreamChangedEvent):
        """Handle audio stream changes (show/hide volume meter)."""
        if event.audio_stream is None:
            self.hide_volume_meter()
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def _volume_changed(self, _: VolumeChangedEvent):
        """Handle volume changes (show volume meter)."""
        self.show_volume_meter = True
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    # ========== Presentation State Updates ==========

    def update_presentation_state(
        self,
        show_blink_segment: bool = None,
        room_brightness: RoomBrightness = None,
        is_scrolling: bool = None,
    ) -> bool:
        """
        Update presentation state. Returns True if any value changed.

        This allows efficient display refresh only when presentation state changes.
        The ViewModel decides what requires a redraw.

        Args:
            show_blink_segment: Whether to show blinking elements (colon)
            room_brightness: Ambient brightness for display adjustment
            is_scrolling: Whether content is currently scrolling

        Returns:
            True if any state changed (indicating redraw needed)
        """
        changed = False

        if (
            show_blink_segment is not None
            and self.show_blink_segment != show_blink_segment
        ):
            self.show_blink_segment = show_blink_segment
            changed = True

        if room_brightness is not None and self.room_brightness != room_brightness:
            self.room_brightness = room_brightness
            changed = True

        if is_scrolling is not None and self.is_scrolling != is_scrolling:
            self.is_scrolling = is_scrolling
            changed = True

        return changed

    # ========== Alarm Information (Domain Delegation) ==========

    def update_next_alarm(self, job: Job):
        """
        Update next alarm from scheduler job (infrastructure adapter).

        This method acts as an adapter between Infrastructure (APScheduler Job)
        and Interface (NextAlarmInfo value object).
        """
        next_run = job.next_run_time if job is not None else None
        self.next_alarm_info = NextAlarmInfo(next_run)

    def show_alarm_preview(self) -> bool:
        """
        Whether to show alarm preview based on proximity.

        Business rule: Show preview if alarm is within configured hours.
        """
        if not self.next_alarm_info.has_alarm():
            return False
        hours_until = (
            self.next_alarm_info.get_timedelta_to_alarm().total_seconds() / 3600
        )
        return hours_until <= self.alarm_clock_context.config.alarm_preview_hours

    def get_next_alarm(self) -> datetime:
        """Get next alarm datetime (or None)."""
        return self.next_alarm_info.next_run_time

    def get_timedelta_to_alarm(self) -> timedelta:
        """Get time remaining until next alarm."""
        return self.next_alarm_info.get_timedelta_to_alarm()

    # ========== Environment Information (Domain Delegation) ==========

    def get_is_online(self) -> bool:
        """Delegate to environment context (domain aggregate)."""
        return self.alarm_clock_context.environment.is_online

    @property
    def current_weather(self) -> Weather:
        """Delegate to environment context (domain aggregate)."""
        return self.alarm_clock_context.environment.current_weather

    # ========== Volume Meter ==========

    def hide_volume_meter(self):
        """Hide the volume meter display element."""
        self.show_volume_meter = False

    # ========== Playback Information (Delegation) ==========

    def current_playback_title(self) -> str:
        """Get current playback title (or None if idle)."""
        return (
            self.playback_content.audio_stream.stream_name
            if self.playback_content.playback_mode != Mode.Idle
            and self.playback_content.audio_stream is not None
            else None
        )

    def current_volume(self) -> float:
        """Get current playback volume."""
        return self.playback_content.volume
