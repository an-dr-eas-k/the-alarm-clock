import datetime
import logging
import os
import subprocess
import traceback
from gpiozero import Button, DigitalOutputDevice
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from domain import AlarmClockState, AlarmDefinition, AudioDefinition, DisplayContent, Observation, Observer, Config
from utils.geolocation import GeoLocation, SunEvent

button1Id = 0
button2Id = 5
button3Id = 6
button4Id = 13
alarm_store = 'alarm'
default_store = 'default'

class Controls(Observer):
	jobstores = {
    alarm_store: {'type': 'memory'},
    default_store: {'type': 'memory'}
	}
	scheduler = BackgroundScheduler(jobstores=jobstores)
	buttons = []
	state: AlarmClockState

	def __init__(self, state: AlarmClockState, display_content: DisplayContent) -> None:
		self.state = state
		self.display_content = display_content
		self.sun_event_occured(state.geo_location.last_sun_event())
		self.add_scheduler_jobs()
		self.scheduler.start()
		self.print_active_jobs(default_store)

	def add_scheduler_jobs(self):
		self.scheduler.add_job(
			self.update_clock, 
			'interval', 
			seconds=self.state.configuration.refresh_timeout_in_secs, 
			id="clock_interval",
			jobstore=default_store)

		self.scheduler.add_job(
			self.update_wifi_status, 
			'interval', 
			seconds=60,
			id="wifi_check_interval", 
			jobstore=default_store)

		for event in SunEvent.__members__.values():
			self.scheduler.add_job(
				lambda : self.sun_event_occured(event), 
				trigger=self.state.geo_location.get_sun_event_cron_trigger(event),
				id=event.value,
				jobstore=default_store)

	def update(self, observation: Observation):
		super().update(observation)
		if isinstance(observation.observable, Config):
			self.update_from_config(observation, observation.observable)
		if isinstance(observation.observable, AudioDefinition):
			self.update_from_audio_definition(observation, observation.observable)

	def update_from_audio_definition(self, observation: Observation, audio_definition: AudioDefinition):
		if observation.property_name == 'volume' and not observation.during_registration:
			self.display_content.show_volume_meter()
			self.start_hide_volume_meter_trigger()

	def start_hide_volume_meter_trigger(self):
		job_id = 'hide_volume_meter_trigger'
		trigger = DateTrigger(run_date=GeoLocation().now() + datetime.timedelta(seconds=5))

		existing_job = self.scheduler.get_job(job_id=job_id)
		if existing_job:
			self.scheduler.reschedule_job(job_id=job_id, trigger=trigger)
		else:
			self.scheduler.add_job(id=job_id, trigger=trigger,
				func=self.display_content.hide_volume_meter)

	def update_from_config(self, observation: Observation, config: Config):
		if observation.property_name == 'alarm_definitions':
			self.scheduler.remove_all_jobs(jobstore=alarm_store)
			alDef: AlarmDefinition
			for alDef in config.alarm_definitions:
				if not alDef.is_active:
					continue
				logging.info("adding job for '%s'", alDef.alarm_name)
				self.scheduler.add_job(
					lambda : self.ring_alarm(alDef), 
					id=alDef.alarm_name,
					jobstore=alarm_store,
					trigger=alDef.to_cron_trigger())
			self.cleanup_alarms()
			self.print_active_jobs(alarm_store)

	def print_active_jobs(self, jobstore):
			for job in self.scheduler.get_jobs(jobstore=jobstore):
				if (hasattr(job, 'next_run_time') and job.next_run_time is not None):
					logging.info("next runtime for job '%s': %s", job.id, job.next_run_time.strftime(f"%Y-%m-%d %H:%M:%S"))

	def button1_action(self):
		self.state.audio_state.decrease_volume()

	def button2_action(self):
		self.state.audio_state.increase_volume()

	def button3_action(self):
		self.scheduler.shutdown(wait=False)
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
		blink_segment = " "
		if (self.state.show_blink_segment):
			blink_segment = self.state.configuration.blink_segment
		
		self.state.show_blink_segment = not self.state.show_blink_segment

		self.state.clock	\
			= GeoLocation().now().strftime(self.state.configuration.clock_format_string.replace("<blinkSegment>", blink_segment))
		logging.info ("update clock %s", self.state.clock)

	def update_wifi_status(self):

		def is_ping_successful(hostname):
			result = subprocess.run(
				["ping", "-c", "1", hostname], 
				stdout=subprocess.DEVNULL, 
				stderr=subprocess.DEVNULL)
			return result.returncode == 0

		self.state.is_wifi_available = is_ping_successful("google.com")
		logging.info ("update wifi, is available: %s", self.state.is_wifi_available)

	def sun_event_occured(self, event: SunEvent):
		logging.info ("sun event %s", event)
		self.state.is_daytime = event == SunEvent.sunrise

	def ring_alarm(self, alarmDefinition: AlarmDefinition):
		logging.info ("ring alarm %s", alarmDefinition.alarm_name)

		self.state.audio_state.audio_effect = alarmDefinition.audio_effect
		self.state.audio_state.is_streaming = True

		if alarmDefinition.date is not None:
			self.state.configuration.remove_alarm_definition(alarmDefinition.alarm_name)

	def cleanup_alarms(self):
		job: Job
		for job in self.scheduler.get_jobs(jobstore=alarm_store):
			if job.next_run_time is None:
				self.state.configuration.remove_alarm_definition(job.id)

class SoftwareControls(Controls):
	def __init__(self, state: AlarmClockState, display_content: DisplayContent) -> None:
		super().__init__(state, display_content)
		self.state.configuration.brightness = 12

	def configure(self):
		def key_pressed_action(key):
			logging.info ("pressed %s", key)
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
				logging.warning("%s", traceback.format_exc())

		try:
			from pynput.keyboard import Listener
			Listener(on_press=key_pressed_action).start()
		except:
			super().configure()