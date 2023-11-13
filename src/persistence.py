
from domain import Config, Observation, Observer


class Persistence(Observer):
	config: Config
	configFileName: str

	def __init__(self, config: Config, configFileName: str):
		self.config = config
		self.configFileName = configFileName
		super().__init__()


	def notify(self, observation: Observation):
		if (observation.duringRegistration):
			return

		with open(self.configFileName, 'w') as f:
			f.write(self.config.serialize())

