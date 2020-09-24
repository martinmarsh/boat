# boat

Asyncio based Low level boat data processing, data logger and autohelm controller.

Designed to run on a RPI model 3 with optional hardware for heading and autohelm control:

CMPS12 - CMPS12 - 4th generation tilt compensated compass by Robot-electronics
VNH5019 Motor Driver Carrier 12A by Pololu

# Features:

1) Muxes multiple NMEA0183 and 2000 (via an Actisense 2000 to 0183 gateway).
2) AIS and NMEA0183 from NMEA0183 to NMEA2000 with sending to OpenCPN via UDP
3) NMEA decoding of defined sentances to Data for processing internally
4) Electronic Compass
5) Autopilot
6) Data logging to file of all data every 5s
7) Query of data and setting of autohelm via UPD (support for Web front end data management)

# Status
Basic function with a GPS dongle tested.
Autohlem basic faetures working but testing in progress.  Sea trials to be done
Some configuation, modulalisation and plugin development required.
Testing in progress
Would need some code chnage to be made compatible to a particular use 
