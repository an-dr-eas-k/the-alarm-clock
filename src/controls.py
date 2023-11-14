import datetime
import os
import sys
import traceback
from gpiozero import Button, DigitalOutputDevice
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from domain import AlarmClockState, AlarmDefinition, AudioDefinition, Observation, Observer, Config

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
		if isinstance(observation.observable, Config):
			self.update_from_config(observation, observation.observable)
		if isinstance(observation.observable, AudioDefinition):
			self.update_from_audio_definition(observation, observation.observable)

	def update_from_audio_definition(self, observation: Observation, audio_definition: AudioDefinition):
		if observation.property_name == 'volume' and not observation.during_registration:
			self.state.display_content.show_volume_meter()
			self.start_hide_volume_meter_trigger()

	def start_hide_volume_meter_trigger(self):
		job_id = 'hide_volume_meter_trigger'
		trigger = DateTrigger(run_date=datetime.datetime.now() + datetime.timedelta(seconds=5))

		existing_job = self.scheduler.get_job(job_id=job_id)
		if existing_job:
			self.scheduler.reschedule_job(job_id=job_id, trigger=trigger)
		else:
			self.scheduler.add_job(id=job_id, trigger=trigger,
				func=self.state.display_content.hide_volume_meter)

	def update_from_config(self, observation: Observation, config: Config):
		if observation.property_name == 'alarm_definitions':
			self.scheduler.remove_all_jobs(jobstore='alarm')
			alDef: AlarmDefinition
			for alDef in config.alarm_definitions:
				print(f"adding job for {alDef.alarm_name}")
				self.scheduler.add_job(
					lambda : self.ring_alarm(alDef), 
					jobstore='alarm', 
					trigger=alDef.toCronTrigger())

	def button1_action(self):
		self.state.audio_state.decrease_volume()

	def button2_action(self):
		self.state.audio_state.increase_volume()

	def button3_action(self):
		os._exit(0) 

	def button4_action(self):
		self.state.audio_state.toggle_stream()

	def configure(self):
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
		self.state.audio_state.is_streaming = True

class SoftwareControls(Controls):
	def __init__(self, state: AlarmClockState) -> None:
		super().__init__(state)

	def configure(self):
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