from time import sleep, monotonic
import pigpio


class BoatModel:

    def __init__(self):
        self._pi = pigpio.pi('localhost', 8888)
        self._pi.set_mode(23, pigpio.OUTPUT)
        self._pi.set_mode(24, pigpio.OUTPUT)
        self._cm = self._pi.i2c_open(1, 0x60)  # compass module CMPS12
        self.calibration = None
        self.power_on = False
        self.power = 0
        self.compass = 0
        self.compass_correction = 0
        self.helm_direction = 1
        self.helm_power = 0
        self.applied_helm_power = 0
        self.rudder = 0
        self.roll = 0
        self.pitch = 0
        self.run = 1
        self.last_power_at = monotonic()

    def _port(self):
        self._pi.write(23, 0)
        if self.run:
            self._pi.write(24, 1)
        else:
            self._pi.write(24, 0)

    def _starboard(self):
        self._pi.write(24, 0)
        if self.run:
            self._pi.write(23, 1)
        else:
            self._pi.write(23, 0)

    def _read_signed_word(self, hi_reg, lo_reg):
        return int.from_bytes([
            self._pi.i2c_read_byte_data(self._cm, hi_reg),
            self._pi.i2c_read_byte_data(self._cm, lo_reg)
        ], byteorder='big', signed=True)

    def read_compass(self):
        # Read Compass in  deci-degrees
        self.compass = self._read_signed_word(2, 3) + self.compass_correction
        self.calibration = self._pi.i2c_read_byte_data(self._cm, 0x1E)

        if self.compass > 3600:
            self.compass -= 3600
        if self.compass < 0:
            self.compass += 3600
        return self.compass

    def read_bosch_heading(self):
        return self._read_signed_word(0x1A, 0x1B) / 16

    def read_pitch(self):
        self.pitch = int.from_bytes([self._pi.i2c_read_byte_data(self._cm, 0x04)], byteorder='big', signed=True)
        return self.pitch

    def read_roll(self):
        self.roll = int.from_bytes([self._pi.i2c_read_byte_data(self._cm, 0x05)], byteorder='big', signed=True)
        return self.roll

    def _read_cmps_data(self):
        # Read Compass in  deci-degrees
        self.read_compass()
        self.read_pitch()
        self.read_roll()

        acc_x = self._read_signed_word(0x0C, 0x0D)
        acc_y = self._read_signed_word(0x0E, 0x0F)
        acc_z = self._read_signed_word(0x10, 0x11)

        gyo_x = self._read_signed_word(0x12, 0x13)
        gyo_y = self._read_signed_word(0x14, 0x15)
        gyo_z = self._read_signed_word(0x16, 0x17)

        mag_x = self._read_signed_word(0x06, 0x07)
        mag_y = self._read_signed_word(0x08, 0x09)
        mag_z = self._read_signed_word(0x0A, 0x0B)

        bosch_heading = self.read_bosch_heading()
        pitch_16 = self._read_signed_word(0x1C, 0x1D)

        temp = self._read_signed_word(0x18, 0x19)

        print("{} temp {} head {} {} roll {} pitch {} {}"
              "  acc {} {} {}  gyo {} {} {} mag {} {} {}".
              format(self.calibration, temp, self.compass, bosch_heading, self.roll, self.pitch, pitch_16,
                     acc_x, acc_y, acc_z,
                     gyo_x, gyo_y, gyo_z, mag_x, mag_y, mag_z
                     ))

    def update(self):
        self._read_cmps_data()

    def helm(self, correction):
        self.helm_power = correction
        self.helm_drive()
        self.helm_power = 0

    def helm_drive(self):
        """
        Drives the helm motor using PWM where 1,000,000 is
        full on

        """
        if self.power_on:
            self.helm_direction = -1 if self.helm_power < 0 else 1
            if self.helm_direction > 0:
                self._starboard()
            else:
                self._port()

            duty = int(abs(self.helm_power))
            if duty < 2000:
                duty = 0
            elif duty > 998000:
                duty = 1000000

            self.applied_helm_power = duty * self.helm_direction
        else:
            self.applied_helm_power = 0
            duty = 0

        time_now = monotonic()
        self.rudder += self.applied_helm_power * (time_now - self.last_power_at)/1000000
        self.last_power_at = time_now
        # 5khz rate - pulse width is fraction of 1M
        # print(duty)
        self._pi.hardware_PWM(18, 5000, duty)

    def config_save(self):
        self._pi.i2c_write_byte_data(self._cm, 0, 0xF0)
        sleep(.025)
        self._pi.i2c_write_byte_data(self._cm, 0, 0xF5)
        sleep(.025)
        self._pi.i2c_write_byte_data(self._cm, 0, 0xF6)
        sleep(.025)
        print("saved config")
        sleep(2.0)

    def config_delete(self):
        self._pi.i2c_write_byte_data(self._cm, 0, 0xE0)
        sleep(.025)
        self._pi.i2c_write_byte_data(self._cm, 0, 0xE5)
        sleep(.025)
        self._pi.i2c_write_byte_data(self._cm, 0, 0xE2)
        sleep(.025)
        print("deleted config")
        sleep(2.0)