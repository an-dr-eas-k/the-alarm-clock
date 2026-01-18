#!/bin/bash
# Monitor iwd state changes via journalctl
# This avoids DBus and PyGObject dependencies

INTERFACE="wlan0"
API_URL="https://localhost/api/system/wifi"

echo "iwd monitor started (journal mode) for $INTERFACE"

# Monitor iwd logs for station state changes
journalctl -u iwd -f -o cat | grep --line-buffered "station: $INTERFACE, state:" | while read -r line; do
    if echo "$line" | grep -q "state: connected"; then
        echo "Connection detected"
        curl -k -X POST "$API_URL?status=connected" -s > /dev/null
    elif echo "$line" | grep -q "state: disconnected"; then
        echo "Disconnection detected"
        curl -k -X POST "$API_URL?status=disconnected" -s > /dev/null
    fi
done
