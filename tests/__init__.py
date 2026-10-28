"""Test package bootstrap.

Puts ``src`` on ``sys.path`` (the application uses ``src`` as import root) and
makes ``GeoLocation`` deterministic and offline: its constructor would
otherwise call a public IP-geolocation API.
"""

import logging
import os
import sys
from unittest import mock

SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

OFFLINE_IP_API_RESPONSE = {
    "city": "Munich",
    "region": "Bavaria",
    "timezone": "Europe/Berlin",
    "lat": 48.1372,
    "lon": 11.5755,
}

# Deliberately never stopped: the GeoLocation singleton may be created by any test.
mock.patch(
    "utils.geolocation.json_api", return_value=dict(OFFLINE_IP_API_RESPONSE)
).start()

# Keep expected warnings (e.g. "No handlers registered") out of the test output.
logging.getLogger("tac").addHandler(logging.NullHandler())
