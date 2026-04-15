import socket
import json
import time
import config

try:
    import uselect as select
except ImportError:
    import select

import sys

CONFIG_FILE = "wifi.json"


def _set_wireless_country():
    # The wireless country is set before Wi-Fi startup so the radio uses the correct regional configuration.
    try:
        import rp2
        if hasattr(rp2, "country"):
            rp2.country(config.WIRELESS_COUNTRY)
    except Exception as exc:
        _serial_print("Wireless country setup warning: {}".format(exc))


def _get_network_module():
    _set_wireless_country()
    import network
    return network

def _status(status_callback, message):
    # Status messages are centralized here so setup and connection logs stay consistent.
    if status_callback:
        status_callback(message)


def _serial_print(message):
    # USB serial output mirrors setup progress so the Pico can still be configured over microUSB.
    print("[SNARE USB] {}".format(message))


def _url_decode(value):
    # Form values are decoded manually to keep this setup portal lightweight on MicroPython.
    value = value.replace("+", " ")
    result = []
    index = 0
    while index < len(value):
        if value[index] == "%" and index + 2 < len(value):
            try:
                result.append(chr(int(value[index + 1:index + 3], 16)))
                index += 3
                continue
            except ValueError:
                pass
        result.append(value[index])
        index += 1
    return "".join(result)


def _parse_request_fields(request):
    # Both query-string and POST-body form fields are supported so the setup page is more forgiving.
    try:
        request_str = request.decode()
    except Exception:
        return {}

    if "\r\n\r\n" in request_str:
        body = request_str.split("\r\n\r\n", 1)[1]
    else:
        body = ""

    query = ""
    first_line = request_str.split("\r\n", 1)[0]
    if "?" in first_line and " HTTP/" in first_line:
        query = first_line.split("?", 1)[1].split(" HTTP/", 1)[0]

    payload = body or query
    fields = {}
    for pair in payload.split("&"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        fields[key] = _url_decode(value)
    return fields


def _send_html(client, body, status="200 OK"):
    # A small HTML page is returned so the user can enter Wi-Fi credentials and manage stored scan data from a phone.
    response = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
        "{}"
    ).format(status, body)
    client.send(response.encode("utf-8"))


def _send_redirect(client, location):
    # Redirects help phones and laptops land on the local setup page even if they request another URL first.
    response = (
        "HTTP/1.1 302 Found\r\n"
        "Location: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(location)
    client.send(response.encode("utf-8"))


def _send_json_download(client, payload, file_name="snare_scan_data.json"):
    # JSON is returned as a downloadable attachment so the connected phone can save the scan results directly.
    body = json.dumps(payload, indent=2)
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Disposition: attachment; filename=\"{}\"\r\n"
        "Connection: close\r\n\r\n"
        "{}"
    ).format(file_name, body)
    client.send(response.encode("utf-8"))


def _serial_help():
    return (
        "USB setup commands:\n"
        "  help\n"
        "  ssid <wifi-name>\n"
        "  password <wifi-password>\n"
        "  save\n"
        "  status\n"
        "  download\n"
        "  clear\n"
        "  exit\n"
    )


def _safe_read_line():
    try:
        line = sys.stdin.readline()
    except Exception:
        return None
    if not line:
        return None
    return line.strip()


def _handle_usb_serial(serial_state, status_callback=None, load_data_callback=None, clear_data_callback=None):
    # USB serial commands provide a setup/download fallback when Wi-Fi or BLE discovery is unreliable.
    try:
        readers, _, _ = select.select([sys.stdin], [], [], 0)
    except Exception:
        return False

    if not readers:
        return False

    line = _safe_read_line()
    if not line:
        return False

    command, _, argument = line.partition(" ")
    command = command.lower()
    argument = argument.strip()

    if command == "help":
        _serial_print(_serial_help())
        return False

    if command == "ssid":
        serial_state["ssid"] = argument
        _serial_print("SSID staged as '{}'.".format(argument))
        return False

    if command == "password":
        serial_state["password"] = argument
        _serial_print("Wi-Fi password staged.")
        return False

    if command == "save":
        if not serial_state["ssid"] or not serial_state["password"]:
            _serial_print("Both SSID and password must be provided before save.")
            return False

        save_wifi(serial_state["ssid"], serial_state["password"])
        connected = connect_wifi(status_callback=status_callback)
        if connected:
            _serial_print("Wi-Fi credentials saved and Pico connected to Wi-Fi.")
        else:
            _serial_print("Wi-Fi credentials saved, but Pico could not connect to Wi-Fi.")
        return False

    if command == "status":
        creds = load_wifi() or {}
        network = _get_network_module()
        wlan = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)
        _serial_print("AP active: {}".format(ap.active()))
        _serial_print("Saved SSID: {}".format(creds.get("ssid", "<none>")))
        _serial_print("STA connected: {}".format(wlan.isconnected()))
        if wlan.isconnected():
            _serial_print("STA IP: {}".format(wlan.ifconfig()[0]))
        return False

    if command == "download":
        payload = load_data_callback() if load_data_callback else []
        _serial_print("BEGIN-DOWNLOAD")
        print(json.dumps(payload, indent=2))
        _serial_print("END-DOWNLOAD")
        if clear_data_callback:
            clear_data_callback()
            _serial_print("Stored scan data cleared after USB download.")
        return False

    if command == "clear":
        if clear_data_callback:
            clear_data_callback()
        _serial_print("Stored scan data cleared from the Pico.")
        return False

    if command == "exit":
        _serial_print("USB setup requested portal exit.")
        return True

    _serial_print("Unknown command.")
    _serial_print(_serial_help())
    return False


