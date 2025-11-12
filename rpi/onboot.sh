#!/bin/bash

check_internet() {
		timeout=120
		start_time=$(date +%s)
		end_time=$((start_time + timeout))
		ping_success=false

		while [[ $(date +%s) -lt $end_time ]]; do
				if ping -c 1 google.com >/dev/null; then
						ping_success=true
						break
				fi
		done

		if $ping_success; then
				echo "Ping successful."
		else
				echo "Timeout reached. Continuing anyways."
		fi
}

check_internet

cd /srv/the-alarm-clock/app
git config pull.ff only

while true; do
  echo "update from git"
  git reset --hard "@{upstream}"
  git pull

  echo "git status"
  git status

  echo "\n\n\n\nLast git commit:"
  git log -1
  echo "\n\n\n\n"
  
  echo "calling rpi/run.sh"

  bash ./rpi/run.sh
done
