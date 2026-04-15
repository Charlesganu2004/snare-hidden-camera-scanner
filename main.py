import time
import json
from machine import Pin, SoftI2C
from Button import Button
from Storage import Storage
from Ultrasonic import Ultrasonic
from IR_Sensor import D6T
from Motor_Control import MotorControl
import Wifi_manager
import Graph_Manager
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
ROTATION_TIME = getattr(config, "ROTATION_TIME_SECONDS", 90)  # seconds for full 360 degree rotation
SCAN_SAMPLE_INTERVAL = getattr(config, "SCAN_SAMPLE_INTERVAL_SECONDS", 1)
SETUP_HOLD_TIME = 10
STOP_HOLD_TIME = 30

# --- Global stop flag ---
stop_flag = False
live_scan_enabled = False
latest_scan_sample = {}
live_scan_history = []
last_live_graph_time = 0
serial_state = {"ssid": None, "password": None}

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


def classify_ir_temperatures(temps, heat_min, heat_max):
    if not temps:
        return "No Detection"

    min_temp = min(temps)
    max_temp = max(temps)
    if heat_min <= min_temp <= heat_max and heat_min <= max_temp <= heat_max:
        return "Hidden Camera"
    if any(heat_min <= temp <= heat_max for temp in temps):
        return "Maybe Hidden Camera"
    return "No Detection"


def is_detection(status_text):
    return status_text in ("Hidden Camera", "Maybe Hidden Camera")


def sensor_angle(sensor_name, rotation_angle):
    geometry = getattr(config, "SENSOR_GEOMETRY", {}).get(sensor_name, {})
    return (rotation_angle + geometry.get("angle_offset", 0)) % 360


def build_detection_points(sensor_readings, rotation_angle):
    points = []
    geometry = getattr(config, "SENSOR_GEOMETRY", {})
    for sensor_name, reading in sensor_readings.items():
        if not is_detection(reading.get("status")):
            continue
        sensor_info = geometry.get(sensor_name, {})
        points.append({
            "sensor": sensor_name,
            "label": sensor_info.get("label", sensor_name),
            "sensor_type": sensor_info.get("type", reading.get("type", "sensor")),
            "angle_degrees": sensor_angle(sensor_name, rotation_angle),
            "distance_cm": reading.get("distance_cm"),
            "status": reading.get("status"),
        })
    return points


def build_scan_record(data, ultra_results, ir_results, sample_details):
    # Each stored scan gets an order number plus both machine-readable and human-readable time fields.
    recorded_at = time.time()
    scan_number = data[-1]["scan_number"] + 1 if data else 1
    record = {
        "scan_number": scan_number,
        "scan_label": "Scan {:02d}".format(scan_number),
        "stored_at": format_timestamp(recorded_at),
        "timestamp": recorded_at,
        "ultra": ultra_results,
        "ir": ir_results,
    }
    record.update(sample_details)
    return record


def safe_json(payload):
    try:
        return json.dumps(payload)
    except TypeError:
        return str(payload)


def round2(value):
    return int(value * 100) / 100


def build_live_payload():
    return {
        "live_enabled": live_scan_enabled,
        "sample_count": len(live_scan_history),
        "latest": latest_scan_sample,
        "samples": live_scan_history,
    }


def build_live_terminal_image():
    return Graph_Manager.build_terminal_scan_image(build_live_payload())


def write_live_snapshot():
    try:
        with open(getattr(config, "LIVE_SCAN_FILE", "live_scan.json"), "w") as f:
            json.dump(build_live_payload(), f)
    except Exception as exc:
        status("Live scan snapshot could not be saved: {}".format(exc))


def set_live_scan(enabled):
    global live_scan_enabled, last_live_graph_time
    live_scan_enabled = enabled
    last_live_graph_time = 0
    if enabled:
        status("Live scan terminal output enabled.")
        print(build_live_terminal_image())
    else:
        status("Live scan terminal output disabled.")


def update_live_scan(sample):
    global latest_scan_sample, live_scan_history, last_live_graph_time
    latest_scan_sample = sample
    live_scan_history.append(sample)
    history_limit = getattr(config, "LIVE_SCAN_HISTORY_LIMIT", 120)
    if len(live_scan_history) > history_limit:
        live_scan_history = live_scan_history[-history_limit:]
    write_live_snapshot()
    if live_scan_enabled:
        print("[SNARE LIVE] {}".format(safe_json(sample)))
        now = time.time()
        if getattr(config, "LIVE_TERMINAL_GRAPH_ENABLED", True):
            interval = getattr(config, "LIVE_TERMINAL_GRAPH_INTERVAL_SECONDS", 3)
            if now - last_live_graph_time >= interval:
                print(build_live_terminal_image())
                last_live_graph_time = now


