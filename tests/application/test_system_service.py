import datetime
import logging
import unittest
from unittest import mock

from core.application.system_service import SystemService, safe_action
from core.domain.events import (
    AlarmStoppedEvent,
    AlarmTriggeredEvent,
    ForcedDisplayUpdateEvent,
    PlaybackChangedEvent,
    PreAlarmTriggeredEvent,
    ShutdownSystemRequest,
    SpotifyStoppedEvent,
    StartupFinishedEvent,
    SunEventOccurredEvent,
    TerminateAppRequest,
    VolumeChangedEvent,
    WeatherUpdatedEvent,
    WifiStatusChangedEvent,
)
from core.domain.model import AlarmClockContext, Mode, RoomBrightness, SchedulerJobIds
from core.infrastructure.scheduler import SchedulerStores
from tests.support import (
    RecordingEventBus,
    frozen_now,
    local_datetime,
    make_alarm,
    make_config,
)
from utils.geolocation import GeoLocation, SunEvent

logging.getLogger("tac").addHandler(logging.NullHandler())

test_logger = logging.getLogger("tac.tests.system_service")


class SafeActionTests(unittest.TestCase):
    def test_runs_action_and_logs_messages(self):
        action = mock.MagicMock()
        logger = mock.MagicMock()
        safe_action(action, info_msg="info", debug_msg="debug", logger=logger)
        action.assert_called_once_with()
        logger.info.assert_called_once_with("info")
        logger.debug.assert_called_once_with("debug")

    def test_exceptions_are_logged_and_swallowed(self):
        logger = mock.MagicMock()
        safe_action(mock.MagicMock(side_effect=RuntimeError("boom")), logger=logger)
        logger.error.assert_called_once()
        self.assertIn("boom", logger.error.call_args.args[1])

    # production bug: the ValueError is caught by the bare except, which then fails on logger=None
    @unittest.expectedFailure
    def test_missing_logger_is_rejected_with_value_error(self):
        action = mock.MagicMock()
        with self.assertRaises(ValueError):
            safe_action(action)


class SystemServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.bus = RecordingEventBus()
        self.config = make_config(self.bus)
        self.context = AlarmClockContext(self.config, is_online=False)
        self.scheduler = mock.MagicMock()
        self.display_content = mock.MagicMock()
        self.display_content.show_blink_segment = False
        self.brightness_sensor = mock.MagicMock()
        self.brightness_sensor.get_room_brightness.return_value = 0.5
        self.os_interaction = mock.MagicMock()
        self.os_interaction.is_internet_available.return_value = False
        self.geo = GeoLocation()
        self.weather = object()
        weather_patch = mock.patch.object(
            self.geo, "get_current_weather", return_value=self.weather
        )
        self.get_weather = weather_patch.start()
        self.addCleanup(weather_patch.stop)
        self.service = self.create_service()

    def create_service(self) -> SystemService:
        return SystemService(
            self.context,
            self.scheduler,
            self.bus,
            self.display_content,
            self.brightness_sensor,
            self.os_interaction,
        )


class InitializationTests(SystemServiceTestCase):
    def test_periodic_jobs_are_registered(self):
        jobs = {c.kwargs["job_id"]: c for c in self.scheduler.add_job.call_args_list}
        self.assertEqual(
            set(jobs),
            {
                SchedulerJobIds.regular_display_refresh.value,
                SchedulerJobIds.wifi_check.value,
                SchedulerJobIds.weather_update_interval.value,
            },
        )
        refresh = jobs[SchedulerJobIds.regular_display_refresh.value]
        self.assertEqual(
            refresh.kwargs["seconds"], self.config.refresh_timeout_in_secs
        )
        self.assertEqual(jobs[SchedulerJobIds.wifi_check.value].kwargs["seconds"], 60)
        self.assertEqual(
            jobs[SchedulerJobIds.weather_update_interval.value].kwargs["minutes"], 5
        )
        for call in jobs.values():
            self.assertEqual(call.kwargs["trigger"], "interval")
            self.assertEqual(call.kwargs["jobstore"], SchedulerStores.default.value)

    def test_sun_event_jobs_are_registered_for_every_sun_event(self):
        job_ids = [c.kwargs["job_id"] for c in self.scheduler.add_cron_job.call_args_list]
        self.assertCountEqual(job_ids, [e.value for e in SunEvent])
        for call in self.scheduler.add_cron_job.call_args_list:
            self.assertIn("hour", call.kwargs)
            self.assertIn("minute", call.kwargs)

    def test_active_jobs_are_logged_for_default_store(self):
        self.scheduler.log_active_jobs.assert_called_once_with(
            SchedulerStores.default.value
        )

    def test_offline_start_does_not_query_weather(self):
        self.get_weather.assert_not_called()
        self.assertEqual(self.bus.emitted_of(WeatherUpdatedEvent), [])

    def test_online_start_publishes_current_weather(self):
        self.context.environment.is_online = True
        self.create_service()
        (event,) = self.bus.emitted_of(WeatherUpdatedEvent)
        self.assertIs(event.weather, self.weather)
        self.assertIs(self.context.environment.current_weather, self.weather)


