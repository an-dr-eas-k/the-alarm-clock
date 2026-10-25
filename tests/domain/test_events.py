import dataclasses
import json
import unittest

from core.domain.events import (
    AlarmStoppedEvent,
    AlarmTriggeredEvent,
    ConfigChangedEvent,
    PlaybackChangedEvent,
    ShutdownSystemRequest,
    SpotifyApiEvent,
    VolumeChangeRequest,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import Mode
from core.infrastructure.event_bus import BaseEvent

from tests.support import make_alarm, make_stream


class FrozenEventsTest(unittest.TestCase):

    def test_dataclass_events_are_immutable(self):
        event = WifiStatusChangedEvent(is_online=True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.is_online = False

    def test_events_are_base_events_with_logging_enabled_by_default(self):
        event = AlarmStoppedEvent()
        self.assertIsInstance(event, BaseEvent)
        self.assertFalse(event.suppress_logging)
        self.assertIsNone(event.alarm_definition)

    def test_logging_can_be_suppressed(self):
        self.assertTrue(VolumeChangedEvent(suppress_logging=True).suppress_logging)

    def test_alarm_triggered_defaults_to_online_media(self):
        alarm = make_alarm()
        event = AlarmTriggeredEvent(alarm)
        self.assertIs(event.alarm_definition, alarm)
        self.assertFalse(event.use_offline_media)

    def test_config_changed_carries_config(self):
        config = object()
        self.assertIs(ConfigChangedEvent(config).config, config)

    def test_shutdown_request_defaults_to_no_reboot(self):
        self.assertFalse(ShutdownSystemRequest().reboot)
        self.assertTrue(ShutdownSystemRequest(reboot=True).reboot)


class VolumeChangeRequestTest(unittest.TestCase):

    def test_relative_or_absolute(self):
        self.assertEqual(VolumeChangeRequest(relative=1).relative, 1)
        self.assertEqual(VolumeChangeRequest(absolute=0.3).absolute, 0.3)

    def test_both_values_are_rejected(self):
        with self.assertRaises(ValueError):
            VolumeChangeRequest(relative=1, absolute=0.3)

    def test_neither_value_is_allowed(self):
        request = VolumeChangeRequest()
        self.assertIsNone(request.relative)
        self.assertIsNone(request.absolute)


class PlaybackChangedEventTest(unittest.TestCase):

    def test_carries_mode_stream_and_volume(self):
        stream = make_stream()
        event = PlaybackChangedEvent(Mode.Music, stream, absolute_volume=0.4)
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIs(event.audio_stream, stream)
        self.assertEqual(event.absolute, 0.4)
        self.assertIsNone(event.relative)

    def test_is_a_volume_change_request(self):
        self.assertIsInstance(PlaybackChangedEvent(Mode.Idle), VolumeChangeRequest)

    def test_rejects_relative_and_absolute_volume_together(self):
        with self.assertRaises(ValueError):
            PlaybackChangedEvent(Mode.Music, relative_volume=1, absolute_volume=0.2)


class SpotifyApiEventTest(unittest.TestCase):

    def test_attributes_are_populated_from_dict(self):
        event = SpotifyApiEvent({"player_event": "playing", "name": "Song"})
        self.assertEqual(event.player_event, "playing")
        self.assertEqual(event.name, "Song")

    def test_classification_of_player_events(self):
        cases = {
            "session_connected": "is_playback_started",
            "playing": "is_playback_started",
            "track_changed": "is_track_changed",
            "session_disconnected": "is_playback_stopped",
            "stopped": "is_playback_stopped",
            "paused": "is_playback_stopped",
            "volume_changed": "is_volume_changed",
        }
        predicates = {
            "is_playback_started",
            "is_track_changed",
            "is_playback_stopped",
            "is_volume_changed",
        }
        for player_event, expected_predicate in cases.items():
            event = SpotifyApiEvent({"player_event": player_event})
            for predicate in predicates:
                with self.subTest(player_event=player_event, predicate=predicate):
                    self.assertEqual(
                        getattr(event, predicate)(), predicate == expected_predicate
                    )

    def test_unknown_or_missing_player_event_matches_nothing(self):
        for event in (SpotifyApiEvent({"player_event": "preloading"}), SpotifyApiEvent({})):
            self.assertFalse(event.is_playback_started())
            self.assertFalse(event.is_track_changed())
            self.assertFalse(event.is_playback_stopped())
            self.assertFalse(event.is_volume_changed())

    def test_str_is_json(self):
        payload = {"player_event": "playing", "name": "Song"}
        self.assertEqual(json.loads(str(SpotifyApiEvent(payload))), payload)


if __name__ == "__main__":
    unittest.main()
