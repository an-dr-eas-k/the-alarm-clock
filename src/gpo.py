
from domain import AudioDefinition, Observation, Observer
from gpiozero import DigitalOutputDevice

audioPowerPinId = 14

class GeneralPurposeOutput(Observer):

	powerAudioPin: DigitalOutputDevice

	def __init__(self):
		self.powerAudioPin = DigitalOutputDevice(audioPowerPinId)

	def notify(self, observation: Observation):
		super().notify(observation)
		if (observation.propertyName == 'isStreaming' and observation.newValue):
			self.powerAudioPin.on()
		else:
			self.powerAudioPin.off()

