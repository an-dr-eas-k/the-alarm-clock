import logging
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from unittest import mock

from core.infrastructure.event_bus import BaseEvent, EventBus


@dataclass(frozen=True)
class PingEvent(BaseEvent):
    value: int = 0


@dataclass(frozen=True)
class PongEvent(BaseEvent):
    pass


class EventBusTestCase(unittest.TestCase):
    def setUp(self):
        bus_logger = logging.getLogger("tac.core.infrastructure.event_bus")
        self.addCleanup(bus_logger.setLevel, bus_logger.level)
        bus_logger.setLevel(logging.ERROR)
        self.bus = EventBus()
        self.addCleanup(self.bus.shutdown)


class TestRegistrationAndEmit(EventBusTestCase):
    def test_emit_calls_registered_handler_with_event(self):
        received = []
        self.bus.register(PingEvent, received.append)
        event = PingEvent(value=3)

        self.bus.emit(event)

        self.assertEqual([event], received)

    def test_emit_calls_all_handlers_in_registration_order(self):
        calls = []

        def first(e):
            calls.append("first")

        def second(e):
            calls.append("second")

        self.bus.register(PingEvent, first)
        self.bus.register(PingEvent, second)

        self.bus.emit(PingEvent())

        self.assertEqual(["first", "second"], calls)

    def test_emit_only_calls_handlers_of_the_exact_event_type(self):
        pings, pongs = [], []
        self.bus.register(PingEvent, pings.append)
        self.bus.register(PongEvent, pongs.append)

        self.bus.emit(PongEvent())

        self.assertEqual([], pings)
        self.assertEqual(1, len(pongs))

    def test_emit_does_not_dispatch_to_base_class_handlers(self):
        received = []
        self.bus.register(BaseEvent, received.append)

        self.bus.emit(PingEvent())

        self.assertEqual([], received)

    def test_emit_without_handlers_logs_warning_and_does_not_raise(self):
        with self.assertLogs("tac.core.infrastructure.event_bus", "WARNING") as logs:
            self.bus.emit(PingEvent())

        self.assertIn("No handlers registered for PingEvent", logs.output[0])

    def test_on_decorator_registers_and_returns_original_function(self):
        received = []

        @self.bus.on(PingEvent)
        def handler(event):
            received.append(event)

        self.bus.emit(PingEvent(value=1))

        self.assertEqual(1, len(received))
        self.assertTrue(callable(handler))
        self.assertEqual("handler", handler.__name__)

    def test_same_handler_registered_twice_is_called_twice(self):
        calls = []
        handler = calls.append
        self.bus.register(PingEvent, handler)
        self.bus.register(PingEvent, handler)

        self.bus.emit(PingEvent())

        self.assertEqual(2, len(calls))

    def test_bound_method_handler_is_supported(self):
        class Listener:
            def __init__(self):
                self.events = []

            def handle(self, event):
                self.events.append(event)

        listener = Listener()
        self.bus.register(PingEvent, listener.handle)

        self.bus.emit(PingEvent())

        self.assertEqual(1, len(listener.events))

    def test_emit_all_emits_every_event_in_order(self):
        received = []
        self.bus.register(PingEvent, received.append)
        events = [PingEvent(value=i) for i in range(3)]

        self.bus.emit_all(events)

        self.assertEqual(events, received)

    def test_emit_all_with_empty_list_does_nothing(self):
        self.bus.emit_all([])

    def test_handler_can_emit_other_events_reentrantly(self):
        pongs = []
        self.bus.register(PongEvent, pongs.append)
        self.bus.register(PingEvent, lambda e: self.bus.emit(PongEvent()))

        self.bus.emit(PingEvent())

        self.assertEqual(1, len(pongs))


class TestHandlerErrors(EventBusTestCase):
    def test_failing_handler_does_not_prevent_other_handlers(self):
        received = []

        def broken(event):
            raise RuntimeError("boom")

        self.bus.register(PingEvent, broken)
        self.bus.register(PingEvent, received.append)

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR") as logs:
            self.bus.emit(PingEvent())

        self.assertEqual(1, len(received))
        self.assertIn("boom", logs.output[0])
        self.assertIn("broken", logs.output[0])

    def test_failing_handler_does_not_propagate_to_emitter(self):
        def broken(event):
            raise ValueError("bad")

        self.bus.register(PingEvent, broken)

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR"):
            self.bus.emit(PingEvent())

    def test_failing_bound_method_error_is_logged_with_qualified_name(self):
        class Listener:
            def handle(self, event):
                raise RuntimeError("bound boom")

        self.bus.register(PingEvent, Listener().handle)

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR") as logs:
            self.bus.emit(PingEvent())

        self.assertIn("Listener.handle", logs.output[0])


