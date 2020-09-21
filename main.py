#!/usr/bin/env python3.7
import asyncio
import aioserial
import pyudev
import datetime
from aiofile import AIOFile
from time import monotonic
from app.boat_io import BoatModel
import json
import asyncio_dgram
import arrow


def loop(x):
    if x >= 100:
        return x - 100
    elif x < 0:
        return 100 + x
    else:
        return x


def relative_direction(diff):
    if diff < -1800:
        diff += 3600
    elif diff > 1800:
        diff -= 3600
    return diff


async def log(boat_data: dict, q: asyncio.Queue):
    while True:
        await asyncio.sleep(10)
        async with AIOFile("./logs/log.txt", 'a+') as afp:
            line = "".join([json.dumps(boat_data),",\n"])
            print(line)
            await afp.write(line)
            await afp.fsync()

        print(boat_data)


async def autohelm(boat_data: dict, q: asyncio.Queue):
    b = BoatModel()
    items = {}
    c = 0
    cts = 0
    last_heading = None
    while True:
        await asyncio.sleep(.2)
        heading = b.read_compass()
        if last_heading is None:
            last_heading = heading
        items[c] = heading
        if not (c % 100):
            total = 0
            # Every 100 *.2  ie 20s set desired heading
            for x in range(0, 100):
                cx = c - x
                val = items.get(loop(cx), 0)

                if val > 1800:
                    val -= 3600
                total += val

            cts = total / 100
            if cts < 0:
                cts += 3600

            print(f'***************  course to steer {cts/10}')

        c = loop(c + 1)
        # desired turn rate is compass error  / no of secs
        error = relative_direction(heading - cts)
        turn_rate = relative_direction(heading - last_heading) * 3
        correction = (turn_rate + error) * 50
        print(f'heading {heading/10}  cts {cts / 10}  correction {correction}')
        b.helm(correction)
        last_heading = heading


def sign_nmea(symbol, types):
    if types.get(symbol):
        return types[symbol]
    else:
        return 0


def get_micro_secs(real_str: str) -> int:
    """
    If there is a decimal point returns fractional part as an integer
    based on 10 to minus 6 ie if seconds returns microseconds
    :param real_str:  A string with optional fraction
    :return: decimal par as integer based on micro units eg microseconds
    """
    try:
        p1, p2 = real_str.split(".")
    except ValueError:
        return 0
    if p2:
        p2 = f"{p2:0<6}"
        return int(p2)
    return 0


def get_nmea_field_value(value_fields, format_def):
    value = None
    func_map = {
        "hhmmss.ss": lambda value_list: datetime.time(
            hour=int(value_list[0][0:2]), minute=int(value_list[0][2:4]), second=int(value_list[0][4:6]),
            microsecond=get_micro_secs(value_list[0])).isoformat(),
        "yyyyy.yyyy,a": lambda value_list: ((float(value_list[0][0:3]) + float(value_list[0][3:])/60.0)
                                            * sign_nmea(value_list[1], {'E': 1, 'W': -1})),
        "llll.llll,a": lambda value_list: ((float(value_list[0][0:2]) + float(value_list[0][2:])/60.0)
                                            * sign_nmea(value_list[1], {'N': 1, 'S': -1})),
        "x.x": lambda value_list: float(value_list[0]),
        "ddmmyy": lambda value_list: datetime.date(
            day=int(value_list[0][0:2]), month=int(value_list[0][2:4]), year=int(value_list[0][4:])+2000).isoformat(),
        "A": lambda value_list: value_list[0],
        "x.x,a": lambda value_list: float(value_list[0]) * sign_nmea(value_list[1], {'E': 1, 'W': -1}),
        "x": lambda value_list: int(value_list[0]),
        "hhmmss.ss,dd,dd,yyyy,tz_h,tz_m": lambda value_list:  arrow.Arrow(
            int(value_list[3]), int(value_list[2]), int(value_list[1]),
            int(value_list[0][0:2]), int(value_list[0][2:4]), int(value_list[0][4:6]),
            get_micro_secs(value_list[0]),
            f"{int(value_list[4]):+}:{value_list[5]:0>2}"
        ).isoformat(),
        "x.x,R": lambda value_list: float(value_list[0]) * sign_nmea(value_list[1], {'R': 1, 'L': -1}),
        "s": lambda value_list: value_list[0],
        "x.x,T": lambda value_list: value_list[0],   # To do convert to true  if 2nd field is magnetic ie M

    }
    func = func_map.get(format_def[1])
    if func:
        missing = False
        for v in value_fields:
            if not v:
                missing = True
        if missing:
            value = None
        else:
            value = func(value_fields)

    return value


