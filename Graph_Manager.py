import json
import math
import config


def _json_dumps(payload):
    try:
        return json.dumps(payload)
    except TypeError:
        return json.dumps(payload)


def _safe_script_json(payload):
    return _json_dumps(payload).replace("</", "<\\/")


def build_scan_graph_html(records):
    records = records or []
    payload = {
        "records": records,
        "geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "max_distance_cm": getattr(config, "GRAPH_MAX_DISTANCE_CM", 500),
        "rotation_time_seconds": getattr(config, "ROTATION_TIME_SECONDS", 90),
    }

    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SNARE Scan Graph</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f6f7f9;
      color: #17202a;
    }
    main {
      max-width: 980px;
      margin: 0 auto;
      padding: 18px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 26px;
    }
    .summary {
      margin: 0 0 14px;
      color: #4a5563;
    }
    .panel {
      background: #ffffff;
      border: 1px solid #d6dce5;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 14px;
    }
    canvas {
      width: 100%;
      max-width: 900px;
      aspect-ratio: 1 / 1;
      display: block;
      margin: 0 auto;
      background: #fbfcfe;
      border: 1px solid #d6dce5;
      border-radius: 8px;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 10px;
      font-size: 14px;
    }
    .dot {
      display: inline-block;
      width: 11px;
      height: 11px;
      border-radius: 50%;
      margin-right: 6px;
      vertical-align: -1px;
    }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 260px;
      overflow: auto;
      background: #101820;
      color: #f2f6fb;
      padding: 12px;
      border-radius: 6px;
      font-size: 12px;
    }
  </style>
</head>
<body>
<main>
  <h1>SNARE Scan Graph</h1>
  <p id="summary" class="summary"></p>
  <section class="panel">
    <canvas id="scanGraph" width="900" height="900"></canvas>
    <div class="legend">
      <span><span class="dot" style="background:#a3acba"></span>Ultrasonic distance reading</span>
      <span><span class="dot" style="background:#2f80ed"></span>Ultrasonic detection</span>
      <span><span class="dot" style="background:#d64545"></span>IR heat detection</span>
      <span><span class="dot" style="background:#111827"></span>Device center</span>
      <span><span class="dot" style="background:#8a96a8"></span>Scan direction line</span>
    </div>
  </section>
  <section class="panel">
    <h2>Raw Scan Data</h2>
    <pre id="rawData"></pre>
  </section>
</main>
<script>
const SNARE_DATA = __SNARE_DATA__;
const canvas = document.getElementById("scanGraph");
const ctx = canvas.getContext("2d");
const cx = canvas.width / 2;
const cy = canvas.height / 2;
const radius = Math.min(cx, cy) - 64;

function toNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function pointFromAngle(angle, distanceScale) {
  const radians = (angle - 90) * Math.PI / 180;
  return {
    x: cx + Math.cos(radians) * distanceScale,
    y: cy + Math.sin(radians) * distanceScale
  };
}

function statusDetected(status) {
  return status === "Hidden Camera" || status === "Maybe Hidden Camera";
}

function sensorAngle(record, sensorName, index, total) {
  const geometry = SNARE_DATA.geometry || {};
  const sensor = geometry[sensorName] || {};
  const base = toNumber(record.rotation_angle_degrees, (index / Math.max(total - 1, 1)) * 360);
  return (base + toNumber(sensor.angle_offset, 0) + 360) % 360;
}

function detectionPoints(record, index, total) {
  if (Array.isArray(record.detection_points) && record.detection_points.length) {
    return record.detection_points;
  }
  const readings = record.sensor_readings || {};
  const points = [];
  Object.keys(readings).forEach((name) => {
    const reading = readings[name] || {};
    if (!statusDetected(reading.status)) return;
    const geometry = (SNARE_DATA.geometry || {})[name] || {};
    points.push({
      sensor: name,
      label: geometry.label || name,
      sensor_type: geometry.type || reading.type || "sensor",
      angle_degrees: sensorAngle(record, name, index, total),
      distance_cm: reading.distance_cm,
      status: reading.status
    });
  });
  return points;
}

