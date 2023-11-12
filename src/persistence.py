
from domain import Config, Observer


class Persistence(Observer):
	config: Config
	configFileName: str

	def __init__(self, config: Config, configFileName: str):
		self.config = config
		self.configFileName = configFileName
		super().__init__()


	def notify(self, propertyName: str, propertyValue: any):
		with open(self.configFileName, 'w') as f:
			f.write(self.config.serialize())

