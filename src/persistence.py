import os
from domain import (
    AlarmClockState,
    AlarmDefinition,
    AudioEffect,
    Config,
    Mode,
    Observation,
    Observer,
)
from resources.resources import alarm_details_file


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
        if observation.property_name == "desired_alarm_audio_effect":
            self.store_alarm(state.desired_alarm_audio_effect)

    def store_alarm(self, alarm: AudioEffect):
        if alarm is None:
            if os.path.exists(alarm_details_file):
                os.remove(alarm_details_file)
            return

        with open(alarm_details_file, "w") as f:
            f.write(alarm.serialize())
