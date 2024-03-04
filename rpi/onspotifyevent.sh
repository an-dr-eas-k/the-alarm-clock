#!/bin/bash

cd /srv/the-alarm-clock
python -u src/app_librespotify_event_listener.py \
        2>> /var/log/the-alarm-clock.spotify-event.errout \
        1>> /var/log/the-alarm-clock.spotify-event.stdout

exit 0