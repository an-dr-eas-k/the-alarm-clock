import datetime
import unittest

from core.domain.events import (
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    VolumeChangedEvent,
    WeatherUpdatedEvent,
)
from core.domain.mode_coordinator import ModeName
from core.domain.model import Mode, RoomBrightness
from tests.interface.display_helpers import (
    DisplayEnvironment,
    make_coordinator,
    make_playback,
    next_alarm_info_at,
)
from tests.support import frozen_now, local_datetime, make_stream
from utils.geolocation import Weather


class DisplayContentInitialStateTest(unittest.TestCase):
    def test_starts_without_alarm_and_dimmed_brightness(self):
        env = DisplayEnvironment(brightness=0.5)
        fresh = type(env.content)(env.context, env.playback, env.bus)

        self.assertFalse(fresh.has_next_alarm())
        self.assertTrue(fresh.room_brightness.is_highly_dimmed())
        self.assertFalse(fresh.show_volume_meter)
        self.assertTrue(fresh.show_blink_segment)
        self.assertIsNone(fresh.current_weather)


class DisplayContentEventHandlingTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment()
        self.bus = self.env.bus
        self.content = self.env.content

    def test_volume_changed_shows_meter_and_forces_update(self):
        self.bus.emit(VolumeChangedEvent(new_volume=0.4))

        self.assertTrue(self.content.show_volume_meter)
        self.assertEqual(1, len(self.bus.emitted_of(ForcedDisplayUpdateEvent)))

    def test_playback_changed_to_idle_hides_meter(self):
        self.content.show_volume_meter = True

        self.bus.emit(PlaybackChangedEvent(Mode.Idle))

        self.assertFalse(self.content.show_volume_meter)
        # once from hide_volume_meter, once from the handler itself
        self.assertEqual(2, len(self.bus.emitted_of(ForcedDisplayUpdateEvent)))

    def test_playback_changed_to_music_keeps_meter(self):
        self.content.show_volume_meter = True

        self.bus.emit(PlaybackChangedEvent(Mode.Music, make_stream()))

        self.assertTrue(self.content.show_volume_meter)
        self.assertEqual(1, len(self.bus.emitted_of(ForcedDisplayUpdateEvent)))

    def test_weather_updated_stores_weather(self):
        weather = Weather(0, 21.5)

        self.bus.emit(WeatherUpdatedEvent(weather=weather))

        self.assertIs(weather, self.content.current_weather)

    def test_hide_volume_meter_emits_forced_update(self):
        self.content.show_volume_meter = True

        self.content.hide_volume_meter()

        self.assertFalse(self.content.show_volume_meter)
        self.assertEqual(1, len(self.bus.emitted_of(ForcedDisplayUpdateEvent)))


class UpdatePresentationStateTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment()
        self.content = self.env.content
        self.content.room_brightness = RoomBrightness(0.5)

    def test_blink_change_in_default_mode_is_reported(self):
        changed = self.content.update_presentation_state(
            False, RoomBrightness(0.5)
        )

        self.assertTrue(changed)
        self.assertFalse(self.content.show_blink_segment)

    def test_nothing_changed_reports_false(self):
        changed = self.content.update_presentation_state(True, RoomBrightness(0.5))

        self.assertFalse(changed)

    def test_brightness_change_within_same_grayscale_step_is_ignored(self):
        changed = self.content.update_presentation_state(True, RoomBrightness(0.6))

        self.assertFalse(changed)
        self.assertEqual(0.5, self.content.room_brightness.value)

    def test_significant_brightness_change_is_applied(self):
        changed = self.content.update_presentation_state(True, RoomBrightness(0.1))

        self.assertTrue(changed)
        self.assertEqual(0.1, self.content.room_brightness.value)

    def test_brightness_from_zero_is_applied(self):
        self.content.room_brightness = RoomBrightness(0.0)

        changed = self.content.update_presentation_state(True, RoomBrightness(0.5))

        self.assertTrue(changed)
        self.assertEqual(0.5, self.content.room_brightness.value)

    def test_small_relative_change_across_grayscale_step_is_ignored(self):
        self.content.room_brightness = RoomBrightness(0.15)

        changed = self.content.update_presentation_state(True, RoomBrightness(0.149))

        self.assertFalse(changed)
        self.assertEqual(0.15, self.content.room_brightness.value)

    def test_scrolling_forces_change(self):
        self.content.is_scrolling = True

        changed = self.content.update_presentation_state(True, RoomBrightness(0.5))

        self.assertTrue(changed)

    def test_menu_mode_ignores_all_changes(self):
        self.env.context.mode_coordinator = make_coordinator(ModeName.ALARM_VIEW)
        self.content.is_scrolling = True

        changed = self.content.update_presentation_state(False, RoomBrightness(0.1))

        self.assertFalse(changed)
        self.assertTrue(self.content.show_blink_segment)
        self.assertEqual(0.5, self.content.room_brightness.value)

    def test_default_mode_coordinator_behaves_like_no_coordinator(self):
        self.env.context.mode_coordinator = make_coordinator(ModeName.DEFAULT)

        changed = self.content.update_presentation_state(False, RoomBrightness(0.5))

        self.assertTrue(changed)


