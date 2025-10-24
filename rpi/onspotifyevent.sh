#!/bin/bash

cd /srv/the-alarm-clock/app
python -u src/app_librespotify_event_listener.py 2>&1 \
| systemd-cat -t the-alarm-clock.spotify-event.service

exit 0
