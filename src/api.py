

import base64
import io
import json
import os
import tornado
import tornado.web

from domain import AlarmClockState, AlarmDefinition, Config, Weekday

class DisplayHandler(tornado.web.RequestHandler):

		def initialize(self, imageGetter) -> None:
				self.imageGetter = imageGetter

		def get(self):
				buffered = io.BytesIO()
				img= self.imageGetter()
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

		def parseAlarmDefinition(self, formArguments):
			ala = AlarmDefinition()
			ala.time = formArguments['time']
			ala.alarmName = formArguments['alarmName']
			ala.weekdays = Weekday._member_names_
			if (formArguments.get('weekdays') is not None):
				weekdays = formArguments['weekdays']
				if not isinstance(weekdays, list):
					weekdays = [weekdays]
				ala.weekdays = list(map(
					lambda weekday: Weekday[weekday.upper()], 
					weekdays))
			ala.isActive = formArguments['isActive'] == 'on'
			return ala


		def post(self):
			formArguments = tornado.escape.json_decode(self.request.body)
			self.config.alarmDefinitions = self.parseAlarmDefinition(formArguments)

class Api:

				app: tornado.web.Application

				def __init__(self, state: AlarmClockState, imageGetter):
					root = os.path.join(os.path.dirname(__file__), "webroot")
					handlers = [
						(r"/api/config", ConfigApiHandler, {"config": state.configuration}),
						(r"/(.*)", tornado.web.StaticFileHandler, {"path": root, "default_filename": "alarm.html"}),
					]

					if imageGetter is not None:
							handlers= [(r"/display", DisplayHandler, {"imageGetter": imageGetter} ),]+handlers

					self.app = tornado.web.Application(handlers)


				def start(self, port):
								self.app.listen(port)


if __name__ == '__main__':
				Api(8080).app.run()