class WifiStatusTests(SystemServiceTestCase):
    def test_going_online_updates_environment_and_weather(self):
        self.bus.emit(WifiStatusChangedEvent(is_online=True))
        self.assertTrue(self.context.environment.is_online)
        (event,) = self.bus.emitted_of(WeatherUpdatedEvent)
        self.assertIs(event.weather, self.weather)

    def test_going_online_with_unchanged_weather_emits_nothing(self):
        self.context.environment.current_weather = self.weather
        self.bus.emit(WifiStatusChangedEvent(is_online=True))
        self.assertEqual(self.bus.emitted_of(WeatherUpdatedEvent), [])

    def test_going_offline_keeps_weather_until_next_periodic_update(self):
        self.context.environment.is_online = True
        self.context.environment.current_weather = self.weather
        self.bus.emit(WifiStatusChangedEvent(is_online=False))
        self.assertFalse(self.context.environment.is_online)
        self.assertIs(self.context.environment.current_weather, self.weather)
        self.assertEqual(self.bus.emitted_of(WeatherUpdatedEvent), [])

        self.service._update_weather_status()

        (event,) = self.bus.emitted_of(WeatherUpdatedEvent)
        self.assertIsNone(event.weather)
        self.assertIsNone(self.context.environment.current_weather)

    def test_wifi_check_emits_event_when_connectivity_changed(self):
        self.os_interaction.is_internet_available.return_value = True
        self.service._update_wifi_status()
        events = self.bus.emitted_of(WifiStatusChangedEvent)
        self.assertEqual([e.is_online for e in events], [True])
        self.assertTrue(self.context.environment.is_online)

    def test_wifi_check_is_silent_when_connectivity_is_unchanged(self):
        self.service._update_wifi_status()
        self.assertEqual(self.bus.emitted_of(WifiStatusChangedEvent), [])

    def test_wifi_check_detects_connection_loss(self):
        self.context.environment.is_online = True
        self.service._update_wifi_status()
        events = self.bus.emitted_of(WifiStatusChangedEvent)
        self.assertEqual([e.is_online for e in events], [False])

    def test_wifi_check_errors_are_swallowed(self):
        self.os_interaction.is_internet_available.side_effect = OSError("no ping")
        self.service._update_wifi_status()
        self.assertEqual(self.bus.emitted_of(WifiStatusChangedEvent), [])

    def test_startup_finished_checks_wifi_status(self):
        self.os_interaction.is_internet_available.return_value = True
        self.bus.emit(StartupFinishedEvent())
        self.os_interaction.is_internet_available.assert_called()
        self.assertEqual(len(self.bus.emitted_of(WifiStatusChangedEvent)), 1)

    def test_pre_alarm_restarts_networking_when_offline(self):
        self.bus.emit(PreAlarmTriggeredEvent(make_alarm()))
        self.os_interaction.restart_networking_service.assert_called_once_with()

    def test_pre_alarm_leaves_networking_alone_when_online(self):
        self.context.environment.is_online = True
        self.bus.emit(PreAlarmTriggeredEvent(make_alarm()))
        self.os_interaction.restart_networking_service.assert_not_called()


class WeatherTests(SystemServiceTestCase):
    def test_unchanged_weather_is_not_republished(self):
        self.context.environment.is_online = True
        self.context.environment.current_weather = self.weather
        self.service._update_weather_status()
        self.assertEqual(self.bus.emitted_of(WeatherUpdatedEvent), [])

    def test_weather_lookup_errors_are_swallowed(self):
        self.context.environment.is_online = True
        self.get_weather.side_effect = ConnectionError("down")
        self.service._update_weather_status()
        self.assertEqual(self.bus.emitted_of(WeatherUpdatedEvent), [])
        self.assertIsNone(self.context.environment.current_weather)


class SunEventTests(SystemServiceTestCase):
    def test_sunrise_marks_daytime_and_reschedules(self):
        self.context.environment.is_daytime = False
        self.scheduler.add_cron_job.reset_mock()

        self.service._sun_event_occured(SunEvent.sunrise)

        (event,) = self.bus.emitted_of(SunEventOccurredEvent)
        self.assertEqual(event.event, SunEvent.sunrise)
        self.assertTrue(self.context.environment.is_daytime)
        self.scheduler.add_cron_job.assert_called_once()
        self.assertEqual(
            self.scheduler.add_cron_job.call_args.kwargs["job_id"],
            SunEvent.sunrise.value,
        )

    def test_sunset_marks_night(self):
        self.context.environment.is_daytime = True
        self.service._sun_event_occured(SunEvent.sunset)
        self.assertFalse(self.context.environment.is_daytime)

    def test_registered_sun_job_triggers_the_sun_event(self):
        job = next(
            c
            for c in self.scheduler.add_cron_job.call_args_list
            if c.kwargs["job_id"] == SunEvent.sunset.value
        )
        job.args[0]()
        (event,) = self.bus.emitted_of(SunEventOccurredEvent)
        self.assertEqual(event.event, SunEvent.sunset)


