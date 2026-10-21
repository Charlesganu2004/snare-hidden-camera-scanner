import time
import json
from machine import Pin, SoftI2C
from Button import Button
from Storage import Storage
from Ultrasonic import Ultrasonic
from IR_Sensor import D6T
from Motor_Control import MotorControl
from GPS import GPS
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
gps_reader = GPS()

# --- LEDs ---
red_led = Pin(config.RED_LED_PIN, Pin.OUT)     # external red LED
green_led = Pin(config.GREEN_LED_PIN, Pin.OUT) # onboard Pico LED

# --- Constants ---
DATA_LIMIT = 50
ROTATION_TIME = getattr(config, "ROTATION_TIME_SECONDS", 90)  # seconds for full 360 degree rotation
SCAN_SAMPLE_INTERVAL = getattr(config, "SCAN_SAMPLE_INTERVAL_SECONDS", 1)
SCAN_CLICK_MAX_TIME = getattr(config, "SCAN_CLICK_MAX_SECONDS", 5)
SETUP_HOLD_TIME = getattr(config, "SETUP_HOLD_TIME_SECONDS", 10)
STOP_HOLD_TIME = getattr(config, "STOP_HOLD_TIME_SECONDS", 30)

# --- Global stop flag ---
stop_flag = False
live_scan_enabled = False
latest_scan_sample = {}
live_scan_history = []
live_scan_status = "idle"
live_scan_message = "No live scan is running."
last_live_graph_time = 0
serial_state = {"ssid": None, "password": None}
last_button_pressed = False
next_scan_number_cache = None

# --- Status helper ---
def status(message):
    # One status helper is used so every device message has the same prefix in the serial logs.
    print("[SNARE] {}".format(message))


def button_is_pressed():
    # This wrapper prints button edges once, which helps confirm the tactile button wiring in the terminal.
    global last_button_pressed
    pressed = button.pressed()
    if pressed and not last_button_pressed:
        active = button.active_pins()
        status("Button pressed. Watching {}; active: {}.".format(
            button.pins_label(),
            ", ".join("GP{}".format(pin) for pin in active) if active else "unknown",
        ))
    elif not pressed and last_button_pressed:
        status("Button released. Watching {}.".format(button.pins_label()))
    last_button_pressed = pressed
    return pressed


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


def build_hit_summary(detection_points):
    # The hits block makes downloads easy to scan without losing the full sensor evidence.
    summary = {
        "count": len(detection_points),
        "has_detection": len(detection_points) > 0,
        "has_ir_hit": False,
        "has_ultrasonic_hit": False,
        "confirmed_count": 0,
        "possible_count": 0,
    }
    for point in detection_points:
        if point.get("sensor_type") == "ir":
            summary["has_ir_hit"] = True
        if point.get("sensor_type") == "ultrasonic":
            summary["has_ultrasonic_hit"] = True
        if point.get("status") == "Hidden Camera":
            summary["confirmed_count"] += 1
        if point.get("status") == "Maybe Hidden Camera":
            summary["possible_count"] += 1
    return summary


def compact_sensor_readings(sensor_readings):
    # Storage keeps compact features so encrypted saves do not run out of RAM on the Pico.
    compact = {}
    keep_raw_ir = getattr(config, "STORE_RAW_IR_TEMPERATURES", False)
    for sensor_name, reading in (sensor_readings or {}).items():
        sensor_type = reading.get("type")
        item = {
            "type": sensor_type,
            "status": reading.get("status"),
            "angle_degrees": reading.get("angle_degrees"),
        }
        if sensor_type == "ultrasonic":
            distance = reading.get("distance_cm")
            item["distance_cm"] = round2(distance) if distance is not None else None
        elif sensor_type == "ir":
            temps = reading.get("temperatures_c") or []
            item["temperature_summary"] = summarize_temperatures(temps)
            if keep_raw_ir:
                item["temperatures_c"] = temps
        compact[sensor_name] = item
    return compact


def current_gps_snapshot():
    try:
        return gps_reader.snapshot(timeout_ms=getattr(config, "GPS_READ_TIMEOUT_MS", 80))
    except Exception as exc:
        status("GPS read warning: {}".format(exc))
        return gps_reader.empty_snapshot()


def get_next_scan_number():
    global next_scan_number_cache
    if next_scan_number_cache is None:
        next_scan_number_cache = Storage.next_scan_number()
    scan_number = next_scan_number_cache
    next_scan_number_cache += 1
    return scan_number


def clear_stored_data():
    global next_scan_number_cache
    Storage.clear()
    next_scan_number_cache = None


