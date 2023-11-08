
from domain import AudioDefinition, Observer
from gpiozero import DigitalOutputDevice

audioPowerPinId = 14

class GeneralPurposeOutput(Observer):

	powerAudioPin: DigitalOutputDevice

	def __init__(self):
		self.powerAudioPin = DigitalOutputDevice(audioPowerPinId)

	def notify(self, propertyName, propertyValue):
		super().notify(propertyName, propertyValue)
		if (propertyName == 'isStreaming' and propertyValue):
			self.powerAudioPin.on()
		else:
			self.powerAudioPin.off()

