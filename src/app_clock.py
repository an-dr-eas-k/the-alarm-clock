import argparse
import logging
import logging.config
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
from domain import AlarmClockState, Config, DisplayContent
from gpo import GeneralPurposeOutput
from persistence import Persistence


class ClockApp:
	configFile = f"{os.path.dirname(os.path.realpath(__file__))}/config.json"

	def __init__(self) -> None:
		logging.config.fileConfig(os.path.join(os.path.dirname(os.path.relpath(__file__)), 'logging.conf'))
		parser = argparse.ArgumentParser("ClockApp")
		parser.add_argument("-s", '--software', action='store_true')
		self.args = parser.parse_args()

	def is_on_hardware(self):
		return not self.args.software
	
	def go(self):

		self.state = AlarmClockState(Config())
		if os.path.exists(self.configFile):
			self.state.configuration = Config.deserialize(self.configFile)
		
		logging.info("config available")

		display_content = DisplayContent(self.state)
		self.state.attach(display_content)

		device: luma_device

		if (self.is_on_hardware()):
			self.controls = Controls(self.state, display_content)
			self.state.audio_state.attach(GeneralPurposeOutput())
			device = ssd1322(serial_interface=spi(device=0, port=0))
			port = 80
		else:
			self.controls = SoftwareControls(self.state, display_content)
			device = dummy(height=64, width=256, mode="RGB")
			port = 8080

		self.display = Display(device, display_content, self.state.configuration)
		self.state.configuration.attach(
			Persistence( self.configFile))

		self.state.audio_state.attach(Speaker(self.state.configuration))
		self.state.configuration.attach(self.controls)
		self.state.audio_state.attach(self.controls)
		self.controls.configure()

		self.api = Api(self.state, lambda:self.display.current_display_image)
		self.api.start(port)

		tornado.ioloop.IOLoop.current().start()
		
if __name__ == '__main__':
	logging.info ("start")
	ClockApp().go()