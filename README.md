
# Getting started
```
curl https://raw.githubusercontent.com/an-dr-eas-k/the-alarm-clock/main/rpi/setup.sh |bash
python3 src/app_clock.py
```

7 Segment Font is included from https://github.com/keshikan/DSEG/releases \
weather symbols are included from https://github.com/erikflowers/weather-icons


# Box

## Simple



# Connection Guide

|         |||||||||
|---------|---------------|--------------|----|---|----|---------|-----------------|---------|
| red     |  vcc          |    3V3       |  1 |   |  2 |     5V  |  i2s            |     red |
| orange  |  i2c (sda)    | GPIO02       |  3 |   |  4 |     5V  |  amp ( +5V, 6)  |    blue |
| yellow  |  i2c (scl)    | GPIO03       |  5 |   |  6 |    GND  |  amp ( GND, 7)  |   white |
|         |               | GPIO04       |  7 |   |  8 | GPIO14  |  amp (  SW, 5)  |  yellow |
| brown   |  gnd          |    GND       |  9 |   | 10 | GPIO15  |                 |         |
|         |               | GPIO17       | 11 |   | 12 | GPIO18  |  i2s   (bclk)   |  purple |
|         |               | GPIO27       | 13 |   | 14 |    GND  |                 |         |
|         | mute (future) | GPIO22       | 15 |   | 16 | GPIO23  |                 |         |
| red     | spi (vbat, 2) |    3V3       | 17 |   | 18 | GPIO24  | spi (   dc, 14) |   gray  |
| white   | spi ( sdi, 5) | GPIO10       | 19 |   | 20 |    GND  | spi (  vss,  1) |  black  |
|         |               | GPIO09       | 21 |   | 22 | GPIO25  | spi (reset, 15) |   pink  |
| brown   | spi (sclk, 4) | GPIO11       | 23 |   | 24 | GPIO08  | spi (   cs, 16) |   blue  |
|         |               |    GND       | 25 |   | 26 | GPIO07  |                 |         |
| orange  | btn1          | GPIO00       | 27 |   | 28 | GPIO01  |                 |         |
| yellow  | btn2          | GPIO05       | 29 |   | 30 |    GND  |                 |         |
| green   | btn3          | GPIO06       | 31 |   | 32 | GPIO12  |                 |         |
| blue    | btn4          | GPIO13       | 33 |   | 34 |    GND  |                 |         |
| green   | i2s  (lrclk)  | GPIO19       | 35 |   | 36 | GPIO16  |                 |         |
|         |               | GPIO26       | 37 |   | 38 | GPIO20  |  i2s (future)   |         |
|         |               |    GND       | 39 |   | 40 | GPIO21  |  i2s    (din)   |  blue   |