import datetime
import logging
import os
import tempfile
import unittest
from unittest import mock

from core.application.alarm_audio_service import AlarmAudioService
from core.domain.events import (
    AlarmStoppedEvent,
    AlarmTriggeredEvent,
    ConfigChangedEvent,
    PlaybackChangedEvent,
    PreAlarmTriggeredEvent,
    SpeakerErrorEvent,
    StartupFinishedEvent,
    VolumeChangeRequest,
)
from core.domain.model import (
    FAILED_ALARM_ID,
    AlarmClockContext,
    Mode,
    NextAlarmInfo,
    OfflineStream,
    SchedulerJobIds,
)
from core.infrastructure.scheduler import SchedulerStores
from tests.support import (
    RecordingEventBus,
    frozen_now,
    local_datetime,
    make_alarm,
    make_config,
    make_stream,
)

logging.getLogger("tac").addHandler(logging.NullHandler())

SERVICE_MODULE = "core.application.alarm_audio_service"


class AlarmAudioServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.bus = RecordingEventBus()
        self.stream = make_stream("Radio", "http://radio", id="s1")
        self.config = make_config(self.bus, streams=[self.stream])
        self.context = AlarmClockContext(self.config, is_online=True)
        self.playback = mock.MagicMock()
        self.playback.playback_mode = Mode.Idle
        self.display_content = mock.MagicMock()
        self.scheduler = mock.MagicMock()
        self.scheduler.get_next_alarm_info.return_value = NextAlarmInfo()
        self.scheduler.get_jobs.return_value = []
        self.os_interaction = mock.MagicMock()
        self.os_interaction.is_internet_available.return_value = True
        self.service = AlarmAudioService(
            self.context,
            self.display_content,
            self.playback,
            self.bus,
            self.scheduler,
            self.os_interaction,
        )

    def playback_events(self) -> list[PlaybackChangedEvent]:
        return self.bus.emitted_of(PlaybackChangedEvent)

    def add_recurring_alarm(self, id="a1", **kwargs):
        kwargs.setdefault("recurring", ["MONDAY", "FRIDAY"])
        alarm = make_alarm(id=id, **kwargs)
        self.config.add_alarm_definition(alarm)
        return alarm

    def make_job(self, alarm, next_run_time):
        job = mock.MagicMock()
        job.args = (alarm,)
        job.next_run_time = next_run_time
        return job


class ConfigChangedTests(AlarmAudioServiceTestCase):
    def test_all_alarm_jobs_are_replaced_by_active_alarms(self):
        active = self.add_recurring_alarm("a1", hour=6, minute=15)
        self.add_recurring_alarm("a2", is_active=False)

        self.bus.emit(ConfigChangedEvent(self.config))

        self.scheduler.remove_all_jobs.assert_called_once_with(
            jobstore=SchedulerStores.alarm.value
        )
        self.scheduler.add_cron_job.assert_called_once()
        kwargs = self.scheduler.add_cron_job.call_args.kwargs
        self.assertEqual(kwargs["job_id"], "a1")
        self.assertEqual(kwargs["args"], (active,))
        self.assertEqual(kwargs["jobstore"], SchedulerStores.alarm.value)
        self.assertEqual(kwargs["func"], self.service._ring_alarm)
        self.assertEqual(kwargs["hour"], 6)
        self.assertEqual(kwargs["minute"], 15)
        self.assertEqual(kwargs["day_of_week"], "0,4")

    def test_onetime_alarm_job_is_limited_to_its_date(self):
        day = datetime.date(2030, 1, 2)
        self.config.add_alarm_definition(make_alarm("once", onetime=day))

        self.bus.emit(ConfigChangedEvent(self.config))

        kwargs = self.scheduler.add_cron_job.call_args.kwargs
        self.assertEqual(kwargs["start_date"], day)
        self.assertEqual(kwargs["end_date"], day + datetime.timedelta(days=1))

    def test_inactive_alarms_are_not_scheduled(self):
        self.add_recurring_alarm(is_active=False)
        self.bus.emit(ConfigChangedEvent(self.config))
        self.scheduler.add_cron_job.assert_not_called()

    def test_cleanup_and_next_alarm_refresh_follow_rescheduling(self):
        self.bus.emit(ConfigChangedEvent(self.config))
        self.scheduler.cleanup_alarms.assert_called_once_with(self.config)
        self.scheduler.get_next_alarm_info.assert_called_once()
        self.display_content.update_next_alarm.assert_called_once()


