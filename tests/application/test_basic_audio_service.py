import logging
import unittest
from unittest import mock

from core.application.basic_audio_service import BasicAudioService
from core.domain.events import (
    ConfigChangedEvent,
    PlaybackChangedEvent,
    SpeakerErrorEvent,
    SpotifyApiEvent,
    StreamChangeRequest,
    ToggleAudioRequest,
    VolumeChangedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import (
    AlarmClockContext,
    Mode,
    OfflineStream,
    SpotifyStream,
)
from tests.support import RecordingEventBus, make_alarm, make_config, make_stream

logging.getLogger("tac").addHandler(logging.NullHandler())


class _InstantiableBasicAudioService(BasicAudioService):
    """BasicAudioService registers a ``_config_changed`` handler it does not define."""

    def _config_changed(self, event: ConfigChangedEvent):
        pass


class BasicAudioServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.bus = RecordingEventBus()
        self.streams = [
            make_stream("One", "http://one", id="s1"),
            make_stream("Two", "http://two", id="s2"),
            make_stream("Three", "http://three", id="s3"),
        ]
        self.config = make_config(self.bus, streams=self.streams)
        self.context = AlarmClockContext(self.config, is_online=True)
        self.playback = mock.MagicMock()
        self.playback.playback_mode = Mode.Idle
        self.playback.audio_stream = None
        self.service = _InstantiableBasicAudioService(
            self.context,
            mock.MagicMock(),
            self.playback,
            self.bus,
            mock.MagicMock(),
            mock.MagicMock(),
        )

    def last_playback_event(self) -> PlaybackChangedEvent:
        events = self.bus.emitted_of(PlaybackChangedEvent)
        self.assertTrue(events, "no PlaybackChangedEvent emitted")
        return events[-1]


class ToggleStreamTests(BasicAudioServiceTestCase):
    def test_toggle_while_playing_emits_idle(self):
        self.playback.playback_mode = Mode.Music
        self.bus.emit(ToggleAudioRequest())
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Idle)
        self.assertIsNone(event.audio_stream)

    def test_toggle_during_alarm_emits_idle(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(ToggleAudioRequest())
        self.assertEqual(self.last_playback_event().playback_mode, Mode.Idle)

    def test_toggle_when_idle_without_history_plays_default_stream(self):
        self.bus.emit(ToggleAudioRequest())
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIs(event.audio_stream, self.streams[0])

    def test_toggle_when_idle_resumes_previously_played_stream(self):
        self.playback.audio_stream = self.streams[2]
        self.bus.emit(ToggleAudioRequest())
        self.assertIs(self.last_playback_event().audio_stream, self.streams[2])

    def test_toggle_when_idle_ignores_previous_offline_stream(self):
        self.playback.audio_stream = self.config.get_offline_stream()
        self.bus.emit(ToggleAudioRequest())
        self.assertIs(self.last_playback_event().audio_stream, self.streams[0])

    def test_toggle_when_idle_resumes_previous_spotify_stream(self):
        spotify = SpotifyStream({"name": "Song"})
        self.playback.audio_stream = spotify
        self.bus.emit(ToggleAudioRequest())
        self.assertIs(self.last_playback_event().audio_stream, spotify)

    def test_toggle_when_idle_without_any_streams_emits_music_without_stream(self):
        self.config.audio_streams.clear()
        self.bus.emit(ToggleAudioRequest())
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIsNone(event.audio_stream)


class ChangeStreamTests(BasicAudioServiceTestCase):
    def test_ignored_when_not_in_music_mode(self):
        for mode in (Mode.Idle, Mode.Alarm, Mode.Spotify, Mode.Boot):
            self.playback.playback_mode = mode
            self.bus.emit(StreamChangeRequest())
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_ignored_when_no_streams_configured(self):
        self.config.audio_streams.clear()
        self.playback.playback_mode = Mode.Music
        self.bus.emit(StreamChangeRequest())
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_switches_to_next_stream(self):
        self.playback.playback_mode = Mode.Music
        self.playback.audio_stream = self.streams[0]
        self.bus.emit(StreamChangeRequest())
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Music)
        self.assertIs(event.audio_stream, self.streams[1])

    def test_wraps_around_after_last_stream(self):
        self.playback.playback_mode = Mode.Music
        self.playback.audio_stream = self.streams[2]
        self.bus.emit(StreamChangeRequest())
        self.assertIs(self.last_playback_event().audio_stream, self.streams[0])

    def test_unknown_current_stream_starts_with_first_stream(self):
        self.playback.playback_mode = Mode.Music
        self.playback.audio_stream = make_stream("Gone", id="gone")
        self.bus.emit(StreamChangeRequest())
        self.assertIs(self.last_playback_event().audio_stream, self.streams[0])

    def test_single_stream_selects_itself_again(self):
        self.config.audio_streams[:] = [self.streams[0]]
        self.playback.playback_mode = Mode.Music
        self.playback.audio_stream = self.streams[0]
        self.bus.emit(StreamChangeRequest())
        self.assertIs(self.last_playback_event().audio_stream, self.streams[0])


