import base64
import io
import logging
import os
import json
import subprocess
import traceback
import tornado
import tornado.web
from PIL.Image import Image

from domain import AlarmClockState, AlarmDefinition, AudioEffect, AudioStream, Config, LibreSpotifyEvent, PlaybackContent, SpotifyAudioEffect, StreamAudioEffect, VisualEffect, Weekday, try_update
from gpi import get_room_brightness

def split_path_arguments(path) -> tuple[str, int, str]:
	path_args = path[0].split('/')
	return (
		path_args[0], 
		int(path_args[1]) if len(path_args) > 1 else None,
		path_args[2] if len(path_args) > 2 else None
	)

class LibreSpotifyEventHandler(tornado.web.RequestHandler):

	def initialize(self, playback_content: PlaybackContent) -> None:
		self.playback_content = playback_content

	def post(self):
		body = '{}' if self.request.body is None or len(self.request.body) == 0 else self.request.body
		spotify_event_payload: dict[str, str] = tornado.escape.json_decode(body)

		spotify_event_dict = {key: value for key, value in spotify_event_payload.items()}

		spotify_event = LibreSpotifyEvent(spotify_event_dict)
		if spotify_event.is_playback_changed():
			if not isinstance(self.playback_content.audio_effect, SpotifyAudioEffect):
				self.playback_content.audio_effect = SpotifyAudioEffect(volume=spotify_event.volume)

			self.playback_content.audio_effect.spotify_event=spotify_event
			
		self.playback_content.is_streaming = spotify_event.is_playback_active()

class DisplayHandler(tornado.web.RequestHandler):

	def initialize(self, imageGetter) -> None:
		self.imageGetter = imageGetter

	def get(self):
		buffered = io.BytesIO()
		img= self.imageGetter()
		assert isinstance(img, Image)
		img.save(buffered, format="png")
		img.seek(0)
		img_str = base64.b64encode(buffered.getvalue())
		my_html = '<img src="data:image/png;base64, {}">'.format(img_str.decode('utf-8'))
		self.write(my_html)

class ConfigHandler(tornado.web.RequestHandler):

	root = os.path.join(os.path.dirname(__file__), "webroot")
	
	def initialize(self, config: Config, api) -> None:
		self.config = config
		self.api = api

	def get(self, *args, **kwargs):
		try:
			self.render(f'{self.root}/alarm.html', config=self.config, api=self.api)
		except:
			logging.warning("%s", traceback.format_exc())

class ActionApiHandler(tornado.web.RequestHandler):

	def post(self, *args):
		try:
			(type, _1, _2) = split_path_arguments(args)

			if(type == 'update'):
				os._exit(0)
			elif (type == 'reboot'):
				os.system('sudo reboot')
			elif (type == 'shutdown'):
				os.system('sudo shutdown -h now')
			else:
				logging.warning("Unknown action: %s", type)

		except:
			logging.warning("%s", traceback.format_exc())


class ConfigApiHandler(tornado.web.RequestHandler):

	def initialize(self, config: Config) -> None:
		self.config = config

	def get(self):
		try:
			self.set_header('Content-Type', 'application/json')
			self.write(self.config.serialize())
		except:
			logging.warning("%s", traceback.format_exc())
	
	def delete(self, *args):
		try:
			(type, id, _) = split_path_arguments(args)
			if (type == 'alarm'):
				self.config.remove_alarm_definition(id) 
			elif type == 'stream':
				self.config.remove_audio_stream(id) 
		except:
			logging.warning("%s", traceback.format_exc())

	def post(self, *args):
		try:
			(type, id, property) = split_path_arguments(args)
			simpleValue = tornado.escape.to_unicode(self.request.body)
			if try_update(self.config, type, simpleValue):
				return
			alarmDef = self.config.get_alarm_definition(id)
			if True \
				and alarmDef is not None \
				and try_update(alarmDef, property, simpleValue):
				self.config.remove_alarm_definition(id)
				self.config.add_alarm_definition(alarmDef)
				return

			body = '{}' if self.request.body is None or len(self.request.body) == 0 else self.request.body
			form_arguments = tornado.escape.json_decode(body)
			if type == 'alarm':
					self.config.add_alarm_definition ( self.parse_alarm_definition(form_arguments) )
			elif type == 'stream':
				self.config.add_audio_stream ( self.parse_stream_definition(form_arguments) )
			elif type == 'start_powernap':
				self.config.add_alarm_definition_for_powernap ()
		except:
			logging.warning("%s", traceback.format_exc())

	def parse_stream_definition(self, form_arguments) -> AlarmDefinition:
		stream_name = form_arguments['streamName']
		stream_url = form_arguments['streamUrl']
		return AudioStream(stream_name=stream_name, stream_url=stream_url)

	def parse_visual_effect(self, form_arguments) -> VisualEffect:
		use_visual_effect = form_arguments.get('visualEffectActive') is not None and form_arguments['visualEffectActive'] == 'on'
		if use_visual_effect:
			return VisualEffect()
		return None
		
	def parse_audio_effect(self, form_arguments) -> AudioEffect:
		stream_id = int(form_arguments['streamId'])
		return StreamAudioEffect(
			stream_definition=self.config.get_audio_stream(stream_id), 
			volume=float(form_arguments['volume']))

	def parse_alarm_definition(self, form_arguments) -> AlarmDefinition:
		ala = AlarmDefinition()
		ala.alarm_name = form_arguments['alarmName']
		(ala.hour, ala.min)= map(int, form_arguments['time'].split(':'))
		ala.weekdays = None
		ala.date = None
		if (form_arguments.get('weekdays') is not None):
			weekdays = form_arguments['weekdays']
			if not isinstance(weekdays, list):
				weekdays = [weekdays]
			ala.weekdays = list(map(
				lambda weekday: Weekday[weekday.upper()].name, 
				weekdays))
		else:
			ala.set_future_date(ala.hour, ala.min)

		ala.audio_effect = self.parse_audio_effect(form_arguments)
		ala.visual_effect = self.parse_visual_effect(form_arguments)
		ala.is_active = form_arguments.get('isActive') is not None and form_arguments['isActive'] == 'on'
		return ala


class Api:

	app: tornado.web.Application

	def __init__(self, state: AlarmClockState, playback_content: PlaybackContent, image_getter):
		self.state = state
		handlers = [
			(r"/api/config/?(.*)", ConfigApiHandler, {"config": state.configuration}),
			(r"/api/action/?(.*)", ActionApiHandler ),
			(r"/api/librespotify/?(.*)", LibreSpotifyEventHandler, {"playback_content": playback_content} ),
			(r"/(.*)", ConfigHandler, {"config": state.configuration, "api": self})
		]

		if image_getter is not None:
			handlers= [(r"/display", DisplayHandler, {"imageGetter": image_getter} ),]+handlers

		self.app = tornado.web.Application(handlers)

	def get_git_log(self) -> str:
		return subprocess.check_output(['git', 'log', '-1']).decode('utf-8')

	def get_state_as_json(self) -> str:
		return json.dumps(
			obj=dict(
				room_brightness = get_room_brightness(),
				is_wifi_available = self.state.is_wifi_available,
				is_daytime = self.state.is_daytime,
				geo_location = self.state.geo_location.location_info.__dict__,
				uptime = subprocess.check_output(['uptime']).strip().decode('utf-8'),
			), 
			indent=2)


	def start(self, port):
		self.app.listen(port)


if __name__ == '__main__':
	Api(8080).app.run()