def get_sentence_data(sentence: str, var_names: list) -> dict:
    """
    Gets a dict of extracted from the NMEA 0183 sentence as defined by var_names
    :param sentence - received NMEA 0183 sentence or line read
    :param var_names - list of variables to extract in processing order
    :return: variables and values extracted
    """

    def_vars = {
        "time": (1, "hhmmss.ss"),       # time of fix
        "status": (1, "A"),             # status of fix A = ok V = fail
        "lat": (2, "llll.llll,a"),      # lat float N positive
        "long": (2, "yyyyy.yyyy,a"),    # long float E positive
        "SOG": (1, "x.x"),              # Speed Over Ground  float knots
        "TMG": (1, "x.x"),              # Track Made Good
        "date": (1, "ddmmyy"),          # Date of fix may not be valid with some GPS
        "mag_var": (2, "x.x,a"),        # Mag Var E positive
        "datetime": (6, "hhmmss.ss,dd,dd,yyyy,tz_h,tz_m"),  # Datetime from ZDA if available
        "XTE": (2, "x.x,R"),             # Cross Track Error R is positive
        "XTE_units": (1, "A"),           # Units for XTE - N = Nm
        "ACir": (1, "A"),                # In arrival circle  V = not arrived A= True
        "APer": (1, "A"),                # Passing wpt perpendicular  V = not arrived A= True
        "BOD": (2, "x.x,T"),             # Bearing to Destination T = true M = Mag
        "Did": (1, "s"),                 # Destination id
        "HTS": (2, "x.x,T"),              # Heading to Steer  T = true M = Mag
    }
    sentence_data = {}
    fields = sentence[7:].split(",")
    for var_name in var_names:
        field_values = []             # more than one Nmea data field may be used to make a data variable (var_name)
        x = def_vars[var_name][0]
        while x > 0 and fields:
            field_values.append(fields.pop(0))
            x -= 1
        value = get_nmea_field_value(field_values, def_vars[var_name])
        if value:
            sentence_data[var_name] = value

    return sentence_data


def nmea_decoder(sentence: str, data: dict):
    """
    Decodes a received NMEA 0183 sentence into variables and adds them to current data store
    :param sentence:
    :param data:
    :return:
    """

    sentences = {
        "RMC": ["time", "status", "lat", "long", "SOG", "TMG", "date", "mag_var"],
        "ZDA": ["datetime"],
        "APB": ["status", "", "XTE", "XTE_units", "ACir", "APer", "BOD", "Did", "HTS"],

    }
    code = ""
    try:
        if len(sentence) > 9:
            code = sentence[3:6]
            if code in sentences:
                sentence_data = get_sentence_data(sentence, sentences[code])
                if sentence_data.get('status', 'A') == 'A':
                    for n, v in sentence_data.items():
                        data[n] = v

    except (AttributeError, ValueError, ) as err:
        print(f"NMEA {code} sentence translation error: {err} when processing {sentence}")


async def nmea_reader(device_name: str, aioserial_instance: aioserial.AioSerial, boat_data: dict,
                      q_serial: asyncio.Queue, q_udp: asyncio.Queue):
    while True:
        line = await aioserial_instance.readline_async()
        line_str = line.decode(errors='ignore')
        nmea_decoder(line_str, boat_data)
        await q_serial.put(line)
        await q_udp.put(line)


async def read_to_queue(aioserial_instance: aioserial.AioSerial, q_serial: asyncio.Queue, q_udp: asyncio.Queue):
    while True:
        line = await aioserial_instance.readline_async()
        await q_serial.put(line)
        await q_udp.put(line)


async def process_queue(q: asyncio.Queue, combined_nmea_out: aioserial.AioSerial):
    while True:
        line: bytes = await q.get()
        q.task_done()
        s = monotonic()
        number_of_byte: int = await combined_nmea_out.write_async(line)
        # print(monotonic()-s)
        line_str = line.decode(errors='ignore')
        # if line_str[:6] == "$GPGGA": print("**** found it ****")
        # print(line_str, end='', flush=True)
        # print(monotonic() - s)


