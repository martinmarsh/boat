import asyncio
from app.boat_io import BoatModel


async def auto_helm(boat_data: dict, q: asyncio.Queue):
    b = BoatModel()
    last_heading = None
    while True:
        await asyncio.sleep(.2)
        heading = b.read_compass()  # heading is *10 deci-degrees
        boat_data["compass_cal"] = b.calibration
        boat_data["compass"] = heading/10
        heal = b.read_roll()
        pitch = b.read_pitch()

        boat_data["max_heal"] = max(boat_data["max_heal"], heal)
        boat_data["min_heal"] = min(boat_data["min_heal"], heal)
        boat_data["max_pitch"] = max(boat_data["max_pitch"], pitch)
        boat_data["min_pitch"] = min(boat_data["min_pitch"], pitch)

        if last_heading is None:
            last_heading = heading
        hts = int((boat_data.get('hts', 0) + boat_data.get('mag_var', 0))*10)

        # desired turn rate is compass error  / no of secs
        error = relative_direction(heading - hts)
        turn_rate = relative_direction(heading - last_heading)

        # Desired turn rate is 10 degrees per second ie  2 per .2s or 20 deci-degrees
        desired_rate = error / 20
        gain = 80000
        correction = (desired_rate - turn_rate) * gain
        # print(f'heading {heading/10}  hts {hts / 10} turn rate {turn_rate} '
        #       f'error {error}  desired {desired_rate} correction {correction/1000000}')
        b.helm(correction)
        last_heading = heading


def relative_direction(diff):
    if diff < -1800:
        diff += 3600
    elif diff > 1800:
        diff -= 3600
    return diff
