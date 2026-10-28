import datetime
import logging
import unittest
from unittest import mock

from apscheduler.schedulers.base import STATE_STOPPED

from core.domain.events import ConfigChangedEvent
from core.domain.model import NextAlarmInfo
from core.infrastructure.scheduler import SchedulerService, SchedulerStores
from tests.support import RecordingEventBus, frozen_now, local_datetime, make_alarm, make_config


def noop(*args, **kwargs):
    pass


FUTURE = local_datetime(2099, 1, 1, 12, 0)


def quiet_event_bus_logger(test_case):
    bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
    previous = bus_logger.level
    bus_logger.setLevel(logging.ERROR)
    test_case.addCleanup(bus_logger.setLevel, previous)


class SchedulerTestCase(unittest.TestCase):
    def setUp(self):
        quiet_event_bus_logger(self)
        self.bus = RecordingEventBus()
        self.service = SchedulerService(self.bus)
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        if self.service.scheduler.running:
            self.service.shutdown()


class TestLifecycle(SchedulerTestCase):
    def test_scheduler_is_started_with_memory_stores(self):
        self.assertTrue(self.service.scheduler.running)
        self.assertEqual([], self.service.get_jobs(SchedulerStores.alarm.value))
        self.assertEqual([], self.service.get_jobs(SchedulerStores.default.value))

    def test_shutdown_stops_scheduler(self):
        self.service.shutdown()

        self.assertEqual(STATE_STOPPED, self.service.scheduler.state)

    def test_shutdown_twice_is_safe(self):
        self.service.shutdown()

        self.service.shutdown()

        self.assertEqual(STATE_STOPPED, self.service.scheduler.state)

    def test_scheduler_stores_are_enum_backed(self):
        self.assertEqual("alarm", SchedulerStores.alarm.value)
        self.assertEqual("default", SchedulerStores.default.value)


class TestAddingJobs(SchedulerTestCase):
    def test_add_date_job_registers_job_with_run_date(self):
        job = self.service.add_date_job(noop, "j1", FUTURE)

        self.assertEqual("j1", job.id)
        self.assertEqual(FUTURE, self.service.get_job("j1").next_run_time)

    def test_add_date_job_passes_args_and_kwargs(self):
        self.service.add_date_job(noop, "j1", FUTURE, args=[1, 2], kwargs={"k": 3})

        job = self.service.get_job("j1")

        self.assertEqual((1, 2), job.args)
        self.assertEqual({"k": 3}, job.kwargs)

    def test_add_date_job_uses_given_jobstore(self):
        self.service.add_date_job(noop, "j1", FUTURE, jobstore="alarm")

        self.assertIsNotNone(self.service.get_job("j1", "alarm"))
        self.assertIsNone(self.service.get_job("j1", "default"))

    def test_add_date_job_with_duplicate_id_raises(self):
        from apscheduler.jobstores.base import ConflictingIdError

        self.service.add_date_job(noop, "j1", FUTURE)

        with self.assertRaises(ConflictingIdError):
            self.service.add_date_job(noop, "j1", FUTURE)

    def test_add_cron_job_computes_next_run_from_cron_fields(self):
        job = self.service.add_cron_job(noop, "cron", hour=7, minute=30)

        next_run = job.next_run_time
        self.assertEqual((7, 30), (next_run.hour, next_run.minute))
        self.assertGreater(next_run, datetime.datetime.now(next_run.tzinfo))

    def test_add_job_with_date_trigger_arguments(self):
        job = self.service.add_job(
            noop, "gen", trigger="date", run_date=FUTURE, args=["x"]
        )

        self.assertEqual(FUTURE, job.next_run_time)
        self.assertEqual(("x",), job.args)

    def test_add_job_with_interval_trigger(self):
        job = self.service.add_job(noop, "interval", trigger="interval", hours=1)

        self.assertIsNotNone(job.next_run_time)

    def test_add_or_replace_date_job_creates_job_when_missing(self):
        self.service.add_or_replace_date_job(noop, "j1", FUTURE)

        self.assertEqual(FUTURE, self.service.get_job("j1").next_run_time)

    def test_add_or_replace_date_job_replaces_existing_job(self):
        later = FUTURE + datetime.timedelta(days=1)
        self.service.add_or_replace_date_job(noop, "j1", FUTURE, args=["old"])

        self.service.add_or_replace_date_job(noop, "j1", later, args=["new"])

        jobs = self.service.get_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual(later, jobs[0].next_run_time)
        self.assertEqual(("new",), jobs[0].args)