def build_scan_record(scan_number, ultra_results, ir_results, sample_details):
    # Each stored scan gets an order number plus both machine-readable and human-readable time fields.
    recorded_at = time.time()
    sensor_readings = compact_sensor_readings(sample_details.get("sensor_readings"))
    detection_points = sample_details.get("detection_points") or []
    record = {
        "scan_number": scan_number,
        "scan_label": "Scan {:02d}".format(scan_number),
        "stored_at": format_timestamp(recorded_at),
        "timestamp": recorded_at,
        "device_time": {
            "timestamp": recorded_at,
            "stored_at": format_timestamp(recorded_at),
        },
        "gps": sample_details.get("gps"),
        "hits": sample_details.get("hits"),
        "ultra": ultra_results,
        "ir": ir_results,
        "scan_session": sample_details.get("scan_session"),
        "elapsed_seconds": sample_details.get("elapsed_seconds"),
        "rotation_angle_degrees": sample_details.get("rotation_angle_degrees"),
        "progress_percent": sample_details.get("progress_percent"),
        "sensor_readings": sensor_readings,
        "detection_points": detection_points,
    }
    return record


def safe_json(payload):
    try:
        return json.dumps(payload)
    except TypeError:
        return str(payload)


def round2(value):
    return int(value * 100) / 100


def summarize_temperatures(temps):
    # Temperature summaries are exported beside the raw IR array so later filter tuning has quick numeric features.
    valid = []
    for temp in temps or []:
        try:
            valid.append(float(temp))
        except Exception:
            pass
    if not valid:
        return {"count": 0, "min_c": None, "max_c": None, "avg_c": None}
    return {
        "count": len(valid),
        "min_c": round2(min(valid)),
        "max_c": round2(max(valid)),
        "avg_c": round2(sum(valid) / len(valid)),
    }


def build_live_payload():
    return {
        "schema": "snare-live-radar-v1",
        "created_at": format_timestamp(time.time()),
        "timestamp": time.time(),
        "live_enabled": live_scan_enabled,
        "scan_status": live_scan_status,
        "message": live_scan_message,
        "sensor_geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "max_distance_cm": getattr(config, "GRAPH_MAX_DISTANCE_CM", 500),
        "rotation_time_seconds": ROTATION_TIME,
        "sample_interval_seconds": SCAN_SAMPLE_INTERVAL,
        "sample_count": len(live_scan_history),
        "gps": latest_scan_sample.get("gps") if latest_scan_sample else gps_reader.last_fix,
        "hits": latest_scan_sample.get("hits") if latest_scan_sample else build_hit_summary([]),
        "latest": latest_scan_sample,
        "samples": live_scan_history,
    }


def build_live_terminal_image():
    return Graph_Manager.build_terminal_scan_image(
        build_live_payload(),
        width=getattr(config, "TERMINAL_RADAR_WIDTH", 61),
        height=getattr(config, "TERMINAL_RADAR_HEIGHT", 31),
    )


def write_live_snapshot():
    try:
        with open(getattr(config, "LIVE_SCAN_FILE", "live_scan.json"), "w") as f:
            json.dump(build_live_payload(), f)
    except Exception as exc:
            status("Live scan snapshot could not be saved: {}".format(exc))


def set_live_scan_status(scan_status, message):
    global live_scan_status, live_scan_message
    live_scan_status = scan_status
    live_scan_message = message
    write_live_snapshot()


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


def build_live_radar_page():
    return Graph_Manager.build_live_radar_html(load_live_scan_data())


def build_radar_replay_download():
    return Graph_Manager.build_radar_replay_html(Storage.load())


def legacy_sensor_reading(record, sensor_name):
    # Older stored records are still exported by mapping their original ultra/IR lists into the newer sensor shape.
    if sensor_name.startswith("ir"):
        index = int(sensor_name[-1]) - 1
        old_ir = record.get("ir") or []
        if index < len(old_ir):
            return {"type": "ir", "status": old_ir[index], "temperatures_c": []}
    if sensor_name.startswith("ultra"):
        index = int(sensor_name[-1]) - 1
        old_ultra = record.get("ultra") or []
        if index < len(old_ultra):
            return {"type": "ultrasonic", "status": old_ultra[index], "distance_cm": None}
    return {}


