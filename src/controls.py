import datetime
import json
import logging
import os
import subprocess
import traceback
from urllib.request import urlopen
from gpiozero import Button
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.job import Job
from domain import AlarmClockState, AlarmDefinition, AudioDefinition, DisplayContent, InternetRadio, Observation, Observer, Config
from utils.geolocation import GeoLocation, SunEvent
from utils.network import is_internet_available

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
		self.update_weather_status()
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

		self.scheduler.add_job(
			self.update_weather_status,
			'interval', 
			minutes=5,
			id="weather_check_interval", 
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
		self.start_generic_trigger(
			'hide_volume_meter_trigger', 
			datetime.timedelta(seconds=5), 
			func=self.display_content.hide_volume_meter
		)

	def start_generic_trigger(self, job_id: str, duration: datetime.timedelta, func):
		trigger = DateTrigger(run_date=GeoLocation().now() + duration)

		existing_job = self.scheduler.get_job(job_id=job_id)
		if existing_job:
			self.scheduler.reschedule_job(job_id=job_id, trigger=trigger)
		else:
			self.scheduler.add_job(id=job_id, trigger=trigger, func=func)

	def update_from_config(self, observation: Observation, config: Config):
		if observation.property_name == 'alarm_definitions':
			self.scheduler.remove_all_jobs(jobstore=alarm_store)
			alDef: AlarmDefinition
			for alDef in config.alarm_definitions:
				if not alDef.is_active:
					continue
				logging.info("adding job for '%s'", alDef.alarm_name)
				self.scheduler.add_job(
					func=self.ring_alarm,
					args=(alDef,),
					id=f'{alDef.id}',
					jobstore=alarm_store,
					trigger=alDef.to_cron_trigger())
			self.cleanup_alarms()
			self.display_content.next_alarm_job = self.get_next_alarm_job()
			self.print_active_jobs(alarm_store)

	def get_next_alarm_job(self) -> Job:
		jobs = sorted (self.scheduler.get_jobs(jobstore=alarm_store), key=lambda job: job.next_run_time)
		return jobs[0] if len(jobs) > 0 else None


	def print_active_jobs(self, jobstore):
			for job in self.scheduler.get_jobs(jobstore=jobstore):
				if (hasattr(job, 'next_run_time') and job.next_run_time is not None):
					logging.info("next runtime for job '%s': %s", job.id, job.next_run_time.strftime(f"%Y-%m-%d %H:%M:%S"))

	def button_action(action, button_id):
		try:
			logging.info("button %s pressed", button_id)
			action()
		except:
			logging.error("%s", traceback.format_exc())
		

	def button1_action(self):
		Controls.button_action(self.state.audio_state.decrease_volume, 1)

	def button2_action(self):
		Controls.button_action(self.state.audio_state.increase_volume, 2)

	def button3_action(self):

		def exit():
			self.scheduler.shutdown(wait=False)
			os._exit(0) 

		Controls.button_action(exit, 3)

	def button4_action(self):

		def toggle_stream():
			audio_state = self.state.audio_state
			if not audio_state.audio_effect:
					first_stream = self.state.configuration.audio_streams[0]
					ir = InternetRadio()
					ir.stream_definition=first_stream
					ir.volume = self.state.configuration.default_volume
					audio_state.audio_effect = ir

			self.state.audio_state.toggle_stream()
		
		Controls.button_action(toggle_stream, 4)

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
		try:
			logging.debug ("update show blink segment: %s", self.state.show_blink_segment)
			self.state.show_blink_segment = not self.state.show_blink_segment
		except:
			logging.error("%s", traceback.format_exc())

	def update_weather_status(self):
		try:
			self.display_content.current_weather = GeoLocation().get_current_weather()
			logging.info ("weather updated: %s", self.display_content.current_weather)
		except:
			logging.error("%s", traceback.format_exc())


	def update_wifi_status(self):
		try:
			self.state.is_wifi_available = is_internet_available()
			logging.info ("update wifi, is available: %s", self.state.is_wifi_available)
		except:
			logging.error("%s", traceback.format_exc())

	def sun_event_occured(self, event: SunEvent):
		try:
			logging.info ("sun event %s", event)
			self.state.is_daytime = event == SunEvent.sunrise
		except:
			logging.error("%s", traceback.format_exc())

	def ring_alarm(self, alarmDefinition: AlarmDefinition):
		try:
			logging.info ("ring alarm %s", alarmDefinition.alarm_name)

			self.state.audio_state.audio_effect = alarmDefinition.audio_effect
			self.state.audio_state.is_streaming = True

			self.after_ring_alarm(alarmDefinition)
		except:
			logging.error("%s", traceback.format_exc())

	def after_ring_alarm(self, alarmDefinition: AlarmDefinition):

		self.start_generic_trigger(
			'stop_alarm_trigger', 
			datetime.timedelta(minutes=self.state.configuration.alarm_duration_in_mins), 
			func=lambda: self.state.audio_state.toggle_stream(new_value=False)
		)

		self.display_content.next_alarm_job = self.get_next_alarm_job()
		if alarmDefinition.is_one_time():
			self.state.configuration.remove_alarm_definition(alarmDefinition.id)

	def cleanup_alarms(self):
		job: Job
		for job in self.scheduler.get_jobs(jobstore=alarm_store):
			if job.next_run_time is None:
				self.state.configuration.remove_alarm_definition(job.id)

class SoftwareControls(Controls):
	def __init__(self, state: AlarmClockState, display_content: DisplayContent) -> None:
		super().__init__(state, display_content)

	def configure(self):
		def key_pressed_action(key):
			logging.debug ("pressed %s", key)
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