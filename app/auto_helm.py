import asyncio

import aioredis

import settings
from app.boat_io import BoatModel


async def auto_helm(boat_data: dict):
    b = BoatModel()
    b.power_on = 0
    last_heading = None
    if settings.redis_host:
        redis = await aioredis.create_redis_pool(settings.redis_host)
    else:
        redis = None

    while redis:
        await asyncio.sleep(.2)
        helm = await redis.hgetall("helm")

        if helm.get("turn_on"):
            b.power_on = 1
            b.rudder = 0
            await redis.hset("helm", "turn_on", 0)

        if helm.get("turn_off"):
            b.power_on = 0
            await redis.hset("helm", "turn_off", 0)

        heading = b.read_compass()  # heading is *10 deci-degrees
        boat_data["compass_cal"] = b.calibration
        boat_data["compass"] = heading/10

        await redis.hset("current_data", "compass", boat_data["compass"])

        heal = b.read_roll()
        pitch = b.read_pitch()
        boat_data["max_heal"] = max(boat_data["max_heal"], heal)
        boat_data["min_heal"] = min(boat_data["min_heal"], heal)
        boat_data["max_pitch"] = max(boat_data["max_pitch"], pitch)
        boat_data["min_pitch"] = min(boat_data["min_pitch"], pitch)

        if last_heading is None:
            last_heading = heading

        hts_str = helm.get(b'hts')
        if hts_str:
            hts = int(hts_str)
        else:
            hts = int((boat_data.get('hts', 0) + boat_data.get('mag_var', 0))*10)

        gain = 80000
        gain_str = helm.get(b'gain')
        if gain_str:
            gain = int(gain_str)

        turn_speed_factor = 20
        turn_speed_factor_str = helm.get(b'tsf')
        if turn_speed_factor_str:
            turn_speed_factor = max(int(turn_speed_factor_str), 1)

        # desired turn rate is compass error  / no of secs
        error = relative_direction(heading - hts)
        turn_rate = relative_direction(last_heading - heading)

        # Desired turn rate is 10 degrees per second ie  2 per .2s or 20 deci-degrees
        desired_rate = error / turn_speed_factor

        correction = (desired_rate - turn_rate) * gain
        # print(f'heading {heading/10}  hts {hts / 10} turn rate {turn_rate} gain {gain} ts {turn_speed_factor}'
        #      f' error {error}  desired {desired_rate} correction {correction/1000000}')

        if abs(b.rudder) > 15:
            b.power_on = 0

        b.helm(correction)
        if b.power_on != boat_data.get("autohelm"):
            boat_data["autohelm"] = b.power_on
            await redis.hset("current_data", "autohelm", boat_data["autohelm"])
        boat_data["power"] = b.applied_helm_power
        boat_data["rudder"] = int(b.rudder)
        await redis.hset("current_data", "power", boat_data["power"])
        await redis.hset("current_data", "rudder", boat_data["rudder"])
        last_heading = heading
    print("No redis connection")


def relative_direction(diff):
    if diff < -1800:
        diff += 3600
    elif diff > 1800:
        diff -= 3600
    return diff
