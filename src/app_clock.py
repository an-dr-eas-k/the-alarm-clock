import argparse
import os
from luma.oled.device import ssd1322
from luma.core.device import device as luma_device
from luma.core.interface.serial import spi
from luma.core.device import dummy

import tornado.ioloop
import tornado.web
from api import Api
from audio import Speaker
from controls import Controls, SoftwareControls

from display import Display
from domain import AlarmClockState, Config
from gpo import GeneralPurposeOutput
from persistence import Persistence

class ClockApp:
	configFile = f"{os.path.dirname(os.path.realpath(__file__))}/config.json"

	def __init__(self) -> None:
		parser = argparse.ArgumentParser("ClockApp")
		parser.add_argument("-s", '--software', action='store_true')
		self.args = parser.parse_args()

	def is_on_hardware(self):
		return not self.args.software
	

	def go(self):

		self.state = AlarmClockState(Config())
		if os.path.exists(self.configFile):
			self.state.configuration = Config.deserialize(self.configFile)
		
		print("config available")

		device: luma_device

		if (self.is_on_hardware()):
			self.controls = Controls(self.state)
			self.state.audio_state.attach(GeneralPurposeOutput())
			device = ssd1322(serial_interface=spi(device=0, port=0))
			port = 80
		else:
			self.controls = SoftwareControls(self.state)
			device = dummy(height=64, width=256, mode="RGB")
			port = 8080

		self.display = Display(device, self.state.display_content)
		self.state.configuration.attach(
			Persistence( self.state.configuration, self.configFile))

		self.state.audio_state.attach(Speaker())
		self.state.configuration.attach(self.controls)
		self.state.audio_state.attach(self.controls)
		self.controls.configure()

		self.api = Api(self.state, lambda:device.image if isinstance (device, dummy) else None)
		self.api.start(port)

		tornado.ioloop.IOLoop.current().start()
		
if __name__ == '__main__':
	print ("start")
	ClockApp().go()