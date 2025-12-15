import os
import threading
from core.domain.events import (
    AlarmStoppedEvent,
    AlarmTriggeredEvent,
    ConfigChangedEvent,
)
from core.domain.model import (
    AlarmDefinition,
    Config,
)
from core.infrastructure.event_bus import EventBus
from resources.resources import active_alarm_definition_file


class Persistence:
    config_file: str

    def __init__(self, config_file: str, event_bus: EventBus):
        self.config_file = config_file
        self.event_bus = event_bus
        self.event_bus.on(AlarmTriggeredEvent)(self._alarm_triggered_event)
        self.event_bus.on(AlarmStoppedEvent)(self._alarm_stopped_event)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)
        self.threadLock = threading.Lock()


    def _config_changed(self, configChangedEvent: ConfigChangedEvent):
        threading.Thread(
            name=f"config saver",
            daemon=True,
            target=self.store_config,
            args=(
                configChangedEvent.config,
            ),
        ).start()

    def _alarm_triggered_event(self, event: AlarmTriggeredEvent):
        self.store_alarm(event.alarm_definition)

    def _alarm_stopped_event(self, _: AlarmStoppedEvent):
        self.store_alarm(None)

    def store_config(self, config: Config):
        self.threadLock.acquire(True)

        with open(self.config_file, "w") as f:
            f.write(config.serialize())

        self.threadLock.release()

    def store_alarm(self, alarm_definition: AlarmDefinition):
        if alarm_definition is None:
            if os.path.exists(active_alarm_definition_file):
                os.remove(active_alarm_definition_file)
            return

        alarm_definition.serialize(active_alarm_definition_file)
