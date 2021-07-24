import asyncio

import aioredis

import settings
from app.boat_io import BoatModel


async def auto_helm(boat_data: dict):
    b = BoatModel()
    b.power_on = 0
    last_heading = None
    mode = 0
    old_compass_mode = 0
    old_mode = -1
    if settings.redis_host:
        redis = await aioredis.create_redis_pool(settings.redis_host)
    else:
        redis = None

    await asyncio.sleep(15)
    while redis:
        await asyncio.sleep(.2)
        b.alarm_off()
        helm = await redis.hgetall("helm")
        auto_mode = int(helm.get(b'auto_mode', "0"))
        compass_mode = int(helm.get(b'compass_mode', "1"))

        if auto_mode:
            if auto_mode == 1:
                b.power_on = 0
            else:
                b.power_on = 1
            mode = auto_mode      # set when auto_mode is >0
            b.rudder = 0
            await redis.hset("helm", "auto_mode", 0)

        heading = b.read_compass()  # heading is *10 deci-degrees
        boat_data["compass_cal"] = b.calibration
        # use HDM if available
        hdm = boat_data.get('HDM', None)

        if hdm is not None:
            hdm10 = int(hdm * 10)
            boat_data["head_diff"] = relative_direction(heading - hdm10)
            if compass_mode == 2:
                heading = hdm10
        else:
            compass_mode = 1

        if compass_mode != old_compass_mode:
            if compass_mode == 2:
                boat_data["compass_mode"] = "ext"
            else:
                boat_data["compass_mode"] = "int"
            b.alarm_on()
            old_compass_mode = compass_mode

        boat_data["compass"] = heading/10
        await redis.hset("current_data", "compass", boat_data["compass"])

        heal = b.read_roll()
        pitch = b.read_pitch()
        try:
            boat_data["max_heal"] = max(boat_data["max_heal"], heal)
            boat_data["min_heal"] = min(boat_data["min_heal"], heal)
            boat_data["max_pitch"] = max(boat_data["max_pitch"], pitch)
            boat_data["min_pitch"] = min(boat_data["min_pitch"], pitch)
        except Exception:
           pass

        if last_heading is None:
            last_heading = heading

        hts_str = helm.get(b'hts')

        if hts_str:
            try:
                hts = int(hts_str)
            except ValueError:
                hts = 0
        else:
            hts = int((boat_data.get('hts', 0) + boat_data.get('mag_var', 0))*10)

        gain = 8000
        gain_str = helm.get(b'gain')
        if gain_str:
            gain = 1 + int(gain_str)

        turn_speed_factor = 250
        turn_speed_factor_str = helm.get(b'tsf')
        if turn_speed_factor_str:
            turn_speed_factor = 1 + int(turn_speed_factor_str)

        error_correct = relative_direction(hts - heading)
        turn_rate = relative_direction(heading - last_heading)

        # desired turn rate is compass error  / no of secs
        # Desired turn rate is 10 degrees per second ie  2 per .2s or 20 deci-degrees

        correction = int((error_correct - turn_rate * turn_speed_factor/100) * gain)

        # print(f"{desired_rate } {turn_rate}")

        # if abs(b.rudder) > 10:
        #    if correction > 0 > b.rudder or correction < 0 < b.rudder and mode == 9:
        #        b.power_on = 1
        #        mode = 2
        #    elif mode == 2:
        #        b.power_on = 0
        #        mode = 9
        if mode == 2:
            b.helm(correction)
        elif mode == 3:
            drive = int(helm.get(b'drive', 0)) * 10000
            b.helm(drive)

        if mode != old_mode:
            if mode == 2:
                boat_data["auto_helm"] = "auto"
            elif mode == 3:
                boat_data["auto_helm"] = "manual"
            else:
                boat_data["auto_helm"] = "stand-by"
            b.alarm_on()
            old_mode = mode

        boat_data["gain"] = gain
        boat_data["tsf"] = turn_speed_factor
        boat_data["power"] = b.applied_helm_power
        boat_data["rudder"] = int(b.rudder)
        last_heading = heading
    print("No redis connection")


def relative_direction(diff):
    if diff < -1800:
        diff += 3600
    elif diff > 1800:
        diff -= 3600
    return diff
