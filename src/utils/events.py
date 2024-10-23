import logging
import re
from typing import List

logger = logging.getLogger("tac.events")


class TACEvent:
    during_registration: bool
    reason: str = None
    property_name: str = None
    new_value: any = None
    subscriber: "TACEventSubscriber" = None

    def __init__(
        self,
        property_name: str = None,
        reason: str = None,
        during_registration: bool = False,
        event_publisher: "TACEventPublisher" = None,
    ) -> None:
        assert property_name or reason
        self.during_registration = during_registration
        self.reason = reason
        self.property_name = property_name
        self.subscriber = event_publisher

    def to_string(self):
        property_segment = ""
        if self.property_name:
            property_segment = f"property {self.property_name}={self.new_value}"
        reason_segment = ""
        if self.reason:
            reason_segment = f"reason {self.reason}"
        return f"event {self.subscriber.__class__.__name__}: {reason_segment}{property_segment}"


class TACEventSubscriber:

    def handle(self, event: TACEvent):
        logger.debug(f"{self.__class__.__name__} is handled: {event.to_string()}")


class TACEventPublisher:
    event_subscriber: List["TACEventSubscriber"]

    def __init__(self):
        self.event_subscriber = []

    def publish(self, property=None, reason=None, during_registration: bool = False):

        o: TACEvent
        if property:
            assert property in dir(self)
            o = TACEvent(
                property_name=property,
                during_registration=during_registration,
                event_publisher=self,
            )
            o.new_value = self.__getattribute__(o.property_name)
        else:
            o = TACEvent(
                reason=reason,
                during_registration=during_registration,
                event_publisher=self,
            )

        for subscriber in self.event_subscriber:
            assert isinstance(subscriber, TACEventSubscriber)
            subscriber.handle(o)

    def subscribe(self, subscriber: TACEventSubscriber):
        assert isinstance(subscriber, TACEventSubscriber)
        if subscriber in self.event_subscriber:
            return

        self.event_subscriber.append(subscriber)
        properties = [
            attr
            for attr in dir(self)
            if True
            and attr != "event_subscriber"
            and not re.match(r"^__.*__$", attr)
            and hasattr(self, attr)
            and not callable(getattr(self, attr))
        ]
        for property_name in properties:
            try:
                self.publish(property=property_name, during_registration=True)
            except:
                pass

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["event_subscriber"]
        return state

    def __setstate__(self, state):
        state["event_subscriber"] = []
        self.__dict__.update(state)
