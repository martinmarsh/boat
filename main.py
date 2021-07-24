#!/usr/bin/env python3.7
import asyncio
import contextvars
import json
import random

import aioredis
import aioserial
import asyncio_dgram
import pyudev
from aiofile import AIOFile
from time import monotonic
import settings
from app.auto_helm import auto_helm
from app.nmea_0183 import nmea_reader
from copy import copy
# declare context var
queue_dict = contextvars.ContextVar('distribution queues')
redis_connect = contextvars.ContextVar('redis connection')


def del_items(adict, delete_list):
    for item in delete_list:
        if adict.get(item):
            del(adict[item])


async def log(boat_data: dict):
    """
    logs all current boat data every minute (10 delays) and resets pitch and heal
    logs every 6s (a delay) only boat data which has changed during the last 5 seconds line has a count
    and lapse (internal time in secs since start)
    Boat data accumulates so last reading may be very old so HDM depth etc may be very old
    application must resolve this.  When reading the log only the delta records could be used
    :param boat_data:
    :return:-
    """
    async with AIOFile(f"./logs/latest.txt", 'a+') as afp:
        contents = await afp.read()
        if contents:
            current_id = int(contents) + 1
            afp.truncate()
        else:
            current_id = 1
        await afp.write(str(current_id))
        await afp.fsync()

    boat_data["max_heal"] = -90
    boat_data["min_heal"] = 90
    boat_data["max_pitch"] = -90
    boat_data["min_pitch"] = 90
    del_items(boat_data, ['error'])
    down_count = 10
    count = 0
    start_time = monotonic()
    lines = [json.dumps(boat_data)]
    while True:
        log_data = copy(boat_data)
        await asyncio.sleep(6)

        count += 1
        log_it = {"count": count, "lapse": round(monotonic()-start_time, 1)}
        for i in boat_data:
            if boat_data[i] != log_data.get(i, None):
                log_it[i] = boat_data[i]
        lines.append(json.dumps(log_it))

        down_count -= 1
        if down_count == 0:
            async with AIOFile(f"./logs/logv2_{current_id}.txt", 'a+') as afp:
                await afp.write(",\n".join(lines))
                await afp.fsync()
            lines = ["", json.dumps(boat_data)]
            down_count = 10
            boat_data["max_heal"] = -90
            boat_data["min_heal"] = 90
            boat_data["max_pitch"] = -90
            boat_data["min_pitch"] = 90
            del_items(boat_data, ['error'])
        if boat_data:
            redis = redis_connect.get()
            await redis.hmset_dict('current_data', boat_data)


class SentenceRelay:

    def __init__(self, name: str,  q_list: list) -> None:
        """
        SentenceRelay is typically used to send NMEA sentences to different Queues
        A list of named queues is given when creating the task.
        A call to put will send a sentence to all the queues unless it has been disabled
        using the key name.
        :param name: Name of mux
        :param q_list: A list of names which should match an item in global context queue_dict
        """
        self.name = name
        self.q_list = q_list
        self.disabled_list = []

    def disable(self, named_q: str) -> None:
        # print(f"disable {named_q} in {self.name}")
        if named_q in self.disabled_list:
            self.disabled_list.append(named_q)

    def enable(self, named_q: str) -> None:
        # print(f"enable {named_q} in {self.name}")
        if named_q in self.disabled_list:
            self.disabled_list.remove(named_q)

    async def put(self, line: bytes) -> None:
        """
        Puts the byte array to the all the enabled queues defined on instantiation
        This method an be used as a NMEA reader call back
        :param line:

        """
        q_dist = queue_dict.get()
        for q_name in self.q_list:
            if q_name not in self.disabled_list:
                q = q_dist.get(q_name)
                if q:
                    await q.put(line)


async def relay_serial_input(aioserial_instance: aioserial.AioSerial, relay: SentenceRelay):
    while True:
        line = await aioserial_instance.readline_async()
        await relay.put(line)


async def write_queue_to_serial(read_queue: str, combined_nmea_out: aioserial.AioSerial):
    q_dist = queue_dict.get()
    while True:
        line: bytes = await q_dist[read_queue].get()
        q_dist[read_queue].task_done()
        await combined_nmea_out.write_async(line)


