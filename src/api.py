import base64
import io
import os
import tornado
import tornado.web
from PIL.Image import Image
from datetime import timedelta

from domain import AlarmClockState, AlarmDefinition, Config, Weekday
from utils.geolocation import GeoLocation

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
	def initialize(self, config: Config) -> None:
		self.config = config

	def get(self, *args, **kwargs):
		self.render(f'{self.root}/alarm.html', config=self.config)

class ConfigApiHandler(tornado.web.RequestHandler):

	def initialize(self, config: Config) -> None:
		self.config = config

	def get(self):
		self.set_header('Content-Type', 'application/json')
		self.write(self.config.serialize())
	
	def delete(self, alarm_name):
		self.config.remove_alarm_definition(alarm_name) 

	def post(self, _):
		form_arguments = tornado.escape.json_decode(self.request.body)
		self.config.add_alarm_definition ( self.parse_alarm_definition(form_arguments) )

	def get_future_date(hour, minute):
		now = GeoLocation().now()
		target = now.replace(hour=hour, minute=minute)
		if target < now:
				target = target + timedelta(days=1)
		return target.date()

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

			next_day = ConfigApiHandler.get_future_date(ala.hour, ala.min)
			ala.date = next_day
		ala.is_active = form_arguments['isActive'] == 'on'
		return ala


class Api:

	app: tornado.web.Application

	def __init__(self, state: AlarmClockState, image_getter):
		root = os.path.join(os.path.dirname(__file__), "webroot")
		handlers = [
			(r"/api/config/?(.*)", ConfigApiHandler, {"config": state.configuration}),
			(r"/(.*)", ConfigHandler, {"config": state.configuration}),
			# (r"/(.*)", tornado.web.StaticFileHandler, {"path": root, "default_filename": "alarm.html"}),
		]

		if image_getter is not None:
			handlers= [(r"/display", DisplayHandler, {"imageGetter": image_getter} ),]+handlers

		self.app = tornado.web.Application(handlers)


	def start(self, port):
		self.app.listen(port)


if __name__ == '__main__':
				Api(8080).app.run()