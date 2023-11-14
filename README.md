
# Getting started
```
pip3 install -r requirements.txt
python3 src/app_clock.py
```

7 Segment Font is included from https://github.com/keshikan/DSEG/releases

# Connection Guide

e               |              |    |   |    |         |                 |
|---------------|--------------|----|---|----|---------|--------------   |
|  light        |    3V3       |  1 |   |  2 |     5V  |                 |
|  light        | GPIO02       |  3 |   |  4 |     5V  |                 |
|  light        | GPIO03       |  5 |   |  6 |    GND  |  btn1           |
|               | GPIO04       |  7 |   |  8 | GPIO14  |  btn1           |
|  light        |    GND       |  9 |   | 10 | GPIO15  |                 |
|               | GPIO17       | 11 |   | 12 | GPIO18  |                 |
|               | GPIO27       | 13 |   | 14 |    GND  |  btn2           |
|               | GPIO22       | 15 |   | 16 | GPIO23  |  btn2           |
| spi (vbat, 2) |    3V3       | 17 |   | 18 | GPIO24  | spi (dc, 14)    |
| spi (sdi, 5)  | GPIO10       | 19 |   | 20 |    GND  | spi (vss, 1)    |
|               | GPIO09       | 21 |   | 22 | GPIO25  | spi (reset, 15) |
| spi (sclk, 4) | GPIO11       | 23 |   | 24 | GPIO08  | spi (cs, 16)    |
|               |    GND       | 25 |   | 26 | GPIO07  |                 |
|               | GPIO00       | 27 |   | 28 | GPIO01  |                 |
|               | GPIO05       | 29 |   | 30 |    GND  |  btn3           |
|               | GPIO06       | 31 |   | 32 | GPIO12  |  btn3           |
|               | GPIO13       | 33 |   | 34 |    GND  |  btn4           |
|               | GPIO19       | 35 |   | 36 | GPIO16  |  btn4           |
|               | GPIO26       | 37 |   | 38 | GPIO20  |                 |
|  amp          |    GND       | 39 |   | 40 | GPIO21  |  amp            |