def _build_setup_page(message=""):
    # The setup page stays simple because it only needs Wi-Fi provisioning plus data download controls.
    notice = "<p>{}</p>".format(message) if message else ""
    return """<!doctype html>
<html>
<head><title>SNARE Setup</title></head>
<body>
  <h1>SNARE Setup and Data Download</h1>
  <p>Enter the Wi-Fi name and Wi-Fi password to save them on the Pico and connect the device.</p>
  <p>Use the download button to save the decrypted scan data directly to the connected phone.</p>
  <p>Downloaded scan data is automatically cleared from the Pico after a successful download.</p>
  <p>If the setup page does not open automatically, browse to <strong>http://192.168.4.1/</strong>.</p>
  {notice}
  <form action="/save" method="post">
    <label>Wi-Fi SSID<br><input name="ssid" required></label><br><br>
    <label>Wi-Fi Password<br><input name="password" type="password" required></label><br><br>
    <button type="submit">Save Wi-Fi</button>
  </form>
  <br>
  <form action="/download" method="get">
    <button type="submit">Download Stored Data</button>
  </form>
  <br>
  <form action="/clear" method="post">
    <button type="submit">Clear Stored Data</button>
  </form>
</body>
</html>""".format(notice=notice)


def save_wifi(ssid, password):
    # Wi-Fi credentials are stored locally so the device can reuse them later without reflashing.
    data = {"ssid": ssid, "password": password}
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

def load_wifi():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def connect_wifi(status_callback=None):
    network = _get_network_module()
    creds = load_wifi()
    if not creds:
        _status(status_callback, "No saved Wi-Fi credentials were found.")
        return False

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        # This short-circuits reconnection so an existing working connection is not interrupted.
        _status(status_callback, "Wi-Fi was already connected.")
        return True

    _status(status_callback, "Starting Wi-Fi transmission to '{}'.".format(creds["ssid"]))
    wlan.connect(creds["ssid"], creds["password"])

    # This helper is kept for future use even though the download workflow does not depend on joining another network.
    timeout = 15
    while timeout > 0:
        if wlan.isconnected():
            _status(status_callback, "Wi-Fi connected with IP {}.".format(wlan.ifconfig()[0]))
            return True
        time.sleep(1)
        timeout -= 1

    _status(status_callback, "Wi-Fi connection failed.")
    return False


