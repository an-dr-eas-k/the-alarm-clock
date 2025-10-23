uid=1010
uhome=/srv/the-alarm-clock
app=${uhome}/app

echo "killing processes"
killall -u the-alarm-clock

if [ "${1:-}" = "fast" ]; then
  echo "fast mode: skipping system update and dependency installation"
else
  echo "update system and install dependencies"
  apt-get -y update
  apt-get -y dist-upgrade
  apt-get -y install git python3 vlc python3-pip curl libasound2-plugin-equal python3-dbus python3-alsaaudio libasound2-dev

  apt-get -y remove python3-rpi.gpio
  apt-get -y install python3-rpi-lgpio 

  # apt-get -y remove python3-rpi-lgpio 
  # apt-get -y install python3-rpi.gpio

  curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
  curl -sL -o raspotify-latest_armhf.deb https://dtcooper.github.io/raspotify/raspotify-latest_armhf.deb
  dpkg -i raspotify-latest_armhf.deb
  apt-get -y autoremove
fi

echo "add and configure the-alarm-clock user"
mkdir -p $uhome
addgroup --system --gid $uid the-alarm-clock
adduser --system --home $uhome --uid $uid --gid $uid --disabled-password the-alarm-clock
adduser the-alarm-clock gpio
adduser the-alarm-clock i2c
adduser the-alarm-clock spi
adduser the-alarm-clock audio

if [ -f "$app/src/config.json" ]; then
  echo "copy existing config.json to $uhome"
  cp -af $app/src/config.json $uhome
fi
cp -af $app/rpi/tls/cert.* $uhome

echo "clone the-alarm-clock"
rm -rf $app
git clone -b develop https://github.com/an-dr-eas-k/the-alarm-clock.git $app
chown $uid:$uid -R $uhome
chmod +x $app/rpi/*.sh

if [ -f "$uhome/cert.key" ]; then
  cp -a $uhome/cert.* $app/rpi/tls/
else
  pushd $app/rpi/tls/
  ./new-ca-and-cert.sh
  popd
  cp -a $app/rpi/tls/cert.* $uhome/
fi

if [ -f "$uhome/config.json" ]; then
  cp -a $uhome/config.json $app/src/
else
  cp -a $app/src/config_example.json $app/src/config.json
fi

echo "configure system"
ln -fs $app/rpi/resources/pigpiod.service /lib/systemd/system/pigpiod.service
systemctl daemon-reload
systemctl disable pigpiod
# systemctl disable aplay.service



echo "update config.txt"
cat $app/rpi/resources/rpi-boot-config.txt > /boot/firmware/config.txt

echo "config sudoers"
rm /etc/sudoers.d/the-alarm-clock
cat $app/rpi/resources/sudoers > /etc/sudoers.d/the-alarm-clock

echo "configure log rotation"
rm /etc/logrotate.d/the-alarm-clock
cat $app/rpi/resources/logrotate > /etc/logrotate.d/the-alarm-clock

echo "setup equalizer"
ln -fs $app/rpi/resources/asoundrc $uhome/.asoundrc



echo "setup raspotify"
chown $uid:$uid -R /etc/raspotify
ln -fs $app/rpi/resources/raspotify.service /lib/systemd/system/raspotify.service
systemctl daemon-reload
systemctl enable raspotify
ln -fs $app/rpi/resources/raspotify.conf /etc/raspotify/conf
touch /var/log/the-alarm-clock.spotify-event.stdout
touch /var/log/the-alarm-clock.spotify-event.errout
chown $uid:$uid -R /var/log/the-alarm-clock.*


echo "setup the-alarm-clock app"
ln -fs /usr/bin/python3 /usr/bin/python
setcap CAP_NET_BIND_SERVICE=+eip $(readlink /usr/bin/python -f)

if [ -z "$( grep the-alarm-clock /etc/rc.local )" ]; then
	echo "update /etc/rc.local"
	sed -i '/exit/d' /etc/rc.local
  cat >> /etc/rc.local << EOF
sudo -u the-alarm-clock -- bash -c "$app/rpi/onboot.sh 2>&1 | systemd-cat -t the-alarm-clock.app" &
exit 0
EOF
chmod +x /etc/rc.local
fi

echo "done, please reboot"
