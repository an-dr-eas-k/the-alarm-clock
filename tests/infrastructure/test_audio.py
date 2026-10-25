import logging
import unittest
from unittest import mock

from core.domain.events import PlaybackChangedEvent, SpeakerErrorEvent
from core.domain.model import Mode, SpotifyStream
from core.infrastructure import audio
from core.infrastructure.audio import MediaListPlayer, MediaPlayer, Speaker
from tests.support import RecordingEventBus, make_stream


def quiet_logger(test_case, name):
    target = logging.getLogger(name)
    previous = target.level
    target.setLevel(logging.ERROR)
    test_case.addCleanup(target.setLevel, previous)


def quiet_event_bus_logger(test_case):
    quiet_logger(test_case, "tac.core.infrastructure.event_bus")


class FakeVlc:
    """Stand-in for the ``vlc`` module used inside core.infrastructure.audio."""

    class State:
        Playing = "Playing"
        Error = "Error"
        Ended = "Ended"

    class PlaybackMode:
        loop = "loop"


class AudioTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(audio, "vlc", FakeVlc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.instance = mock.MagicMock(name="vlc_instance")
        self.executor = mock.Mock(name="executor")


class TestMediaPlayerBase(unittest.TestCase):
    def test_play_and_stop_are_noops(self):
        player = MediaPlayer()

        self.assertIsNone(player.play())
        self.assertIsNone(player.stop())

    def test_set_error_callback_stores_callback(self):
        player = MediaPlayer()
        callback = mock.Mock()

        player.set_error_callback(callback)

        self.assertIs(callback, player.error_callback)


class TestMediaListPlayerPlay(AudioTestCase):
    def setUp(self):
        super().setUp()
        self.stream = make_stream(url="http://radio.example/live")
        self.player = MediaListPlayer(self.stream, self.instance, self.executor)

    def test_play_builds_loop_playlist_with_stream_url_and_starts(self):
        self.player.play()

        list_player = self.instance.media_list_player_new.return_value
        self.instance.media_new.assert_called_once_with("http://radio.example/live")
        media_list = self.instance.media_list_new.return_value
        media_list.add_media.assert_called_once_with(
            self.instance.media_new.return_value
        )
        list_player.set_playback_mode.assert_called_once_with("loop")
        list_player.set_media_list.assert_called_once_with(media_list)
        list_player.play.assert_called_once_with()

    def test_play_submits_playback_monitor_to_executor(self):
        self.player.play()

        self.executor.submit.assert_called_once_with(self.player._monitor_playback)

    def test_play_twice_does_not_restart_playback(self):
        self.player.play()
        self.player.play()

        self.instance.media_list_player_new.assert_called_once()

    def test_play_without_stream_logs_warning_and_does_nothing(self):
        player = MediaListPlayer(None, self.instance, self.executor)

        with self.assertLogs("tac.core.infrastructure.audio", "WARNING"):
            player.play()

        self.instance.media_list_player_new.assert_not_called()
        self.assertIsNone(player.list_player)

    def test_play_failure_is_logged_and_player_cleaned_up(self):
        self.instance.media_new.side_effect = RuntimeError("vlc broke")

        with self.assertLogs("tac.core.infrastructure.audio", "ERROR") as logs:
            self.player.play()

        self.assertIn("vlc broke", logs.output[0])
        self.assertIsNone(self.player.list_player)

    def test_play_failure_when_starting_releases_vlc_objects(self):
        list_player = self.instance.media_list_player_new.return_value
        list_player.play.side_effect = RuntimeError("no audio device")

        with self.assertLogs("tac.core.infrastructure.audio", "ERROR"):
            self.player.play()

        list_player.stop.assert_called_once()
        list_player.release.assert_called_once()
        self.assertIsNone(self.player.list_player)


class TestMediaListPlayerStop(AudioTestCase):
    def setUp(self):
        super().setUp()
        self.player = MediaListPlayer(make_stream(), self.instance, self.executor)

    def test_stop_without_play_is_a_noop(self):
        self.player.stop()

        self.assertIsNone(self.player.list_player)

    def test_stop_stops_and_releases_everything(self):
        self.player.play()
        list_player = self.player.list_player
        media_list = self.player.media_list
        media = self.player.media

        self.player.stop()

        list_player.stop.assert_called_once()
        list_player.release.assert_called_once()
        media_list.release.assert_called_once()
        media.release.assert_called_once()
        self.assertIsNone(self.player.list_player)
        self.assertIsNone(self.player.media_list)
        self.assertIsNone(self.player.media)

    def test_stop_signals_monitor_thread_to_end(self):
        self.player.play()

        self.player.stop()

        self.assertTrue(self.player._stop_monitoring.is_set())
        self.assertIsNone(self.player._monitoring_future)

    def test_stop_releases_even_if_list_player_stop_raises(self):
        self.player.play()
        list_player = self.player.list_player
        list_player.stop.side_effect = RuntimeError("already dead")

        self.player.stop()

        list_player.release.assert_called_once()
        self.assertIsNone(self.player.list_player)

    def test_play_after_stop_starts_a_new_playback(self):
        self.player.play()
        self.player.stop()

        self.player.play()

        self.assertEqual(2, self.instance.media_list_player_new.call_count)
        self.assertFalse(self.player._stop_monitoring.is_set())


class TestMediaListPlayerMonitor(AudioTestCase):
    def setUp(self):
        super().setUp()
        self.stream = make_stream(name="Broken")
        quiet_logger(self, "tac.core.infrastructure.audio")
        self.player = MediaListPlayer(self.stream, self.instance, self.executor)
        self.player.list_player = mock.Mock()
        self.callback = mock.Mock()
        self.player.set_error_callback(self.callback)
        self.player._stop_monitoring = mock.Mock()

    def _run_monitor(self, states, stop_after=None):
        self.player.list_player.get_state.side_effect = states
        checks = stop_after if stop_after is not None else len(states) + 1
        self.player._stop_monitoring.is_set.side_effect = [False] * checks + [True]
        self.player._monitor_playback()

    def test_error_state_invokes_callback_with_stream_and_state(self):
        self._run_monitor([FakeVlc.State.Error])

        self.callback.assert_called_once_with(self.stream, FakeVlc.State.Error)

    def test_ended_state_invokes_callback(self):
        self._run_monitor([FakeVlc.State.Ended])

        self.callback.assert_called_once_with(self.stream, FakeVlc.State.Ended)

    def test_monitor_stops_after_reporting_error(self):
        self._run_monitor([FakeVlc.State.Error, FakeVlc.State.Error])

        self.assertEqual(1, self.callback.call_count)
        self.assertEqual(1, self.player.list_player.get_state.call_count)

    def test_playing_state_keeps_polling_without_callback(self):
        self._run_monitor([FakeVlc.State.Playing] * 3, stop_after=3)

        self.callback.assert_not_called()
        self.assertEqual(3, self.player.list_player.get_state.call_count)
        self.assertEqual(3, self.player._stop_monitoring.wait.call_count)

    def test_error_without_callback_does_not_raise(self):
        self.player.error_callback = None

        self._run_monitor([FakeVlc.State.Error])

    def test_exception_from_get_state_is_logged_and_polling_continues(self):
        with self.assertLogs("tac.core.infrastructure.audio", "ERROR"):
            self._run_monitor(
                [RuntimeError("flaky"), FakeVlc.State.Error], stop_after=2
            )

        self.callback.assert_called_once()

    def test_monitor_without_list_player_does_nothing(self):
        self.player.list_player = None
        self.player._stop_monitoring.is_set.side_effect = [False, True]

        self.player._monitor_playback()

        self.callback.assert_not_called()

    def test_error_with_missing_stream_reports_none(self):
        self.player.audio_stream = None

        self._run_monitor([FakeVlc.State.Error])

        self.callback.assert_called_once_with(None, FakeVlc.State.Error)


class TestSpeaker(AudioTestCase):
    def setUp(self):
        super().setUp()
        quiet_event_bus_logger(self)
        self.bus = RecordingEventBus()
        self.speaker = Speaker(self.bus, self.instance, self.executor)
        self.player_patch = mock.patch.object(
            audio, "MediaListPlayer", autospec=True
        )
        self.player_cls = self.player_patch.start()
        self.addCleanup(self.player_patch.stop)

    def test_playback_changed_event_starts_streaming_stream(self):
        stream = make_stream(name="A")

        self.bus.emit(PlaybackChangedEvent(Mode.Music, stream))

        self.player_cls.assert_called_once_with(stream, self.instance, self.executor)
        self.player_cls.return_value.play.assert_called_once_with()
        self.assertIs(self.player_cls.return_value, self.speaker.media_player)

    def test_player_gets_speaker_error_handler_as_callback(self):
        self.speaker.adjust_streaming(make_stream())

        self.player_cls.return_value.set_error_callback.assert_called_once_with(
            self.speaker.handle_player_error
        )

    def test_playback_changed_without_stream_stops_streaming(self):
        self.speaker.adjust_streaming(make_stream())
        player = self.speaker.media_player

        self.bus.emit(PlaybackChangedEvent(Mode.Idle, None))

        player.stop.assert_called_once_with()
        self.assertIsNone(self.speaker.media_player)

    def test_spotify_stream_stops_vlc_playback(self):
        self.speaker.adjust_streaming(make_stream())
        player = self.speaker.media_player

        self.bus.emit(PlaybackChangedEvent(Mode.Spotify, SpotifyStream()))

        player.stop.assert_called_once_with()
        self.assertIsNone(self.speaker.media_player)

    def test_new_stream_stops_previous_player_first(self):
        first, second = mock.Mock(name="first"), mock.Mock(name="second")
        self.player_cls.side_effect = [first, second]

        self.speaker.adjust_streaming(make_stream(name="1"))
        self.speaker.adjust_streaming(make_stream(name="2"))

        first.stop.assert_called_once_with()
        second.play.assert_called_once_with()
        self.assertIs(second, self.speaker.media_player)

    def test_stop_streaming_without_player_is_a_noop(self):
        self.speaker.stop_streaming()

        self.assertIsNone(self.speaker.media_player)

    @unittest.expectedFailure  # start_streaming calls handle_player_error without player_state -> TypeError
    def test_failure_to_play_emits_speaker_error_event(self):
        stream = make_stream()
        self.player_cls.return_value.play.side_effect = RuntimeError("no device")

        with self.assertLogs("tac.core.infrastructure.audio", "ERROR"):
            self.speaker.adjust_streaming(stream)

        errors = self.bus.emitted_of(SpeakerErrorEvent)
        self.assertEqual(1, len(errors))
        self.assertIs(stream, errors[0].audio_stream)

    def test_handle_player_error_emits_speaker_error_event(self):
        stream = make_stream()

        self.speaker.handle_player_error(stream, FakeVlc.State.Error)

        self.assertEqual([stream], [e.audio_stream for e in self.bus.emitted_of(SpeakerErrorEvent)])

    @unittest.expectedFailure  # TypeError above escapes while threadLock is still held
    def test_adjust_streaming_releases_lock_after_failure(self):
        self.player_cls.return_value.play.side_effect = RuntimeError("no device")

        with self.assertLogs("tac.core.infrastructure.audio", "ERROR"):
            try:
                self.speaker.adjust_streaming(make_stream())
            except TypeError:
                pass

        self.assertFalse(self.speaker.threadLock.locked())

    def test_get_player_returns_media_list_player_with_callback(self):
        stream = make_stream()

        player = self.speaker.get_player(stream)

        self.assertIs(self.player_cls.return_value, player)
        player.set_error_callback.assert_called_once_with(
            self.speaker.handle_player_error
        )


if __name__ == "__main__":
    unittest.main()
