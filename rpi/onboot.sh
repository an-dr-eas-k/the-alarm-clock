
git config pull.ff only
cd /srv/the-alarm-clock
while true; do
	echo "installing requirements"
	pip3 install -r requirements.txt
	echo "invoking app_clock.py"
	python3 -u src/app_clock.py
	echo "update from git"
	git pull
	echo "git status"
	git status
	git log -1
done