class UpdateNextAlarmTests(AlarmAudioServiceTestCase):
    def test_pre_alarm_is_scheduled_before_next_alarm(self):
        alarm = self.add_recurring_alarm()
        run_time = local_datetime(2030, 1, 7, 7, 30)
        info = NextAlarmInfo(run_time, alarm)
        self.scheduler.get_next_alarm_info.return_value = info
        self.config.pre_alarm_trigger_in_mins = 15

        self.service.update_next_alarm()

        self.scheduler.add_or_replace_date_job.assert_called_once()
        kwargs = self.scheduler.add_or_replace_date_job.call_args.kwargs
        self.assertEqual(kwargs["run_date"], local_datetime(2030, 1, 7, 7, 15))
        self.assertEqual(kwargs["job_id"], SchedulerJobIds.pre_alarm.value)
        self.assertEqual(kwargs["jobstore"], SchedulerStores.default.value)
        self.assertEqual(kwargs["args"], [alarm])
        self.assertEqual(kwargs["func"], self.service._trigger_pre_alarm)
        self.display_content.update_next_alarm.assert_called_once_with(info)

    def test_no_pre_alarm_without_upcoming_alarm(self):
        self.service.update_next_alarm()
        self.scheduler.add_or_replace_date_job.assert_not_called()
        self.display_content.update_next_alarm.assert_called_once()

    def test_alarms_are_sorted_by_activity_then_next_run_time(self):
        late = self.add_recurring_alarm("late")
        inactive = self.add_recurring_alarm("off", is_active=False)
        early = self.add_recurring_alarm("early")
        unscheduled = self.add_recurring_alarm("unscheduled")
        self.scheduler.get_jobs.return_value = [
            self.make_job(late, local_datetime(2030, 1, 8, 7)),
            self.make_job(early, local_datetime(2030, 1, 7, 7)),
            self.make_job(inactive, None),
        ]

        self.service.update_next_alarm()

        self.assertEqual(
            [a.id for a in self.config.alarm_definitions],
            ["early", "late", "unscheduled", "off"],
        )
        self.assertIs(self.config.alarm_definitions[2], unscheduled)

    def test_pre_alarm_trigger_emits_event(self):
        alarm = self.add_recurring_alarm()
        self.service._trigger_pre_alarm(alarm)
        events = self.bus.emitted_of(PreAlarmTriggeredEvent)
        self.assertEqual([e.alarm_definition for e in events], [alarm])

    def test_pre_alarm_trigger_swallows_errors(self):
        alarm = self.add_recurring_alarm()
        with mock.patch.object(self.bus, "emit", side_effect=RuntimeError("boom")):
            self.service._trigger_pre_alarm(alarm)


class RingAlarmTests(AlarmAudioServiceTestCase):
    def test_ring_alarm_emits_alarm_triggered(self):
        alarm = self.add_recurring_alarm()
        self.service._ring_alarm(alarm)
        events = self.bus.emitted_of(AlarmTriggeredEvent)
        self.assertEqual([e.alarm_definition for e in events], [alarm])

    def test_ring_alarm_swallows_errors_from_handlers_and_bus(self):
        alarm = self.add_recurring_alarm()
        with mock.patch.object(self.bus, "emit", side_effect=RuntimeError("boom")):
            self.service._ring_alarm(alarm)


