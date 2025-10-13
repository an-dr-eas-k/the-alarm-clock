import os
from core.domain.model import (
    AlarmClockContext,
    AlarmDefinition,
    Config,
    TACEvent,
    TACEventSubscriber,
)
from resources.resources import active_alarm_definition_file


class Persistence(TACEventSubscriber):
    config_file: str

    def __init__(self, config_file: str):
        self.config_file = config_file
        super().__init__()

    def handle(self, observation: TACEvent):
        super().handle(observation)
        if observation.during_registration:
            return

        if isinstance(observation.subscriber, Config):
            self.update_from_config(observation, observation.subscriber)

        if isinstance(observation.subscriber, AlarmClockContext):
            self.update_from_context(observation, observation.subscriber)

    def update_from_config(self, _: TACEvent, config: Config):
        self.store_config(config)

    def store_config(self, config: Config):
        with open(self.config_file, "w") as f:
            f.write(config.serialize())

    def update_from_context(
        self, observation: TACEvent, alarm_clock_context: AlarmClockContext
    ):
        if observation.property_name == "active_alarm":
            self.store_alarm(alarm_clock_context.active_alarm)

    def store_alarm(self, alarm_definition: AlarmDefinition):
        if alarm_definition is None:
            if os.path.exists(active_alarm_definition_file):
                os.remove(active_alarm_definition_file)
            return

        alarm_definition.serialize(active_alarm_definition_file)
