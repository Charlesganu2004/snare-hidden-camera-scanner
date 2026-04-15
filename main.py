import time
from machine import Pin, SoftI2C
from Button import Button
from Storage import Storage
from Ultrasonic import Ultrasonic
from IR_Sensor import D6T
from Motor_Control import MotorControl
import Wifi_manager
from Bluetooth_manager import BluetoothManager
import config

# --- Sensors ---
ultra1 = Ultrasonic(config.ULTRA1_TRIG, config.ULTRA1_ECHO, max_distance=500)
ultra2 = Ultrasonic(config.ULTRA2_TRIG, config.ULTRA2_ECHO, max_distance=500)
ultra3 = Ultrasonic(config.ULTRA3_TRIG, config.ULTRA3_ECHO, max_distance=500)
ultra4 = Ultrasonic(config.ULTRA4_TRIG, config.ULTRA4_ECHO, max_distance=500)

# IR Sensors using SoftI2C for flexible GPIO pins
ir1_i2c = SoftI2C(sda=Pin(config.IR1_SDA), scl=Pin(config.IR1_SCL), freq=100000)
ir2_i2c = SoftI2C(sda=Pin(config.IR2_SDA), scl=Pin(config.IR2_SCL), freq=100000)

ir1 = D6T(config.IR1_SDA, config.IR1_SCL)
ir1.i2c = ir1_i2c
ir2 = D6T(config.IR2_SDA, config.IR2_SCL)
ir2.i2c = ir2_i2c

motor = MotorControl()
button = Button()
bluetooth = BluetoothManager()

# --- LEDs ---
red_led = Pin(config.RED_LED_PIN, Pin.OUT)     # external red LED
green_led = Pin(config.GREEN_LED_PIN, Pin.OUT) # onboard Pico LED

# --- Constants ---
DATA_LIMIT = 50
ROTATION_TIME = 80  # seconds for full 360 degrees rotation

# --- Global stop flag ---
stop_flag = False

# --- Status helper ---
def status(message):
    # One status helper is used so every device message has the same prefix in the serial logs.
    print("[SNARE] {}".format(message))


def format_timestamp(epoch_seconds):
    # A readable local timestamp is stored with each scan so downloads show when each record was captured.
    year, month, day, hour, minute, second, _, _ = time.localtime(epoch_seconds)
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        year, month, day, hour, minute, second
    )


def build_scan_record(data, ultra_results, ir_results):
    # Each stored scan gets an order number plus both machine-readable and human-readable time fields.
    recorded_at = time.time()
    scan_number = data[-1]["scan_number"] + 1 if data else 1
    return {
        "scan_number": scan_number,
        "scan_label": "Scan {:02d}".format(scan_number),
        "stored_at": format_timestamp(recorded_at),
        "timestamp": recorded_at,
        "ultra": ultra_results,
        "ir": ir_results,
    }

# --- LED helper functions ---
def red_on(): red_led.value(1)
def red_off(): red_led.value(0)
def green_on(): green_led.value(1)
def green_off(): green_led.value(0)

def flash_both(duration=0.2):
    red_on(); green_on()
    time.sleep(duration)
    red_off(); green_off()
    time.sleep(duration)

def flash_green(times=1, duration=0.5):
    for _ in range(times):
        green_on(); time.sleep(duration)
        green_off(); time.sleep(duration)

# --- Stop button check ---
def check_stop():
    global stop_flag
    if button.pressed():
        # A very long hold is reserved for emergency stop so shorter presses can still trigger scan and setup actions.
        start = time.time()
        while button.pressed():
            time.sleep(0.1)
            if time.time() - start >= 30:
                stop_flag = True
                print("STOP triggered by user!")
                for _ in range(3):
                    red_on(); green_on(); time.sleep(0.1)
                    red_off(); green_off(); time.sleep(0.1)
                return True
    return False

# --- Scanning function ---
def scan_with_rotation():
    global stop_flag
    status("Starting 360 degree scan.")

    # Flash green LED for 5 seconds at start
    start_time = time.time()
    while time.time() - start_time < 5:
        if stop_flag or check_stop():
            return
        green_on(); time.sleep(0.5)
        green_off(); time.sleep(0.5)

    status("Motor starting rotation.")
    red_on()               # solid red during scan
    motor.set_speed_percent(80)  # slow rotation
    start = time.time()

    try:
        while time.time() - start < ROTATION_TIME:
            if stop_flag or check_stop():
                return

            # --- Read IR sensors ---
            # Both IR arrays are sampled first so heat confirmation can be used while evaluating ultrasonic hits.
            ir_results = [ir1.check_hidden_camera(), ir2.check_hidden_camera()]

            # --- Combine ultrasonic with IR detection ---
            heat_detected = any(r in ["Hidden Camera", "Maybe Hidden Camera"] for r in ir_results)
            ultra_results = [u.check_hidden_camera(heat_detected=heat_detected) for u in [ultra1, ultra2, ultra3, ultra4]]

            # --- Store scan data ---
            # The saved format stays simple so it is easy to decrypt and download later.
            # Up to 50 scan records are kept on the device, and each record is labeled by order and stored time.
            data = Storage.load()
            if len(data) >= DATA_LIMIT:
                data = data[-(DATA_LIMIT - 1):]
            data.append(build_scan_record(data, ultra_results, ir_results))
            Storage.save(data)

            # --- LED feedback ---
            # Both LEDs flash when any sensor suggests a likely or possible hidden camera.
            if "Hidden Camera" in ir_results + ultra_results or "Maybe Hidden Camera" in ir_results + ultra_results:
                flash_both(0.2)
                red_on()  # back to solid red

            time.sleep(1)
    finally:
        # The motor is stopped in a finally block so the platform shuts down cleanly even if scanning exits early.
        motor.stop()
        red_off()
        status("Motor rotation finished.")
        status("Scan complete.")

# --- Long press action: Wi-Fi + Bluetooth setup ---
def long_press_action():
    global stop_flag
    status("Long press detected: activating Bluetooth and the setup/download portal.")
    bluetooth.start()

    blink_state = {"last_toggle": 0, "red_on": False}

    def setup_heartbeat():
        # The red LED blinks while the setup portal is waiting so the user knows the device is in config mode.
        now = time.time()
        if now - blink_state["last_toggle"] >= 0.5:
            blink_state["red_on"] = not blink_state["red_on"]
            red_led.value(1 if blink_state["red_on"] else 0)
            blink_state["last_toggle"] = now

    def load_download_data():
        return Storage.load()

    def clear_download_data():
        Storage.clear()

    Wifi_manager.start_setup(
        stop_checker=check_stop,
        heartbeat=setup_heartbeat,
        status_callback=status,
        load_data_callback=load_download_data,
        clear_data_callback=clear_download_data,
    )
    red_off()

    if stop_flag:
        status("Setup/download portal closed because execution was stopped.")
        return

    status("Setup/download portal closed.")

# --- Boot: initial scan ---
status("Device powering on: initial scan")
scan_with_rotation()

# --- Main loop ---
while True:
    if stop_flag:
        status("Execution stopped by user.")
        motor.stop()
        red_off()
        green_off()
        break

    if button.pressed():
        press_start = time.time()
        while button.pressed():
            time.sleep(0.1)
        press_duration = time.time() - press_start

        if press_duration >= 10:
            long_press_action()  # Long press -> Wi-Fi + Bluetooth
        elif press_duration >= 5:
            scan_with_rotation() # Short press -> scan again

    check_stop()
    time.sleep(0.2)