class AlarmTriggeredTests(AlarmAudioServiceTestCase):
    def trigger(self, alarm):
        self.bus.emit(AlarmTriggeredEvent(alarm))

    def test_alarm_plays_configured_stream_at_alarm_volume(self):
        alarm = self.add_recurring_alarm(volume=0.4)
        self.context.active_alarm_definition = None

        self.trigger(alarm)

        self.assertIs(self.context.active_alarm_definition, alarm)
        (event,) = self.playback_events()
        self.assertEqual(event.playback_mode, Mode.Alarm)
        self.assertIs(event.audio_stream, alarm.audio_effect.audio_stream)
        self.assertEqual(event.absolute, 0.4)

    def test_alarm_auto_stop_is_scheduled_after_alarm_duration(self):
        alarm = self.add_recurring_alarm()
        self.config.alarm_duration_in_mins = 25

        self.trigger(alarm)

        self.scheduler.start_generic_trigger.assert_called_once_with(
            SchedulerJobIds.stop_alarm.value,
            datetime.timedelta(minutes=25),
            func=self.service._set_to_idle_mode,
        )

    def test_alarm_without_internet_uses_offline_stream(self):
        alarm = self.add_recurring_alarm(volume=0.5)
        self.os_interaction.is_internet_available.return_value = False

        self.trigger(alarm)

        (event,) = self.playback_events()
        self.assertIsInstance(event.audio_stream, OfflineStream)
        self.assertEqual(event.absolute, 0.5)

    def test_alarm_while_music_or_spotify_is_playing_uses_offline_stream(self):
        alarm = self.add_recurring_alarm()
        for mode in (Mode.Music, Mode.Spotify):
            self.bus.emitted.clear()
            self.playback.playback_mode = mode
            self.trigger(alarm)
            (event,) = self.playback_events()
            self.assertIsInstance(event.audio_stream, OfflineStream, mode)

    def test_recurring_alarm_stays_configured_and_refreshes_next_alarm(self):
        alarm = self.add_recurring_alarm()

        self.trigger(alarm)

        self.assertIn(alarm, self.config.alarm_definitions)
        self.assertEqual(self.bus.emitted_of(ConfigChangedEvent), [])
        self.display_content.update_next_alarm.assert_called_once()

    def test_onetime_alarm_is_removed_after_ringing(self):
        alarm = self.add_recurring_alarm(
            "once", recurring=None, onetime=datetime.date(2030, 1, 1)
        )
        keep = self.add_recurring_alarm("keep")

        self.trigger(alarm)

        self.assertEqual([a.id for a in self.config.alarm_definitions], ["keep"])
        self.assertIs(self.config.alarm_definitions[0], keep)
        (changed,) = self.bus.emitted_of(ConfigChangedEvent)
        self.assertIs(changed.config, self.config)
        self.assertIs(self.context.active_alarm_definition, alarm)

    def test_failed_alarm_recovery_is_not_removed_from_config(self):
        failed = make_alarm(FAILED_ALARM_ID, onetime=datetime.date(2030, 1, 1))
        other = self.add_recurring_alarm("other")

        self.trigger(failed)

        self.assertEqual(self.config.alarm_definitions, [other])
        self.assertEqual(self.bus.emitted_of(ConfigChangedEvent), [])
        (event,) = self.playback_events()
        self.assertEqual(event.playback_mode, Mode.Alarm)

    def test_fade_in_alarm_starts_at_start_volume_and_schedules_ticks(self):
        alarm = self.add_recurring_alarm(volume=0.6, fadein_in_secs=30)
        self.config.start_volume = 0.1
        start = local_datetime(2030, 1, 7, 7, 30)

        with frozen_now(start):
            self.trigger(alarm)

        (event,) = self.playback_events()
        self.assertEqual(event.absolute, 0.1)
        self.assertEqual(self.service._volume_increase_start_time, start)
        self.assertEqual(self.service._volume_increase_start_volume, 0.1)
        self.scheduler.add_job.assert_called_once()
        job_kwargs = self.scheduler.add_job.call_args.kwargs
        self.assertEqual(job_kwargs["job_id"], SchedulerJobIds.volume_increase.value)
        self.assertEqual(job_kwargs["trigger"], "interval")
        self.assertEqual(job_kwargs["seconds"], 2)
        self.assertEqual(
            self.scheduler.add_job.call_args.args[0], self.service._volume_increase_tick
        )

    def test_alarm_without_fade_in_does_not_schedule_volume_ticks(self):
        self.trigger(self.add_recurring_alarm(fadein_in_secs=0))
        self.scheduler.add_job.assert_not_called()
        self.assertIsNone(self.service._volume_increase_start_time)


class AlarmStoppedTests(AlarmAudioServiceTestCase):
    def test_stopping_cancels_timers_and_resets_state(self):
        alarm = self.add_recurring_alarm(fadein_in_secs=10)
        with frozen_now(local_datetime(2030, 1, 7, 7, 30)):
            self.bus.emit(AlarmTriggeredEvent(alarm))
        self.scheduler.reset_mock()

        self.bus.emit(AlarmStoppedEvent(alarm))

        self.scheduler.stop_generic_trigger.assert_any_call(
            SchedulerJobIds.stop_alarm.value
        )
        self.scheduler.stop_generic_trigger.assert_any_call(
            SchedulerJobIds.volume_increase.value
        )
        self.assertIsNone(self.service._volume_increase_start_time)
        self.assertIsNone(self.service._volume_increase_start_volume)
        self.assertIsNone(self.context.active_alarm_definition)

    def test_auto_stop_callback_switches_to_idle_when_ringing(self):
        self.playback.playback_mode = Mode.Alarm
        self.service._set_to_idle_mode()
        (event,) = self.playback_events()
        self.assertEqual(event.playback_mode, Mode.Idle)

    def test_auto_stop_callback_is_noop_when_already_idle(self):
        self.service._set_to_idle_mode()
        self.assertEqual(self.playback_events(), [])


