#!/usr/bin/env python3.7
import asyncio
import aioserial
import pyudev
from time import monotonic
from app.boat_io import BoatModel


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


async def autohelm():
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


async def readline_and_put_to_queue(aioserial_instance: aioserial.AioSerial, q: asyncio.Queue):
    while True:
        line = await aioserial_instance.readline_async()
        await q.put(line)


async def process_queue(q: asyncio.Queue, aioserial_instance: aioserial.AioSerial):
    while True:
        line: bytes = await q.get()
        q.task_done()
        s = monotonic()
        number_of_byte: int = await aioserial_instance.write_async(line)
        # print(monotonic()-s)
        line_str = line.decode(errors='ignore')
        # if line_str[:6] == "$GPGGA": print("**** found it ****")
        print(line_str, end='', flush=True)
        # print(monotonic() - s)


def create_read_task(attached_devs, name, desc, baud, q,  task_list):
    serial_device = None
    if attached_devs.get(name):
        print(f"Found {desc} at {name} = {attached_devs[name]}")
        serial_device = aioserial.AioSerial(port=attached_devs[name], baudrate=baud)
        task_list.append(asyncio.create_task(readline_and_put_to_queue(serial_device, q)))
    return serial_device


async def main():
    context = pyudev.Context()
    attached_devs = {}

    for device in context.list_devices(subsystem='tty'):
        dev_name = device.properties['DEVNAME']
        if 'USB' in dev_name:
            if device.properties['ID_VENDOR'] == 'FTDI':
                num = device.properties.get('ID_USB_INTERFACE_NUM', '00')
                attached_devs['multi_'+num] = dev_name
            elif device.properties['ID_VENDOR'] == 'Prolific_Technology_Inc.':
                attached_devs['usb_serial'] = dev_name
            elif device.properties['ID_VENDOR'] == 'Silicon_Labs' and device.properties['ID_MODEL_ID'] == 'ea60':
                attached_devs['gps_dongle'] = dev_name
    print(attached_devs)
    # blue_next_dongle: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB0', baudrate=9600)
    # NMEA_2000_conv: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB1', baudrate=38400)
    # combined: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB2', baudrate=4800)
    # compass: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB0', baudrate=4800)
    # ais: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB3', baudrate=38400)

    # q: queue.Queue = queue.Queue()
    q = asyncio.Queue()

    run_list = [
        asyncio.create_task(autohelm())
    ]
    consumers = []

    create_read_task(attached_devs, 'gps_dongle', 'Blue Next GPS Dongle', 9600, q, run_list)
    create_read_task(attached_devs, 'multi_00', 'Compass', 4800, q, run_list)
    nmea_2000_conv = create_read_task(attached_devs, 'multi_01', 'NMEA 2000 conv', 38400, q, run_list)
    create_read_task(attached_devs, 'multi_02', 'Combined Log, Depth and GPS display', 4800, q, run_list)
    create_read_task(attached_devs, 'multi_03', 'AIS', 38400, q, run_list)
    create_read_task(attached_devs, 'usb_serial', 'General USB (Prolific)', 38400, q, run_list)

    if nmea_2000_conv:
        consumers.append(asyncio.create_task(process_queue(q, nmea_2000_conv)))

    await asyncio.gather(*run_list)

    await q.join()  # Implicitly awaits consumers, too
    for c in consumers:
        c.cancel()

if __name__ == "__main__":
    asyncio.run(main())