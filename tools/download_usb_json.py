#!/usr/bin/env python3
import argparse
import json
import sys
import time


def import_serial():
    try:
        import serial
        return serial
    except ImportError:
        return None


def parse_args():
    parser = argparse.ArgumentParser(description="Download SNARE JSON data from a Pico over USB serial.")
    parser.add_argument("--port", default=None, help="Serial port such as COM7, /dev/ttyACM0, or /dev/ttyS7.")
    parser.add_argument("--output", default="snare_scan_data.json", help="Output JSON file path.")
    parser.add_argument("--command", default="import", help="Command to send to the Pico.")
    parser.add_argument("--begin", default="BEGIN-DOWNLOAD", help="Begin marker printed by the Pico.")
    parser.add_argument("--end", default="END-DOWNLOAD", help="End marker printed by the Pico.")
    parser.add_argument("--baud", default=115200, type=int, help="Serial baud rate.")
    parser.add_argument("--timeout", default=30, type=int, help="Seconds to wait for the export.")
    return parser.parse_args()


def guess_port(serial_module):
    ports = list(serial_module.tools.list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    if ports:
        print("Available serial ports:", file=sys.stderr)
        for port in ports:
            print("  {} {}".format(port.device, port.description), file=sys.stderr)
    return None


def main():
    args = parse_args()
    serial_module = import_serial()
    if serial_module is None:
        print("pyserial is required. Install it with: python3 -m pip install pyserial", file=sys.stderr)
        return 2

    try:
        from serial.tools import list_ports
        serial_module.tools = type("tools", (), {"list_ports": list_ports})
    except Exception:
        pass

    port = args.port or guess_port(serial_module)
    if not port:
        print("No serial port selected. Pass --port, for example --port /dev/ttyACM0.", file=sys.stderr)
        return 2

    json_lines = []
    capturing = False
    deadline = time.time() + args.timeout

    with serial_module.Serial(port, args.baud, timeout=1, write_timeout=1) as ser:
        time.sleep(0.8)
        ser.reset_input_buffer()
        ser.write((args.command + "\n").encode("utf-8"))
        ser.flush()

        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").rstrip("\r\n")

            if args.begin in line:
                capturing = True
                continue

            if args.end in line:
                break

            if capturing:
                json_lines.append(line)

    if not json_lines:
        print("No JSON data was received from the Pico.", file=sys.stderr)
        return 1

    json_text = "\n".join(json_lines).strip()
    json.loads(json_text)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(json_text)
        f.write("\n")
    print("Saved SNARE JSON to {}".format(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
