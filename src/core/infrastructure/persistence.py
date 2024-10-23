import os
from core.domain import (
    AlarmClockState,
    AlarmDefinition,
    AudioEffect,
    Config,
    Mode,
    Observation,
    Observer,
)
from resources.resources import active_alarm_definition_file


class Persistence(Observer):
    config_file_name: str

    def __init__(self, config_file_name: str):
        self.config_file_name = config_file_name
        super().__init__()

    def update(self, observation: Observation):
        super().update(observation)
        if observation.during_registration:
            return

        if isinstance(observation.observable, Config):
            self.update_from_config(observation, observation.observable)

        if isinstance(observation.observable, AlarmClockState):
            self.update_from_state(observation, observation.observable)

    def update_from_config(self, _: Observation, config: Config):
        self.store_config(config)

    def store_config(self, config: Config):
        with open(self.config_file_name, "w") as f:
            f.write(config.serialize())

    def update_from_state(self, observation: Observation, state: AlarmClockState):
        if observation.property_name == "active_alarm":
            self.store_alarm(state.active_alarm)

    def store_alarm(self, alarm_definition: AlarmDefinition):
        if alarm_definition is None:
            if os.path.exists(active_alarm_definition_file):
                os.remove(active_alarm_definition_file)
            return

        alarm_definition.serialize(active_alarm_definition_file)
