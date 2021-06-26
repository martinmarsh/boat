
redis_host = 'redis://localhost'   # set to done if redis is not used/required

# Identify usb ports by their device unique properties rather than for example  {'DEVNAME': '/dev/ttyUSB3'} which might
# change as ports are connected and re-connected or with each system deployment
usb_serial_devices = {
    "ftdi_multi_00": {'ID_VENDOR': 'FTDI', 'ID_USB_INTERFACE_NUM': '00'},
    "ftdi_multi_01": {'ID_VENDOR': 'FTDI', 'ID_USB_INTERFACE_NUM': '01'},
    "ftdi_multi_02": {'ID_VENDOR': 'FTDI', 'ID_USB_INTERFACE_NUM': '02'},
    "ftdi_multi_03": {'ID_VENDOR': 'FTDI', 'ID_USB_INTERFACE_NUM': '03'},
    "gps_dongle":  {'ID_VENDOR': 'Silicon_Labs'},
    "prolific_usb_serial":  {'ID_VENDOR': 'Prolific_Technology_Inc.', 'ID_MODEL_ID': '2303'},
}

# Configure serial ports and assign a logical name to be used for reading and writing
serial_ports = {
    'gps_dongle':  {"name": 'blue_next_gps_dongle', "baud": 9600},
    'ftdi_multi_00': {"name": 'compass', "baud": 4800},
    'ftdi_multi_01': {"name": 'nmea_2000_bridge', "baud": 38400},
    'ftdi_multi_02': {"name": 'combined_log_depth', "baud": 4800},
    'ftdi_multi_03': {"name": 'ais', "baud": 38400},
    'prolific_usb_serial': {"name": 'position', "baud": 4800},
}

# define queues - a queue is required so you can send to a task - a queue can only be consumed by one task
# many tasks can write to a queue.  The queue name 'q_udp' is used by udp task
distribution_queues = [
    "q_to_2000",  # All from NMEA0183 Network so don't send back sentences from NMEA 2000
    "q_from_2000",  # All sentences from NMEA2000 Network translated to NMEA0183 by Actisense Gateway
    "q_udp"  # Everything we need to send via UDP - typically OpenCPN might read this
]

# a relay allows a task to write to many queues and items can be disabled when consumer disconnects
relays = {
    "from_2000": ["q_from_2000", "q_udp"],
    "to_2000": ["q_to_2000", "q_udp"]
}

tasks = (
    {'task': "auto_helm"},
    {'task': "log"},
    {"task": "udp_sender", "kwargs": {"read_queue": "q_udp", "ip": "192.168.0.100", "port": 8011,
                                      "relays_writing_udp": ["from_2000", "to_2000"]}},
    {"task": "relay_serial_input", "kwargs": {"read_serial": 'ais', "relay_to": 'to_2000'}},
    {"task": "nmea_reader", "kwargs": {"read_serial": 'nmea_2000_bridge', "relay_to": 'from_2000'}},
    {"task": "nmea_reader", "kwargs": {"read_serial": 'compass', "relay_to": 'to_2000'}},
    {"task": "nmea_reader", "kwargs": {"read_serial": 'combined_log_depth', "relay_to": 'to_2000'}},
    {"task": "nmea_reader", "kwargs": {"read_serial": 'blue_next_gps_dongle', "relay_to": 'to_2000'}},
    {"task": "write_queue_to_serial", "kwargs": {"read_queue": "q_to_2000", "write_serial": "nmea_2000_bridge"}},
    {"task": "write_queue_to_serial", "kwargs": {"read_queue": "q_from_2000", "write_serial": "position"}},

)