class TestUnregisterAndClear(EventBusTestCase):
    def test_unregister_removes_handler(self):
        received = []
        self.bus.register(PingEvent, received.append)
        handler = self.bus._handlers[PingEvent][0]

        self.bus.unregister(PingEvent, handler)
        with self.assertLogs("tac.core.infrastructure.event_bus", "WARNING"):
            self.bus.emit(PingEvent())

        self.assertEqual([], received)

    def test_unregister_only_removes_given_handler(self):
        calls = []

        def a(e):
            calls.append("a")

        def b(e):
            calls.append("b")

        self.bus.register(PingEvent, a)
        self.bus.register(PingEvent, b)

        self.bus.unregister(PingEvent, a)
        self.bus.emit(PingEvent())

        self.assertEqual(["b"], calls)

    def test_unregister_unknown_handler_logs_warning(self):
        def known(e):
            pass

        def unknown(e):
            pass

        self.bus.register(PingEvent, known)

        with self.assertLogs("tac.core.infrastructure.event_bus", "WARNING") as logs:
            self.bus.unregister(PingEvent, unknown)

        self.assertIn("not found", logs.output[0])
        self.assertEqual([known], self.bus._handlers[PingEvent])

    def test_unregister_for_unknown_event_type_is_a_noop(self):
        def handler(e):
            pass

        self.bus.unregister(PingEvent, handler)

        self.assertEqual({}, self.bus._handlers)

    def test_clear_removes_all_handlers(self):
        received = []
        self.bus.register(PingEvent, received.append)
        self.bus.register(PongEvent, received.append)

        self.bus.clear()
        with self.assertLogs("tac.core.infrastructure.event_bus", "WARNING"):
            self.bus.emit(PingEvent())
            self.bus.emit(PongEvent())

        self.assertEqual([], received)
        self.assertEqual({}, self.bus._handlers)


class TestLogging(EventBusTestCase):
    def test_emit_logs_info_by_default(self):
        self.bus.register(PingEvent, lambda e: None)

        with self.assertLogs("tac.core.infrastructure.event_bus", "INFO") as logs:
            self.bus.emit(PingEvent())

        self.assertTrue(any("Emitting PingEvent" in line for line in logs.output))

    def test_suppress_logging_silences_info_logs(self):
        self.bus.register(PingEvent, lambda e: None)

        with self.assertNoLogs("tac.core.infrastructure.event_bus", "INFO"):
            self.bus.emit(PingEvent(suppress_logging=True))

    def test_suppress_logging_still_logs_handler_errors(self):
        def broken(e):
            raise RuntimeError("still visible")

        self.bus.register(PingEvent, broken)

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR") as logs:
            self.bus.emit(PingEvent(suppress_logging=True))

        self.assertIn("still visible", logs.output[0])

    def test_base_event_suppress_logging_defaults_to_false(self):
        self.assertFalse(BaseEvent().suppress_logging)


class TestAsyncEmit(unittest.TestCase):
    def test_emit_async_runs_handler_in_worker_thread(self):
        bus = EventBus()
        done = threading.Event()
        thread_names = []

        def handler(event):
            thread_names.append(threading.current_thread().name)
            done.set()

        bus.register(PingEvent, handler)
        bus.emit_async(PingEvent())

        self.assertTrue(done.wait(2))
        bus.shutdown()
        self.assertTrue(thread_names[0].startswith("EventBus"))
        self.assertNotEqual(threading.current_thread().name, thread_names[0])

    def test_emit_all_async_delivers_all_events(self):
        bus = EventBus()
        received = []
        lock = threading.Lock()

        def handler(event):
            with lock:
                received.append(event.value)

        bus.register(PingEvent, handler)
        bus.emit_all_async([PingEvent(value=i) for i in range(5)])
        bus.shutdown(wait=True)

        self.assertEqual([0, 1, 2, 3, 4], sorted(received))

    def test_async_handler_error_is_isolated(self):
        bus = EventBus()
        received = []

        def broken(event):
            raise RuntimeError("async boom")

        bus.register(PingEvent, broken)
        bus.register(PingEvent, received.append)

        with self.assertLogs("tac.core.infrastructure.event_bus", "ERROR"):
            bus.emit_async(PingEvent())
            bus.shutdown(wait=True)

        self.assertEqual(1, len(received))

    def test_custom_executor_is_used_for_async_emit(self):
        executor = mock.Mock(spec=ThreadPoolExecutor)
        bus = EventBus(executor)
        event = PingEvent()

        bus.emit_async(event)

        executor.submit.assert_called_once_with(bus.emit, event)

    def test_shutdown_delegates_to_executor(self):
        executor = mock.Mock(spec=ThreadPoolExecutor)
        bus = EventBus(executor)

        bus.shutdown(wait=False)

        executor.shutdown.assert_called_once_with(wait=False)


if __name__ == "__main__":
    unittest.main()
