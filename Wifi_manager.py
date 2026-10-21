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


def _send_all(client, data):
    # Sending in chunks is more reliable for larger JSON/HTML downloads on phones and computers.
    total_sent = 0
    while total_sent < len(data):
        try:
            sent = client.send(data[total_sent:total_sent + 1024])
        except OSError:
            # Browsers sometimes disconnect during refreshes; the portal should keep running anyway.
            return False
        if not sent:
            return False
        total_sent += sent
    return True


def _open_http_server(addr, status_callback=None):
    # Reusing the socket address prevents soft-restart crashes when an older portal socket is still closing.
    last_error = None
    for attempt in range(5):
        server = socket.socket()
        try:
            try:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            try:
                server.settimeout(0.2)
            except Exception:
                pass
            server.bind(addr)
            server.listen(3)
            return server
        except OSError as exc:
            last_error = exc
            try:
                server.close()
            except Exception:
                pass
            _status(status_callback, "Setup portal socket was busy; retrying web server start.")
            time.sleep(0.5)
        except Exception:
            try:
                server.close()
            except Exception:
                pass
            raise
    raise last_error


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
    body_bytes = body.encode("utf-8")
    response = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, len(body_bytes))
    return _send_all(client, response.encode("utf-8") + body_bytes)


def _send_redirect(client, location):
    # Redirects help phones land on the setup page even if they probe another captive-portal URL first.
    response = (
        "HTTP/1.1 302 Found\r\n"
        "Location: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Length: 0\r\n"
        "Connection: close\r\n\r\n"
    ).format(location)
    return _send_all(client, response.encode("utf-8"))


def _send_json_download(client, payload, file_name="snare_scan_data.json"):
    # JSON is returned as a downloadable attachment so the connected phone can save the scan results directly.
    body = _json_dumps(payload, pretty=True)
    body_bytes = body.encode("utf-8")
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Disposition: attachment; filename=\"{}\"\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(file_name, len(body_bytes))
    return _send_all(client, response.encode("utf-8") + body_bytes)


def _json_dumps(payload, pretty=False):
    try:
        if pretty:
            return json.dumps(payload, indent=2)
        return json.dumps(payload)
    except TypeError:
        return json.dumps(payload)


def _send_text_download(client, body, content_type, file_name):
    body_bytes = body.encode("utf-8")
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: {}\r\n"
        "Content-Disposition: attachment; filename=\"{}\"\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(content_type, file_name, len(body_bytes))
    return _send_all(client, response.encode("utf-8") + body_bytes)


def _send_json(client, payload):
    body = _json_dumps(payload, pretty=True)
    body_bytes = body.encode("utf-8")
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(len(body_bytes))
    return _send_all(client, response.encode("utf-8") + body_bytes)


def _safe_send_html(client, body, status="200 OK"):
    try:
        return _send_html(client, body, status=status)
    except OSError:
        return False


