#!/bin/bash

# 1. Update from git (replaces onboot.sh logic)
echo "Updating repository..."
git config pull.ff only || true
git reset --hard @{upstream} || true
git pull || true
echo "!"
echo "!"
git log -1 
echo "!"
echo "!"

# 2. Install requirements (integrates run.sh logic)
# Check if requirements.txt was modified in the last 2 hours (120 min)
# This handles the case where git pull updated it.
if [ $(find requirements.txt -mmin -120) ]; then
  echo "requirements.txt changed, installing requirements..."
  sudo apt-get update || true
  echo "Installing system packages via apt..."
  # Clean requirements, remove comments, remove empty lines, remove inline comments
  grep -v '^#' requirements.txt | sed 's/#.*//' | sed 's/[[:space:]]*$//' | grep -v '^$' | sed 's/pillow/pil/' | while read -r pkg; do
    sudo apt-get install -y "python3-$pkg" || echo "python3-$pkg not found, skipping apt..."
  done

  echo "Ensuring remaining requirements via pip..."
  pip3 install --break-system-packages -r requirements.txt || true
  pip3 uninstall -y --break-system-packages RPi.GPIO || true
fi

# 3. Setup sound (integrates run.sh logic)
echo "Restoring audio settings..."
alsactl --no-ucm --file rpi/resources/asound.state restore || true
python3 src/app_sound_device.py -D equal -a set -f rpi/resources/equalizer.conf > /dev/null || true
