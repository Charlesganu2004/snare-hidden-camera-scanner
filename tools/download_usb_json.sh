#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-/dev/ttyACM0}"
OUTPUT="${2:-snare_scan_data.json}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$SCRIPT_DIR/download_usb_json.py" \
  --port "$PORT" \
  --output "$OUTPUT" \
  --command "import" \
  --begin "BEGIN-DOWNLOAD" \
  --end "END-DOWNLOAD"
