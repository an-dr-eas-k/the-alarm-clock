import datetime
import os
import sys
import traceback
from gpiozero import Button, DigitalOutputDevice
from apscheduler.schedulers.background import BackgroundScheduler
from domain import AlarmClockState, AlarmDefinition, Observation, Observer, Config

button1Id = 23
button2Id = 24
button3Id = 12
button4Id = 16

class Controls(Observer):
	jobstores = {
    'alarm': {'type': 'memory'},
    'default': {'type': 'memory'}
	}
	scheduler = BackgroundScheduler(jobstores=jobstores)
	buttons = []
	state: AlarmClockState

	def __init__(self, state: AlarmClockState) -> None:
		self.state = state
		self.update_clock()
		self.scheduler.add_job(
			self.update_clock, 
			'interval', 
			seconds=self.state.configuration.refresh_timeout_in_secs, 
			id="clock_interval")
		self.scheduler.start()

	def update(self, observation: Observation):
		super().update(observation)
		if (True 
			and isinstance(observation.observable, Config)
			and observation.property_name == 'alarm_definitions'):
			self.scheduler.remove_all_jobs(jobstore='alarm')
			alDef: AlarmDefinition
			for alDef in observation.observable.alarm_definitions:
				print(f"adding job for {alDef.alarm_name}")
				self.scheduler.add_job(
					lambda : self.ring_alarm(alDef), 
					jobstore='alarm', 
					trigger=alDef.toCronTrigger())

	def gpio_input(self, channel):
		print(f"button {channel} pressed")

	def button1_action(self):
		self.state.audio_state.decrease_volume()

	def button2_action(self):
		self.state.audio_state.increase_volume()

	def button3_action(self):
		os._exit(0) 

	def button4_action(self):
		self.state.audio_state.toggle_stream()

	def configure_keyboard(self):
		def key_pressed_action(key):
			print (f"pressed {key}")
			if not hasattr(key, 'char'):
				return
			try:
				if (key.char == '1'):
					self.button1_action()
				if (key.char == '2'):
					self.button2_action()
				if (key.char == '3'):
					# self.button3_action()
					pass
				if (key.char == '4'):
					self.button4_action()
			except Exception:
				print(traceback.format_exc())

		from pynput.keyboard import Listener
		Listener(on_press=key_pressed_action).start()

	def configure_gpio(self):
		for button in ([
			dict(b=button1Id, ht=0.5, hr=True, wa=self.button1_action, wh=self.button1_action), 
			dict(b=button2Id, ht=0.5, hr=True, wa=self.button2_action, wh=self.button2_action), 
			dict(b=button3Id, wa=self.button3_action), 
			dict(b=button4Id, wa=self.button4_action)
			]):
			b = Button(button['b'])
			if ('ht' in button): b.hold_time=button['ht']
			if ('hr' in button): b.hold_repeat = button['hr']
			if ('wh' in button): b.when_held = button['wh']
			if ('wa' in button): b.when_activated = button['wa']
			self.buttons.append(b)

	def update_clock(self):
		print ("update clock")
		now = datetime.datetime.now()
		blink_segment = " "
		if (self.state.display_content.show_blink_segment):
			blink_segment = self.state.configuration.blink_segment

		self.state.display_content.show_blink_segment = not self.state.display_content.show_blink_segment

		self.state.display_content.clock	\
			= now.strftime(self.state.configuration.clock_format_string.replace("<blinkSegment>", blink_segment))

	def ring_alarm(self, alarmDefinition: AlarmDefinition):
		print ("ring alarm")

		self.state.audio_state.audio_effect = alarmDefinition.audio_effect
		self.state.audio_state.start_stream()