#!/bin/bash

if [ $(find requirements.txt -mmin -720) ]; then
  echo "installing requirements"
  pip3 install --break-system-packages -r requirements.txt
fi

echo "restore asound state"
alsactl --no-ucm --file rpi/resources/asound.state restore

python -u src/app_sound_device.py -D equal -a set -f rpi/resources/equalizer.conf

echo "invoking app_clock.py"
GPIOZERO_PIN_FACTORY=pigpio python -u src/app_clock.py
# python -u src/app_clock.py
