#!/bin/bash

check_internet() {
		timeout=30
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


git config pull.ff only
cd /srv/the-alarm-clock
git pull
while true; do
	echo "invoking app_clock.py"
	python3 -u src/app_clock.py
	echo "update from git"
	git pull
	echo "git status"
	git status
	git log -1
	echo "installing requirements"
	pip3 install -r requirements.txt
done