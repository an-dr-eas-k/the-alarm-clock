#!/bin/bash
# WiFi watchdog - monitors journalctl for DISASSOC_LOW_ACK and resets USB dongle

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESET_SCRIPT="$SCRIPT_DIR/reset-wifi-usb.sh"
COOLDOWN=300  # 5 minutes cooldown between resets

LAST_RESET=0

echo "WiFi watchdog started - monitoring for DISASSOC_LOW_ACK and reason=4 errors"
echo "Reset script: $RESET_SCRIPT"

# Follow kernel messages in real-time with optimized filtering
journalctl -k -f --since "now" -o cat | grep --line-buffered "wlan.*\(DISASSOC_LOW_ACK\|Reason: 34\|reason=4\)" | while read -r line; do
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
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] DISASSOC_LOW_ACK detected, but in cooldown period ($REMAINING seconds remaining)"
    fi
done
