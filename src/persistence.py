
from domain import Config, Observation, Observer


class Persistence(Observer):
	config: Config
	config_file_name: str

	def __init__(self, config: Config, config_file_name: str):
		self.config = config
		self.config_file_name = config_file_name
		super().__init__()


	def update(self, observation: Observation):
		if (observation.during_registration):
			return

		with open(self.config_file_name, 'w') as f:
			f.write(self.config.serialize())