async def process_udp_queue(q: asyncio.Queue, ip: str, port: int):
    """
    Processes a queue sending each line to a UDP sever such as OpenCPN
    set up with ip address 0.0.0.0 and same port. This is fully async
    non async udp would work with just:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
    sock.sendto(line, (ip, port))
    :param q:
    :param ip:  Ip of UDP server which receives the message
    :param port: Port used at both ends gg 8011
    """
    while True:
        try:
            stream = await asyncio_dgram.connect((ip, port))
            while True:
                line: bytes = await q.get()
                q.task_done()
                await stream.send(line)
        except ConnectionError as err:
            print(f"Failed to connect to OpenCPN error: {err}")
            await asyncio.sleep(20)


def open_serial(attached_devs, port_name, device_name, baud, serial_devices):
    if attached_devs.get(port_name):
        print(f"Found {device_name} at {port_name} = {attached_devs[port_name]}")
        serial_device = aioserial.AioSerial(port=attached_devs[port_name], baudrate=baud)
        serial_devices[device_name] = serial_device


def get_usb_devices():
    attached_devs = {}
    context = pyudev.Context()
    for device in context.list_devices(subsystem='tty'):
        dev_name = device.properties['DEVNAME']
        if 'USB' in dev_name:
            if device.properties['ID_VENDOR'] == 'FTDI':
                num = device.properties.get('ID_USB_INTERFACE_NUM', '00')
                attached_devs['ftdi_multi_' + num] = dev_name
            elif device.properties['ID_VENDOR'] == 'Prolific_Technology_Inc.':
                attached_devs['prolific_usb_serial'] = dev_name
            elif device.properties['ID_VENDOR'] == 'Silicon_Labs' and device.properties['ID_MODEL_ID'] == 'ea60':
                attached_devs['gps_dongle'] = dev_name
    return attached_devs


async def main(consumers):
    attached_devs = get_usb_devices()  # attached usb devices by interface name eg
    # multi port fdi device port 0 has an interface name "ftdi_multi_00"
    boat_data = {}  # data obtained from NMEA reader
    serial_devices = {}  # opened async serial devices by device name eg compass
    q_other = asyncio.Queue()
    q_gps = asyncio.Queue()
    q_udp = asyncio.Queue()
    producers = [
        # asyncio.create_task(autohelm(boat_data, q_other)),
        asyncio.create_task(log(boat_data, q_other)),
        asyncio.create_task(process_udp_queue(q_udp, "192.168.1.88", 8011)),
    ]   # producers write to queues to pass and multiplex nmea sentences to consumers

    open_serial(attached_devs, 'gps_dongle', 'blue_next_gps_dongle', 9600, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_00', 'compass', 4800, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_01', 'nmea_2000_bridge', 38400, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_02', 'combined_log_depth', 4800, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_03', 'ais', 38400, serial_devices)
    open_serial(attached_devs, 'prolific_usb_serial', 'position', 4800, serial_devices)

    for device_name, serial_obj in serial_devices.items():
        if device_name == 'ais':
            producers.append(asyncio.create_task(read_to_queue(serial_obj, q_other, q_udp)))
        if device_name == 'nmea_2000_bridge':
            producers.append(asyncio.create_task(nmea_reader(device_name, serial_obj, boat_data, q_gps, q_udp)))
        else:
            producers.append(asyncio.create_task(nmea_reader(device_name, serial_obj, boat_data, q_other, q_udp)))

    if serial_devices.get('nmea_2000_bridge'):
        consumers.append(asyncio.create_task(process_queue(q_other, serial_devices['nmea_2000_bridge'])))

    if serial_devices.get('position'):
        consumers.append(asyncio.create_task(process_queue(q_gps, serial_devices['position'])))

    await asyncio.gather(*producers)

    await q_gps.join()  # Implicitly awaits consumers, too
    await q_other.join()
    cancel_consumers(consumers)


def cancel_consumers(consumer_list):
    print("Cancel consumers")
    for c in consumer_list:
        c.cancel()


if __name__ == "__main__":
    consumers = []  # consumers read queues to pass receive multiplexed nmea sentences
    try:
        asyncio.run(main(consumers))
    except (KeyboardInterrupt, BaseException) as e:
        print(e)
        cancel_consumers(consumers)
