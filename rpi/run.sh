#!/bin/bash
echo "update from git"
git reset --hard "@{upstream}"
git pull

echo "git status"
git status
git log -1

echo "installing requirements"
pip3 install --break-system-packages -r requirements.txt

echo "restore asound state"
alsactl --no-ucm --file rpi/resources/asound.state restore

python -u src/app_sound_device.py -D equal -a set -f rpi/resources/equalizer.conf

echo "invoking app_clock.py"
python -u src/app_clock.py
