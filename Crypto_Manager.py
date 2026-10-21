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

ENCRYPTED_CHUNK_SIZE = 256
RECORD_LINE_PREFIX = "SNAREREC1:"


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


def _xor_chunk(data, secret, nonce, start_offset):
    # Chunks are encrypted a little at a time so the Pico does not need one giant keystream in RAM.
    encrypted = bytearray(len(data))
    done = 0
    while done < len(data):
        absolute = start_offset + done
        counter = absolute // 32
        skip = absolute % 32
        block = _sha256(secret + nonce + counter.to_bytes(4, "big"))
        usable = min(len(data) - done, 32 - skip)
        for index in range(usable):
            encrypted[done + index] = data[done + index] ^ block[skip + index]
        done += usable
    return encrypted


def load_encrypted_file(file_name):
    # Older data.json files used a JSON wrapper with hex ciphertext, so this keeps existing data readable.
    with open(file_name, "r") as f:
        raw = f.read().strip()
    if not raw:
        return []
    return decrypt_payload(json.loads(raw))


def encrypt_record_line(record):
    # Each stored scan sample is encrypted separately so saving one new sample does not require
    # re-encrypting the whole history in RAM.
    json_text = json.dumps(record)
    secret = _to_bytes(config.STORAGE_SECRET)
    nonce_seed = "{}:{}".format(_ticks_ms(), len(json_text)).encode("utf-8")
    nonce = _sha256(secret + nonce_seed)[:8]
    ciphertext = bytearray()
    byte_offset = 0
    for start in range(0, len(json_text), ENCRYPTED_CHUNK_SIZE):
        chunk = json_text[start:start + ENCRYPTED_CHUNK_SIZE].encode("utf-8")
        ciphertext.extend(_xor_chunk(chunk, secret, nonce, byte_offset))
        byte_offset += len(chunk)
    return "{}{}:{}\n".format(
        RECORD_LINE_PREFIX,
        binascii.hexlify(nonce).decode("utf-8"),
        binascii.hexlify(bytes(ciphertext)).decode("utf-8"),
    )


def decrypt_record_line(line):
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    if not line.startswith(RECORD_LINE_PREFIX):
        return None
    body = line[len(RECORD_LINE_PREFIX):]
    nonce_hex, ciphertext_hex = body.split(":", 1)
    secret = _to_bytes(config.STORAGE_SECRET)
    nonce = binascii.unhexlify(nonce_hex)
    ciphertext = binascii.unhexlify(ciphertext_hex)
    plaintext = bytearray()
    byte_offset = 0
    for start in range(0, len(ciphertext), ENCRYPTED_CHUNK_SIZE):
        chunk = ciphertext[start:start + ENCRYPTED_CHUNK_SIZE]
        plaintext.extend(_xor_chunk(chunk, secret, nonce, byte_offset))
        byte_offset += len(chunk)
    return json.loads(bytes(plaintext).decode("utf-8"))


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