class NextAlarmDelegationTest(unittest.TestCase):
    def setUp(self):
        self.env = DisplayEnvironment()
        self.content = self.env.content
        self.now = local_datetime(2026, 3, 1, 6, 0)

    def test_has_next_alarm_false_without_run_time(self):
        self.assertFalse(self.content.has_next_alarm())
        self.content.next_alarm_info = None
        self.assertFalse(self.content.has_next_alarm())

    def test_update_next_alarm_makes_alarm_available(self):
        run_time = self.now + datetime.timedelta(hours=1)
        self.content.update_next_alarm(next_alarm_info_at(run_time))

        self.assertTrue(self.content.has_next_alarm())
        self.assertEqual(run_time, self.content.get_next_alarm())

    def test_alarm_preview_within_configured_hours(self):
        self.env.config.alarm_preview_hours = 12
        with frozen_now(self.now):
            self.content.update_next_alarm(
                next_alarm_info_at(self.now + datetime.timedelta(hours=12))
            )
            self.assertTrue(self.content.show_alarm_preview())

    def test_alarm_preview_hidden_beyond_configured_hours(self):
        self.env.config.alarm_preview_hours = 12
        with frozen_now(self.now):
            self.content.update_next_alarm(
                next_alarm_info_at(self.now + datetime.timedelta(hours=12, minutes=1))
            )
            self.assertFalse(self.content.show_alarm_preview())

    def test_alarm_preview_false_without_alarm(self):
        self.assertFalse(self.content.show_alarm_preview())

    def test_get_next_alarm_without_info_object_raises(self):
        self.content.next_alarm_info = None

        with self.assertRaises(AttributeError):
            self.content.get_next_alarm()


class EnvironmentAndPlaybackDelegationTest(unittest.TestCase):
    def test_is_online_follows_environment(self):
        env = DisplayEnvironment()
        env.context.environment.is_online = False
        self.assertFalse(env.content.get_is_online())
        env.context.environment.is_online = True
        self.assertTrue(env.content.get_is_online())

    def test_playback_title_none_when_idle(self):
        env = DisplayEnvironment(
            playback=make_playback(Mode.Idle, make_stream("Jazz"))
        )
        self.assertIsNone(env.content.current_playback_title())

    def test_playback_title_none_without_stream(self):
        env = DisplayEnvironment(playback=make_playback(Mode.Music, None))
        self.assertIsNone(env.content.current_playback_title())

    def test_playback_title_is_stream_name_while_playing(self):
        env = DisplayEnvironment(
            playback=make_playback(Mode.Music, make_stream("Jazz"))
        )
        self.assertEqual("Jazz", env.content.current_playback_title())

    def test_current_volume_passes_through_value(self):
        env = DisplayEnvironment(playback=make_playback(volume=0.45))
        self.assertEqual(0.45, env.content.current_volume())

    def test_current_volume_none_when_unknown(self):
        env = DisplayEnvironment(playback=make_playback(volume=None))
        self.assertIsNone(env.content.current_volume())


if __name__ == "__main__":
    unittest.main()
