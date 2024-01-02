apt-get -y update
apt-get -y install git python3 vlc python3-pip curl 
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
ln -s /usr/bin/python3 /usr/bin/python
setcap CAP_NET_BIND_SERVICE=+eip $(readlink /usr/bin/python -f)
uid=1010
addgroup --system --gid $uid the-alarm-clock
adduser --system --home /srv/the-alarm-clock/ --uid $uid --gid $uid --disabled-password the-alarm-clock
adduser the-alarm-clock gpio
adduser the-alarm-clock i2c
adduser the-alarm-clock spi
mkdir -p /srv/the-alarm-clock
chown $uid:$uid -R /srv/the-alarm-clock

if [ -z "$( grep the-alarm-clock /etc/rc.local )" ]; then
	sed -i '/exit/d' /etc/rc.local
	cat >> /etc/rc.local << "EOF"
sudo -u the-alarm-clock -- bash /srv/the-alarm-clock/rpi/onboot.sh 2> /var/log/the-alarm-clock.errout > /var/log/the-alarm-clock.stdout &
exit 0
EOF

fi


	cat >> /etc/logrotate.d/the-alarm-clock << "EOF"
/var/log/the-alarm-clock.errout
/var/log/the-alarm-clock.stdout
{
	rotate 10
	size 1M
}
EOF

	cat >> /etc/sudoers.d/the-alarm-clock << "EOF"
%the-alarm-clock	ALL=(ALL:ALL) NOPASSWD: /usr/sbin/shutdown, /usr/sbin/reboot
EOF