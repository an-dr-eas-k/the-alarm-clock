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

	def __init__(self) -> None:
		parser = argparse.ArgumentParser("ClockApp")
		parser.add_argument("-s", '--software', action='store_true')
		self.args = parser.parse_args()

	def isOnHardware(self):
		return not self.args.software
	

	def go(self):

		self.state = AlarmClockState(Config())

		device = dummy(height=64, width=256, mode="1")
		port = 8080
		if self.isOnHardware():
			port = 80
			try:
				device = ssd1322()
			except: pass

		self.state.configuration.registerObserver(Persistence( \
			self.state.configuration, \
			f"{os.path.dirname(os.path.realpath(__file__))}/config.json"))

		self.state.audioState.registerObserver(Speaker())
		if (self.isOnHardware()):
			self.state.audioState.registerObserver(GeneralPurposeOutput())
		self.display = Display(device, self.state.displayContent)
		self.controls = Controls(self.state)
		self.api = Api(self.state, lambda:device.image if isinstance (device, dummy) else None)
		self.api.start(port)
		

		if self.isOnHardware():
			self.controls.configureGpio()
		else:
			self.controls.configureKeyboard()

		tornado.ioloop.IOLoop.current().start()
		
if __name__ == '__main__':
	print ("start")
	ClockApp().go()