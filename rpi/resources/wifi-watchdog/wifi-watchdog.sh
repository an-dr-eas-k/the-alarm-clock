#!/bin/bash
# WiFi watchdog - monitors journalctl for DISASSOC_LOW_ACK and resets USB dongle

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESET_SCRIPT="$SCRIPT_DIR/reset-wifi-usb.sh"
COOLDOWN=300  # 5 minutes cooldown between resets
API_URL="https://localhost/api/system/wifi"

LAST_RESET=0

echo "WiFi watchdog started - monitoring for connectivity and errors"
echo "Reset script: $RESET_SCRIPT"

# Follow messages in real-time (removed -k to see wpa_supplicant logs)
journalctl -f --since "now" -o cat | grep --line-buffered "wlan.*\(DISASSOC_LOW_ACK\|Reason: 34\|reason=4\|CTRL-EVENT-CONNECTED\|CTRL-EVENT-DISCONNECTED\)" | while read -r line; do
    
    # Check for connection events
    if echo "$line" | grep -q "CTRL-EVENT-CONNECTED"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WiFi Connected"
        curl -X POST "$API_URL?status=connected" -s > /dev/null &
    fi

    if echo "$line" | grep -q "CTRL-EVENT-DISCONNECTED"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WiFi Disconnected"
        curl -X POST "$API_URL?status=disconnected" -s > /dev/null &
    fi

    # Check for errors requiring reset
    if echo "$line" | grep -q "\(DISASSOC_LOW_ACK\|Reason: 34\|reason=4\)"; then
        CURRENT_TIME=$(date +%s)
        TIME_SINCE_RESET=$((CURRENT_TIME - LAST_RESET))
        
        if [ $TIME_SINCE_RESET -gt $COOLDOWN ]; then
            echo ""
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Connection drop detected (DISASSOC_LOW_ACK or reason=4)!"
            echo "Triggering USB reset..."
            
            if [ -x "$RESET_SCRIPT" ]; then
                "$RESET_SCRIPT"
                LAST_RESET=$CURRENT_TIME
                echo "Reset complete. Next reset allowed in $COOLDOWN seconds."
            else
                echo "ERROR: Reset script not found or not executable: $RESET_SCRIPT"
            fi
        else
            REMAINING=$((COOLDOWN - TIME_SINCE_RESET))
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Error detected, but in cooldown period ($REMAINING seconds remaining)"
        fi
    fi
done
