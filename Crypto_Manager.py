import json
import time

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

import config


def _ticks_ms():
    # A millisecond-style timestamp is used here to derive a fresh nonce each time data is saved.
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _to_bytes(value):
    # Everything is normalized to bytes because the hash and XOR logic expects byte strings.
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _sha256(data):
    # Hashing is used repeatedly to build a predictable keystream from the storage secret.
    digest = hashlib.sha256()
    digest.update(data)
    return digest.digest()


def _keystream(secret, nonce, length):
    # The secret is expanded into a keystream so payloads can be XOR-encrypted without storing plaintext on the device.
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = _sha256(secret + nonce + counter.to_bytes(4, "big"))
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def encrypt_payload(data):
    # Scan data is turned into JSON first, then encrypted before being written to disk.
    plaintext = json.dumps(data).encode("utf-8")
    secret = _to_bytes(config.STORAGE_SECRET)
    nonce_seed = "{}:{}".format(_ticks_ms(), len(plaintext)).encode("utf-8")
    nonce = _sha256(secret + nonce_seed)[:8]
    stream = _keystream(secret, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    return {
        "encrypted": True,
        "nonce": binascii.hexlify(nonce).decode("utf-8"),
        "ciphertext": binascii.hexlify(ciphertext).decode("utf-8"),
    }


def decrypt_payload(payload):
    # The file is decrypted only when the saved scan data needs to be read or emailed.
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    if not payload.get("encrypted"):
        return payload

    secret = _to_bytes(config.STORAGE_SECRET)
    nonce = binascii.unhexlify(payload["nonce"])
    ciphertext = binascii.unhexlify(payload["ciphertext"])
    stream = _keystream(secret, nonce, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
    return json.loads(plaintext.decode("utf-8"))
