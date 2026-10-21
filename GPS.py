from machine import UART, Pin
import time
import config


class GPS:
    def __init__(self):
        # The GPS module sends NMEA text over UART, so the scan code can attach time and location
        # evidence to each stored sample without needing Wi-Fi or a phone clock.
        self.uart = UART(
            getattr(config, "GPS_UART", 0),
            baudrate=getattr(config, "GPS_BAUDRATE", 9600),
            tx=Pin(config.GPS_TX),
            rx=Pin(config.GPS_RX),
        )
        self.last_fix = self.empty_snapshot()

    def empty_snapshot(self):
        return {
            "available": False,
            "fix_valid": False,
            "gps_time_utc": None,
            "gps_date": None,
            "gps_timestamp_utc": None,
            "latitude": None,
            "longitude": None,
            "altitude_m": None,
            "satellites": None,
            "speed_knots": None,
            "course_degrees": None,
            "last_sentence": None,
        }

    def read(self):
        # This raw reader is kept for simple terminal testing and backwards compatibility.
        if self.uart.any():
            return self.uart.readline()
        return None

    def snapshot(self, timeout_ms=80):
        # Several NMEA lines can arrive close together, so this drains the UART briefly and keeps
        # the best parsed fix. If the GPS has no lock yet, the stored data still shows GPS was checked.
        start = self._ticks_ms()
        parsed_any = False
        while self._ticks_diff(self._ticks_ms(), start) < timeout_ms:
            line = self.read()
            if not line:
                time.sleep_ms(5)
                continue
            parsed = self.parse_sentence(line)
            if parsed:
                parsed_any = True
                self.last_fix.update(parsed)
                self.last_fix["available"] = True
        if not parsed_any:
            return dict(self.last_fix)
        return dict(self.last_fix)

    def parse_sentence(self, sentence):
        try:
            if isinstance(sentence, bytes):
                sentence = sentence.decode().strip()
            else:
                sentence = str(sentence).strip()
        except Exception:
            return None

        if not sentence:
            return None

        if sentence.startswith("$GPRMC") or sentence.startswith("$GNRMC"):
            return self._parse_rmc(sentence)
        if sentence.startswith("$GPGGA") or sentence.startswith("$GNGGA"):
            return self._parse_gga(sentence)
        return None

    def _parse_rmc(self, sentence):
        parts = sentence.split(",")
        if len(parts) < 10:
            return None

        gps_time = self._format_time(parts[1])
        gps_date = self._format_date(parts[9])
        fix_valid = parts[2] == "A"
        data = {
            "fix_valid": fix_valid,
            "gps_time_utc": gps_time,
            "gps_date": gps_date,
            "gps_timestamp_utc": self._combine_timestamp(gps_date, gps_time),
            "latitude": self._convert_coord(parts[3], parts[4]),
            "longitude": self._convert_coord(parts[5], parts[6]),
            "speed_knots": self._to_float(parts[7]),
            "course_degrees": self._to_float(parts[8]),
            "last_sentence": "$RMC",
        }
        if not fix_valid:
            data["latitude"] = None
            data["longitude"] = None
        return data

    def _parse_gga(self, sentence):
        parts = sentence.split(",")
        if len(parts) < 10:
            return None

        fix_quality = self._to_int(parts[6])
        fix_valid = fix_quality is not None and fix_quality > 0
        data = {
            "fix_valid": fix_valid,
            "gps_time_utc": self._format_time(parts[1]),
            "latitude": self._convert_coord(parts[2], parts[3]),
            "longitude": self._convert_coord(parts[4], parts[5]),
            "satellites": self._to_int(parts[7]),
            "altitude_m": self._to_float(parts[9]),
            "last_sentence": "$GGA",
        }
        if not fix_valid:
            data["latitude"] = None
            data["longitude"] = None
        return data

    def _convert_coord(self, raw, hemi):
        if not raw or not hemi:
            return None
        try:
            dot_index = raw.find(".")
            degree_digits = dot_index - 2
            degrees = float(raw[:degree_digits])
            minutes = float(raw[degree_digits:])
            value = degrees + minutes / 60
            if hemi in ("S", "W"):
                value = -value
            return self._round6(value)
        except Exception:
            return None

    def _format_time(self, raw):
        if not raw or len(raw) < 6:
            return None
        return "{}:{}:{}".format(raw[0:2], raw[2:4], raw[4:6])

    def _format_date(self, raw):
        if not raw or len(raw) != 6:
            return None
        day = raw[0:2]
        month = raw[2:4]
        year = "20" + raw[4:6]
        return "{}-{}-{}".format(year, month, day)

    def _combine_timestamp(self, gps_date, gps_time):
        if not gps_date or not gps_time:
            return None
        return "{}T{}Z".format(gps_date, gps_time)

    def _to_float(self, value):
        try:
            if value == "":
                return None
            return float(value)
        except Exception:
            return None

    def _to_int(self, value):
        try:
            if value == "":
                return None
            return int(value)
        except Exception:
            return None

    def _round6(self, value):
        return int(value * 1000000) / 1000000

    def _ticks_ms(self):
        if hasattr(time, "ticks_ms"):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, now, start):
        if hasattr(time, "ticks_diff"):
            return time.ticks_diff(now, start)
        return now - start