def reset_live_scan():
    global latest_scan_sample, live_scan_history
    latest_scan_sample = {}
    live_scan_history = []
    write_live_snapshot()


def load_live_scan_data():
    if latest_scan_sample or live_scan_history:
        return build_live_payload()
    try:
        with open(getattr(config, "LIVE_SCAN_FILE", "live_scan.json"), "r") as f:
            return json.load(f)
    except Exception:
        return build_live_payload()


def build_graph_download():
    return Graph_Manager.build_scan_graph_html(Storage.load())


def handle_usb_commands():
    Wifi_manager.handle_usb_commands(
        serial_state,
        status_callback=status,
        load_data_callback=Storage.load,
        clear_data_callback=Storage.clear,
        build_graph_callback=build_graph_download,
        live_data_callback=load_live_scan_data,
        live_graph_callback=build_live_terminal_image,
        set_live_callback=set_live_scan,
    )
    if serial_state.get("wifi_requested"):
        serial_state["wifi_requested"] = False
        status("Setup mode requested from USB terminal.")
        return "setup"
    return None

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


def trigger_stop():
    global stop_flag
    stop_flag = True
    status("STOP triggered by user.")
    for _ in range(3):
        red_on(); green_on(); time.sleep(0.1)
        red_off(); green_off(); time.sleep(0.1)


# --- Stop button check ---
def check_stop():
    if button.pressed():
        # A very long hold is reserved for emergency stop so shorter presses can still trigger scan and setup actions.
        start = time.time()
        while button.pressed():
            time.sleep(0.1)
            if time.time() - start >= STOP_HOLD_TIME:
                trigger_stop()
                return True
    return False


def check_scan_mode_request():
    if not button.pressed():
        return None

    press_start = time.time()
    setup_indicator_on = False

    while button.pressed():
        elapsed = time.time() - press_start
        if elapsed >= SETUP_HOLD_TIME and not setup_indicator_on:
            # The green LED turns on once the setup-mode threshold is reached during a scan.
            green_on()
            setup_indicator_on = True

        time.sleep(0.1)

        if elapsed >= STOP_HOLD_TIME:
            green_off()
            trigger_stop()
            return "stop"

    if setup_indicator_on:
        green_off()

    if time.time() - press_start >= SETUP_HOLD_TIME:
        status("Setup mode requested during scan.")
        return "setup"

    return None


def setup_exit_requested():
    if not button.pressed():
        return False

    status("Button press detected. Closing setup mode.")
    while button.pressed():
        time.sleep(0.05)
    return True

