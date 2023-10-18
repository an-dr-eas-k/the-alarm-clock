from gpiozero import Button

from domain import AlarmClockState

button1 = 23
button2 = 24
button3 = 12
button4 = 16

class Controls:
	buttons = []
	state: AlarmClockState

	def __init__(self, state: AlarmClockState) -> None:
		self.state = state

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