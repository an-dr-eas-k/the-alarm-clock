from http.client import HTTPResponse
import json
import logging
import ssl
import traceback
from urllib.request import Request, urlopen

from utils.os import is_ping_successful

logger = logging.getLogger("tac.network")


def is_internet_available():
    return is_ping_successful("8.8.8.8")


def json_api(url, headers={"Content-Type": "application/json"}, data_bytes=None):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        request = Request(url, headers=headers, data=data_bytes)
        response: HTTPResponse = urlopen(request, context=ctx)
        return_code = response.getcode()
    except:
        logger.error("Error calling url %s. %s", url, traceback.format_exc())
        return False

    if return_code != 200:
        logger.error(
            "Error calling url %s. status code: %s, response: %s",
            url,
            return_code,
            response.read(),
        )
        return False

    if response.readable():
        response_bytes = response.read()
        if response_bytes:
            return json.loads(response_bytes)

    return True
