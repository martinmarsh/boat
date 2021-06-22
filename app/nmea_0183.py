import datetime
from typing import Callable

import aioserial
import arrow


def sign_nmea(symbol, types):
    if types.get(symbol):
        return types[symbol]
    else:
        return 0


def get_micro_secs(real_str: str) -> int:
    """
    If there is a decimal point returns fractional part as an integer in units
    based on 10 to minus 6 ie if dealing with time; real_str is in seconds and any factional
    part is returned as an integer representing microseconds. Zero returned if no factional part
    :param real_str:  A string with optional fraction
    :return: decimal part as integer based on micro units eg microseconds
    """
    try:
        p1, p2 = real_str.split(".")
    except ValueError:
        return 0
    if p2:
        p2 = f"{p2:0<6}"
        return int(p2)
    return 0


def to_true(amount: float, flag: str, mag_var: float) -> float:
    """
    Returns True bearing or Course
    :param amount: value of direction in degrees
    :param flag: T = True M = Magnetic
    :param mag_var:  variation to correct magnetic values
    :return: True value
    """
    value = amount
    if flag == 'M':
        value = amount - mag_var
    return value


def gps_date(day, month, year):
    yr = int(year)
    if yr < 1980:
        yr += 2000
    d = arrow.get(day=int(day), month=int(month), year=yr)
    if yr < 2020:
        # correct for last roll over assuming GPS was corrected for up to 2019
        d = d.shift(weeks=1024)
    return d.date().isoformat()


def get_nmea_field_value(value_fields: list, format_def: tuple, mag_var: float) -> object:
    """
    Returns a single value (str, int, float) based on a key which selects how the fields are processed.
    Given a extracted portion of a NME0183 sentence (each comma separated field sent in a list)
    we convert the strings there into a single value and return it. Some conversions require a single
    field whilst datetime, lat and long etc require many.
    The format def is really a key to defines which lambda function we will use; see func_map. The
    key is written in a format which helps the developer to write and check the function.
    :param value_fields: list of value strings to be converted into a single value
    :param format_def: key to select the appropriate function
    :param mag_var: Magnetic Variation for conversion true to magnetic
    :return: the computed value
    """
    value = None
    func_map = {
        "hhmmss.ss": lambda value_list: datetime.time(
            hour=int(value_list[0][0:2]), minute=int(value_list[0][2:4]), second=int(value_list[0][4:6]),
            microsecond=get_micro_secs(value_list[0])).isoformat(),
        "yyyyy.yyyy,a": lambda value_list: ((float(value_list[0][0:3]) + float(value_list[0][3:])/60.0)
                                            * sign_nmea(value_list[1], {'E': 1, 'W': -1})),
        "llll.llll,a": lambda value_list: ((float(value_list[0][0:2]) + float(value_list[0][2:])/60.0)
                                           * sign_nmea(value_list[1], {'N': 1, 'S': -1})),
        "x.x": lambda value_list: float(value_list[0]),
        "ddmmyy": lambda value_list:  gps_date(value_list[0][0:2], value_list[0][2:4], value_list[0][4:]),
        "A": lambda value_list: value_list[0],
        "x.x,a": lambda value_list: float(value_list[0]) * sign_nmea(value_list[1], {'E': 1, 'W': -1}),
        "x": lambda value_list: int(value_list[0]),
        "hhmmss.ss,dd,dd,yyyy,tz_h,tz_m": lambda value_list:  arrow.Arrow(
            int(value_list[3]), int(value_list[2]), int(value_list[1]),
            int(value_list[0][0:2]), int(value_list[0][2:4]), int(value_list[0][4:6]),
            get_micro_secs(value_list[0]),
            f"+{int(value_list[4]):0>2}:{value_list[5]:0>2}"
        ).isoformat(),
        "x.x,R": lambda value_list: float(value_list[0]) * sign_nmea(value_list[1], {'R': 1, 'L': -1}),
        "s": lambda value_list: value_list[0],
        "x.x,T": lambda value_list: to_true(value_list[0], value_list[1], mag_var)

    }
    func = func_map.get(format_def[1])
    if func:
        missing = False
        for v in value_fields:
            if not v:
                missing = True
        if missing:
            value = None
        else:
            value = func(value_fields)

    return value


