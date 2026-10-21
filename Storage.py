import gc
from Crypto_Manager import (
    RECORD_LINE_PREFIX,
    decrypt_record_line,
    encrypt_record_line,
    load_encrypted_file,
)


class Storage:
    FILE_NAME = "data.json"

    @staticmethod
    def _missing_file(exc):
        return bool(exc.args and exc.args[0] == 2)

    @staticmethod
    def _is_record_line_file():
        try:
            with open(Storage.FILE_NAME, "r") as f:
                first = f.read(len(RECORD_LINE_PREFIX))
            if not first:
                return True
            return first == RECORD_LINE_PREFIX
        except OSError as exc:
            if Storage._missing_file(exc):
                return True
            raise

    @staticmethod
    def _load_record_lines(limit=None):
        records = []
        with open(Storage.FILE_NAME, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                record = decrypt_record_line(line)
                if record is None:
                    raise ValueError("Storage file is not record-line encrypted.")
                records.append(record)
                if limit and len(records) > limit:
                    records.pop(0)
        return records

    @staticmethod
    def save(data):
        # Records are written one encrypted line at a time to avoid building one huge encrypted payload in RAM.
        try:
            gc.collect()
            with open(Storage.FILE_NAME, "w") as f:
                for record in data or []:
                    f.write(encrypt_record_line(record))
            return True
        except MemoryError as exc:
            gc.collect()
            print("Storage save failed: not enough memory:", exc)
            return False
        except Exception as exc:
            print("Storage save failed:", exc)
            return False

    @staticmethod
    def append(record, limit=None):
        try:
            gc.collect()
            if not Storage._is_record_line_file():
                records = Storage.load()
                records.append(record)
                if limit:
                    records = records[-limit:]
                return Storage.save(records)

            with open(Storage.FILE_NAME, "a") as f:
                f.write(encrypt_record_line(record))

            if limit and Storage.count() > limit:
                return Storage.save(Storage._load_record_lines(limit=limit))
            return True
        except MemoryError as exc:
            gc.collect()
            print("Storage append failed: not enough memory:", exc)
            return False
        except Exception as exc:
            print("Storage append failed:", exc)
            return False

    @staticmethod
    def load():
        try:
            gc.collect()
            if Storage._is_record_line_file():
                return Storage._load_record_lines()
            return load_encrypted_file(Storage.FILE_NAME)
        except OSError as exc:
            if Storage._missing_file(exc):
                return []
            print("Storage load failed:", exc)
            return []
        except MemoryError as exc:
            gc.collect()
            print("Storage load failed: not enough memory:", exc)
            return []
        except Exception as exc:
            print("Storage load failed:", exc)
            return []

    @staticmethod
    def count():
        try:
            total = 0
            with open(Storage.FILE_NAME, "r") as f:
                for line in f:
                    if line.strip():
                        total += 1
            return total
        except OSError as exc:
            if Storage._missing_file(exc):
                return 0
            raise

    @staticmethod
    def next_scan_number():
        try:
            if not Storage._is_record_line_file():
                records = Storage.load()
                if not records:
                    return 1
                return int(records[-1].get("scan_number", 0)) + 1

            last_record = None
            with open(Storage.FILE_NAME, "r") as f:
                for line in f:
                    if line.strip():
                        last_record = decrypt_record_line(line)
            if not last_record:
                return 1
            return int(last_record.get("scan_number", 0)) + 1
        except Exception:
            return 1

    @staticmethod
    def clear():
        # Clearing leaves an empty encrypted-record file ready for the next scan.
        Storage.save([])
