"""
 - Add this line to /etc/rc.local (before the exit 0):
	-   /home/pi/ONBOOT.sh 2> /home/pi/ONBOOT.errors > /home/pi/ONBOOT.stdout &
	- Add the following ONBOOT.sh script to /home/pi and make it executable:
	
#!/bin/bash
cd /home/pi/iot-clock/src
python app_clock.py
"""

import os
import io
import base64
import threading
import time
import traceback
import argparse
from luma.oled.device import ssd1322
from luma.core.device import dummy

import tornado.ioloop
import tornado.web
from audio import Speaker

from display import Display
from domain import AlarmClockState, Config

from gpiozero import Button

button1 = 23
button2 = 24
button3 = 12
button4 = 16

class DisplayHandler(tornado.web.RequestHandler):

		def initialize(self, device: dummy) -> None:
				self.device = device

		def get(self):
				buffered = io.BytesIO()
				img= self.device.image
				img.save(buffered, format="png")
				img.seek(0)
				img_str = base64.b64encode(buffered.getvalue())
				my_html = '<img src="data:image/png;base64, {}">'.format(img_str.decode('utf-8'))
				self.write(my_html)

class ConfigHandler(tornado.web.RequestHandler):

		def initialize(self, config: Config) -> None:
				self.config = config

		def _get_json(self):
			ret = {
					'brightness': self.config.brightness,
					'clockFormatString': self.config.clockFormatString,
			}        
			return ret

		def get(self):

			brightness = self.get_argument('brightness', None)
			clockFormatString = self.get_argument('clockFormatString', None)

			if brightness is not None:
				self.config.brightness = int(brightness)

			if clockFormatString is not None:
				self.config.clockFormatString = clockFormatString

			self.set_header('Content-Type', 'application/json')
			self.write(self._get_json())

class ClockApp:

	buttons = []

	def __init__(self) -> None:
		parser = argparse.ArgumentParser("ClockApp")
		parser.add_argument("-s", '--software', action='store_true')
		self.args = parser.parse_args()

	def isOnHardware(self):
		return not self.args.software
	
	def repeat(self, callback: callable, startTime = time.time()):
		startTime = startTime+1
		callback()
		threading.Timer( startTime - time.time(), lambda _: self.repeat(startTime) ).start()

	def gpioInput(self, channel):
		print(f"button {channel} pressed")
		

	def button1Action(self):
		self.state.audioState.decreaseVolume()
		self.speaker.adjustVolume()

	def button2Action(self):
		self.state.audioState.increaseVolume()
		self.speaker.adjustVolume()

	def button3Action(self):
		exit(0) 

	def button4Action(self):
		self.state.audioState.toggleStream()
		self.speaker.adjustStreaming()

	def configureGpio(self):
		dict(foo = "bar")
		for button in ([
			dict(b=button1, ht=0.5, hr=True, wh=self.button1Action), 
			dict(b=button2, ht=0.5, hr=True, wh=self.button2Action), 
			dict(b=button3, wa=self.button3Action), 
			dict(b=button4, wa=self.button4Action)
			]):
			b = Button(button['b'])
			if ('ht' in button): b.hold_time=button['ht']
			if ('hr' in button): b.hold_repeat = button['hr']
			if ('wh' in button): b.when_held = button['wh']
			if ('wa' in button): b.when_activated = button['wa']
			self.buttons.append(b)

	def go(self):
		def keyPressedAction(key):
			try:
				if (key.char == 'r'):
					self.playLivestream()
				if (key.char == 's'):
					self.speaker.stopStreaming()
			except Exception:
				print(traceback.format_exc())
			pass

		self.state = AlarmClockState(Config())

		device = dummy(height=64, width=256, mode="1")
		if self.isOnHardware():
			try:
				device = ssd1322()
			except: pass

		self.speaker = Speaker(self.state.audioState)
		self.display = Display(device, self.state)
		
		loop = tornado.ioloop.IOLoop.current()


		if self.isOnHardware():
			self.configureGpio()
		# else:
			# import pynput
			# from pynput import keyboard
			# from pynput.keyboard import Key, Listener, KeyCode
			# with Listener(on_press=keyPressedAction) as listener:
			# 	listener.join()

		root = os.path.join(os.path.dirname(__file__), "webroot")
		handlers = [
			(r"/config", ConfigHandler, {"config": self.state.configuration}),
			(r"/(.*)", tornado.web.StaticFileHandler, {"path": root, "default_filename": "index.html"}),
		]
		if isinstance(device, dummy):
				handlers= [(r"/display", DisplayHandler, {"device": device} ),]+handlers


		app = tornado.web.Application(handlers)

		if self.isOnHardware():
				app.listen(80)
		else:
				app.listen(8080)

		def loopAction():
				self.adjustClock()
				loop.call_later(self.state.configuration.refreshTimeoutInSecs, loopAction)
		loopAction()

		loop.start()

	def adjustClock(self):
		self.display.adjustDisplay()
		self.speaker.adjustSpeaker()


if __name__ == '__main__':
	print ("start")
	ClockApp().go()