def start_setup(stop_checker=None, heartbeat=None, status_callback=None, load_data_callback=None, clear_data_callback=None):
    # A temporary AP and lightweight web portal are opened so setup and data download do not require reflashing code.
    network = _get_network_module()
    ap = network.WLAN(network.AP_IF)
    sta = network.WLAN(network.STA_IF)
    try:
        sta.active(False)
    except Exception:
        pass
    ap.active(True)
    time.sleep(0.5)
    ap_started_with_password = False
    authmode_wpa2 = getattr(network, "AUTH_WPA2_PSK", 3)
    config_attempts = []

    if getattr(config, "AP_PASSWORD", ""):
        config_attempts.extend([
            {"ssid": config.AP_SSID, "password": config.AP_PASSWORD, "authmode": authmode_wpa2, "channel": config.AP_CHANNEL},
            {"essid": config.AP_SSID, "password": config.AP_PASSWORD, "authmode": authmode_wpa2, "channel": config.AP_CHANNEL},
        ])

    config_attempts.extend([
        {"ssid": config.AP_SSID, "channel": config.AP_CHANNEL},
        {"essid": config.AP_SSID, "channel": config.AP_CHANNEL},
    ])

    last_config_error = None
    for attempt in config_attempts:
        try:
            ap.config(**attempt)
            ap_started_with_password = "password" in attempt
            last_config_error = None
            break
        except Exception as exc:
            last_config_error = exc

    try:
        ap_name = ap.config("ssid")
    except Exception:
        ap_name = config.AP_SSID

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    server = socket.socket()
    try:
        server.settimeout(0.2)
    except Exception:
        pass
    server.bind(addr)
    server.listen(1)
    _status(status_callback, "Connect your phone to the Wi-Fi network '{}' to save Wi-Fi and download scan data.".format(ap_name))
    _status(status_callback, "Setup portal IP address: {}.".format(ap.ifconfig()[0]))
    _status(status_callback, "If the phone does not open the page automatically, browse to http://192.168.4.1/.")
    if ap_started_with_password:
        _status(status_callback, "Setup portal password: {}.".format(config.AP_PASSWORD))
    elif last_config_error is not None and getattr(config, "AP_PASSWORD", ""):
        _status(status_callback, "Passworded AP setup was not accepted by this firmware, so the portal may be open instead.")
    _serial_print("Setup portal started.")
    _serial_print("Expected Wi-Fi name: {}".format(ap_name))
    _serial_print("Portal IP: {}".format(ap.ifconfig()[0]))
    _serial_print("AP channel: {}".format(config.AP_CHANNEL))
    if ap_started_with_password:
        _serial_print("Portal password: {}".format(config.AP_PASSWORD))
    elif last_config_error is not None and getattr(config, "AP_PASSWORD", ""):
        _serial_print("Passworded AP setup warning: {}".format(last_config_error))
    _serial_print(_serial_help())

    serial_state = {"ssid": None, "password": None}

    try:
        while True:
            # Heartbeat is called regularly so the red LED can blink while the portal waits for a client.
            if heartbeat:
                heartbeat()
            if stop_checker and stop_checker():
                _status(status_callback, "Wi-Fi setup was cancelled.")
                return None

            if _handle_usb_serial(
                serial_state,
                status_callback=status_callback,
                load_data_callback=load_data_callback,
                clear_data_callback=clear_data_callback,
            ):
                _status(status_callback, "USB setup requested portal exit.")
                return None

            try:
                client, _ = server.accept()
            except OSError:
                continue

            try:
                request = client.recv(2048)
                request_str = request.decode()
                first_line = request_str.split("\r\n", 1)[0]
                request_path = "/"
                if len(first_line.split()) >= 2:
                    request_path = first_line.split()[1]
                if "?" in request_path:
                    request_path = request_path.split("?", 1)[0]

                fields = _parse_request_fields(request)

                # Redirect common captive-portal probes and unknown paths to the local setup page.
                captive_probe_paths = {
                    "/hotspot-detect.html",
                    "/library/test/success.html",
                    "/generate_204",
                    "/gen_204",
                    "/connecttest.txt",
                    "/ncsi.txt",
                    "/redirect",
                    "/success.txt",
                    "/canonical.html",
                    "/fwlink",
                }

                if request_path == "/save":
                    ssid = fields.get("ssid")
                    password = fields.get("password")
                    if ssid and password:
                        # Saving happens only after both Wi-Fi fields are present.
                        save_wifi(ssid, password)
                        connected = connect_wifi(status_callback=status_callback)
                        if connected:
                            _send_html(client, _build_setup_page("Wi-Fi credentials saved and the Pico connected to Wi-Fi."))
                            _status(status_callback, "Wi-Fi credentials were saved and the Pico connected to Wi-Fi.")
                        else:
                            _send_html(client, _build_setup_page("Wi-Fi credentials saved, but the Pico could not connect to Wi-Fi."))
                            _status(status_callback, "Wi-Fi credentials were saved, but the Pico could not connect to Wi-Fi.")
                    else:
                        _send_html(client, _build_setup_page("Both Wi-Fi fields are required."))
                    continue

                if request_path == "/download":
                    payload = load_data_callback() if load_data_callback else []
                    _send_json_download(client, payload)
                    if clear_data_callback:
                        clear_data_callback()
                    _status(status_callback, "Stored scan data was downloaded to the connected phone and then cleared from the Pico.")
                    continue

                if request_path == "/clear":
                    if clear_data_callback:
                        clear_data_callback()
                    _send_html(client, _build_setup_page("Stored scan data cleared from the device."))
                    _status(status_callback, "Data on the device has been cleared.")
                    continue

                if request_path in captive_probe_paths:
                    _send_redirect(client, "http://192.168.4.1/")
                    continue

                if request_path not in ("/", "/index.html"):
                    _send_redirect(client, "http://192.168.4.1/")
                    continue

                _send_html(client, _build_setup_page())
            finally:
                client.close()
    finally:
        try:
            server.close()
        except Exception:
            pass
        ap.active(False)
