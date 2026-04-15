from machine import Pin, PWM
import config

class MotorControl:
    def __init__(self):
        self.ain1 = Pin(config.MOTOR_AIN1, Pin.OUT)
        self.ain2 = Pin(config.MOTOR_AIN2, Pin.OUT)
        self.stby = Pin(config.MOTOR_STBY, Pin.OUT)
        self.pwm = PWM(Pin(config.MOTOR_PWM))
        self.pwm.freq(1000)
        # The driver starts disabled so the platform does not move unexpectedly during boot.
        self.disable()  # Ensure motor is off at start

    def set_direction(self, clockwise=True):
        # The H-bridge direction pins are driven explicitly so PWM is not the only motor control signal.
        if clockwise:
            self.ain1.value(1)
            self.ain2.value(0)
        else:
            self.ain1.value(0)
            self.ain2.value(1)

    def enable(self):
        self.stby.value(1)

    def disable(self):
        self.stby.value(0)

    def set_speed_percent(self, percent, clockwise=True):
        # The requested speed is clamped to a safe percentage range before turning it into a 16-bit duty cycle.
        percent = max(0, min(100, percent))
        if percent == 0:
            self.stop()
            return
        self.set_direction(clockwise)
        duty = int(percent / 100 * 65535)
        self.pwm.duty_u16(duty)
        self.enable()

    def stop(self):
        # PWM is dropped, direction pins are cleared, and standby is disabled so the motor fully stops.
        self.pwm.duty_u16(0)
        self.ain1.value(0)
        self.ain2.value(0)
        self.disable()
