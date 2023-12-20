import base64
import io
import os
import tornado
import tornado.web
from PIL.Image import Image

from domain import AlarmClockState, AlarmDefinition, Config, Weekday

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

class ConfigApiHandler(tornado.web.RequestHandler):

	def initialize(self, config: Config) -> None:
		self.config = config

	def get(self):
		self.set_header('Content-Type', 'application/json')
		self.write(self.config.serialize())

	def parse_alarm_definition(self, form_arguments):
		ala = AlarmDefinition()
		ala.alarm_name = form_arguments['alarmName']
		(ala.hour, ala.min)= form_arguments['time'].split(':')
		ala.weekdays = Weekday._member_names_
		if (form_arguments.get('weekdays') is not None):
			weekdays = form_arguments['weekdays']
			if not isinstance(weekdays, list):
				weekdays = [weekdays]
			ala.weekdays = list(map(
				lambda weekday: Weekday[weekday.upper()], 
				weekdays))
		ala.is_active = form_arguments['isActive'] == 'on'
		return ala


	def post(self):
		form_arguments = tornado.escape.json_decode(self.request.body)
		self.config.alarm_definitions = self.parse_alarm_definition(form_arguments)

class Api:

	app: tornado.web.Application

	def __init__(self, state: AlarmClockState, image_getter):
		root = os.path.join(os.path.dirname(__file__), "webroot")
		handlers = [
			(r"/api/config", ConfigApiHandler, {"config": state.configuration}),
			(r"/(.*)", tornado.web.StaticFileHandler, {"path": root, "default_filename": "alarm.html"}),
		]

		if image_getter is not None:
			handlers= [(r"/display", DisplayHandler, {"imageGetter": image_getter} ),]+handlers

		self.app = tornado.web.Application(handlers)


	def start(self, port):
		self.app.listen(port)


if __name__ == '__main__':
				Api(8080).app.run()