class VolumeFadeInTickTests(AlarmAudioServiceTestCase):
    START = local_datetime(2030, 1, 7, 7, 30)

    def setUp(self):
        super().setUp()
        self.config.start_volume = 0.2
        self.alarm = self.add_recurring_alarm(volume=0.6, fadein_in_secs=20)
        with frozen_now(self.START):
            self.bus.emit(AlarmTriggeredEvent(self.alarm))
        self.bus.emitted.clear()
        self.scheduler.reset_mock()
        self.playback.playback_mode = Mode.Alarm

    def tick_at(self, seconds: float):
        with frozen_now(self.START + datetime.timedelta(seconds=seconds)):
            self.service._volume_increase_tick()

    def volume_requests(self) -> list[VolumeChangeRequest]:
        return [
            e
            for e in self.bus.emitted_of(VolumeChangeRequest)
            if not isinstance(e, PlaybackChangedEvent)
        ]

    def test_volume_ramps_linearly_between_start_and_alarm_volume(self):
        self.tick_at(10)
        (request,) = self.volume_requests()
        self.assertAlmostEqual(request.absolute, 0.4)
        self.scheduler.stop_generic_trigger.assert_not_called()

    def test_first_tick_without_elapsed_time_keeps_start_volume(self):
        self.tick_at(0)
        (request,) = self.volume_requests()
        self.assertAlmostEqual(request.absolute, 0.2)

    def test_final_tick_reaches_alarm_volume_and_stops_ticking(self):
        self.tick_at(20)
        (request,) = self.volume_requests()
        self.assertAlmostEqual(request.absolute, 0.6)
        self.scheduler.stop_generic_trigger.assert_called_once_with(
            SchedulerJobIds.volume_increase.value
        )

    def test_volume_never_exceeds_alarm_volume(self):
        self.tick_at(500)
        (request,) = self.volume_requests()
        self.assertAlmostEqual(request.absolute, 0.6)

    def test_tick_is_ignored_when_alarm_is_no_longer_playing(self):
        self.playback.playback_mode = Mode.Idle
        self.tick_at(10)
        self.assertEqual(self.volume_requests(), [])

    def test_tick_is_ignored_without_fade_in_start_time(self):
        self.service._volume_increase_start_time = None
        self.tick_at(10)
        self.assertEqual(self.volume_requests(), [])

    def test_tick_errors_are_swallowed(self):
        self.context.active_alarm_definition = None
        self.tick_at(10)
        self.assertEqual(self.volume_requests(), [])


class FailedAlarmRecoveryTests(AlarmAudioServiceTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.active_file = os.path.join(self.tmp.name, "active_alarm.json")
        patcher = mock.patch(
            f"{SERVICE_MODULE}.active_alarm_definition_file", self.active_file
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_happens_without_persisted_alarm(self):
        self.bus.emit(StartupFinishedEvent())
        self.assertEqual(self.bus.emitted_of(AlarmTriggeredEvent), [])
        self.assertEqual(self.playback_events(), [])

    def test_persisted_alarm_is_rung_again_on_startup_as_failed_alarm(self):
        persisted = make_alarm("a1", volume=0.35, recurring=["MONDAY"])
        persisted.serialize(self.active_file)

        self.bus.emit(StartupFinishedEvent())

        (triggered,) = self.bus.emitted_of(AlarmTriggeredEvent)
        self.assertEqual(triggered.alarm_definition.id, FAILED_ALARM_ID)
        self.assertEqual(triggered.alarm_definition.audio_effect.volume, 0.35)
        (event,) = self.playback_events()
        self.assertEqual(event.playback_mode, Mode.Alarm)
        self.assertEqual(event.absolute, 0.35)
        self.assertEqual(self.context.active_alarm_definition.id, FAILED_ALARM_ID)

    def test_recovered_onetime_alarm_does_not_touch_config(self):
        persisted = make_alarm("a1", onetime=datetime.date(2030, 1, 1))
        persisted.serialize(self.active_file)
        keep = self.add_recurring_alarm("keep")

        self.service.consider_failed_alarm()

        self.assertEqual(self.config.alarm_definitions, [keep])

    def test_corrupt_persisted_alarm_raises_and_rings_nothing(self):
        with open(self.active_file, "w") as f:
            f.write("not json")
        with self.assertRaises(Exception):
            self.service.consider_failed_alarm()
        self.assertEqual(self.bus.emitted_of(AlarmTriggeredEvent), [])


class InheritedBehaviourTests(AlarmAudioServiceTestCase):
    def test_speaker_error_during_alarm_falls_back_to_offline_stream(self):
        self.playback.playback_mode = Mode.Alarm
        self.bus.emit(SpeakerErrorEvent(self.stream))
        (event,) = self.playback_events()
        self.assertIsInstance(event.audio_stream, OfflineStream)


if __name__ == "__main__":
    unittest.main()
