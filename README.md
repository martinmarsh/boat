# boat

Asyncio based Low level boat data processing, data logger and autohelm controller.

Designed to run on a RPI model 3B with optional hardware for heading and autohelm control.

Hardware (Optional):

Raspbery Pi - required if low level IO apps are run

CMPS12 - CMPS12 - 4th generation tilt compensated compass by Robot-electronics

VNH5019 Motor Driver Carrier 12A by Pololu

If a NMEA 2000 Network is present a 2000 to 0183 Gateway is required ideally bi-directional
eg Actisense NGW-1 NMEA 2000

## Features:

1) Manages NMEA sentence distribution between NMEA0183 and 2000 (gateway hardware required).
2) AIS and NMEA0183 from NMEA0183 to NMEA2000 with sending to OpenCPN via UDP
3) NMEA decoding of defined sentences to Data for processing internally
4) Electronic Compass
5) Autopilot controlled via Redis keys
6) Write to log file every 5s - (Each line a data dict in JSON format)
7) All sentences sent via UPD (if reader connected) ideal for sending OpenCPN on another server via WiFi
8) Data optionally logged to Redis for further processing or display


## Status
* Basic function with a GPS dongle tested.
* Autohlem basic features working but testing in progress.  Sea trials to be done
* Testing in progress
* Can now modify settings to configure requirements, serial usb ports, sentence routing and tasks
