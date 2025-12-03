#!/bin/bash
set -e

# This script attempts to build the Open Screen cast_receiver on a Raspberry Pi (or Linux).
# It requires a significant amount of disk space and time.

PROJECT_ROOT=$(pwd)
VENDOR_DIR="$PROJECT_ROOT/vendor/openscreen"

if [ ! -d "$VENDOR_DIR" ]; then
    echo "Error: vendor/openscreen directory not found. Please run this script from the project root."
    exit 1
fi

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    python3 \
    curl \
    git \
    libsdl2-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswresample-dev \
    ninja-build

# Check if gn is installed, if not try to install it
if ! command -v gn &> /dev/null; then
    echo "gn not found. Installing gn..."
    sudo apt-get install -y gn || echo "Could not install gn via apt. You might need to install it manually."
fi

# Setup depot_tools if not present
if [ ! -d "$PROJECT_ROOT/vendor/depot_tools" ]; then
    echo "Cloning depot_tools..."
    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git "$PROJECT_ROOT/vendor/depot_tools"
fi

export PATH="$PROJECT_ROOT/vendor/depot_tools:$PATH"

cd "$VENDOR_DIR"

echo "Syncing dependencies with gclient (this may take a while)..."
# We need a .gclient file for gclient sync to work
if [ ! -f ".gclient" ]; then
    cat <<EOF > .gclient
solutions = [
  {
    "name": ".",
    "url": "https://chromium.googlesource.com/openscreen.git",
    "deps_file": "DEPS",
    "managed": False,
    "custom_deps": {},
  },
]
EOF
fi

gclient sync

echo "Generating build files..."
# We enable ffmpeg and libsdl2 for the standalone receiver
gn gen out/Default --args="have_ffmpeg=true have_libsdl2=true is_debug=false"

echo "Building cast_receiver..."
ninja -C out/Default cast_receiver

echo "Build complete!"
echo "Executable should be at: $VENDOR_DIR/out/Default/cast_receiver"
