#!/bin/bash
# Reset WiFi USB dongle by detecting wireless interface

set -e

# Find wireless interface
WLAN_IF=$(iwconfig 2>/dev/null | grep -o "^wlan[0-9]*" | head -1)
[ -z "$WLAN_IF" ] && { echo "No wireless interface found"; exit 1; }

echo "Found wireless interface: $WLAN_IF"

# Find USB device path for this interface
USB_PATH=$(readlink -f "/sys/class/net/$WLAN_IF/device" | grep -o "[0-9]\+-[0-9]\+\(\.[0-9]\+\)*$")
[ -z "$USB_PATH" ] && { echo "Could not determine USB path"; exit 1; }

echo "Resetting USB device: $USB_PATH"
echo "$USB_PATH" > /sys/bus/usb/drivers/usb/unbind
sleep 2
echo "$USB_PATH" > /sys/bus/usb/drivers/usb/bind
sleep 3

echo "Done."