def _serial_help():
    return (
        "USB setup commands:\n"
        "  help\n"
        "  ssid <wifi-name>\n"
        "  password <wifi-password>\n"
        "  save\n"
        "  status\n"
        "  wifi       (open Wi-Fi setup/download portal)\n"
        "  live\n"
        "  live on\n"
        "  live off\n"
        "  live image\n"
        "  clean\n"
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


def _handle_usb_serial(
    serial_state,
    status_callback=None,
    clear_data_callback=None,
    live_data_callback=None,
    live_graph_callback=None,
    set_live_callback=None,
    wifi_connected_callback=None,
    enable_exit=True,
):
    # USB serial commands stay focused on setup, live viewing, and manual cleaning.
    try:
        readers, _, _ = select.select([sys.stdin], [], [], 0)
    except Exception:
        return False

    if not readers:
        return False

    line = _safe_read_line()
    if not line:
        return False

    if ":" in line and (line.split(":", 1)[0].lower() in ("ssid", "password", "pass")):
        command, argument = line.split(":", 1)
    else:
        command, _, argument = line.partition(" ")
    command = command.lower()
    argument = argument.strip()
    if command.endswith(":"):
        command = command[:-1]
    if command == "pass":
        command = "password"

    if command == "help":
        _serial_print(_serial_help())
        return False

    if command == "ssid":
        serial_state["ssid"] = argument
        _serial_print("SSID staged as '{}'.".format(argument))
        _serial_print("Type password: <wifi-password>, then type save.")
        return False

    if command == "password":
        serial_state["password"] = argument
        _serial_print("Wi-Fi password staged.")
        _serial_print("Type save to store the Wi-Fi credentials and connect.")
        return False

    if command == "save":
        if not serial_state["ssid"] or not serial_state["password"]:
            _serial_print("Both SSID and password must be provided before save.")
            return False

        save_wifi(serial_state["ssid"], serial_state["password"])
        connected = connect_wifi(status_callback=status_callback)
        if connected:
            _serial_print("Wi-Fi credentials saved and Pico connected to Wi-Fi.")
            if wifi_connected_callback:
                wifi_connected_callback()
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

    if command == "wifi":
        if serial_state is not None:
            serial_state["wifi_requested"] = True
        _serial_print("Wi-Fi setup/download portal requested.")
        return False

    if command == "live":
        option = argument.lower()
        if option in ("on", "start"):
            if set_live_callback:
                set_live_callback(True)
            _serial_print("Live scan terminal output enabled.")
            return False
        if option in ("off", "stop"):
            if set_live_callback:
                set_live_callback(False)
            _serial_print("Live scan terminal output disabled.")
            return False

        if option in ("image", "graph", "scan"):
            if live_graph_callback:
                print(live_graph_callback())
            else:
                _serial_print("Live scan image is not available in this mode.")
            return False

        payload = live_data_callback() if live_data_callback else {}
        _serial_print("LATEST-LIVE-SCAN")
        print(_json_dumps(payload, pretty=True))
        return False

    if command in ("clear", "clean"):
        if clear_data_callback:
            clear_data_callback()
        _serial_print("Stored scan data cleaned from the Pico.")
        return False

    if command == "exit":
        if not enable_exit:
            _serial_print("Exit is only used while the setup portal is open.")
            return False
        _serial_print("USB setup requested portal exit.")
        return True

    _serial_print("Unknown command.")
    _serial_print(_serial_help())
    return False


def handle_usb_commands(
    serial_state,
    status_callback=None,
    clear_data_callback=None,
    live_data_callback=None,
    live_graph_callback=None,
    set_live_callback=None,
    wifi_connected_callback=None,
    run_scan_callback=None,
):
    return _handle_usb_serial(
        serial_state,
        status_callback=status_callback,
        clear_data_callback=clear_data_callback,
        live_data_callback=live_data_callback,
        live_graph_callback=live_graph_callback,
        set_live_callback=set_live_callback,
        wifi_connected_callback=wifi_connected_callback,
        enable_exit=False,
    )


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
  <p>The portal stays open after Wi-Fi connects, so downloads and live radar remain available.</p>
  <p>Downloads do not clean the Pico. Use Clean Stored Data only after confirming the file saved.</p>
  <p>If the page does not open automatically, browse to <strong>http://192.168.4.1/</strong>.</p>
  {notice}
  <form action="/save" method="post">
    <label>Wi-Fi SSID<br><input name="ssid" required></label><br><br>
    <label>Wi-Fi Password<br><input name="password" type="password" required></label><br><br>
    <button type="submit">Save Wi-Fi</button>
  </form>
  <br>
  <form action="/download" method="get">
    <button type="submit">Download Stored Data JSON</button>
  </form>
  <br>
  <form action="/download-graph" method="get">
    <button type="submit">Download Scan Graph</button>
  </form>
  <br>
  <form action="/live-scan" method="get">
    <button type="submit">Live Scan Radar</button>
  </form>
  <br>
  <form action="/download-live" method="get">
    <button type="submit">Download Live Radar JSON</button>
  </form>
  <br>
  <form action="/download-radar-json" method="get">
    <button type="submit">Download Radar Scan JSON</button>
  </form>
  <br>
  <form action="/download-radar-video" method="get">
    <button type="submit">Download Radar Replay Video</button>
  </form>
  <br>
  <form action="/download-filter" method="get">
    <button type="submit">Download Filter-Ready JSON</button>
  </form>
  <br>
  <form action="/clean" method="post" onsubmit="return confirm('Clean stored scan data from the Pico?');">
    <button type="submit">Clean Stored Data</button>
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


def _wifi_status_text(network, status_code):
    # MicroPython exposes helpful status constants when a Wi-Fi connection fails.
    status_names = (
        "STAT_IDLE",
        "STAT_CONNECTING",
        "STAT_WRONG_PASSWORD",
        "STAT_NO_AP_FOUND",
        "STAT_CONNECT_FAIL",
        "STAT_GOT_IP",
    )
    for name in status_names:
        try:
            if getattr(network, name) == status_code:
                return name
        except Exception:
            pass
    return str(status_code)


def _decode_ssid(raw_ssid):
    try:
        return raw_ssid.decode()
    except Exception:
        return str(raw_ssid)


def _report_target_visibility(wlan, ssid, status_callback=None):
    # A quick scan tells whether the requested hotspot is visible before the Pico tries to join it.
    try:
        networks = wlan.scan()
    except Exception as exc:
        _status(status_callback, "Wi-Fi scan skipped: {}".format(exc))
        return None

    for network_info in networks:
        found_ssid = _decode_ssid(network_info[0])
        if found_ssid == ssid:
            channel = network_info[2] if len(network_info) > 2 else "?"
            rssi = network_info[3] if len(network_info) > 3 else "?"
            _status(status_callback, "Target Wi-Fi '{}' was found on channel {} with RSSI {}.".format(ssid, channel, rssi))
            return {"channel": channel, "rssi": rssi}

    _status(status_callback, "Target Wi-Fi '{}' was not seen during scan.".format(ssid))
    _status(status_callback, "If this is an iPhone hotspot, turn on Maximize Compatibility and keep Personal Hotspot open.")
    _status(status_callback, "Use a second phone/computer for the SNARE portal if the hotspot phone cannot host and connect to SNARE_Device_101 at the same time.")
    return None


def _align_ap_channel_with_target(network, target_info, status_callback=None):
    # The Pico has one Wi-Fi radio, so AP and station mode are more reliable on the same channel.
    if not target_info:
        return
    channel = target_info.get("channel")
    if not isinstance(channel, int):
        return

    try:
        ap = network.WLAN(network.AP_IF)
    except Exception:
        return
    if not ap.active():
        return

    try:
        current_channel = ap.config("channel")
    except Exception:
        current_channel = None
    if current_channel == channel:
        return

    _status(status_callback, "Moving SNARE portal AP to channel {} to match the hotspot.".format(channel))
    _status(status_callback, "The computer may briefly disconnect from SNARE_Device_101; reconnect and refresh http://192.168.4.1/ if needed.")
    try:
        ap.config(channel=channel)
        time.sleep(0.5)
    except Exception as exc:
        _status(status_callback, "Could not move AP channel: {}".format(exc))


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
    target_info = _report_target_visibility(wlan, creds["ssid"], status_callback=status_callback)
    _align_ap_channel_with_target(network, target_info, status_callback=status_callback)
    wlan.connect(creds["ssid"], creds["password"])

    # This helper is kept for future use even though the download workflow does not depend on joining another network.
    timeout = getattr(config, "WIFI_CONNECT_TIMEOUT_SECONDS", 30)
    last_status = None
    while timeout > 0:
        if wlan.isconnected():
            _status(status_callback, "Wi-Fi connected with IP {}.".format(wlan.ifconfig()[0]))
            return True
        try:
            current_status = wlan.status()
        except Exception:
            current_status = None
        if current_status != last_status and current_status is not None:
            _status(status_callback, "Wi-Fi status: {}.".format(_wifi_status_text(network, current_status)))
            last_status = current_status
        time.sleep(1)
        timeout -= 1

    try:
        final_status = wlan.status()
    except Exception:
        final_status = "unknown"
    _status(status_callback, "Wi-Fi connection failed with status {}.".format(_wifi_status_text(network, final_status)))
    return False


def start_setup(
    stop_checker=None,
    exit_checker=None,
    heartbeat=None,
    status_callback=None,
    load_data_callback=None,
    clear_data_callback=None,
    build_graph_callback=None,
    build_live_page_callback=None,
    build_replay_callback=None,
    radar_data_callback=None,
    filter_data_callback=None,
    live_data_callback=None,
    live_graph_callback=None,
    set_live_callback=None,
    wifi_connected_callback=None,
    run_scan_callback=None,
):
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
    server = _open_http_server(addr, status_callback=status_callback)
    _status(status_callback, "Connect your phone to the Wi-Fi network '{}' to save Wi-Fi and download scan data.".format(ap_name))
    _status(status_callback, "Setup portal IP address: {}.".format(ap.ifconfig()[0]))
    _status(status_callback, "Download works directly from the Pico portal. The Pico does not need to join another Wi-Fi network first.")
    _status(status_callback, "Phones and computers may show 'No Internet'; stay connected because this is a local Pico portal.")
    _status(status_callback, "Press the button again to close setup mode.")
    _status(status_callback, "If the phone does not open the page automatically, browse to http://192.168.4.1/.")
    if ap_started_with_password:
        _status(status_callback, "Setup portal password: {}.".format(config.AP_PASSWORD))
    elif last_config_error is not None and getattr(config, "AP_PASSWORD", ""):
        _status(status_callback, "Passworded AP setup was not accepted by this firmware, so the portal may be open instead.")
    _serial_print("Setup portal started.")
    _serial_print("Expected Wi-Fi name: {}".format(ap_name))
    _serial_print("Portal IP: {}".format(ap.ifconfig()[0]))
    _serial_print("AP channel: {}".format(config.AP_CHANNEL))
    _serial_print("No Internet warning is expected; use http://192.168.4.1/ while connected to this Pico Wi-Fi.")
    if ap_started_with_password:
        _serial_print("Portal password: {}".format(config.AP_PASSWORD))
    elif last_config_error is not None and getattr(config, "AP_PASSWORD", ""):
        _serial_print("Passworded AP setup warning: {}".format(last_config_error))
    _serial_print(_serial_help())

    serial_state = {"ssid": None, "password": None}
    portal_state = {"scan_requested": False, "scan_running": False, "stop_requested": False}

    def service_live_client_during_scan():
        # During a web-started scan, this lightweight poll keeps the live radar page receiving data.
        try:
            server.settimeout(0)
        except Exception:
            pass
        try:
            client, _ = server.accept()
        except OSError:
            return None

        try:
            try:
                client.settimeout(0.2)
            except Exception:
                pass
            try:
                request = client.recv(2048)
            except OSError:
                return None
            if not request:
                return None

            try:
                request_str = request.decode()
            except Exception:
                return None
            first_line = request_str.split("\r\n", 1)[0]
            request_path = "/"
            if len(first_line.split()) >= 2:
                request_path = first_line.split()[1]
            if "?" in request_path:
                request_path = request_path.split("?", 1)[0]

            if request_path == "/live.json":
                payload = live_data_callback() if live_data_callback else {}
                _send_json(client, payload)
                return "live-json"

            if request_path in ("/live", "/live-scan"):
                live_page = build_live_page_callback() if build_live_page_callback else "<!doctype html><p>No live radar page is available.</p>"
                _send_html(client, live_page)
                return "live-page"

            if request_path == "/run-live-scan":
                _send_json(client, {
                    "status": "running",
                    "message": "A scan is already running. The live radar will update as samples arrive.",
                })
                return "already-running"

            if request_path == "/stop-live-scan":
                portal_state["stop_requested"] = True
                _send_json(client, {
                    "status": "stopping",
                    "message": "Stop requested. The motor will stop at the next safe scan check.",
                })
                return "stop-live-scan"

            if request_path == "/download-live":
                payload = live_data_callback() if live_data_callback else {}
                _send_json_download(
                    client,
                    payload,
                    getattr(config, "LIVE_SCAN_EXPORT_FILE", "snare_live_scan_data.json"),
                )
                return "download-live"

            _send_redirect(client, "http://192.168.4.1/live-scan")
            return "redirect"
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                server.settimeout(0.2)
            except Exception:
                pass

    try:
        while True:
            # Heartbeat is called regularly so the red LED can blink while the portal waits for a client.
            if heartbeat:
                heartbeat()
            if stop_checker and stop_checker():
                _status(status_callback, "Wi-Fi setup was cancelled.")
                return None
            if exit_checker:
                exit_action = exit_checker()
                if exit_action == "scan":
                    if run_scan_callback:
                        portal_state["scan_requested"] = True
                        _status(status_callback, "Live scan requested from the device button.")
                    else:
                        _status(status_callback, "Button requested live scan, but scan control is unavailable.")
                    continue
                if exit_action:
                    _status(status_callback, "Setup mode closed by button press.")
                    return None

            if portal_state["scan_requested"] and run_scan_callback:
                portal_state["scan_requested"] = False
                portal_state["stop_requested"] = False
                portal_state["scan_running"] = True
                _status(status_callback, "Live radar run requested. Starting scan while portal stays open.")
                try:
                    scan_result = run_scan_callback(service_live_client_during_scan)
                finally:
                    portal_state["scan_running"] = False
                    try:
                        server.settimeout(0.2)
                    except Exception:
                        pass
                _status(status_callback, "Live radar scan finished. Portal is still open.")
                if scan_result == "portal-stop":
                    _status(status_callback, "Live radar scan was stopped from the page. Portal is still open.")
                    continue
                if scan_result == "stop":
                    return None
                continue

            if _handle_usb_serial(
                serial_state,
                status_callback=status_callback,
                clear_data_callback=clear_data_callback,
                live_data_callback=live_data_callback,
                live_graph_callback=live_graph_callback,
                set_live_callback=set_live_callback,
                wifi_connected_callback=wifi_connected_callback,
            ):
                _status(status_callback, "USB setup requested portal exit.")
                return None

            try:
                client, _ = server.accept()
            except OSError:
                continue

            try:
                try:
                    client.settimeout(1.0)
                except Exception:
                    pass
                try:
                    request = client.recv(2048)
                except OSError:
                    continue
                if not request:
                    continue

                try:
                    request_str = request.decode()
                except Exception:
                    continue
                first_line = request_str.split("\r\n", 1)[0]
                request_path = "/"
                if len(first_line.split()) >= 2:
                    request_path = first_line.split()[1]
                if "?" in request_path:
                    request_path = request_path.split("?", 1)[0]

                fields = _parse_request_fields(request)
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

                if request_path == "/run-live-scan":
                    _status(status_callback, "Run Scan Now button was pressed in the live radar page.")
                    if not run_scan_callback:
                        _status(status_callback, "Run Scan Now cannot start because no scan callback is registered.")
                        _send_json(client, {
                            "status": "unavailable",
                            "message": "Run Scan Now is not available in this mode.",
                        })
                    elif portal_state["scan_running"] or portal_state["scan_requested"]:
                        _status(status_callback, "Run Scan Now ignored because a live scan is already running or queued.")
                        _send_json(client, {
                            "status": "running",
                            "message": "A scan is already running. The live radar will update as samples arrive.",
                        })
                    else:
                        portal_state["scan_requested"] = True
                        _send_json(client, {
                            "status": "starting",
                            "message": "Pico received Run Scan Now. Starting scan; keep this page open to watch live radar samples arrive.",
                        })
                        _status(status_callback, "Run Scan Now was queued. The scan will start after the browser response is sent.")
                    continue

                if request_path == "/stop-live-scan":
                    if portal_state["scan_running"]:
                        portal_state["stop_requested"] = True
                        _send_json(client, {
                            "status": "stopping",
                            "message": "Stop requested. The motor will stop at the next safe scan check.",
                        })
                    elif portal_state["scan_requested"]:
                        portal_state["scan_requested"] = False
                        _send_json(client, {
                            "status": "cancelled",
                            "message": "The pending live scan request was cancelled.",
                        })
                    else:
                        _send_json(client, {
                            "status": "idle",
                            "message": "No live scan is running right now.",
                        })
                    continue

                if request_path == "/save":
                    ssid = fields.get("ssid")
                    password = fields.get("password")
                    if ssid and password:
                        # Saving happens only after both Wi-Fi fields are present.
                        save_wifi(ssid, password)
                        connected = connect_wifi(status_callback=status_callback)
                        if connected:
                            _safe_send_html(client, _build_setup_page("Wi-Fi credentials saved and the Pico connected to Wi-Fi. The portal is still open for downloads and live radar."))
                            _status(status_callback, "Wi-Fi credentials were saved and the Pico connected to Wi-Fi.")
                            if wifi_connected_callback:
                                wifi_connected_callback()
                        else:
                            _safe_send_html(client, _build_setup_page("Wi-Fi credentials saved, but the Pico could not connect to Wi-Fi."))
                            _status(status_callback, "Wi-Fi credentials were saved, but the Pico could not connect to Wi-Fi.")
                    else:
                        _safe_send_html(client, _build_setup_page("Both Wi-Fi fields are required."))
                    continue

                if request_path == "/download":
                    payload = load_data_callback() if load_data_callback else []
                    _send_json_download(client, payload)
                    _status(status_callback, "Stored scan data was downloaded. Data was not cleared from the Pico.")
                    continue

                if request_path == "/download-graph":
                    graph_html = build_graph_callback() if build_graph_callback else "<!doctype html><p>No graph data is available.</p>"
                    _send_text_download(
                        client,
                        graph_html,
                        "text/html; charset=utf-8",
                        "snare_scan_graph.html",
                    )
                    _status(status_callback, "Scan graph file was downloaded to the connected phone.")
                    continue

                if request_path in ("/live", "/live-scan"):
                    live_page = build_live_page_callback() if build_live_page_callback else "<!doctype html><p>No live radar page is available.</p>"
                    _send_html(client, live_page)
                    _status(status_callback, "Live radar page opened.")
                    continue

                if request_path == "/download-live":
                    payload = live_data_callback() if live_data_callback else {}
                    _send_json_download(
                        client,
                        payload,
                        getattr(config, "LIVE_SCAN_EXPORT_FILE", "snare_live_scan_data.json"),
                    )
                    _status(status_callback, "Live scan data was downloaded as JSON.")
                    continue

                if request_path == "/download-radar-json":
                    payload = radar_data_callback() if radar_data_callback else (load_data_callback() if load_data_callback else [])
                    _send_json_download(
                        client,
                        payload,
                        getattr(config, "RADAR_JSON_EXPORT_FILE", "snare_radar_scan_data.json"),
                    )
                    _status(status_callback, "Radar scan JSON was downloaded without clearing stored data.")
                    continue

                if request_path == "/download-radar-video":
                    replay_html = build_replay_callback() if build_replay_callback else "<!doctype html><p>No radar replay is available.</p>"
                    _send_text_download(
                        client,
                        replay_html,
                        "text/html; charset=utf-8",
                        getattr(config, "RADAR_REPLAY_EXPORT_FILE", "snare_radar_replay.html"),
                    )
                    _status(status_callback, "Radar replay video HTML was downloaded.")
                    continue

                if request_path == "/download-filter":
                    payload = filter_data_callback() if filter_data_callback else {}
                    _send_json_download(
                        client,
                        payload,
                        getattr(config, "FILTER_SCAN_EXPORT_FILE", "snare_filter_scan_data.json"),
                    )
                    _status(status_callback, "Filter-ready scan JSON was downloaded without clearing stored data.")
                    continue

                if request_path == "/live.json":
                    payload = live_data_callback() if live_data_callback else {}
                    _send_json(client, payload)
                    continue

                if request_path in ("/clear", "/clean"):
                    if clear_data_callback:
                        clear_data_callback()
                    _send_html(client, _build_setup_page("Stored scan data cleaned from the device."))
                    _status(status_callback, "Data on the device has been cleaned.")
                    continue

                if request_path in captive_probe_paths:
                    _send_redirect(client, "http://192.168.4.1/")
                    continue

                if request_path not in ("/", "/index.html"):
                    _send_redirect(client, "http://192.168.4.1/")
                    continue

                _send_html(client, _build_setup_page())
            finally:
                try:
                    client.close()
                except Exception:
                    pass
    finally:
        try:
            server.close()
        except Exception:
            pass
        ap.active(False)