class SystemRequestTests(SystemServiceTestCase):
    def test_spotify_stopped_restarts_spotify_daemon(self):
        self.bus.emit(SpotifyStoppedEvent())
        self.os_interaction.restart_spotify_daemon.assert_called_once_with()

    def test_volume_change_schedules_hiding_of_volume_meter(self):
        self.bus.emit(VolumeChangedEvent(new_volume=0.3))
        self.scheduler.start_generic_trigger.assert_called_once_with(
            SchedulerJobIds.hide_volume_meter.value,
            datetime.timedelta(seconds=5),
            func=self.display_content.hide_volume_meter,
        )

    def test_reboot_request_reboots_system(self):
        self.bus.emit(ShutdownSystemRequest(reboot=True))
        self.os_interaction.reboot_system.assert_called_once_with()
        self.os_interaction.shutdown_system.assert_not_called()

    def test_shutdown_request_shuts_system_down(self):
        self.bus.emit(ShutdownSystemRequest())
        self.os_interaction.shutdown_system.assert_called_once_with()
        self.os_interaction.reboot_system.assert_not_called()

    def test_shutdown_failures_are_swallowed(self):
        self.os_interaction.shutdown_system.side_effect = OSError("denied")
        self.service.handle_shutdown_system_request(ShutdownSystemRequest())

    def test_terminate_request_stops_playback_and_clears_event_handlers(self):
        self.bus.emit(TerminateAppRequest())
        (event,) = self.bus.emitted_of(PlaybackChangedEvent)
        self.assertEqual(event.playback_mode, Mode.Idle)
        self.assertEqual(self.bus._handlers, {})

    def test_alarm_events_are_accepted_without_side_effects(self):
        self.bus.emit(AlarmTriggeredEvent(make_alarm()))
        self.bus.emit(AlarmStoppedEvent())
        self.assertEqual(
            [type(e) for e in self.bus.emitted],
            [AlarmTriggeredEvent, AlarmStoppedEvent],
        )

    def test_room_brightness_is_read_from_sensor(self):
        self.assertEqual(self.service.get_room_brightness(), 0.5)


class RegularDisplayUpdateTests(SystemServiceTestCase):
    NOW = local_datetime(2030, 1, 7, 7, 30, 10)

    def update(self, previous_second: int, changed: bool = True):
        self.service._previous_tac_time = self.NOW.replace(second=previous_second)
        self.display_content.update_presentation_state.return_value = changed
        with frozen_now(self.NOW):
            self.service._emit_regular_display_update()

    def blink_argument(self) -> bool:
        return self.display_content.update_presentation_state.call_args.kwargs[
            "show_blink_segment"
        ]

    def test_blink_state_toggles_when_second_changes(self):
        self.display_content.show_blink_segment = False
        self.update(previous_second=9)
        self.assertTrue(self.blink_argument())
        self.assertEqual(self.service._previous_tac_time, self.NOW)

    def test_blink_state_is_kept_within_the_same_second(self):
        self.display_content.show_blink_segment = True
        self.update(previous_second=10)
        self.assertTrue(self.blink_argument())

    def test_room_brightness_is_passed_to_display_content(self):
        self.update(previous_second=9)
        brightness = self.display_content.update_presentation_state.call_args.kwargs[
            "room_brightness"
        ]
        self.assertEqual(brightness, RoomBrightness(0.5))

    def test_forced_update_is_emitted_when_presentation_changed(self):
        self.update(previous_second=9, changed=True)
        (event,) = self.bus.emitted_of(ForcedDisplayUpdateEvent)
        self.assertTrue(event.suppress_logging)
        self.assertEqual(self.display_content.refresh_duration_in_ms, 0)

    def test_no_forced_update_when_presentation_is_unchanged(self):
        self.update(previous_second=9, changed=False)
        self.assertEqual(self.bus.emitted_of(ForcedDisplayUpdateEvent), [])

    def test_sensor_errors_are_swallowed(self):
        self.brightness_sensor.get_room_brightness.side_effect = OSError("i2c")
        self.update(previous_second=9)
        self.assertEqual(self.bus.emitted_of(ForcedDisplayUpdateEvent), [])

    def test_forced_display_update_resets_previous_time(self):
        self.service._previous_tac_time = self.NOW - datetime.timedelta(hours=1)
        with frozen_now(self.NOW):
            self.bus.emit(ForcedDisplayUpdateEvent())
        self.assertEqual(self.service._previous_tac_time, self.NOW)


if __name__ == "__main__":
    unittest.main()
