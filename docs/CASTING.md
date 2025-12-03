# Google Cast Support

This project includes support for the Open Screen Protocol (Google Cast) via the [Open Screen](https://chromium.googlesource.com/openscreen/) library.

## Setup

The Open Screen library is a C++ project that must be compiled for your target architecture (Raspberry Pi). The source code is located in `vendor/openscreen`.

To build the `cast_receiver` executable, run the provided setup script on your Raspberry Pi:

```bash
./rpi/setup_openscreen.sh
```

**Warning:** This build process requires:
- Significant disk space (for Chromium build tools and dependencies).
- Time (compiling C++ on a Pi can be slow).
- Internet access (to fetch dependencies).

## Usage

Once built, the `cast_receiver` executable will be located at `vendor/openscreen/out/Default/cast_receiver`.

The Alarm Clock application (`src/app_clock.py`) automatically detects this executable and starts it in the background.

- The receiver advertises itself on the network.
- You should be able to cast to it from Chrome or Android devices.
- Note: This is a development implementation (`-d` flag is used for developer certificates), so you might see warnings or need to accept untrusted certificates depending on the sender.

## Troubleshooting

- Check the application logs for `[CastReceiver]` entries to see output from the cast process.
- If the executable is missing, the service will log a warning and continue without casting support.
