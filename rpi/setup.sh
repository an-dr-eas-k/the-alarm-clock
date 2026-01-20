uid=1010
uhome=/srv/the-alarm-clock
app=${uhome}/app
BRANCH="develop"
FAST_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    fast|--fast)
      FAST_MODE=true
      shift # past argument
      ;;
    -b|--branch)
      BRANCH="$2"
      shift # past argument
      shift # past value
      ;;
    *)
      BRANCH="$1"
      shift # past argument
      ;;
  esac
done

echo "killing processes"
killall -u the-alarm-clock

if [ "$FAST_MODE" = true ]; then
  echo "fast mode: skipping system update and dependency installation"
else
  echo "update system and install dependencies"
  apt-get -y update
  apt-get -y dist-upgrade
  apt-get -y install git python3 vlc python3-pip curl libasound2-plugin-equal python3-alsaaudio libasound2-dev libsystemd-dev log2ram
  
  apt-get -y remove python3-rpi.gpio
  apt-get -y install python3-rpi-lgpio 

  # curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
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
git clone -b $BRANCH https://github.com/an-dr-eas-k/the-alarm-clock.git $app
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



echo "update rpi config.txt, somehow this step did not work last time, the manual enablement of i2c with raspi-config was necessary."
cat $app/rpi/resources/rpi-boot-config.txt > /boot/firmware/config.txt

echo "config sudoers"
rm /etc/sudoers.d/the-alarm-clock
cat $app/rpi/resources/sudoers > /etc/sudoers.d/the-alarm-clock


echo "setup equalizer"
ln -fs $app/rpi/resources/asoundrc $uhome/.asoundrc


echo "setup raspotify"
chown $uid:$uid -R /etc/raspotify
ln -fs $app/rpi/resources/raspotify.service /lib/systemd/system/raspotify.service
systemctl daemon-reload
systemctl enable raspotify
ln -fs $app/rpi/resources/raspotify.conf /etc/raspotify/conf


echo "setup the-alarm-clock app"
ln -fs /usr/bin/python3 /usr/bin/python
setcap CAP_NET_BIND_SERVICE=+eip $(readlink /usr/bin/python -f)
ln -fs $app/rpi/resources/aic8800-driver.service /lib/systemd/system/aic8800-driver.service
ln -fs $app/rpi/resources/the-alarm-clock.service /lib/systemd/system/the-alarm-clock.service
# ln -fs $app/rpi/resources/the-alarm-clock-wifi-monitor.service /lib/systemd/system/the-alarm-clock-wifi-monitor.service
systemctl daemon-reload
systemctl enable aic8800-driver.service
systemctl enable the-alarm-clock.service
# systemctl enable the-alarm-clock-wifi-monitor.service



echo "done, please reboot"
