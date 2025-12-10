from datetime import datetime
import logging
from timeit import timeit
from typing import Callable, Dict, List, Type
from dataclasses import dataclass
import uuid


logger = logging.getLogger("tac.core.infrastructure.event_bus")


@dataclass(frozen=True, kw_only=True)
class BaseEvent:
    suppress_logging: bool = False
    id: uuid.UUID = uuid.uuid4()


class EventBus:

    def __init__(self):
        self._handlers: Dict[Type[BaseEvent], List[Callable[[BaseEvent], None]]] = {}

    def on(self, event_type: Type[BaseEvent]) -> Callable:

        def decorator(func: Callable[[BaseEvent], None]) -> Callable:
            self.register(event_type, func)
            return func

        return decorator

    def register(
        self, event_type: Type[BaseEvent], handler: Callable[[BaseEvent], None]
    ):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(f"Registered handler {handler.__name__} for {event_type.__name__}")

    def emit(self, event: BaseEvent):
        event_type = type(event)
        suppress_logging = getattr(event, "suppress_logging", False)
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            logger.warning(f"No handlers registered for {event_type.__name__}")
            return

        if not suppress_logging:
            logger.info(
                f"Emitting {event_type.__name__}({event.id}) to {len(handlers)} handler(s)"
            )
        handler_times = {}
        for handler in handlers:
            try:
                handler_name = (
                    f"{handler.__func__.__qualname__}"
                    if hasattr(handler, "__func__")
                    else handler.__name__
                )
                handler_times[handler_name] = (
                    timeit(lambda: handler(event), number=1) * 1000
                )
            except Exception as e:
                logger.error(
                    f"Error in handler {handler_name} for {event_type.__name__}: {e}",
                    exc_info=True,
                )
        if not suppress_logging:
            msg = f"Emitted {event_type.__name__}({event.id}) to {len(handlers)} handler(s) with execution times:"
            for handler, exec_time in handler_times.items():
                msg += f"\n - {f"{handler}: {exec_time:.2f} ms"}"
            logger.debug(msg)

    def emit_all(self, events: List[BaseEvent]):
        for event in events:
            self.emit(event)

    def unregister(
        self, event_type: Type[BaseEvent], handler: Callable[[BaseEvent], None]
    ):
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                logger.debug(
                    f"Unregistered handler {handler.__name__} for {event_type.__name__}"
                )
            except ValueError:
                logger.warning(
                    f"Handler {handler.__name__} not found for {event_type.__name__}"
                )

    def clear(self):
        self._handlers.clear()
        logger.debug("Cleared all event handlers")


# Example domain events (can be moved to appropriate domain modules later)
if __name__ == "__main__":
    from dataclasses import dataclass

    @dataclass
    class AlarmTriggered(BaseEvent):
        """Domain event: An alarm has been triggered."""

        alarm_id: str = None
        scheduled_time: datetime = None

    @dataclass
    class AlarmSnoozed(BaseEvent):
        """Domain event: An alarm has been snoozed."""

        alarm_id: str = None
        snooze_duration_minutes: int = None

    # Test the event bus
    logging.basicConfig(level=logging.DEBUG)

    bus = EventBus()

    # Register handlers using decorator
    @bus.on(AlarmTriggered)
    def handle_alarm_triggered(event: AlarmTriggered):
        print(f"🔔 Alarm {event.alarm_id} triggered at {event.scheduled_time}")

    @bus.on(AlarmTriggered)
    def another_handler(event: AlarmTriggered):
        print(f"📢 Another handler got: {event.alarm_id}")

    # Register handler directly
    def handle_alarm_snoozed(event: AlarmSnoozed):
        print(
            f"😴 Alarm {event.alarm_id} snoozed for {event.snooze_duration_minutes} minutes"
        )

    bus.register(AlarmSnoozed, handle_alarm_snoozed)

    # Emit events
    print("\n=== Emitting AlarmTriggered ===")
    bus.emit(AlarmTriggered(alarm_id="alarm-123", scheduled_time=datetime.now()))

    print("\n=== Emitting AlarmSnoozed ===")
    bus.emit(AlarmSnoozed(alarm_id="alarm-123", snooze_duration_minutes=10))

    print("\n=== Emitting multiple events ===")
    bus.emit_all(
        [
            AlarmTriggered(alarm_id="alarm-456", scheduled_time=datetime.now()),
            AlarmSnoozed(alarm_id="alarm-456", snooze_duration_minutes=5),
        ]
    )