function drawGraph() {
  const records = SNARE_DATA.records || [];
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "#d8dee9";
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 5; ring++) {
    ctx.beginPath();
    ctx.arc(cx, cy, radius * ring / 5, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.strokeStyle = "#eef1f5";
  for (let a = 0; a < 360; a += 30) {
    const p = pointFromAngle(a, radius);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
  }

  records.forEach((record, index) => {
    const angle = toNumber(record.rotation_angle_degrees, (index / Math.max(records.length - 1, 1)) * 360);
    const edge = pointFromAngle(angle, radius);
    ctx.strokeStyle = "rgba(75, 85, 99, 0.16)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(edge.x, edge.y);
    ctx.stroke();

    const readings = record.sensor_readings || {};
    Object.keys(readings).forEach((name) => {
      const reading = readings[name] || {};
      if (reading.type !== "ultrasonic" || reading.distance_cm === null || reading.distance_cm === undefined) {
        return;
      }
      const maxDistance = toNumber(SNARE_DATA.max_distance_cm, 500);
      const distanceScale = Math.max(16, Math.min(radius, toNumber(reading.distance_cm, 0) / maxDistance * radius));
      const p = pointFromAngle(sensorAngle(record, name, index, records.length), distanceScale);
      ctx.fillStyle = "rgba(120, 132, 150, 0.35)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      ctx.fill();
    });

    detectionPoints(record, index, records.length).forEach((detection) => {
      const maxDistance = toNumber(SNARE_DATA.max_distance_cm, 500);
      const rawDistance = detection.distance_cm === null || detection.distance_cm === undefined
        ? maxDistance * 0.82
        : toNumber(detection.distance_cm, maxDistance * 0.82);
      const distanceScale = Math.max(16, Math.min(radius, rawDistance / maxDistance * radius));
      const p = pointFromAngle(toNumber(detection.angle_degrees, angle), distanceScale);
      const isIr = detection.sensor_type === "ir";
      ctx.fillStyle = isIr ? "#d64545" : "#2f80ed";
      ctx.strokeStyle = detection.status === "Hidden Camera" ? "#111827" : "#ffffff";
      ctx.lineWidth = detection.status === "Hidden Camera" ? 3 : 1.5;
      ctx.beginPath();
      ctx.arc(p.x, p.y, detection.status === "Hidden Camera" ? 8 : 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
  });

  ctx.fillStyle = "#111827";
  ctx.beginPath();
  ctx.arc(cx, cy, 11, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#17202a";
  ctx.font = "14px Arial";
  ctx.fillText("Device", cx + 16, cy + 5);
}

drawGraph();
const records = SNARE_DATA.records || [];
const detections = records.reduce((count, record, index) => {
  return count + detectionPoints(record, index, records.length).length;
}, 0);
document.getElementById("summary").textContent =
  records.length + " stored scan samples, " + detections + " detection points plotted.";
document.getElementById("rawData").textContent = JSON.stringify(SNARE_DATA.records || [], null, 2);
</script>
</body>
</html>"""

    return html.replace("__SNARE_DATA__", _safe_script_json(payload))


def _to_number(value, fallback=0):
    try:
        if value is None:
            return fallback
        return float(value)
    except Exception:
        return fallback


def _records_from_payload(payload):
    if isinstance(payload, dict):
        if "samples" in payload:
            return payload.get("samples") or []
        if "records" in payload:
            return payload.get("records") or []
        if "sensor_readings" in payload:
            return [payload]
    if isinstance(payload, list):
        return payload
    return []


def _detected(status):
    return status in ("Hidden Camera", "Maybe Hidden Camera")


def _point_from_angle(angle, distance_scale, cx, cy, rx, ry):
    radians = (angle - 90) * math.pi / 180
    x = cx + math.cos(radians) * distance_scale * rx
    y = cy + math.sin(radians) * distance_scale * ry
    return int(x + 0.5), int(y + 0.5)


def _mark(grid, x, y, char):
    if y < 0 or y >= len(grid):
        return
    if x < 0 or x >= len(grid[0]):
        return
    grid[y][x] = char


def _line(grid, cx, cy, x2, y2, char):
    dx = x2 - cx
    dy = y2 - cy
    steps = max(abs(dx), abs(dy), 1)
    for step in range(steps + 1):
        x = cx + int((dx * step / steps) + 0.5)
        y = cy + int((dy * step / steps) + 0.5)
        _mark(grid, x, y, char)


def _sensor_angle(record, sensor_name, index, total):
    geometry = getattr(config, "SENSOR_GEOMETRY", {})
    sensor = geometry.get(sensor_name, {})
    fallback_angle = (index * 360 / max(total - 1, 1)) if total else 0
    base = _to_number(record.get("rotation_angle_degrees"), fallback_angle)
    return (base + _to_number(sensor.get("angle_offset"), 0)) % 360


def _detection_points(record, index, total):
    if record.get("detection_points"):
        return record.get("detection_points")

    geometry = getattr(config, "SENSOR_GEOMETRY", {})
    readings = record.get("sensor_readings", {})
    points = []
    for sensor_name, reading in readings.items():
        if not _detected(reading.get("status")):
            continue
        sensor = geometry.get(sensor_name, {})
        points.append({
            "sensor": sensor_name,
            "sensor_type": sensor.get("type", reading.get("type", "sensor")),
            "angle_degrees": _sensor_angle(record, sensor_name, index, total),
            "distance_cm": reading.get("distance_cm"),
            "status": reading.get("status"),
        })
    return points


def build_terminal_scan_image(payload, width=41, height=21):
    records = _records_from_payload(payload)
    if not records:
        return "[SNARE LIVE IMAGE]\n(no live scan samples yet)"

    width = max(25, width)
    height = max(13, height)
    cx = width // 2
    cy = height // 2
    rx = (width - 4) / 2
    ry = (height - 4) / 2
    max_distance = _to_number(getattr(config, "GRAPH_MAX_DISTANCE_CM", 500), 500)
    grid = [[" " for _ in range(width)] for _ in range(height)]

    for y in range(height):
        for x in range(width):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            distance = math.sqrt(dx * dx + dy * dy)
            if abs(distance - 1) < 0.08:
                grid[y][x] = "."
            elif abs(distance - 0.5) < 0.055:
                grid[y][x] = ","

    latest = records[-1]
    latest_angle = _to_number(latest.get("rotation_angle_degrees"), 0)
    line_x, line_y = _point_from_angle(latest_angle, 1, cx, cy, rx, ry)
    _line(grid, cx, cy, line_x, line_y, "+")

    for index, record in enumerate(records):
        readings = record.get("sensor_readings", {})
        for sensor_name, reading in readings.items():
            if reading.get("type") != "ultrasonic":
                continue
            if reading.get("distance_cm") is None:
                continue
            distance_scale = min(1, max(0.05, _to_number(reading.get("distance_cm"), 0) / max_distance))
            angle = _sensor_angle(record, sensor_name, index, len(records))
            x, y = _point_from_angle(angle, distance_scale, cx, cy, rx, ry)
            _mark(grid, x, y, "o")

        for point in _detection_points(record, index, len(records)):
            distance = point.get("distance_cm")
            distance_scale = 0.78 if distance is None else min(1, max(0.05, _to_number(distance, 0) / max_distance))
            angle = _to_number(point.get("angle_degrees"), _to_number(record.get("rotation_angle_degrees"), 0))
            x, y = _point_from_angle(angle, distance_scale, cx, cy, rx, ry)
            char = "I" if point.get("sensor_type") == "ir" else "U"
            if point.get("status") == "Hidden Camera":
                char = "X"
            _mark(grid, x, y, char)

    _mark(grid, cx, cy, "D")
    lines = ["".join(row).rstrip() for row in grid]
    detection_count = 0
    for index, record in enumerate(records):
        detection_count += len(_detection_points(record, index, len(records)))
    header = "[SNARE LIVE IMAGE] samples={} detections={} angle={} progress={}%".format(
        len(records),
        detection_count,
        _to_number(latest.get("rotation_angle_degrees"), 0),
        _to_number(latest.get("progress_percent"), 0),
    )
    legend = "D=device  +=current scan line  o=ultrasonic distance  U=ultrasonic hit  I=IR hit  X=confirmed"
    return header + "\n" + "\n".join(lines) + "\n" + legend