def build_filter_row(record):
    # This row format gives future filter work a stable, spreadsheet-friendly shape while keeping raw records available.
    geometry = getattr(config, "SENSOR_GEOMETRY", {})
    readings = record.get("sensor_readings") or {}
    detection_points = record.get("detection_points") or []
    row = {
        "scan_number": record.get("scan_number"),
        "scan_label": record.get("scan_label"),
        "scan_session": record.get("scan_session"),
        "stored_at": record.get("stored_at"),
        "timestamp": record.get("timestamp"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "rotation_angle_degrees": record.get("rotation_angle_degrees"),
        "progress_percent": record.get("progress_percent"),
        "gps_timestamp_utc": (record.get("gps") or {}).get("gps_timestamp_utc"),
        "gps_date": (record.get("gps") or {}).get("gps_date"),
        "gps_time_utc": (record.get("gps") or {}).get("gps_time_utc"),
        "gps_fix_valid": (record.get("gps") or {}).get("fix_valid"),
        "gps_latitude": (record.get("gps") or {}).get("latitude"),
        "gps_longitude": (record.get("gps") or {}).get("longitude"),
        "gps_altitude_m": (record.get("gps") or {}).get("altitude_m"),
        "gps_satellites": (record.get("gps") or {}).get("satellites"),
        "detection_count": len(detection_points),
        "has_ir_detection": False,
        "has_ultrasonic_detection": False,
        "has_confirmed_detection": False,
    }

    for sensor_name in ("ir1", "ir2", "ultra1", "ultra2", "ultra3", "ultra4"):
        sensor_info = geometry.get(sensor_name, {})
        reading = readings.get(sensor_name) or legacy_sensor_reading(record, sensor_name)
        status_text = reading.get("status")
        sensor_type = sensor_info.get("type", reading.get("type"))
        row[sensor_name + "_status"] = status_text
        row[sensor_name + "_angle_degrees"] = reading.get("angle_degrees")
        row[sensor_name + "_geometry_offset_degrees"] = sensor_info.get("angle_offset")

        if sensor_type == "ir":
            summary = reading.get("temperature_summary") or summarize_temperatures(reading.get("temperatures_c") or [])
            row[sensor_name + "_temp_count"] = summary["count"]
            row[sensor_name + "_temp_min_c"] = summary["min_c"]
            row[sensor_name + "_temp_max_c"] = summary["max_c"]
            row[sensor_name + "_temp_avg_c"] = summary["avg_c"]
            if is_detection(status_text):
                row["has_ir_detection"] = True

        if sensor_type == "ultrasonic":
            row[sensor_name + "_distance_cm"] = reading.get("distance_cm")
            if is_detection(status_text):
                row["has_ultrasonic_detection"] = True

        if status_text == "Hidden Camera":
            row["has_confirmed_detection"] = True

    return row


def build_filter_scan_export():
    records = Storage.load()
    return {
        "schema": "snare-filter-scan-v1",
        "created_at": format_timestamp(time.time()),
        "timestamp": time.time(),
        "purpose": "Filter-ready scan features plus raw records for later detection tuning.",
        "rotation_time_seconds": ROTATION_TIME,
        "sample_interval_seconds": SCAN_SAMPLE_INTERVAL,
        "sensor_geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "samples": [build_filter_row(record) for record in records],
        "raw_records": records,
    }


def build_radar_scan_export():
    records = Storage.load()
    return {
        "schema": "snare-radar-scan-v1",
        "created_at": format_timestamp(time.time()),
        "timestamp": time.time(),
        "sensor_geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "max_distance_cm": getattr(config, "GRAPH_MAX_DISTANCE_CM", 500),
        "rotation_time_seconds": ROTATION_TIME,
        "sample_interval_seconds": SCAN_SAMPLE_INTERVAL,
        "record_count": len(records),
        "gps": gps_reader.last_fix,
        "records": records,
        "latest_live": load_live_scan_data(),
    }


def handle_usb_commands():
    Wifi_manager.handle_usb_commands(
        serial_state,
        status_callback=status,
        clear_data_callback=clear_stored_data,
        live_data_callback=load_live_scan_data,
        live_graph_callback=build_live_terminal_image,
        set_live_callback=set_live_scan,
        wifi_connected_callback=flash_wifi_connected,
        run_scan_callback=scan_with_rotation,
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


def flash_red(times=1, duration=0.2):
    for _ in range(times):
        red_on(); time.sleep(duration)
        red_off(); time.sleep(duration)


def flash_wifi_connected():
    # Three quick green flashes confirm that the saved Wi-Fi credentials connected successfully.
    green_off()
    time.sleep(0.1)
    flash_green(times=3, duration=0.18)
    green_on()


def trigger_stop():
    global stop_flag
    stop_flag = True
    status("30 second hold detected: turning the device off.")
    motor.stop()
    for _ in range(3):
        red_on(); green_on(); time.sleep(0.1)
        red_off(); green_off(); time.sleep(0.1)
    try:
        bluetooth.stop()
    except Exception:
        pass
    red_off()
    green_off()


def wait_for_button_action(allow_scan=False):
    if not button_is_pressed():
        return None

    press_start = time.time()
    setup_indicator_on = False
    setup_announced = False

    while button_is_pressed():
        elapsed = time.time() - press_start
        if elapsed >= SETUP_HOLD_TIME and not setup_indicator_on:
            # A solid green LED confirms the setup threshold was reached, and rotation stops
            # before the setup portal starts so Wi-Fi/Bluetooth setup is handled first.
            motor.stop()
            red_off()
            green_on()
            setup_indicator_on = True
            set_live_scan_status("setup-requested", "Button hold reached 10 seconds. Rotation stopped for setup.")
        if elapsed >= SETUP_HOLD_TIME and not setup_announced:
            status("10 second hold detected: rotation stopped. Release now to open Bluetooth and Wi-Fi setup.")
            setup_announced = True
        if elapsed >= STOP_HOLD_TIME:
            trigger_stop()
            return "stop"
        time.sleep(0.1)

    press_duration = time.time() - press_start

    if press_duration >= SETUP_HOLD_TIME:
        status("Setup mode requested by 10 second button hold.")
        return "setup"

    if setup_indicator_on:
        green_off()

    if allow_scan and press_duration <= SCAN_CLICK_MAX_TIME:
        status("Scan requested by short button press.")
        return "scan"

    if allow_scan:
        status("Button press ignored. Short press starts scan, 10 second hold opens setup, 30 second hold stops.")

    return None


# --- Stop button check ---
def check_stop():
    return wait_for_button_action(allow_scan=False) == "stop"


def check_scan_mode_request():
    return wait_for_button_action(allow_scan=False)


def setup_exit_requested():
    if not button_is_pressed():
        return False

    status("Setup button press detected. Press again quickly to run a live scan, release to close setup, or hold 30 seconds to turn off.")
    press_start = time.time()
    while button_is_pressed():
        if time.time() - press_start >= STOP_HOLD_TIME:
            trigger_stop()
            return True
        time.sleep(0.05)

    wait_start = time.time()
    double_press_window = getattr(config, "SETUP_DOUBLE_PRESS_SECONDS", 1.0)
    while time.time() - wait_start < double_press_window:
        if button_is_pressed():
            status("Double click detected: starting rotation while Wi-Fi stays open for live radar.")
            while button_is_pressed():
                time.sleep(0.05)
            return "scan"
        time.sleep(0.05)

    status("Single click detected: closing the Wi-Fi setup portal.")
    return True

# --- Scanning function ---
def scan_with_rotation(portal_poll_callback=None):
    global stop_flag
    status("Starting 360 degree scan.")
    set_live_scan_status("starting", "Live scan is starting.")
    scan_started_at = time.time()
    scan_id = int(scan_started_at)
    scan_result = "complete"
    reset_live_scan()

    def poll_portal_during_scan():
        # The setup portal is serviced during web-started scans so live radar JSON keeps updating.
        if not portal_poll_callback:
            return None
        try:
            action = portal_poll_callback()
            if action == "stop-live-scan":
                status("Stop Live Scan requested from the radar page.")
            return action
        except Exception as exc:
            status("Live radar portal service warning: {}".format(exc))
            return None

    def sleep_with_portal(duration):
        end_time = time.time() + duration
        while time.time() < end_time:
            if poll_portal_during_scan() == "stop-live-scan":
                return "stop-live-scan"
            remaining = end_time - time.time()
            time.sleep(min(0.1, max(0, remaining)))
        return None

    # Flash green LED for 5 seconds at start
    start_time = time.time()
    while time.time() - start_time < 5:
        if poll_portal_during_scan() == "stop-live-scan":
            scan_result = "portal-stop"
            return "portal-stop"
        usb_action = handle_usb_commands()
        if usb_action == "setup":
            scan_result = "setup"
            return "setup"
        button_action = check_scan_mode_request()
        if stop_flag or button_action == "stop":
            scan_result = "stop"
            return "stop"
        if button_action == "setup":
            scan_result = "setup"
            return "setup"
        green_on()
        if sleep_with_portal(0.5) == "stop-live-scan":
            green_off()
            scan_result = "portal-stop"
            return "portal-stop"
        green_off()
        if sleep_with_portal(0.5) == "stop-live-scan":
            scan_result = "portal-stop"
            return "portal-stop"

    status("Motor starting rotation.")
    set_live_scan_status("running", "Live scan is running. Radar samples will update as the platform rotates.")
    red_on()               # solid red during scan
    motor.set_speed_percent(80)  # slow rotation
    start = time.time()

    try:
        while time.time() - start < ROTATION_TIME:
            if poll_portal_during_scan() == "stop-live-scan":
                scan_result = "portal-stop"
                return "portal-stop"
            usb_action = handle_usb_commands()
            if usb_action == "setup":
                scan_result = "setup"
                return "setup"
            button_action = check_scan_mode_request()
            if stop_flag or button_action == "stop":
                scan_result = "stop"
                return "stop"
            if button_action == "setup":
                scan_result = "setup"
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
            sample_details["hits"] = build_hit_summary(sample_details["detection_points"])
            sample_details["gps"] = current_gps_snapshot()
            update_live_scan(sample_details)

            # --- Store scan data ---
            # The saved format stays simple so it is easy to decrypt and download later.
            # Up to 50 scan records are kept on the device, and each record is labeled by order and stored time.
            scan_number = get_next_scan_number()
            record = build_scan_record(scan_number, ultra_results, ir_results, sample_details)
            if not Storage.append(record, limit=DATA_LIMIT):
                status("Storage save skipped for this sample so the scan can continue.")

            # --- LED feedback ---
            # Both LEDs flash when any sensor suggests a likely or possible hidden camera.
            if "Hidden Camera" in ir_results + ultra_results or "Maybe Hidden Camera" in ir_results + ultra_results:
                flash_both(0.2)
                red_on()  # back to solid red

            if sleep_with_portal(SCAN_SAMPLE_INTERVAL) == "stop-live-scan":
                scan_result = "portal-stop"
                return "portal-stop"
    finally:
        # The motor is stopped in a finally block so the platform shuts down cleanly even if scanning exits early.
        motor.stop()
        red_off()
        status("Motor rotation finished.")
        if scan_result == "complete":
            set_live_scan_status("complete", "Live scan complete. Downloads and replay data are ready.")
            status("Scan complete.")
        elif scan_result == "portal-stop":
            set_live_scan_status("stopped", "Live scan stopped from the radar page.")
            status("Live scan stopped from the radar page.")
        elif scan_result == "setup":
            set_live_scan_status("setup-requested", "Live scan paused because setup mode was requested.")
            status("Scan paused because setup mode was requested.")
        elif scan_result == "stop":
            set_live_scan_status("stopped", "Scan stopped by the user.")
            status("Scan stopped by the user.")

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
        clear_stored_data()

    Wifi_manager.start_setup(
        stop_checker=None,
        exit_checker=setup_exit_requested,
        heartbeat=setup_heartbeat,
        status_callback=status,
        load_data_callback=load_download_data,
        clear_data_callback=clear_download_data,
        build_graph_callback=build_graph_download,
        build_live_page_callback=build_live_radar_page,
        build_replay_callback=build_radar_replay_download,
        radar_data_callback=build_radar_scan_export,
        filter_data_callback=build_filter_scan_export,
        live_data_callback=load_live_scan_data,
        live_graph_callback=build_live_terminal_image,
        set_live_callback=set_live_scan,
        wifi_connected_callback=flash_wifi_connected,
        run_scan_callback=scan_with_rotation,
    )
    red_off()
    green_off()
    bluetooth.stop()

    if stop_flag:
        status("Setup/download portal closed because execution was stopped.")
        return

    flash_red(times=1, duration=0.2)
    status("Setup/download portal closed.")

# --- Boot ---
if getattr(config, "AUTO_SCAN_ON_BOOT", False):
    status("Device powering on: initial scan")
    boot_result = scan_with_rotation()
    if boot_result == "setup" and not stop_flag:
        long_press_action()
else:
    status("Device powered on: idle mode.")
    status("Hold the GP{} button for 10 seconds to open Bluetooth/Wi-Fi setup, or short press to scan.".format(config.BUTTON_PIN))

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

    if button_is_pressed():
        button_action = wait_for_button_action(allow_scan=True)
        if button_action == "stop":
            continue
        if button_action == "setup":
            long_press_action()
        elif button_action == "scan":
            scan_result = scan_with_rotation()
            if scan_result == "setup" and not stop_flag:
                long_press_action()

    time.sleep(0.2)
