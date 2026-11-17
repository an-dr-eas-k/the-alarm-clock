#!/bin/bash
# Install aic8800 Wifi driver if not present
# follow https://askubuntu.com/a/1553387/871941

APP_DIR="/srv/the-alarm-clock/app"
DEB_FILE="${APP_DIR}/rpi/resources/aic8800d80fdrvpackage.deb"

if [ ! -f "$DEB_FILE" ]; then
    echo "Error: $DEB_FILE not found"
    exit 1
fi

# A previous boot may have left dpkg mid-upgrade (e.g. a kernel package that
# was not yet configured when this ran); repair that first, otherwise the
# postinst build below fails and leaves dpkg broken for the rest of boot.
dpkg --configure -a || true

# A pending kernel upgrade (reboot required) means the *running* kernel has
# already been superseded, so apt no longer ships headers for it and any
# attempt to build the module against $(uname -r) is doomed until reboot.
if [ -f /var/run/reboot-required ]; then
    echo "Reboot required (pending kernel upgrade), skipping aic8800 driver install until after reboot."
    exit 0
fi

# The package's postinst builds the kernel module against
# /lib/modules/$(uname -r)/build, so headers for the *running* kernel must
# exist first (they may be missing right after a kernel upgrade that hasn't
# been booted into yet).
KERNEL_BUILD_DIR="/lib/modules/$(uname -r)/build"
if [ ! -d "$KERNEL_BUILD_DIR" ]; then
    echo "$KERNEL_BUILD_DIR not found, installing headers for $(uname -r)..."
    apt-get install -y "raspberrypi-kernel-headers" || apt-get install -y "linux-headers-$(uname -r)" || true
fi

if [ ! -d "$KERNEL_BUILD_DIR" ]; then
    echo "Kernel headers for $(uname -r) still unavailable (kernel likely superseded), skipping aic8800 driver install for now (will retry next boot)."
    exit 0
fi

PACKAGE_NAME=$(dpkg-deb -f "$DEB_FILE" Package)

# Check if package is installed or if the module is missing for the current kernel
SHOULD_INSTALL=false
if ! dpkg -s "$PACKAGE_NAME" >/dev/null 2>&1; then
    echo "Package $PACKAGE_NAME is not installed."
    SHOULD_INSTALL=true
else
    # Check if the kernel module exists for the current kernel version
    if ! find "/lib/modules/$(uname -r)" -name "aic8800_fdrv.ko*" | grep -q .; then
        echo "Package $PACKAGE_NAME is installed, but aic8800_fdrv module is missing for kernel $(uname -r)."
        SHOULD_INSTALL=true
    fi
fi

if [ "$SHOULD_INSTALL" = true ]; then
    echo "Installing/Reinstalling $PACKAGE_NAME..."
    dpkg -i "$DEB_FILE" || echo "dpkg -i $PACKAGE_NAME failed, will retry next boot"
else
    echo "$PACKAGE_NAME is already installed and module found for $(uname -r)"
fi
