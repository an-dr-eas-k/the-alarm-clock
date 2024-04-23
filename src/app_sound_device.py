
import argparse
import json
import logging

from resources.resources import init_logging
from utils.sound_device import SoundDevice

logger = logging.getLogger("tac.app_sound_device")


class SoundDeviceApp():
	def __init__(self) -> None:
		parser = argparse.ArgumentParser("SoundDevice")
		parser.add_argument("-D", '--device', type=str, default="default")
		parser.add_argument("-C", '--control', type=str, default=None)
		parser.add_argument("-a", '--action', type=str, default="get", choices=["get", "set"])
		parser.add_argument("-f", '--file', type=str, default=None)
		self.args = parser.parse_args()

	def go(self):
		sd = SoundDevice(self.args.control, self.args.device)
		if self.args.action == "get":
			if self.args.file is None:
				print(json.dumps(sd.get_controls_settings()))
			else:
				with open(self.args.file, 'w') as f:
					json.dump(sd.get_controls_settings(), f)
		elif self.args.action == "set":
			if self.args.file is None:
				raise Exception("no file specified")
			settings = json.load(open(self.args.file))
			sd.set_controls_settings(settings)
			logger.info("new settings are:\n%s" % json.dumps(sd.get_controls_settings()))

if __name__ == "__main__":
	init_logging()
	sda = SoundDeviceApp()
	sda.go()
