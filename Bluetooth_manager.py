import struct
import config

_FLAG_READ = 0x0002

class BluetoothManager:
    def __init__(self):
        self.ble = None
        self.info_handle = None
        self.bluetooth = None

    def _prepare_country(self):
        # The wireless country is set before BLE startup so radio configuration matches the deployment region.
        try:
            import rp2
            if hasattr(rp2, "country"):
                rp2.country(config.WIRELESS_COUNTRY)
        except Exception as exc:
            print("Bluetooth country setup warning: {}".format(exc))

    def _advertising_payload(self, name):
        # The BLE payload includes flags plus the visible device name.
        name_bytes = name.encode("utf-8")
        payload = bytearray()
        payload += struct.pack("BB", 2, 0x01) + b"\x06"
        payload += struct.pack("BB", len(name_bytes) + 1, 0x09) + name_bytes
        return payload

    def start(self):
        try:
            import bluetooth

            self._prepare_country()
            self.bluetooth = bluetooth
            self.ble = bluetooth.BLE()
            self.ble.active(True)
            self.ble.config(gap_name=config.AP_SSID)

            # A small readable characteristic gives scanner apps a hint about where setup actually happens.
            service_uuid = bluetooth.UUID("7d4d0001-8f3c-4e5b-9b35-2d2af2010001")
            info_char_uuid = bluetooth.UUID("7d4d0001-8f3c-4e5b-9b35-2d2af2010002")
            ((self.info_handle,),) = self.ble.gatts_register_services((
                (service_uuid, ((info_char_uuid, _FLAG_READ),)),
            ))
            self.ble.gatts_write(
                self.info_handle,
                "Open Wi-Fi '{}' for setup/download.".format(config.AP_SSID).encode("utf-8"),
            )

            self.ble.gap_advertise(
                500000,
                adv_data=self._advertising_payload(config.AP_SSID),
                connectable=True,
            )
            print("Bluetooth LE advertising as '{}'.".format(config.AP_SSID))
            print("Open the Wi-Fi network '{}' on the phone to reach the setup portal.".format(config.AP_SSID))
            return True
        except Exception as exc:
            print("Bluetooth LE could not start: {}".format(exc))
            print("Open the Wi-Fi network '{}' on the phone to reach the setup portal.".format(config.AP_SSID))
            self.stop()
            return False

    def stop(self):
        if not self.ble:
            return
        try:
            self.ble.gap_advertise(None)
        except Exception:
            pass
        try:
            self.ble.active(False)
        except Exception:
            pass
        self.ble = None
        self.bluetooth = None
        self.info_handle = None