async def process_udp_queue(read_queue: str, ip: str, port: int, relays_writing_udp: list = None, relays: dict = None):
    """
    Processes a queue sending each line to a UDP sever such as OpenCPN
    set up with ip address 0.0.0.0 and same port. This is fully async
    To stop the queue being written to when there is no udp consumer  a list of sentence
    muxs which input into this queue is given

    :param read_queue: Name of Queue must be defined in queue_dict context
    :param ip:  Ip of UDP server which receives the message
    :param port: Port used at both ends gg 8011
    :param relays_writing_udp: List of SentenceRelay names which contain read_queue eg "to_udp" Queue
    :param relays: dict of relays containing SentenceRelay objects
    """
    q_dist = queue_dict.get()
    while True:
        if relays_writing_udp:
            for mux in relays_writing_udp:
                relays[mux].enable(read_queue)
        try:
            stream = await asyncio_dgram.connect((ip, port))
            print("Connected to OpenCPN")
            while True:
                line: bytes = await q_dist[read_queue].get()
                q_dist[read_queue].task_done()
                await stream.send(line)
        except ConnectionError as err:
            # print(f"Failed to connect to OpenCPN error: {err}")
            if relays_writing_udp:
                for mux in relays_writing_udp:
                    relays[mux].disable(read_queue)

            await asyncio.sleep(20)


def open_serial(attached_devs, port_name, device_name, baud, serial_devices):
    if attached_devs.get(port_name):
        print(f"Opened {device_name} at {port_name} = {attached_devs[port_name]}")
        serial_device = aioserial.AioSerial(port=attached_devs[port_name], baudrate=baud)
        serial_devices[device_name] = serial_device


def find_usb_devices(device_def: dict) -> dict:
    attached_devs = {}
    context = pyudev.Context()
    for device in context.list_devices(subsystem='tty'):
        dev_name = device.properties['DEVNAME']
        if 'USB' in dev_name:
            print(f"Detected {dev_name}")
            assigned = False
            for name, props in device_def.items():
                found = True
                for prop_name, prop_value in props.items():
                    if device.properties.get(prop_name) != prop_value:
                        found = False
                        break
                if found:
                    attached_devs[name] = dev_name
                    print(f"Found {name} matches {dev_name}")
                    assigned = True
                    break
            if not assigned:
                print(f"Not Configured {dev_name} properties:")
                for dn, dp in device.properties.items():
                    print(f"    {dn}: {dp}")
    return attached_devs


async def main(consumers):

    if settings.redis_host:
        redis_conn = await aioredis.create_redis_pool(settings.redis_host)
    else:
        redis_conn = None

    redis_connect.set(redis_conn)

    # attached_devs = get_usb_devices()  # attached usb devices by interface name eg
    attached_devs = find_usb_devices(settings.usb_serial_devices)  # attached usb devices by interface name eg
    # multi port fdi device port 0 has an interface name "ftdi_multi_00"
    boat_data = {}  # data obtained from NMEA reader
    serial_devices = {}  # opened async serial devices by device name eg compas
    q_dist = {}
    for q_name in settings.distribution_queues:
        q_dist[q_name] = asyncio.Queue()
    queue_dict.set(q_dist)
    relay_objs = {}
    for r_name, relay_q_list in settings.relays.items():
        relay_objs[r_name] = SentenceRelay(r_name, relay_q_list)

    # Configure serial ports and assign a logical name to be used for reading and writing
    for serial_name, sp in settings.serial_ports.items():
        open_serial(attached_devs, serial_name, sp['name'], sp['baud'], serial_devices)

    tasks_to_run = []
    for task_def in settings.tasks:
        tn = task_def['task']
        kwargs = task_def.get('kwargs', {})
        if tn == "auto_helm":
            tasks_to_run.append(asyncio.create_task(auto_helm(boat_data)))
        elif tn == "log":
            tasks_to_run.append(asyncio.create_task(log(boat_data)))
        elif tn == "udp_sender":
            kwargs["relays"] = relay_objs
            tasks_to_run.append(asyncio.create_task(process_udp_queue(**kwargs)))
        elif tn == "nmea_reader":
            serial_obj = serial_devices.get(kwargs["read_serial"])
            if serial_obj:
                tasks_to_run.append(asyncio.create_task(
                    nmea_reader(serial_obj, boat_data, relay_objs[kwargs["relay_to"]].put)
                ))
        elif tn == "relay_serial_input":
            serial_obj = serial_devices.get(kwargs["read_serial"])
            if serial_obj:
                tasks_to_run.append(asyncio.create_task(
                    relay_serial_input(serial_obj, relay_objs[kwargs["relay_to"]])
                ))
        elif tn == "write_queue_to_serial":
            serial_obj = serial_devices.get(kwargs["write_serial"])
            if serial_obj:
                consumers.append(
                    asyncio.create_task(
                        write_queue_to_serial(kwargs["read_queue"], serial_obj))
                )

    await asyncio.gather(*tasks_to_run)

    for producer in q_dist.values():
        await producer.join()  # Implicitly awaits consumers, too

    cancel_consumers(consumers)


def cancel_consumers(consumer_list):
    print("Cancel consumers")
    for c in consumer_list:
        c.cancel()


if __name__ == "__main__":
    q_readers = []  # consumers read queues to process/relay receive multiplexed nmea sentences
    try:
        asyncio.run(main(q_readers))
    except KeyboardInterrupt as e:
        print(e)
        cancel_consumers(q_readers)
