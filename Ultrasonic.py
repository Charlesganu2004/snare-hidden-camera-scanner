from machine import Pin, time_pulse_us
import time

class Ultrasonic:
    def __init__(self, trig, echo, min_distance=5, max_distance=500, timeout_us=None):
        self.trig = Pin(trig, Pin.OUT)
        self.echo = Pin(echo, Pin.IN)
        self.min_distance = min_distance
        self.max_distance = max_distance
        # A timeout is added so one bad sensor cannot freeze the whole scan loop.
        self.timeout_us = timeout_us or int(max_distance * 120)
        self.last_distance = None

    def read(self):
        # Trigger pulse
        self.trig.low()
        time.sleep_us(2)
        self.trig.high()
        time.sleep_us(10)
        self.trig.low()

        # The return pulse is measured with a timeout so the code can fail fast when there is no echo.
        try:
            pulse_width = time_pulse_us(self.echo, 1, self.timeout_us)
        except OSError:
            self.last_distance = None
            return None
        if pulse_width < 0:
            self.last_distance = None
            return None

        # Distance in cm
        distance = pulse_width * 0.0343 / 2
        self.last_distance = distance
        return distance

    def check_hidden_camera(self, heat_detected=False):
        distance = self.read()
        # A timeout is treated as no detection instead of letting the scan crash or hang.
        if distance is None:
            return "No Detection"
        # Check if distance is within camera range
        in_range = self.min_distance <= distance <= self.max_distance

        if in_range and heat_detected:
            return "Hidden Camera"
        elif in_range or heat_detected:
            return "Maybe Hidden Camera"
        else:
            return "No Detection"
