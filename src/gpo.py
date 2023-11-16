
from domain import AudioDefinition, Observation, Observer
from gpiozero import DigitalOutputDevice

audio_power_pin_id = 21

class GeneralPurposeOutput(Observer):

	power_audio_pin: DigitalOutputDevice

	def __init__(self):
		self.power_audio_pin = DigitalOutputDevice(audio_power_pin_id)

	def update(self, observation: Observation):
		super().update(observation)
		if not isinstance(observation.observable, AudioDefinition):
			return

		if (observation.property_name == 'is_streaming' and observation.observable.is_streaming):
			self.power_audio_pin.on()
		else:
			self.power_audio_pin.off()

