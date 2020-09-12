#!/usr/bin/env python3.7
import asyncio
import aioserial
import concurrent.futures
import queue
from app.boat_io import BoatModel


def loop(x):
    if x >= 30:
        return x - 30
    elif x < 0:
        return 30 + x
    else:
        return x


def relative_direction(diff):
    if diff < -1800:
        diff += 3600
    elif diff > 1800:
        diff -= 3600
    return diff


async def main():
    b = BoatModel()
    items = {}
    motor_drive = 0
    c = 0
    while True:
        items[c] = b.read_compass()
        await asyncio.sleep(.2)
        if not (c % 5):
            # Every 5 *.2  ie 1s interval
            diff = 0
            for x in range(0, 5):
                cx = c - x
                o = items.get(loop(cx), 0)
                diff += relative_direction(o - items.get(loop(cx - 5), o))

            print(f'{diff}, {b.helm_power}, {b.applied_helm_power}')
            b.helm(diff * 5000)

        c = loop(c + 1)


async def readline_and_put_to_queue(aioserial_instance: aioserial.AioSerial, q: queue.Queue):
    while True:
        q.put(await aioserial_instance.readline_async())


async def process_queue(q: queue.Queue):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            line: bytes = await asyncio.get_running_loop().run_in_executor(executor, q.get)
            print(line.decode(errors='ignore'), end='', flush=True)
            q.task_done()


async def read_and_print(aioserial_instance: aioserial.AioSerial):
    print((await aioserial_instance.read_async()).decode(errors='ignore'), end='', flush=True)

if __name__ == "__main__":
    aioserial_ttyUSB0: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB0', baudrate=9600)
    aioserial_ttyUSB1: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB1', baudrate=38400)
    aioserial_ttyUSB2: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB2', baudrate=4800)

    q: queue.Queue = queue.Queue()
    asyncio.run(asyncio.wait([
        readline_and_put_to_queue(aioserial_ttyUSB0, q),
        readline_and_put_to_queue(aioserial_ttyUSB1, q),
        process_queue(q),
        main(),
    ]))
