
from domain import AudioEffect, Config, Observation, Observer, PlaybackContent
from resources.resources import alarm_details_file


class Persistence(Observer):
	config_file_name: str

	def __init__(self, config_file_name: str):
		self.config_file_name = config_file_name
		super().__init__()


	def update(self, observation: Observation):
		super().update(observation)
		if (observation.during_registration):
			return

		if isinstance(observation.observable, Config):
			self.update_from_config(observation, observation.observable)

	def update_from_config(self, _: Observation, config: Config):
		self.store_config(config)

	def store_config(self, config: Config):
		with open(self.config_file_name, 'w') as f:
			f.write(config.serialize())
