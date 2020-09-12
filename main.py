#!/usr/bin/env python3.7
import asyncio

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


if __name__ == "__main__":
    asyncio.run(main())
