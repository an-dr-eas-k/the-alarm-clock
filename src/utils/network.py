from http.client import HTTPResponse
import json
import logging
import traceback
from urllib.request import Request, urlopen

from utils.os import is_ping_successful

def is_internet_available():
	return is_ping_successful("8.8.8.8")

def json_api(url, headers = {'Content-Type': 'application/json'}, data_bytes = None):
	try:
		request = Request(url, headers=headers, data=data_bytes)
		response: HTTPResponse = urlopen(request)
		return_code = response.getcode()
	except:
		logging.error("Error calling url %s. %s", url, traceback.format_exc())
		return False

	if return_code != 200:
		logging.error("Error calling url %s. status code: %s, response: %s", url, return_code, response.read())
		return False

	if response.readable():
		response_bytes = response.read()
		if response_bytes:
			return json.loads(response_bytes)

	return True