class TestReschedulingAndRemoving(SchedulerTestCase):
    def test_reschedule_date_job_changes_run_time(self):
        self.service.add_date_job(noop, "j1", FUTURE)
        later = FUTURE + datetime.timedelta(hours=5)

        self.service.reschedule_date_job("j1", later)

        self.assertEqual(later, self.service.get_job("j1").next_run_time)

    def test_reschedule_job_with_trigger_arguments(self):
        self.service.add_date_job(noop, "j1", FUTURE)
        later = FUTURE + datetime.timedelta(hours=2)

        self.service.reschedule_job("j1", trigger="date", run_date=later)

        self.assertEqual(later, self.service.get_job("j1").next_run_time)

    def test_reschedule_unknown_job_raises(self):
        from apscheduler.jobstores.base import JobLookupError

        with self.assertRaises(JobLookupError):
            self.service.reschedule_date_job("missing", FUTURE)

    def test_remove_job_removes_existing_job(self):
        self.service.add_date_job(noop, "j1", FUTURE)

        self.service.remove_job("j1")

        self.assertIsNone(self.service.get_job("j1"))

    def test_remove_unknown_job_is_a_noop(self):
        self.service.remove_job("missing")

    def test_remove_job_respects_jobstore(self):
        self.service.add_date_job(noop, "j1", FUTURE, jobstore="alarm")

        self.service.remove_job("j1", jobstore="default")

        self.assertIsNotNone(self.service.get_job("j1", "alarm"))

    def test_remove_all_jobs_only_clears_given_jobstore(self):
        self.service.add_date_job(noop, "a", FUTURE, jobstore="alarm")
        self.service.add_date_job(noop, "d", FUTURE, jobstore="default")

        self.service.remove_all_jobs("alarm")

        self.assertEqual([], self.service.get_jobs("alarm"))
        self.assertEqual(1, len(self.service.get_jobs("default")))

    def test_get_job_returns_none_for_unknown_id(self):
        self.assertIsNone(self.service.get_job("missing"))


class TestGenericTrigger(SchedulerTestCase):
    def test_start_generic_trigger_schedules_job_after_duration(self):
        now = local_datetime(2030, 5, 1, 8, 0)

        with frozen_now(now):
            self.service.start_generic_trigger(
                "timer", datetime.timedelta(minutes=10), noop
            )

        self.assertEqual(
            now + datetime.timedelta(minutes=10),
            self.service.get_job("timer").next_run_time,
        )

    def test_start_generic_trigger_reschedules_existing_job(self):
        now = local_datetime(2030, 5, 1, 8, 0)
        with frozen_now(now):
            self.service.start_generic_trigger("timer", datetime.timedelta(minutes=10), noop)
            self.service.start_generic_trigger("timer", datetime.timedelta(minutes=30), noop)

        self.assertEqual(1, len(self.service.get_jobs()))
        self.assertEqual(
            now + datetime.timedelta(minutes=30),
            self.service.get_job("timer").next_run_time,
        )

    def test_start_generic_trigger_uses_given_jobstore(self):
        with frozen_now(local_datetime(2030, 5, 1, 8, 0)):
            self.service.start_generic_trigger(
                "timer", datetime.timedelta(hours=1), noop, jobstore="alarm"
            )

        self.assertIsNotNone(self.service.get_job("timer", "alarm"))
        self.assertIsNone(self.service.get_job("timer", "default"))

    def test_stop_generic_trigger_removes_job(self):
        self.service.add_date_job(noop, "timer", FUTURE)

        self.service.stop_generic_trigger("timer")

        self.assertIsNone(self.service.get_job("timer"))

    def test_stop_generic_trigger_without_job_is_a_noop(self):
        self.service.stop_generic_trigger("timer")


