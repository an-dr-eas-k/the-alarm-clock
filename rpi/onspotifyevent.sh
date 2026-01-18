#!/bin/bash

cd /srv/the-alarm-clock/app
python -u src/app_librespotify_event_listener.py > /dev/null

exit 0
