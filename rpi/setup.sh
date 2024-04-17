uid=1010
uhome=/srv/the-alarm-clock
app=${uhome}/app

killall -u the-alarm-clock
# install dependencies
apt-get -y update
# apt-get -y dist-upgrade
apt-get -y install git python3 vlc python3-pip curl libasound2-plugin-equal python3-dbus
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh

# update system
systemctl disable pigpiod
# systemctl disable aplay.service
raspi-config nonint do_spi 0
raspi-config nonint do_i2c 0

# add and configure the-alarm-clock user
mkdir -p $uhome
addgroup --system --gid $uid the-alarm-clock
adduser --system --home $uhome --uid $uid --gid $uid --disabled-password the-alarm-clock
adduser the-alarm-clock gpio
adduser the-alarm-clock i2c
adduser the-alarm-clock spi
adduser the-alarm-clock audio
chown $uid:$uid -R $uhome

#clone the-alarm-clock
rm -rf $app
git clone -b develop https://github.com/an-dr-eas-k/the-alarm-clock.git $app

#config sudoers
rm /etc/sudoers.d/the-alarm-clock
cat $app/rpi/resources/sudoers > /etc/sudoers.d/the-alarm-clock

# configure log rotation
ln -fs $app/rpi/resources/logrotate /etc/logrotate.d/the-alarm-clock

# setup raspotify
ln -fs $app/rpi/resources/raspotify.service /lib/systemd/system/raspotify.service
ln -fs $app/rpi/resources/asoundrc $uhome/.asoundrc
ln -fs $app/rpi/resources/raspotify.conf /etc/raspotify/conf


# setup the-alarm-clock app
ln -fs /usr/bin/python3 /usr/bin/python
setcap CAP_NET_BIND_SERVICE=+eip $(readlink /usr/bin/python -f)

if [ -z "$( grep the-alarm-clock /etc/rc.local )" ]; then
	sed -i '/exit/d' /etc/rc.local
	cat >> /etc/rc.local << "EOF"
sudo -u the-alarm-clock -- bash ${app}/rpi/onboot.sh 2>> /var/log/the-alarm-clock.errout 1>> /var/log/the-alarm-clock.stdout &
exit 0
EOF
fi
