# install dependencies
apt-get -y update
apt-get -y install git python3 vlc python3-pip curl libasound2-plugin-equal
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh

# update system
systemctl disable pigpiod
systemctl disable aplay.service

# configure log rotation
	cat >> /etc/logrotate.d/the-alarm-clock << "EOF"
/var/log/the-alarm-clock.errout
/var/log/the-alarm-clock.stdout
{
	rotate 10
	size 1M
}
EOF

# add and configure the-alarm-clock user
addgroup --system --gid $uid the-alarm-clock
adduser --system --home /srv/the-alarm-clock/ --uid $uid --gid $uid --disabled-password the-alarm-clock
adduser the-alarm-clock gpio
adduser the-alarm-clock i2c
adduser the-alarm-clock spi
mkdir -p /srv/the-alarm-clock
chown $uid:$uid -R /srv/the-alarm-clock
	cat >> /etc/sudoers.d/the-alarm-clock << "EOF"
%the-alarm-clock	ALL=(ALL:ALL) NOPASSWD: /usr/sbin/shutdown, /usr/sbin/reboot
EOF

# setup raspotify

	cat >> /srv/the-alarm-clock/.asoundrc << "EOF"
cm.!default {
 type plug
 slave.pcm plugequal;
}
 
ctl.equal {
 type equal
}
 
pcm.plugequal {
 type equal
 slave.pcm "plughw:ALSA,0"
}
 
pcm.equal {
 type plug
 slave.pcm plugequal
}
EOF

	cat >> /etc/raspotify/conf << "EOF"
LIBRESPOT_ONEVENT="/srv/the-alarm-clock/rpi/onspotifyevent.sh"
EOF


# setup the-alarm-clock app
ln -s /usr/bin/python3 /usr/bin/python
setcap CAP_NET_BIND_SERVICE=+eip $(readlink /usr/bin/python -f)
uid=1010

if [ -z "$( grep the-alarm-clock /etc/rc.local )" ]; then
	sed -i '/exit/d' /etc/rc.local
	cat >> /etc/rc.local << "EOF"
sudo -u the-alarm-clock -- bash /srv/the-alarm-clock/rpi/onboot.sh 2>> /var/log/the-alarm-clock.errout 1>> /var/log/the-alarm-clock.stdout &
exit 0
EOF
fi