class SpotifyEventTests(BasicAudioServiceTestCase):
    def spotify(self, player_event, **extra) -> SpotifyApiEvent:
        return SpotifyApiEvent(dict(player_event=player_event, **extra))

    def test_playback_started_switches_to_spotify_mode(self):
        self.bus.emit(self.spotify("playing", name="Song", artists="Artist"))
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Spotify)
        self.assertIsInstance(event.audio_stream, SpotifyStream)
        self.assertEqual(event.audio_stream.track_name, "Song")
        self.assertEqual(event.audio_stream.stream_name, "Spotify: Song by Artist")

    def test_session_connected_switches_to_spotify_mode(self):
        self.bus.emit(self.spotify("session_connected"))
        self.assertEqual(self.last_playback_event().playback_mode, Mode.Spotify)

    def test_playing_event_while_already_in_spotify_mode_is_ignored(self):
        self.playback.playback_mode = Mode.Spotify
        self.bus.emit(self.spotify("playing"))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_track_change_is_forwarded_even_in_spotify_mode(self):
        self.playback.playback_mode = Mode.Spotify
        self.bus.emit(self.spotify("track_changed", name="Next"))
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Spotify)
        self.assertEqual(event.audio_stream.track_name, "Next")

    def test_multiline_metadata_keeps_only_first_line(self):
        self.bus.emit(self.spotify("track_changed", artists="A\nB"))
        self.assertEqual(self.last_playback_event().audio_stream.track_artists, "A")

    def test_stopped_event_switches_to_idle_when_playing(self):
        for player_event in ("stopped", "paused", "session_disconnected"):
            self.bus.emitted.clear()
            self.playback.playback_mode = Mode.Spotify
            self.bus.emit(self.spotify(player_event))
            self.assertEqual(
                self.last_playback_event().playback_mode, Mode.Idle, player_event
            )

    def test_stopped_event_while_idle_is_ignored(self):
        self.bus.emit(self.spotify("stopped"))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_volume_change_in_spotify_mode_emits_volume_changed(self):
        self.playback.playback_mode = Mode.Spotify
        self.bus.emit(self.spotify("volume_changed", volume="30"))
        self.assertEqual(len(self.bus.emitted_of(VolumeChangedEvent)), 1)

    def test_volume_change_outside_spotify_mode_is_ignored(self):
        self.playback.playback_mode = Mode.Music
        self.bus.emit(self.spotify("volume_changed"))
        self.assertEqual(self.bus.emitted_of(VolumeChangedEvent), [])

    def test_unrelated_player_event_has_no_effect(self):
        self.bus.emit(self.spotify("preloading"))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])
        self.assertEqual(self.bus.emitted_of(VolumeChangedEvent), [])


class SpeakerErrorTests(BasicAudioServiceTestCase):
    def test_error_during_alarm_falls_back_to_offline_stream(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(SpeakerErrorEvent(self.streams[0]))
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Alarm)
        self.assertIsInstance(event.audio_stream, OfflineStream)

    def test_error_while_playing_music_switches_to_idle(self):
        self.playback.playback_mode = Mode.Music
        self.bus.emit(SpeakerErrorEvent(self.streams[0]))
        self.assertEqual(self.last_playback_event().playback_mode, Mode.Idle)

    def test_error_while_idle_is_ignored(self):
        self.bus.emit(SpeakerErrorEvent(self.streams[0]))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_offline_stream_errors_are_ignored_to_avoid_loops(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(SpeakerErrorEvent(self.config.get_offline_stream()))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_error_without_stream_info_is_still_handled(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(SpeakerErrorEvent())
        self.assertIsInstance(self.last_playback_event().audio_stream, OfflineStream)


class WifiStatusTests(BasicAudioServiceTestCase):
    def setUp(self):
        super().setUp()
        self.alarm = make_alarm(stream=self.streams[1])
        self.context.active_alarm_definition = self.alarm

    def test_going_online_during_alarm_restores_configured_alarm_stream(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(WifiStatusChangedEvent(is_online=True))
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Alarm)
        self.assertIs(event.audio_stream, self.streams[1])

    def test_going_offline_during_alarm_switches_to_offline_stream(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(WifiStatusChangedEvent(is_online=False))
        event = self.last_playback_event()
        self.assertEqual(event.playback_mode, Mode.Alarm)
        self.assertIsInstance(event.audio_stream, OfflineStream)
        self.assertEqual(len(self.bus.emitted_of(PlaybackChangedEvent)), 1)

    def test_going_offline_stops_music_and_spotify(self):
        for mode in (Mode.Music, Mode.Spotify):
            self.bus.emitted.clear()
            self.playback.playback_mode = mode
            self.bus.emit(WifiStatusChangedEvent(is_online=False))
            self.assertEqual(self.last_playback_event().playback_mode, Mode.Idle)

    def test_going_offline_while_idle_does_nothing(self):
        self.bus.emit(WifiStatusChangedEvent(is_online=False))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])

    def test_going_online_outside_alarm_does_nothing(self):
        for mode in (Mode.Idle, Mode.Music, Mode.Spotify):
            self.playback.playback_mode = mode
            self.bus.emit(WifiStatusChangedEvent(is_online=True))
        self.assertEqual(self.bus.emitted_of(PlaybackChangedEvent), [])


class InstantiationTests(unittest.TestCase):
    # production bug: __init__ registers self._config_changed which only AlarmAudioService defines
    @unittest.expectedFailure
    def test_base_service_can_be_instantiated_directly(self):
        bus = RecordingEventBus()
        BasicAudioService(
            AlarmClockContext(make_config(bus)),
            mock.MagicMock(),
            mock.MagicMock(),
            bus,
            mock.MagicMock(),
            mock.MagicMock(),
        )


if __name__ == "__main__":
    unittest.main()
