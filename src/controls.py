import datetime
import traceback
from gpiozero import Button
from apscheduler.schedulers.background import BackgroundScheduler
import pynput
from pynput import keyboard
from pynput.keyboard import Key, Listener, KeyCode
from domain import AlarmClockState

button1 = 23
button2 = 24
button3 = 12
button4 = 16

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
		exit(0) 

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

		with Listener(on_press=keyPressedAction) as listener:
			listener.join()

	def configureGpio(self):
		for button in ([
			dict(b=button1, ht=0.5, hr=True, wa=self.button1Action, wh=self.button1Action), 
			dict(b=button2, ht=0.5, hr=True, wa=self.button2Action, wh=self.button2Action), 
			dict(b=button3, wa=self.button3Action), 
			dict(b=button4, wa=self.button4Action)
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
