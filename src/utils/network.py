from http.client import HTTPResponse
import json
import logging
import subprocess
import traceback
from urllib.request import Request, urlopen

def is_ping_successful(hostname):
	result = subprocess.run(
		["ping", "-c", "1", hostname], 
		stdout=subprocess.DEVNULL, 
		stderr=subprocess.DEVNULL)
	return result.returncode == 0

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

	return json.load(response)