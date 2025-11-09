import os
from core.domain.events import AlarmEvent, ConfigChangedEvent
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
        self.event_bus.on(AlarmEvent)(self._alarm_event)
        self.event_bus.on(ConfigChangedEvent)(self._config_changed)

    def _config_changed(self, configChangedEvent: ConfigChangedEvent):
        self.store_config(configChangedEvent.config)

    def store_config(self, config: Config):
        with open(self.config_file, "w") as f:
            f.write(config.serialize())

    def _alarm_event(self, event: AlarmEvent):
        if event.alarm_definition is not None:
            self.store_alarm(event.alarm_definition)

    def store_alarm(self, alarm_definition: AlarmDefinition):
        if alarm_definition is None:
            if os.path.exists(active_alarm_definition_file):
                os.remove(active_alarm_definition_file)
            return

        alarm_definition.serialize(active_alarm_definition_file)