class TestNextAlarmInfo(SchedulerTestCase):
    def _add_alarm_job(self, job_id, run_date, alarm=None):
        alarm = alarm or make_alarm(id=job_id)
        self.service.add_date_job(
            noop, job_id, run_date, jobstore="alarm", args=[alarm]
        )
        return alarm

    def test_no_alarm_jobs_returns_empty_info(self):
        info = self.service.get_next_alarm_info()

        self.assertIsInstance(info, NextAlarmInfo)
        self.assertIsNone(info.next_run_time)
        self.assertIsNone(info.alarm_definition)

    def test_returns_earliest_alarm(self):
        self._add_alarm_job("late", FUTURE + datetime.timedelta(days=2))
        early = self._add_alarm_job("early", FUTURE)
        self._add_alarm_job("mid", FUTURE + datetime.timedelta(days=1))

        info = self.service.get_next_alarm_info()

        self.assertIs(early, info.alarm_definition)
        self.assertEqual(FUTURE, info.next_run_time)

    def test_ignores_jobs_in_default_store(self):
        self.service.add_date_job(noop, "other", FUTURE, args=[make_alarm()])

        info = self.service.get_next_alarm_info()

        self.assertIsNone(info.alarm_definition)

    def test_paused_alarm_job_does_not_break_next_alarm_lookup(self):
        paused = self._add_alarm_job("paused", FUTURE)
        self.service.scheduler.pause_job("paused", jobstore="alarm")
        active = self._add_alarm_job("active", FUTURE + datetime.timedelta(days=1))

        info = self.service.get_next_alarm_info()

        self.assertIs(active, info.alarm_definition)
        self.assertIsNot(paused, info.alarm_definition)


class TestCleanupAlarms(SchedulerTestCase):
    def test_active_jobs_keep_their_alarms_and_emit_nothing(self):
        config = make_config()
        alarm = make_alarm(id="1")
        config.add_alarm_definition(alarm)
        self.service.add_date_job(noop, "1", FUTURE, jobstore="alarm", args=[alarm])

        self.service.cleanup_alarms(config)

        self.assertEqual([alarm], config.alarm_definitions)
        self.assertEqual([], self.bus.emitted_of(ConfigChangedEvent))

    def test_no_jobs_emits_nothing(self):
        self.service.cleanup_alarms(make_config())

        self.assertEqual([], self.bus.emitted)

    def test_finished_job_removes_alarm_and_emits_config_changed(self):
        config = make_config()
        alarm = make_alarm(id="abc123")
        config.add_alarm_definition(alarm)
        self.service.add_date_job(noop, "abc123", FUTURE, jobstore="alarm", args=[alarm])
        self.service.scheduler.pause_job("abc123", jobstore="alarm")

        self.service.cleanup_alarms(config)

        self.assertEqual([], config.alarm_definitions)
        self.assertEqual(1, len(self.bus.emitted_of(ConfigChangedEvent)))

    def test_numeric_looking_job_id_still_matches_string_alarm_id(self):
        config = make_config()
        alarm = make_alarm(id="7")
        config.add_alarm_definition(alarm)
        self.service.add_date_job(noop, "7", FUTURE, jobstore="alarm", args=[alarm])
        self.service.scheduler.pause_job("7", jobstore="alarm")

        self.service.cleanup_alarms(config)

        self.assertEqual([], config.alarm_definitions)
        self.assertEqual(1, len(self.bus.emitted_of(ConfigChangedEvent)))


class TestLogActiveJobs(SchedulerTestCase):
    def test_logs_next_runtime_of_scheduled_jobs(self):
        self.service.add_date_job(noop, "j1", FUTURE)

        with self.assertLogs("tac.core.infrastructure.scheduler", "INFO") as logs:
            self.service.log_active_jobs("default")

        self.assertIn("j1", logs.output[0])
        self.assertIn("2099-01-01 12:00:00", logs.output[0])

    def test_skips_paused_jobs(self):
        self.service.add_date_job(noop, "j1", FUTURE)
        self.service.scheduler.pause_job("j1")

        with self.assertNoLogs("tac.core.infrastructure.scheduler", "INFO"):
            self.service.log_active_jobs("default")


if __name__ == "__main__":
    unittest.main()