# --- Scanning function ---
def scan_with_rotation():
    global stop_flag
    status("Starting 360 degree scan.")
    scan_started_at = time.time()
    scan_id = int(scan_started_at)
    reset_live_scan()

    # Flash green LED for 5 seconds at start
    start_time = time.time()
    while time.time() - start_time < 5:
        usb_action = handle_usb_commands()
        if usb_action == "setup":
            return "setup"
        button_action = check_scan_mode_request()
        if stop_flag or button_action == "stop":
            return "stop"
        if button_action == "setup":
            return "setup"
        green_on(); time.sleep(0.5)
        green_off(); time.sleep(0.5)

    status("Motor starting rotation.")
    red_on()               # solid red during scan
    motor.set_speed_percent(80)  # slow rotation
    start = time.time()

    try:
        while time.time() - start < ROTATION_TIME:
            usb_action = handle_usb_commands()
            if usb_action == "setup":
                return "setup"
            button_action = check_scan_mode_request()
            if stop_flag or button_action == "stop":
                return "stop"
            if button_action == "setup":
                return "setup"

            elapsed = time.time() - start
            rotation_angle = min(359.9, (elapsed / ROTATION_TIME) * 360)

            # --- Read IR sensors ---
            # Both IR arrays are sampled first so heat confirmation can be used while evaluating ultrasonic hits.
            ir1_temps = ir1.read()
            ir2_temps = ir2.read()
            ir_results = [
                classify_ir_temperatures(ir1_temps, ir1.heat_min, ir1.heat_max),
                classify_ir_temperatures(ir2_temps, ir2.heat_min, ir2.heat_max),
            ]

            # --- Combine ultrasonic with IR detection ---
            heat_detected = any(is_detection(r) for r in ir_results)
            ultra_sensors = [
                ("ultra1", ultra1),
                ("ultra2", ultra2),
                ("ultra3", ultra3),
                ("ultra4", ultra4),
            ]
            ultra_results = []
            sensor_readings = {
                "ir1": {
                    "type": "ir",
                    "status": ir_results[0],
                    "temperatures_c": ir1_temps,
                    "angle_degrees": sensor_angle("ir1", rotation_angle),
                },
                "ir2": {
                    "type": "ir",
                    "status": ir_results[1],
                    "temperatures_c": ir2_temps,
                    "angle_degrees": sensor_angle("ir2", rotation_angle),
                },
            }

            for sensor_name, ultrasonic in ultra_sensors:
                result = ultrasonic.check_hidden_camera(heat_detected=heat_detected)
                ultra_results.append(result)
                sensor_readings[sensor_name] = {
                    "type": "ultrasonic",
                    "status": result,
                    "distance_cm": ultrasonic.last_distance,
                    "angle_degrees": sensor_angle(sensor_name, rotation_angle),
                }

            sample_details = {
                "scan_session": scan_id,
                "elapsed_seconds": round2(elapsed),
                "rotation_angle_degrees": round2(rotation_angle),
                "progress_percent": round2((elapsed / ROTATION_TIME) * 100),
                "sensor_readings": sensor_readings,
                "detection_points": build_detection_points(sensor_readings, rotation_angle),
            }
            update_live_scan(sample_details)

            # --- Store scan data ---
            # The saved format stays simple so it is easy to decrypt and download later.
            # Up to 50 scan records are kept on the device, and each record is labeled by order and stored time.
            data = Storage.load()
            if len(data) >= DATA_LIMIT:
                data = data[-(DATA_LIMIT - 1):]
            data.append(build_scan_record(data, ultra_results, ir_results, sample_details))
            Storage.save(data)

            # --- LED feedback ---
            # Both LEDs flash when any sensor suggests a likely or possible hidden camera.
            if "Hidden Camera" in ir_results + ultra_results or "Maybe Hidden Camera" in ir_results + ultra_results:
                flash_both(0.2)
                red_on()  # back to solid red

            time.sleep(SCAN_SAMPLE_INTERVAL)
    finally:
        # The motor is stopped in a finally block so the platform shuts down cleanly even if scanning exits early.
        motor.stop()
        red_off()
        status("Motor rotation finished.")
        status("Scan complete.")

# --- Long press action: Wi-Fi + Bluetooth setup ---
def long_press_action():
    global stop_flag
    status("Long press detected: activating Bluetooth LE and the setup/download portal.")
    bluetooth_started = bluetooth.start()
    if bluetooth_started:
        status("Bluetooth LE advertising started as '{}'.".format(config.AP_SSID))
    else:
        status("Bluetooth LE did not start; use the Wi-Fi network '{}'.".format(config.AP_SSID))
    green_on()

    def setup_heartbeat():
        # The green LED stays on solid while setup mode is active.
        green_on()

    def load_download_data():
        return Storage.load()

    def clear_download_data():
        Storage.clear()

    Wifi_manager.start_setup(
        stop_checker=None,
        exit_checker=setup_exit_requested,
        heartbeat=setup_heartbeat,
        status_callback=status,
        load_data_callback=load_download_data,
        clear_data_callback=clear_download_data,
        build_graph_callback=build_graph_download,
        live_data_callback=load_live_scan_data,
        live_graph_callback=build_live_terminal_image,
        set_live_callback=set_live_scan,
    )
    red_off()
    green_off()
    bluetooth.stop()

    if stop_flag:
        status("Setup/download portal closed because execution was stopped.")
        return

    status("Setup/download portal closed.")

# --- Boot: initial scan ---
status("Device powering on: initial scan")
boot_result = scan_with_rotation()
if boot_result == "setup" and not stop_flag:
    long_press_action()

# --- Main loop ---
while True:
    usb_action = handle_usb_commands()
    if usb_action == "setup":
        long_press_action()
        continue

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

        if press_duration >= SETUP_HOLD_TIME:
            long_press_action()  # Long press -> Wi-Fi + Bluetooth
        elif press_duration >= 5:
            scan_result = scan_with_rotation() # Short press -> scan again
            if scan_result == "setup" and not stop_flag:
                long_press_action()

    check_stop()
    time.sleep(0.2)
