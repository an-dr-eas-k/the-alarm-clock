"""
 - Add this line to /etc/rc.local (before the exit 0):
	-   /home/pi/ONBOOT.sh 2> /home/pi/ONBOOT.errors > /home/pi/ONBOOT.stdout &
	- Add the following ONBOOT.sh script to /home/pi and make it executable:
	
#!/bin/bash
cd /home/pi/iot-clock/src
python app_clock.py
"""

import argparse
import os
from luma.oled.device import ssd1322
from luma.core.device import dummy

import tornado.ioloop
import tornado.web
from api import Api
from audio import Speaker
from controls import Controls

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

		device = dummy(height=64, width=256, mode="1")
		port = 8080
		if self.is_on_hardware():
			port = 80
			try:
				device = ssd1322()
			except: pass

		self.state.configuration.attach(
			Persistence( self.state.configuration, self.configFile))

		self.state.audio_state.attach(Speaker())
		if (self.is_on_hardware()):
			self.state.audio_state.attach(GeneralPurposeOutput())
		self.display = Display(device, self.state.display_content)
		self.controls = Controls(self.state)
		self.state.configuration.attach(self.controls)
		self.api = Api(self.state, lambda:device.image if isinstance (device, dummy) else None)
		self.api.start(port)
		

		if self.is_on_hardware():
			self.controls.configure_gpio()
		else:
			self.controls.configure_keyboard()

		tornado.ioloop.IOLoop.current().start()
		
if __name__ == '__main__':
	print ("start")
	ClockApp().go()