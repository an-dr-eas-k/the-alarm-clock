import json
import os
import tempfile
import logging
import unittest
from concurrent.futures import Executor, Future
from unittest import mock

from core.domain.events import (
    AlarmStoppedEvent,
    AlarmTriggeredEvent,
    ConfigChangedEvent,
)
from core.domain.model import AlarmDefinition, Config
from core.infrastructure.persistence import Persistence
from tests.support import RecordingEventBus, make_alarm, make_config


def quiet_event_bus_logger(test_case):
    bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
    previous = bus_logger.level
    bus_logger.setLevel(logging.ERROR)
    test_case.addCleanup(bus_logger.setLevel, previous)


class InlineExecutor(Executor):
    """Runs submitted callables immediately in the calling thread."""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, /, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:
            future.set_exception(e)
        return future


class PersistenceTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = tmp.name
        self.config_file = os.path.join(self.tmp_dir, "config.json")
        self.active_alarm_file = os.path.join(self.tmp_dir, "active_alarm.json")
        patcher = mock.patch(
            "core.infrastructure.persistence.active_alarm_definition_file",
            self.active_alarm_file,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        quiet_event_bus_logger(self)
        self.bus = RecordingEventBus()
        self.executor = InlineExecutor()
        self.persistence = Persistence(self.config_file, self.bus, self.executor)


class TestStoreConfig(PersistenceTestCase):
    def test_store_config_writes_serialized_config(self):
        config = make_config()

        self.persistence.store_config(config)

        with open(self.config_file) as f:
            self.assertEqual(config.serialize(), f.read())

    def test_stored_config_round_trips_through_deserialize(self):
        config = make_config()
        config.add_alarm_definition(make_alarm(id=None, hour=6, minute=15))

        self.persistence.store_config(config)
        loaded = Config.deserialize(self.config_file)

        self.assertEqual(1, len(loaded.alarm_definitions))
        self.assertEqual(6, loaded.alarm_definitions[0].hour)
        self.assertEqual(15, loaded.alarm_definitions[0].min)

    def test_store_config_overwrites_existing_file(self):
        with open(self.config_file, "w") as f:
            f.write("old content that is much longer than the new content" * 100)

        self.persistence.store_config(make_config())

        with open(self.config_file) as f:
            content = f.read()
        self.assertNotIn("old content", content)
        json.loads(content)

    def test_store_config_releases_lock_after_success(self):
        self.persistence.store_config(make_config())

        self.assertFalse(self.persistence.threadLock.locked())

    def test_store_config_to_unwritable_path_raises(self):
        self.persistence.config_file = os.path.join(self.tmp_dir, "missing", "c.json")

        with self.assertRaises(FileNotFoundError):
            self.persistence.store_config(make_config())

    @unittest.expectedFailure  # lock is acquired/released without try/finally
    def test_store_config_releases_lock_after_failure(self):
        self.persistence.config_file = os.path.join(self.tmp_dir, "missing", "c.json")

        with self.assertRaises(FileNotFoundError):
            self.persistence.store_config(make_config())

        self.assertFalse(self.persistence.threadLock.locked())


class TestStoreAlarm(PersistenceTestCase):
    def test_store_alarm_writes_file_that_deserializes(self):
        self.persistence.store_alarm(make_alarm(id="x", hour=5, minute=45))

        loaded = AlarmDefinition.deserialize(self.active_alarm_file)

        self.assertEqual("x", loaded.id)
        self.assertEqual(5, loaded.hour)
        self.assertEqual(45, loaded.min)

    def test_store_none_removes_existing_file(self):
        self.persistence.store_alarm(make_alarm())
        self.assertTrue(os.path.exists(self.active_alarm_file))

        self.persistence.store_alarm(None)

        self.assertFalse(os.path.exists(self.active_alarm_file))

    def test_store_none_without_existing_file_is_a_noop(self):
        self.persistence.store_alarm(None)

        self.assertFalse(os.path.exists(self.active_alarm_file))


class TestEventSubscriptions(PersistenceTestCase):
    def test_config_changed_event_stores_config_via_executor(self):
        config = make_config()

        self.bus.emit(ConfigChangedEvent(config))

        self.assertEqual(1, len(self.executor.submitted))
        fn, args, _ = self.executor.submitted[0]
        self.assertEqual(self.persistence.store_config, fn)
        self.assertEqual((config,), args)
        with open(self.config_file) as f:
            self.assertEqual(config.serialize(), f.read())

    def test_alarm_triggered_event_persists_active_alarm(self):
        alarm = make_alarm(id="ringing")

        self.bus.emit(AlarmTriggeredEvent(alarm_definition=alarm))

        self.assertEqual(
            "ringing", AlarmDefinition.deserialize(self.active_alarm_file).id
        )

    def test_alarm_stopped_event_removes_active_alarm(self):
        self.bus.emit(AlarmTriggeredEvent(alarm_definition=make_alarm()))

        self.bus.emit(AlarmStoppedEvent())

        self.assertFalse(os.path.exists(self.active_alarm_file))

    def test_alarm_stopped_event_with_definition_also_removes_file(self):
        self.bus.emit(AlarmTriggeredEvent(alarm_definition=make_alarm()))

        self.bus.emit(AlarmStoppedEvent(alarm_definition=make_alarm()))

        self.assertFalse(os.path.exists(self.active_alarm_file))

    def test_failing_alarm_store_is_isolated_by_event_bus(self):
        missing = os.path.join(self.tmp_dir, "missing", "alarm.json")
        with mock.patch(
            "core.infrastructure.persistence.active_alarm_definition_file", missing
        ):
            with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR"):
                self.bus.emit(AlarmTriggeredEvent(alarm_definition=make_alarm()))


if __name__ == "__main__":
    unittest.main()
