from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.job import Job

from core.domain.model import (
    AlarmClockContext,
    Mode,
    RoomBrightness,
    Weather,
    VisualEffect,
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

    def __init__(
        self,
        next_run_time: datetime = None,
        alarm_name: str = None,
        visual_effect: "VisualEffect" = None,
    ):
        self._next_run_time = next_run_time
        self._alarm_name = alarm_name
        self._visual_effect = visual_effect

    @property
    def next_run_time(self) -> datetime:
        return self._next_run_time

    @property
    def alarm_name(self) -> str:
        return self._alarm_name

    @property
    def visual_effect(self) -> "VisualEffect":
        return self._visual_effect

    def has_alarm(self) -> bool:
        return self._next_run_time is not None

    def get_timedelta_to_alarm(self) -> timedelta:
        if not self.has_alarm():
            return timedelta.max
        return self._calculate_time_delta()

    def _calculate_time_delta(self) -> timedelta:
        from utils.geolocation import GeoLocation

        now = GeoLocation().now()
        return self._next_run_time - now

    def minutes_until_alarm(self) -> int:
        return int(self.get_timedelta_to_alarm().total_seconds() / 60)


class DisplayContent:

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
        self.alarm_clock_context = alarm_clock_context
        self.playback_content = playback_content
        self.event_bus = event_bus
        self.next_alarm_info = NextAlarmInfo()
        self.room_brightness = RoomBrightness(1.0)

        self.event_bus.on(AudioStreamChangedEvent)(self._audio_stream_changed)
        self.event_bus.on(VolumeChangedEvent)(self._volume_changed)

    # ========== Event Handlers ==========

    def _audio_stream_changed(self, event: AudioStreamChangedEvent):
        if event.audio_stream is None:
            self.hide_volume_meter()
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    def _volume_changed(self, _: VolumeChangedEvent):
        self.show_volume_meter = True
        self.event_bus.emit(ForcedDisplayUpdateEvent())

    # ========== Presentation State Updates ==========

    def update_presentation_state(
        self,
        show_blink_segment: bool = None,
        room_brightness: RoomBrightness = None,
        is_scrolling: bool = None,
    ) -> bool:
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
        if job is None:
            self.next_alarm_info = NextAlarmInfo()
            return

        from core.domain.model import AlarmDefinition
        from utils.extensions import get_job_arg

        alarm_def = get_job_arg(job, AlarmDefinition)

        self.next_alarm_info = NextAlarmInfo(
            next_run_time=job.next_run_time,
            alarm_name=alarm_def.alarm_name if alarm_def else None,
            visual_effect=alarm_def.visual_effect if alarm_def else None,
        )

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
