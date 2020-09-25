#!/usr/bin/env python3.7
import asyncio
import aioserial
import pyudev
from app.nmea_0183 import nmea_reader
from aiofile import AIOFile
from time import monotonic
from app.auto_helm import auto_helm
import json
import asyncio_dgram

import aioredis


def del_items(adict, delete_list):
    for item in delete_list:
        if adict.get(item):
            del(adict[item])


async def log(boat_data: dict, q: asyncio.Queue, ip, port):
    stream = None
    while True:
        boat_data["max_heal"] = -90
        boat_data["min_heal"] = 90
        boat_data["max_pitch"] = -90
        boat_data["min_pitch"] = 90
        del_items(boat_data, ["DBT", "TOFF", "STW"])
        await asyncio.sleep(5)

        line = "".join([json.dumps(boat_data), ",\n"])
        async with AIOFile("./logs/log.txt", 'a+') as afp:
            await afp.write(line)
            await afp.fsync()
        try:
            if not stream:
                stream = await asyncio_dgram.connect((ip, port))
            if stream:
                await stream.send(line.encode(errors='ignore'))
        except ConnectionError as err:
            print(f"Failed to connect to data processor error: {err}")
            stream = None


class SentenceMux:

    def __init__(self, name: str,  q_items: dict) -> None:
        """
        SentenceMux is typically used to send NMEA sentences to different Queues
        A dictionary of named queues is given when creating the task.
        A call to put will send a sentence to all the queues unless it has been disabled
        using the key name.
        :param name: Name of mux
        :param q_items: An array of Queues
        """
        self.name = name
        self.q_items = q_items
        self.disabled_list = []

    def disable(self, named_q: str) -> None:
        print(f"disable {named_q} in {self.name}")
        if named_q in self.disabled_list:
            self.disabled_list.append(named_q)

    def enable(self, named_q: str) -> None:
        print(f"enable {named_q} in {self.name}")
        if named_q in self.disabled_list:
            self.disabled_list.remove(named_q)

    async def put(self, line: bytearray) -> None:
        """
        Puts the byte array to the all the enabled queues defined on instantiation
        This method an be used as a NMEA reader call back
        :param line:

        """
        for q_name, q in self.q_items.items():
            if q_name not in self.disabled_list:
                await q.put(line)


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


async def process_udp_queue(q: asyncio.Queue, ip: str, port: int, mux_list: list = None):
    """
    Processes a queue sending each line to a UDP sever such as OpenCPN
    set up with ip address 0.0.0.0 and same port. This is fully async
    a non async udp would work with just:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
    sock.sendto(line, (ip, port))
    :param q:
    :param ip:  Ip of UDP server which receives the message
    :param port: Port used at both ends gg 8011
    :param mux_list: List of SentenceMux objects which contain "to_udp" Queue
    """
    while True:
        if mux_list:
            for mux in mux_list:
                mux.enable("to_udp")
        try:
            stream = await asyncio_dgram.connect((ip, port))
            while True:
                line: bytes = await q.get()
                q.task_done()
                await stream.send(line)
        except ConnectionError as err:
            print(f"Failed to connect to OpenCPN error: {err}")
            if mux_list:
                for mux in mux_list:
                    mux.disable("to_udp")

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
    q_to_2000 = asyncio.Queue()   # All from NMEA0183 Network so don't send back sentences from NMEA 2000
    q_from_2000 = asyncio.Queue()  # All sentences from NMEA2000 Network translated to NMEA0183 by Actisense Gateway
    q_udp = asyncio.Queue()   # Everything we need to send via UDP - typically OpenCPN might read this
    from_2000_mux = SentenceMux("from_200", {"from_2000": q_from_2000, "to_udp": q_udp})
    to_2000_mux = SentenceMux("to_2000", {"to_2000": q_to_2000, "to_udp": q_udp})

    producers = [
        asyncio.create_task(auto_helm(boat_data, q_to_2000)),
        asyncio.create_task(log(boat_data, q_to_2000, "192.168.1.88", 8012)),
        asyncio.create_task(process_udp_queue(q_udp, "192.168.1.88", 8011, [from_2000_mux, to_2000_mux])),
    ]   # producers write to queues to pass and multiplex nmea sentences to consumers

    open_serial(attached_devs, 'gps_dongle', 'blue_next_gps_dongle', 9600, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_00', 'compass', 4800, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_01', 'nmea_2000_bridge', 38400, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_02', 'combined_log_depth', 4800, serial_devices)
    open_serial(attached_devs, 'ftdi_multi_03', 'ais', 38400, serial_devices)
    open_serial(attached_devs, 'prolific_usb_serial', 'position', 4800, serial_devices)

    for device_name, serial_obj in serial_devices.items():
        if device_name == 'ais':
            producers.append(asyncio.create_task(read_to_queue(serial_obj, q_to_2000, q_udp)))
        if device_name == 'nmea_2000_bridge':
            producers.append(asyncio.create_task(nmea_reader(serial_obj, boat_data, from_2000_mux.put)))
        else:
            producers.append(asyncio.create_task(nmea_reader(serial_obj, boat_data, to_2000_mux.put)))

    if serial_devices.get('nmea_2000_bridge'):
        consumers.append(asyncio.create_task(process_queue(q_to_2000, serial_devices['nmea_2000_bridge'])))

    if serial_devices.get('position'):
        consumers.append(asyncio.create_task(process_queue(q_from_2000, serial_devices['position'])))

    await asyncio.gather(*producers)

    await q_from_2000.join()  # Implicitly awaits consumers, too
    await q_to_2000.join()
    cancel_consumers(consumers)


def cancel_consumers(consumer_list):
    print("Cancel consumers")
    for c in consumer_list:
        c.cancel()


if __name__ == "__main__":
    q_readers = []  # consumers read queues to process/relay receive multiplexed nmea sentences
    try:
        asyncio.run(main(q_readers))
    except (KeyboardInterrupt, BaseException) as e:
        print(e)
        cancel_consumers(q_readers)
