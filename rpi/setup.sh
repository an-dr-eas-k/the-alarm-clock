apt-get -y update
apt-get -y install git python3 vlc python3-pip curl 
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
ln -s /usr/bin/python3 /usr/bin/python
mkdir -p /srv/the-alarm-clock
chown $UID:$UID /srv/the-alarm-clock

if [ -z "$( grep the-alarm-clock /etc/rc.local )" ]; then
	sed -i '/exit/d' /etc/rc.local
	cat >> /etc/rc.local << "EOF"
bash /srv/the-alarm-clock/rpi/onboot.sh 2> /var/log/the-alarm-clock.errout > /var/log/the-alarm-clock.stdout &
exit 0
EOF

fi


	cat >> /etc/logrotate.d/the-alarm-clock << "EOF"
/var/log/the-alarm-clock.errout
/var/log/the-alarm-clock.stdout
{
	rotate 10
	size 1M
	compress
}
EOF