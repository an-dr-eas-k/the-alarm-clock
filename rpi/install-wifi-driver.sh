#!/bin/bash
# Install aic8800 Wifi driver if not present
# follow https://askubuntu.com/a/1553387/871941

APP_DIR="/srv/the-alarm-clock/app"
DEB_FILE="${APP_DIR}/rpi/resources/aic8800d80fdrvpackage.deb"

if [ ! -f "$DEB_FILE" ]; then
    echo "Error: $DEB_FILE not found"
    exit 1
fi

PACKAGE_NAME=$(dpkg-deb -f "$DEB_FILE" Package)

if ! dpkg -s "$PACKAGE_NAME" >/dev/null 2>&1; then
    echo "Installing $PACKAGE_NAME..."
    dpkg -i "$DEB_FILE"
else
    echo "$PACKAGE_NAME is already installed"
fi
