import asyncio

import aioredis

import settings
from app.boat_io import BoatModel


async def auto_helm(boat_data: dict):
    b = BoatModel()
    b.power_on = 0
    last_heading = None
    mode = 0
    if settings.redis_host:
        redis = await aioredis.create_redis_pool(settings.redis_host)
    else:
        redis = None

    while redis:
        await asyncio.sleep(.2)
        helm = await redis.hgetall("helm")
        auto_mode = int(helm.get(b'auto_mode', "0"))

        if auto_mode:
            if auto_mode == 1:
                b.power_on = 0
            else:
                b.power_on = 1
            mode = auto_mode      # set when auto_mode is >0

            # b.rudder = 0
            await redis.hset("helm", "auto_mode", 0)

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
            gain = 1 + int(gain_str)

        turn_speed_factor = 20
        turn_speed_factor_str = helm.get(b'tsf')
        if turn_speed_factor_str:
            turn_speed_factor = 1 + int(turn_speed_factor_str)

        error = relative_direction(heading - hts)
        turn_rate = relative_direction(last_heading - heading)

        # desired turn rate is compass error  / no of secs
        # Desired turn rate is 10 degrees per second ie  2 per .2s or 20 deci-degrees
        desired_rate = error / turn_speed_factor

        correction = (desired_rate - turn_rate) * gain

        if abs(b.rudder) > 15:
            b.power_on = 0
            mode = 0
            b.alarm_on()

        if mode == 2:
            b.helm(correction)
        elif mode == 3:
            b.helm(int(helm.get("drive", 0)) * 10000)

        if mode != boat_data.get("auto_helm"):
            boat_data["auto_helm"] = mode
            b.alarm_on()
            await redis.hset("current_data", "auto_helm", boat_data["auto_helm"])
        else:
            b.alarm_off()

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
