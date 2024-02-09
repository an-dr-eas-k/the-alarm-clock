import argparse
import sys
import logging
import os
import json
import traceback
from urllib.request import Request, urlopen
from http.client import HTTPResponse

class LibreSpotifyEventListenerApp:

	librespotify_variables: [] = ["PLAYER_EVENT", "TRACK_ID", "OLD_TRACK_ID", "DURATION_MS", "POSITION_MS", "VOLUME", "SINK_STATUS", "HOME"]
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
		spotify_environment = {key.lower(): value for key, value in envs.items() if key in self.librespotify_variables}
		is_success = self.post_spotify_data(spotify_environment)
		if not is_success:
			sys.exit(1)

	def post_spotify_data(self, data_dict: dict[str, str]) -> int:
		url = f"{self.alarm_clock_protocol}://{self.alarm_clock_hostname}:{self.alarm_clock_port}/{self.alarm_clock_route.strip('/')}"
		data_bytes = json.dumps(data_dict).encode('utf-8')
		headers = {'Content-Type': 'application/json'}
		request = Request(url, headers=headers, data=data_bytes)
		try:
			response: HTTPResponse = urlopen(request)
			return_code = response.getcode()
		except:
			logging.error("Error calling the alarm clock. %s", traceback.format_exc())
			return False

		if return_code != 200:
			logging.error("Error calling the alarm clock. status code: %s, response: %s", return_code, response.read())
			return False
		return True


	def get_environment_variables(self) -> dict[str, str]:
		return os.environ.copy()

if __name__ == '__main__':
	logging.info ("event occured")
	LibreSpotifyEventListenerApp().go()