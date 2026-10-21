from machine import Pin
import config

class Button:
    def __init__(self):
        self.pin_number = config.BUTTON_PIN
        self.button = Pin(self.pin_number, Pin.IN, Pin.PULL_UP)

    def pressed(self):
        return self.button.value() == 0

    def active_pins(self):
        return [self.pin_number] if self.pressed() else []

    def pins_label(self):
        return "GP{}".format(self.pin_number)
