#!/bin/bash

cd /srv/the-alarm-clock
python3 -u src/app_librespotify_event_listener.py 2> /var/log/the-alarm-clock.spotify-event.errout > /var/log/the-alarm-clock.spotfy-event.stdout