def get_sentence_data(sentence: str, var_names: list, mag_var: float) -> dict:
    """
    Gets a dict of extracted from the NMEA 0183 sentence as defined by var_names
    note depth must be calculated by adding DBT and TOFF together then the measure will be from
    keel or from waterline
    HDM is always magnetic as defined by sentence HDM
    :param sentence - received NMEA 0183 sentence or line read
    :param var_names - list of variables to extract in processing order
    :param mag_var: Magnetic Variation for conversion true to magnetic
    :return: variables and values extracted
    """

    def_vars = {
        "time": (1, "hhmmss.ss"),       # time of fix
        "status": (1, "A"),             # status of fix A = ok V = fail
        "lat": (2, "llll.llll,a"),      # lat float N positive
        "long": (2, "yyyyy.yyyy,a"),    # long float E positive
        "SOG": (1, "x.x"),              # Speed Over Ground  float knots
        "TMG": (1, "x.x"),              # Track Made Good
        "date": (1, "ddmmyy"),          # Date of fix may not be valid with some GPS
        "mag_var": (2, "x.x,a"),        # Mag Var E positive
        "datetime": (6, "hhmmss.ss,dd,dd,yyyy,tz_h,tz_m"),  # Datetime from ZDA if available
        "XTE": (2, "x.x,R"),            # Cross Track Error R is positive
        "XTE_units": (1, "A"),          # Units for XTE - N = Nm
        "ACir": (1, "A"),               # Arrived at way pt circle
        "APer": (1, "A"),               # Perpendicular passing of way pt
        "BOD": (2, "x.x,T"),            # Bearing origin to destination True
        "Did": (1, "s"),                # Destination Waypoint ID as a str
        "BPD": (2, "x.x,T"),            # Bearing, present position to Destination True
        "HTS": (2, "x.x,T"),            # Heading to Steer True
        "HDM": (1, "x.x"),              # Heading Magnetic
        "DBT": (1, "x.x"),              # Depth below transducer
        "TOFF": (1, "x.x"),             # Transducer offset -ve from transducer to keel +ve transducer to water line
        "STW": (1, "x.x"),              # Speed Through Water float knots
        "DW": (1, "x.x"),               # Water distance since reset float knots
    }
    sentence_data = {}
    fields = sentence[7:].split(",")
    try:
        fields[-1] = fields[-1].rstrip()
        if fields[-1][-3] == "*":
            fields[-1] = fields[-1][:-3]
    except KeyError:
        pass
    for var_name in var_names:
        if var_name:
            field_values = []             # more than one Nmea data field may be used to make a data variable (var_name)
            x = def_vars[var_name][0]
            while x > 0 and fields:
                field_values.append(fields.pop(0))
                x -= 1
            value = get_nmea_field_value(field_values, def_vars[var_name], mag_var)
            if value:
                sentence_data[var_name] = value
    return sentence_data


def nmea_decoder(sentence: str, data: dict, mag_var: float) -> None:
    """
    Decodes a received NMEA 0183 sentence into variables and adds them to current data store
    :param sentence: received  NMEA sentence
    :param data: variables extracted
    :param mag_var: Magnetic Variation for conversion true to magnetic

    """

    sentences = {
        "RMC": ["time", "status", "lat", "long", "SOG", "TMG", "date", "mag_var"],
        "ZDA": ["datetime"],
        "APB": ["status", "", "XTE", "XTE_units", "ACir", "APer", "BOD", "Did", "BPD", "HTS"],
        "HDG": ["", "", "", "mag_var"],
        "HDM": ["HDM"],  # 136.8, M * 25
        "DPT": ["DBT", "TOFF"],  # 2.8, -0.7
        "VHW": ["", "", "", "", "STW"],  # T,, M, 0.0, N, 0.0, K
        "VLW": ["", "", "WD"],  # 23.2, N, 0.0, N
    }

    code = ""
    try:
        if len(sentence) > 9:
            code = sentence[3:6]
            if code in sentences:
                sentence_data = get_sentence_data(sentence, sentences[code], mag_var)
                if sentence_data.get('status', 'A') == 'A':
                    for n, v in sentence_data.items():
                        data[n] = v
                else:
                    for n, v in sentence_data.items():
                        if n in ['time', 'date', 'status']:
                            data[n] = v
                        elif data.get(n):
                            del data[n]

    except (AttributeError, ValueError, ) as err:
        print(f"NMEA {code} sentence translation error: {err} when processing {sentence}")


async def nmea_reader(aioserial_instance: aioserial.AioSerial, boat_data: dict, call_back: Callable = None) -> None:

    """

    :param aioserial_instance: async serial interface to read NMEA data
    :param boat_data:  Dict of values extracted
    :param call_back:  Optional call back function passing back sentence read
    :return:
    """
    mag_var = 0
    while True:
        line = await aioserial_instance.readline_async()
        line_str = line.decode(errors='ignore')
        nmea_decoder(line_str, boat_data, mag_var)
        mag_var = boat_data.get("mag_var", mag_var)
        if call_back:
            await call_back(line)
