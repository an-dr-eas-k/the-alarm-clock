
# Getting started
```
curl https://raw.githubusercontent.com/an-dr-eas-k/the-alarm-clock/main/rpi/setup.sh | bash -- fast
python3 src/app_clock.py
```

7 Segment Font is included from https://github.com/keshikan/DSEG/releases \
weather symbols are included from https://github.com/erikflowers/weather-icons


# Box

## Simple



# Connection Guide
## RPi GPIO

|         |||||||||
|---------|---------------|--------------|----|---|----|---------|-----------------|---------|
| orange  |  i2c (vcc)    |    3V3       |  1 |   |  2 |     5V  |                 |         |
| green   |  i2c (sda)    | GPIO02       |  3 |   |  4 |     5V  |                 |         |
| yellow  |  i2c (scl)    | GPIO03       |  5 |   |  6 |    GND  |                 |         |
| purple  |  i2c (int)    | GPIO04       |  7 |   |  8 | GPIO14  |                 |         |
|         |               |    GND       |  9 |   | 10 | GPIO15  |                 |         |
|         |               | GPIO17       | 11 |   | 12 | GPIO18  |                 |         |
|         |               | GPIO27       | 13 |   | 14 |    GND  |                 |         |
|         |               | GPIO22       | 15 |   | 16 | GPIO23  |                 |         |
| red     | spi (vbat, 2) |    3V3       | 17 |   | 18 | GPIO24  | spi (   dc, 14) |   gray  |
| white   | spi ( sdi, 5) | GPIO10       | 19 |   | 20 |    GND  | spi (  vss,  1) |  black  |
|         |               | GPIO09       | 21 |   | 22 | GPIO25  | spi (reset, 15) |   pink  |
| brown   | spi (sclk, 4) | GPIO11       | 23 |   | 24 | GPIO08  | spi (   cs, 16) |   blue  |
|         |               |    GND       | 25 |   | 26 | GPIO07  |                 |         |
|         |               | GPIO00       | 27 |   | 28 | GPIO01  |                 |         |
|         |               | GPIO05       | 29 |   | 30 |    GND  |                 |         |
|         |               | GPIO06       | 31 |   | 32 | GPIO12  |                 |         |
|         |               | GPIO13       | 33 |   | 34 |    GND  |                 |         |
|         |               | GPIO19       | 35 |   | 36 | GPIO16  |                 |         |
|         |               | GPIO26       | 37 |   | 38 | GPIO20  |                 |         |
| black   | ground term   |    GND       | 39 |   | 40 | GPIO21  |  i2s    (din)   |  blue   |

## MCP 23017

|         |||||||||
|---------|--------------|----|----------|--------|---------------|---------|----------|---------------|
|         |    A3        |    | VCC      |  blue  | BH1759        | GND     |          |               |
|         |    A2        |    | ITB *1   |        |               | ITA *1  |  purple  | rpi gpio4     |
|         |    A1        |    | B0       |  brown | rotary button | A0      |  white   | mode button   |
|         |    Reset     |    | B1       |  black | rotary 1      | A1      |  grey    | invoke button |
|         |    NC        |    | B2       |  red   | rotary 2      | A2      |          |               |
|         |    NC        |    | B3       |        |               | A3      |          |               |
| green   |    SDA       |    | B4       |        |               | A4      |          |               |
| orange  |    SCL       |    | B5       |        |               | A5      |          |               |
| purple  |    GND       |    | B6       |        |               | A6      |          |               |
| orange  |    VCC       |    | B7       |        |               | A7      |          |               |

# State Diagram

|State|1|2|3|4| Comment|
|------|-----|-----|--|--| --|
|Default|Default,<br>Volume Timer|Default,<br> Volume Timer|AlarmView|Media On, Playing|
|Volume Timer | 
|AlarmView | AlarmView,<br>Previous Alarm | AlarmView,<br>Next Alarm | Default|AlarmEdit |There is a `new Alarm` Alarm|
|AlarmEdit | AlarmEdit,<br>Previous Property|AlarmEdit,<br>Next Property|Default|PropertyEdit|There is a `save` Property|
|PropertyEdit | PropertyEdit,<br>Value Down | PropertyEdit,<br>Value Up| Default | AlarmEdit|

# Devices
## Rotary Encoder
## Light Sensor BH1750
## Port Expander 16-Bit-I/O MCP23017 
## Sound card DigiAMP+