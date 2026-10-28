"""Shared helpers for the test-suite."""

from __future__ import annotations

import datetime
from contextlib import contextmanager
from unittest import mock

from core.domain.model import (
    AlarmDefinition,
    AudioStream,
    Config,
    StreamAudioEffect,
    VisualEffect,
)
from core.infrastructure.event_bus import BaseEvent, EventBus
from utils.geolocation import GeoLocation


class RecordingEventBus(EventBus):
    """Synchronous EventBus that records every emitted event, even unhandled ones."""

    def __init__(self):
        super().__init__()
        self.emitted: list[BaseEvent] = []

    def emit(self, event: BaseEvent):
        self.emitted.append(event)
        super().emit(event)

    def emit_async(self, event: BaseEvent):
        self.emit(event)

    def emitted_of(self, event_type: type) -> list:
        return [e for e in self.emitted if isinstance(e, event_type)]


@contextmanager
def frozen_now(moment: datetime.datetime):
    """Make ``GeoLocation().now()`` return ``moment`` (must be tz-aware)."""
    with mock.patch.object(GeoLocation(), "now", return_value=moment):
        yield moment


def local_datetime(*args, **kwargs) -> datetime.datetime:
    """A tz-aware datetime in the configured GeoLocation timezone."""
    return datetime.datetime(*args, tzinfo=GeoLocation().location_info.tzinfo, **kwargs)


def make_stream(name: str = "Radio", url: str = "http://example.com/stream", id=None):
    return AudioStream(stream_name=name, stream_url=url, id=id)


def make_alarm(
    id: str | None = "a1",
    hour: int = 7,
    minute: int = 30,
    recurring=None,
    onetime=None,
    is_active: bool = True,
    volume: float = 0.3,
    stream: AudioStream | None = None,
    fadein_in_secs: int = 0,
    label: str | None = None,
) -> AlarmDefinition:
    alarm = AlarmDefinition()
    alarm.id = id
    alarm.hour = hour
    alarm.min = minute
    alarm.alarm_name = "Test Alarm"
    alarm.is_active = is_active
    alarm.recurring = recurring
    alarm.onetime = onetime
    alarm.fadein_in_secs = fadein_in_secs
    alarm.alarm_label = label
    alarm.audio_effect = StreamAudioEffect(
        audio_stream=stream or make_stream(), volume=volume
    )
    alarm.visual_effect = VisualEffect()
    return alarm


def make_config(event_bus: EventBus | None = None, streams=None) -> Config:
    config = Config(event_bus)
    for stream in streams if streams is not None else [make_stream(id="s1")]:
        config.add_audio_stream(stream)
    return config
