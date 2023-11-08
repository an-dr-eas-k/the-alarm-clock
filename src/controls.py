import datetime
import os
import sys
import traceback
from gpiozero import Button, DigitalOutputDevice
from apscheduler.schedulers.background import BackgroundScheduler
from domain import AlarmClockState

button1Id = 23
button2Id = 24
button3Id = 12
button4Id = 16
audioPowerPinId = 14

class Controls:
	refreshScheduler = BackgroundScheduler()
	buttons = []
	state: AlarmClockState

	def __init__(self, state: AlarmClockState) -> None:
		self.state = state
		self.updateClock()
		self.refreshScheduler.add_job(self.updateClock, 'interval', seconds=self.state.configuration.refreshTimeoutInSecs)
		self.refreshScheduler.start()

	def gpioInput(self, channel):
		print(f"button {channel} pressed")

	def button1Action(self):
		self.state.audioState.decreaseVolume()

	def button2Action(self):
		self.state.audioState.increaseVolume()

	def button3Action(self):
		os._exit(0) 

	def button4Action(self):
		self.state.audioState.toggleStream()

	def configureKeyboard(self):
		def keyPressedAction(key):
			print (f"pressed {key}")
			if not hasattr(key, 'char'):
				return
			try:
				if (key.char == '1'):
					self.button1Action()
				if (key.char == '2'):
					self.button2Action()
				if (key.char == '3'):
					self.button3Action()
				if (key.char == '4'):
					self.button4Action()
			except Exception:
				print(traceback.format_exc())

		from pynput.keyboard import Listener
		Listener(on_press=keyPressedAction).start()

	def configureGpio(self):
		for button in ([
			dict(b=button1Id, ht=0.5, hr=True, wa=self.button1Action, wh=self.button1Action), 
			dict(b=button2Id, ht=0.5, hr=True, wa=self.button2Action, wh=self.button2Action), 
			dict(b=button3Id, wa=self.button3Action), 
			dict(b=button4Id, wa=self.button4Action)
			]):
			b = Button(button['b'])
			if ('ht' in button): b.hold_time=button['ht']
			if ('hr' in button): b.hold_repeat = button['hr']
			if ('wh' in button): b.when_held = button['wh']
			if ('wa' in button): b.when_activated = button['wa']
			self.buttons.append(b)

	def updateClock(self):
		print ("update clock")
		now = datetime.datetime.now()
		blinkSegment = " "
		if (self.state.displayContent.showBlinkSegment):
			blinkSegment = self.state.configuration.blinkSegment

		self.state.displayContent.showBlinkSegment = not self.state.displayContent.showBlinkSegment

		self.state.displayContent.clock	\
			= now.strftime(self.state.configuration.clockFormatString.replace("<blinkSegment>", blinkSegment))
