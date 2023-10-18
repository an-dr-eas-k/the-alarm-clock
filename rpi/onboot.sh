
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