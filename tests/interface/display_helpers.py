"""Fixtures shared by the display related interface tests."""

from __future__ import annotations

import datetime
import os
from types import SimpleNamespace
from unittest import mock

# Qt must never try to open a real display; read when the application is created.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from core.domain.model import (  # noqa: E402
    AlarmClockContext,
    Mode,
    NextAlarmInfo,
    RoomBrightness,
    VisualEffect,
)
from core.interface.display.display_content import DisplayContent  # noqa: E402
from core.interface.display.format import DisplayFormatter  # noqa: E402
from tests.support import RecordingEventBus, make_alarm, make_config  # noqa: E402


def make_playback(mode: Mode = Mode.Idle, stream=None, volume: float | None = 0.3):
    return SimpleNamespace(playback_mode=mode, audio_stream=stream, volume=volume)


def make_coordinator(mode_name, editing_service=None):
    return SimpleNamespace(
        current_mode_name=mode_name, editing_service=editing_service
    )


def next_alarm_info_at(
    run_time: datetime.datetime, with_visual_effect: bool = False, label=None
) -> NextAlarmInfo:
    alarm = make_alarm(label=label)
    if not with_visual_effect:
        alarm.visual_effect = None
    else:
        alarm.visual_effect = VisualEffect()
    return NextAlarmInfo(run_time, alarm)


class DisplayEnvironment:
    """Wires context, content and formatter around a recording event bus."""

    def __init__(self, brightness: float = 1.0, playback=None):
        self.bus = RecordingEventBus()
        self.config = make_config(self.bus)
        self.context = AlarmClockContext(self.config, is_online=True)
        self.playback = playback or make_playback()
        self.content = DisplayContent(self.context, self.playback, self.bus)
        self.content.room_brightness = RoomBrightness(brightness)
        self.formatter = DisplayFormatter(self.content, self.context)


def make_device(width: int = 256, height: int = 64, mode: str = "RGB"):
    device = mock.MagicMock()
    device.width = width
    device.height = height
    device.mode = mode
    return device
