from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.job import Job

from core.domain.model import (
    AlarmClockContext,
    Mode,
    NextAlarmInfo,
    RoomBrightness,
    Weather,
    VisualEffect,
)

if TYPE_CHECKING:
    from core.infrastructure.event_bus import EventBus
    from core.domain.model import PlaybackContent

from core.domain.events import (
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    VolumeChangedEvent,
)

import logging

logger = logging.getLogger("tac.core.interface.display.display_content")


class DisplayContent:

    show_volume_meter: bool = False
    next_alarm_info: NextAlarmInfo = None
    show_blink_segment: bool = True
    room_brightness: RoomBrightness = None
    is_scrolling: bool = False
    refresh_duration_in_ms: int = None

    def __init__(
        self,
        alarm_clock_context: AlarmClockContext,
        playback_content: "PlaybackContent",
        event_bus: "EventBus" = None,
    ):
        self.alarm_clock_context = alarm_clock_context
        self.playback_content = playback_content
        self.event_bus = event_bus
        self.next_alarm_info = NextAlarmInfo()
        self.room_brightness = RoomBrightness(1.0)

        self.event_bus.on(PlaybackChangedEvent)(self._playback_changed)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

    # ========== Event Handlers ==========

    def _playback_changed(self, event: PlaybackChangedEvent):
        if event.playback_mode == Mode.Idle:
            self.hide_volume_meter()
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def _volume_changed(self, _: VolumeChangedEvent):
        self.show_volume_meter = True
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    # ========== Presentation State Updates ==========

    def update_presentation_state(
        self,
        show_blink_segment: bool,
        room_brightness: RoomBrightness,
    ) -> bool:
        changed = False

        if self.show_blink_segment != show_blink_segment:
            self.show_blink_segment = show_blink_segment
            changed = True

        if self.room_brightness != room_brightness:
            self.room_brightness = room_brightness
            changed = True

        if self.is_scrolling:
            changed = True

        return changed

    # ========== Alarm Information (Domain Delegation) ==========

    def update_next_alarm(self, next_alarm_info: NextAlarmInfo):
        if next_alarm_info is None:
            return

        self.next_alarm_info = next_alarm_info

    def show_alarm_preview(self) -> bool:
        if not self.next_alarm_info.has_alarm():
            return False
        hours_until = (
            self.next_alarm_info.get_timedelta_to_alarm().total_seconds() / 3600
        )
        return hours_until <= self.alarm_clock_context.config.alarm_preview_hours

    def get_next_alarm(self) -> datetime:
        return self.next_alarm_info.next_run_time

    def get_timedelta_to_alarm(self) -> timedelta:
        return self.next_alarm_info.get_timedelta_to_alarm()

    # ========== Environment Information (Domain Delegation) ==========

    def get_is_online(self) -> bool:
        return self.alarm_clock_context.environment.is_online

    @property
    def current_weather(self) -> Weather:
        return self.alarm_clock_context.environment.current_weather

    # ========== Volume Meter ==========

    def hide_volume_meter(self):
        self.show_volume_meter = False

    # ========== Playback Information (Delegation) ==========

    def current_playback_title(self) -> str:
        return (
            self.playback_content.audio_stream.stream_name
            if self.playback_content.playback_mode != Mode.Idle
            and self.playback_content.audio_stream is not None
            else None
        )

    def current_volume(self) -> float:
        return self.playback_content.volume
