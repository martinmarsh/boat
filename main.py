#!/usr/bin/env python3.7
import asyncio
import aioserial
import concurrent.futures
import queue
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


async def main():
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


async def readline_and_put_to_queue(aioserial_instance: aioserial.AioSerial, q: queue.Queue):
    while True:
        q.put(await aioserial_instance.readline_async())


async def process_queue(q: queue.Queue, aioserial_instance: aioserial.AioSerial):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            line: bytes = await asyncio.get_running_loop().run_in_executor(executor, q.get)
            s = monotonic()
            number_of_byte: int = await aioserial_instance.writelines_async(line)
            # print(monotonic()-s)
            line_str = line.decode(errors='ignore')
            # if line_str[:6] == "$GPGGA": rint("**** found it ****")
            print(line_str, end='', flush=True)
            q.task_done()
            # print(monotonic() - s)


async def read_and_print(aioserial_instance: aioserial.AioSerial):
    print((await aioserial_instance.read_async()).decode(errors='ignore'), end='', flush=True)

if __name__ == "__main__":
    blue_next_dongle = NMEA_2000_conv = combined = compass = ais = None
    blue_next_dongle: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB0', baudrate=9600)
    NMEA_2000_conv: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB1', baudrate=38400)
    # combined: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB2', baudrate=4800)
    # compass: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB3', baudrate=4800)
    # ais: aioserial.AioSerial = aioserial.AioSerial(port='/dev/ttyUSB3', baudrate=38400)

    q: queue.Queue = queue.Queue()
    run_list = [
        process_queue(q, NMEA_2000_conv),
        main()
    ]

    if blue_next_dongle:
        run_list.append(readline_and_put_to_queue(blue_next_dongle, q))
    if combined:
        run_list.append(readline_and_put_to_queue(combined, q))
    if compass:
        run_list.append(readline_and_put_to_queue(compass, q))
    if ais:
        run_list.append(readline_and_put_to_queue(ais, q))

    asyncio.run(asyncio.wait(run_list))
