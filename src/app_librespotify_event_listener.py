import argparse
import sys
import logging
import os
import json
from resources.resources import init_logging, librespotify_env_vars
from utils.network import json_api

# logger = logging.getLogger("librespot_ev")

class LibreSpotifyEventListenerApp:

	alarm_clock_protocol = "http"
	alarm_clock_hostname = "localhost"
	alarm_clock_port = 80
	alarm_clock_route = "/api/librespotify"

	def __init__(self) -> None:
		parser = argparse.ArgumentParser(__name__)
		parser.add_argument("-s", '--software', action='store_true')
		self.args = parser.parse_args()

	def go(self):
		if self.args.software:
			self.alarm_clock_port = 8080

		envs = self.get_environment_variables()
		spotify_environment = {key.lower(): value for key, value in envs.items() if key in librespotify_env_vars}

		is_success = self.post_spotify_data(spotify_environment)
		if not is_success:
			# logger.warning("failed to send data to alarm clock")
			sys.exit(1)
		# logger.info(f"sent following data: {json.dumps(spotify_environment)}")

	def post_spotify_data(self, data_dict: dict[str, str]) -> int:
		url = f"{self.alarm_clock_protocol}://{self.alarm_clock_hostname}:{self.alarm_clock_port}/{self.alarm_clock_route.strip('/')}"
		headers = {'Content-Type': 'application/json'}
		data_bytes = json.dumps(data_dict).encode('utf-8')
		return bool(json_api(url, headers, data_bytes))


	def get_environment_variables(self) -> dict[str, str]:
		return os.environ.copy()

if __name__ == '__main__':
	init_logging()
	# logger.debug("event occured")
	logging.info("event occured")
	LibreSpotifyEventListenerApp().go()