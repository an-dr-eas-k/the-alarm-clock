

import base64
import io
import os
import tornado
import tornado.web

from domain import AlarmClockState, Config

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

		def _get_json(self):
			ret = {
					'brightness': self.config.brightness,
					'clockFormatString': self.config.clockFormatString,
			}        
			return ret

		def get(self):

			brightness = self.get_argument('brightness', None)
			clockFormatString = self.get_argument('clockFormatString', None)

			if brightness is not None:
				self.config.brightness = int(brightness)

			if clockFormatString is not None:
				self.config.clockFormatString = clockFormatString

			self.set_header('Content-Type', 'application/json')
			self.write(self._get_json())

		def post(self):
			foo =self.request.body_arguments
			print(foo)
        

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