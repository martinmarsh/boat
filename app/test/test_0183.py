import unittest
from app.nmea_0183 import get_nmea_field_value, nmea_decoder


class TestField(unittest.TestCase):

    def test_time(self):
        self.assertEqual(get_nmea_field_value(['105033.23'], (1, "hhmmss.ss"), 0), '10:50:33.230')
        self.assertEqual(get_nmea_field_value(['000000.00'], (1, "hhmmss.ss"), 0), '00:00:00.000')
        self.assertEqual(get_nmea_field_value(['000001.00'], (1, "hhmmss.ss"), 0), '00:00:01.000')
        self.assertEqual(get_nmea_field_value(['235959.00'], (1, "hhmmss.ss"), 0), '23:59:59.000')
        self.assertEqual(get_nmea_field_value(['235959.99999'], (1, "hhmmss.ss"), 0), '23:59:59.999')

    def test_datetime(self):
        self.assertEqual(get_nmea_field_value(
            ['105033.23', '23', '04', '2021', '00', '00'], (6, "hhmmss.ss,dd,dd,yyyy,tz_h,tz_m"), 0),
            '2021-04-23T10:50:33.230000+00:00')


class TestSentence(unittest.TestCase):

    def test_rmc_zda(self):
        data = {}
        nmea_decoder("$GPRMC,110910.59,A,5047.3986,N,00054.6007,W,0.08,0.19,150920,0.24,W,D,V*75", data, 0)
        self.assertDictEqual(data, {'time': '11:09:10.590', 'status': 'A', 'lat': 50.78997667,
                                    'long': -0.91001167, 'SOG': 0.08, 'TMG': 0.19, 'date': '2020-09-15',
                                    'mag_var': -0.24})
        self.assertEqual(round(data['long']*60, 4), -54.6007)
        self.assertEqual(round((data['lat']-50)*60, 4), 47.3986)
        nmea_decoder("$GPZDA,110910.59,15,09,2020,00,00*6F", data, 0)
        self.assertDictEqual(data, {'time': '11:09:10.590', 'status': 'A', 'lat': 50.78997667,
                                    'long': -0.91001167, 'SOG': 0.08, 'TMG': 0.19, 'date': '2020-09-15',
                                    'datetime': '2020-09-15T11:09:10.590000+00:00', 'mag_var': -0.24})

    def test_hdm(self):
        data = {}
        nmea_decoder("$HCHDM,172.5,M*285", data, 5)
        self.assertDictEqual(data, {'HDM': 172.5})

    def test_abp(self):
        data = {}
        nmea_decoder("$GPAPB,A,A,5,L,N,V,V,359.,T,1,359.1,T,6,T,A*79", data, 5)
        self.assertDictEqual(data, {'status': 'A', 'XTE': -5.0, 'XTE_units': 'N', 'ACir': 'V', 'APer': 'V',
                                    'BOD': '359.', 'Did': '1', 'BPD': '359.1', 'HTS': '6'})

    def test_depth(self):
        data = {}
        nmea_decoder("$SSDPT,2.8,-0.7", data, 5)
        self.assertDictEqual(data, {'DBT': 2.8, 'TOFF': -0.7})

