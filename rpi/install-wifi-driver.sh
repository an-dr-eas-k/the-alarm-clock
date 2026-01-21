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

# Check if package is installed or if the module is missing for the current kernel
SHOULD_INSTALL=false
if ! dpkg -s "$PACKAGE_NAME" >/dev/null 2>&1; then
    echo "Package $PACKAGE_NAME is not installed."
    SHOULD_INSTALL=true
else
    # Check if the kernel module exists for the current kernel version
    if ! find "/lib/modules/$(uname -r)" -name "aic8800_fdrv.ko*" | grep -q .; then
        echo "Package $PACKAGE_NAME is installed, but aic8800_fdrv module is missing for kernel $(uname -r)."
        SHOULD_INSTALL=true
    fi
fi

if [ "$SHOULD_INSTALL" = true ]; then
    echo "Installing/Reinstalling $PACKAGE_NAME..."
    dpkg -i "$DEB_FILE"
else
    echo "$PACKAGE_NAME is already installed and module found for $(uname -r)"
fi
