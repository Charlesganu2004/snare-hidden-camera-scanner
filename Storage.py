import json
from Crypto_Manager import encrypt_payload, decrypt_payload

class Storage:
    FILE_NAME = "data.json"

    @staticmethod
    def save(data):
        # The payload is encrypted before it ever touches the filesystem.
        payload = encrypt_payload(data)
        with open(Storage.FILE_NAME, "w") as f:
            json.dump(payload, f)

    @staticmethod
    def load():
        try:
            with open(Storage.FILE_NAME, "r") as f:
                raw = f.read().strip()
            if not raw:
                return []
            # Decryption happens on load so the rest of the app can keep working with normal Python lists and dicts.
            return decrypt_payload(json.loads(raw))
        except Exception as exc:
            print("Storage load failed:", exc)
            return []

    @staticmethod
    def clear():
        # Clearing saves an encrypted empty list so the file format stays consistent.
        Storage.save([])
