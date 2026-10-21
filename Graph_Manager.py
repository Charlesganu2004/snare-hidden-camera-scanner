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


def _build_radar_player_html(payload, title, live_mode=False, json_file_name="snare_radar_scan_data.json"):
    # The radar player turns scan samples into a browser-playable replay without asking the Pico to create video files.
    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #071013;
      color: #e8f6f3;
    }
    main {
      max-width: 980px;
      margin: 0 auto;
      padding: 16px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 26px;
    }
    .panel {
      background: #0d1f24;
      border: 1px solid #1d4149;
      border-radius: 10px;
      padding: 12px;
      margin-top: 12px;
      box-shadow: 0 14px 40px rgba(0, 0, 0, 0.22);
    }
    canvas {
      width: 100%;
      max-width: 900px;
      aspect-ratio: 1 / 1;
      display: block;
      margin: 0 auto;
      background: radial-gradient(circle, #11333a 0%, #071013 72%);
      border: 1px solid #2d6872;
      border-radius: 10px;
      box-shadow: 0 0 40px rgba(41, 199, 172, 0.16), inset 0 0 40px rgba(41, 199, 172, 0.08);
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 12px;
    }
    button, select {
      border: 0;
      border-radius: 8px;
      padding: 10px 12px;
      background: #29c7ac;
      color: #061012;
      font-weight: 700;
    }
    button.secondary {
      background: #d7fff6;
    }
    button.danger {
      background: #ff5f6d;
      color: #ffffff;
    }
    button:hover {
      filter: brightness(1.08);
    }
    select {
      background: #d7fff6;
    }
    input[type="range"] {
      flex: 1 1 220px;
      min-width: 160px;
    }
    .summary {
      color: #a7d8d1;
      line-height: 1.45;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .stat {
      background: #08171b;
      border: 1px solid #1e4b53;
      border-radius: 8px;
      padding: 10px;
    }
    .stat strong {
      display: block;
      color: #ffffff;
      font-size: 20px;
      margin-top: 4px;
    }
    .detections {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .detection {
      border-left: 4px solid #35a7ff;
      background: #08171b;
      border-radius: 8px;
      padding: 9px 10px;
      color: #dafdf7;
    }
    .detection.ir {
      border-left-color: #ff5f6d;
    }
    .muted {
      color: #8ebbb5;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: #bce9e3;
      font-size: 14px;
      margin-top: 10px;
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
      background: #04090a;
      color: #d8fff7;
      padding: 12px;
      border-radius: 8px;
      font-size: 12px;
    }
  </style>
</head>
<body>
<main>
  <h1>__TITLE__</h1>
  <p id="summary" class="summary">Loading radar data...</p>
  <section class="panel">
    <canvas id="radar" width="900" height="900"></canvas>
    <div class="controls">
      <button id="playPause">Play</button>
      <button id="previous">Previous</button>
      <button id="next">Next</button>
      <input id="frameSlider" type="range" min="0" max="0" value="0">
      <select id="speed">
        <option value="1500">Slow</option>
        <option value="800" selected>Normal</option>
        <option value="350">Fast</option>
      </select>
      <button id="runScan" class="secondary">Run Scan Now</button>
      <button id="stopScan" class="danger">Stop Live Scan</button>
      <button id="downloadJson">Download JSON</button>
      <button id="downloadPng" class="secondary">Save Radar PNG</button>
    </div>
    <div class="legend">
      <span><span class="dot" style="background:#6be7d2"></span>Current scan line</span>
      <span><span class="dot" style="background:#8aa7ad"></span>Ultrasonic distance</span>
      <span><span class="dot" style="background:#35a7ff"></span>Ultrasonic detection</span>
      <span><span class="dot" style="background:#ff5f6d"></span>IR detection</span>
      <span><span class="dot" style="background:#ffffff"></span>Device center</span>
    </div>
  </section>
  <section class="panel">
    <h2>Radar Summary</h2>
    <div class="stats">
      <div class="stat">Frame<strong id="statFrame">0</strong></div>
      <div class="stat">Angle<strong id="statAngle">0 deg</strong></div>
      <div class="stat">Detections<strong id="statDetections">0</strong></div>
      <div class="stat">Samples<strong id="statSamples">0</strong></div>
      <div class="stat">Status<strong id="statStatus">idle</strong></div>
    </div>
    <h3>Detections In This Frame</h3>
    <ul id="detectionList" class="detections"></ul>
  </section>
  <section class="panel">
    <h2>Frame JSON</h2>
    <pre id="frameJson"></pre>
  </section>
</main>
<script>
const EMBEDDED_DATA = __SNARE_DATA__;
const LIVE_MODE = __LIVE_MODE__;
const JSON_FILE_NAME = "__JSON_FILE_NAME__";
const canvas = document.getElementById("radar");
const ctx = canvas.getContext("2d");
const cx = canvas.width / 2;
const cy = canvas.height / 2;
const radius = Math.min(cx, cy) - 64;
let currentData = EMBEDDED_DATA || {};
let records = collectRecords(currentData);
let frameIndex = 0;
let timer = null;

function collectRecords(data) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.records)) return data.records;
  if (data && Array.isArray(data.samples)) return data.samples;
  if (data && data.latest && data.latest.sensor_readings) return [data.latest];
  return [];
}

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

function detected(status) {
  return status === "Hidden Camera" || status === "Maybe Hidden Camera";
}

function geometry() {
  return currentData.geometry || currentData.sensor_geometry || {};
}

function sensorAngle(record, sensorName, index, total) {
  const sensor = geometry()[sensorName] || {};
  const fallback = total > 1 ? index * 360 / (total - 1) : 0;
  const base = toNumber(record.rotation_angle_degrees, fallback);
  return (base + toNumber(sensor.angle_offset, 0) + 360) % 360;
}

function detectionPoints(record, index, total) {
  if (Array.isArray(record.detection_points) && record.detection_points.length) {
    return record.detection_points;
  }
  const readings = record.sensor_readings || {};
  const sensorGeometry = geometry();
  const points = [];
  Object.keys(readings).forEach((name) => {
    const reading = readings[name] || {};
    if (!detected(reading.status)) return;
    const sensor = sensorGeometry[name] || {};
    points.push({
      sensor: name,
      label: sensor.label || name,
      sensor_type: sensor.type || reading.type || "sensor",
      angle_degrees: sensorAngle(record, name, index, total),
      distance_cm: reading.distance_cm,
      status: reading.status
    });
  });
  return points;
}

function drawBase() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const glow = ctx.createRadialGradient(cx, cy, 10, cx, cy, radius);
  glow.addColorStop(0, "rgba(41, 199, 172, 0.22)");
  glow.addColorStop(0.55, "rgba(41, 199, 172, 0.06)");
  glow.addColorStop(1, "rgba(41, 199, 172, 0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const maxDistance = toNumber(currentData.max_distance_cm, 500);
  ctx.strokeStyle = "rgba(107, 231, 210, 0.18)";
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 5; ring++) {
    const ringRadius = radius * ring / 5;
    ctx.beginPath();
    ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "rgba(216, 255, 247, 0.68)";
    ctx.font = "13px Arial";
    ctx.textAlign = "left";
    ctx.fillText(Math.round(maxDistance * ring / 5) + " cm", cx + 8, cy - ringRadius + 4);
  }

  for (let angle = 0; angle < 360; angle += 30) {
    const p = pointFromAngle(angle, radius);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
  }

  const compass = [
    ["N", 0],
    ["E", 90],
    ["S", 180],
    ["W", 270]
  ];
  ctx.fillStyle = "#d8fff7";
  ctx.font = "bold 18px Arial";
  ctx.textAlign = "center";
  compass.forEach(([label, angle]) => {
    const p = pointFromAngle(angle, radius + 26);
    ctx.fillText(label, p.x, p.y + 6);
  });

  ctx.fillStyle = "#ffffff";
  ctx.shadowColor = "rgba(255, 255, 255, 0.85)";
  ctx.shadowBlur = 16;
  ctx.beginPath();
  ctx.arc(cx, cy, 11, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
}

function drawSensorLabels(record, index, total) {
  const sensorGeometry = geometry();
  const readings = record.sensor_readings || {};
  ctx.font = "12px Arial";
  ctx.textAlign = "center";
  Object.keys(sensorGeometry).forEach((name) => {
    const reading = readings[name] || {};
    const label = sensorGeometry[name].label || name;
    const angle = sensorAngle(record, name, index, total);
    const p = pointFromAngle(angle, radius + 46);
    ctx.fillStyle = sensorGeometry[name].type === "ir" || reading.type === "ir" ? "#ffb4bd" : "#b6ecff";
    ctx.fillText(label, p.x, p.y + 4);
  });
}

function drawRecord(record, index, total, isCurrent) {
  const angle = toNumber(record.rotation_angle_degrees, total > 1 ? index * 360 / (total - 1) : 0);
  const edge = pointFromAngle(angle, radius);
  ctx.strokeStyle = isCurrent ? "rgba(107, 231, 210, 0.98)" : "rgba(107, 231, 210, 0.10)";
  ctx.lineWidth = isCurrent ? 4 : 1;
  ctx.shadowColor = isCurrent ? "rgba(107, 231, 210, 0.95)" : "transparent";
  ctx.shadowBlur = isCurrent ? 18 : 0;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(edge.x, edge.y);
  ctx.stroke();
  ctx.shadowBlur = 0;

  const readings = record.sensor_readings || {};
  Object.keys(readings).forEach((name) => {
    const reading = readings[name] || {};
    if (reading.type !== "ultrasonic" || reading.distance_cm === null || reading.distance_cm === undefined) return;
    const maxDistance = toNumber(currentData.max_distance_cm, 500);
    const scale = Math.max(16, Math.min(radius, toNumber(reading.distance_cm, 0) / maxDistance * radius));
    const point = pointFromAngle(sensorAngle(record, name, index, total), scale);
    ctx.fillStyle = isCurrent ? "#8aa7ad" : "rgba(138, 167, 173, 0.35)";
    ctx.shadowColor = isCurrent ? "rgba(138, 167, 173, 0.55)" : "transparent";
    ctx.shadowBlur = isCurrent ? 9 : 0;
    ctx.beginPath();
    ctx.arc(point.x, point.y, isCurrent ? 4 : 2.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  detectionPoints(record, index, total).forEach((detection) => {
    const maxDistance = toNumber(currentData.max_distance_cm, 500);
    const rawDistance = detection.distance_cm === null || detection.distance_cm === undefined
      ? maxDistance * 0.82
      : toNumber(detection.distance_cm, maxDistance * 0.82);
    const scale = Math.max(16, Math.min(radius, rawDistance / maxDistance * radius));
    const point = pointFromAngle(toNumber(detection.angle_degrees, angle), scale);
    const isIr = detection.sensor_type === "ir";
    ctx.fillStyle = isIr ? "#ff5f6d" : "#35a7ff";
    ctx.strokeStyle = detection.status === "Hidden Camera" ? "#ffffff" : "#071013";
    ctx.lineWidth = detection.status === "Hidden Camera" ? 3 : 1.5;
    ctx.shadowColor = isIr ? "rgba(255, 95, 109, 0.9)" : "rgba(53, 167, 255, 0.9)";
    ctx.shadowBlur = 18;
    ctx.beginPath();
    ctx.arc(point.x, point.y, detection.status === "Hidden Camera" ? 9 : 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;
  });
}

function updateDetectionList(record, detections, index, total) {
  const list = document.getElementById("detectionList");
  list.innerHTML = "";
  if (!detections.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "No IR or ultrasonic detections in this frame.";
    list.appendChild(empty);
    return;
  }

  detections.forEach((detection) => {
    const item = document.createElement("li");
    item.className = "detection " + (detection.sensor_type === "ir" ? "ir" : "ultrasonic");
    const angle = toNumber(detection.angle_degrees, toNumber(record.rotation_angle_degrees, 0)).toFixed(1);
    const distance = detection.distance_cm === null || detection.distance_cm === undefined
      ? "no distance"
      : toNumber(detection.distance_cm, 0).toFixed(1) + " cm";
    item.textContent = (detection.label || detection.sensor || "sensor") +
      " | " + detection.status +
      " | " + angle + " deg" +
      " | " + distance;
    list.appendChild(item);
  });
}

function drawFrame(index) {
  records = collectRecords(currentData);
  const slider = document.getElementById("frameSlider");
  slider.max = Math.max(records.length - 1, 0);
  frameIndex = Math.max(0, Math.min(index, Math.max(records.length - 1, 0)));
  slider.value = frameIndex;
  drawBase();

  if (!records.length) {
    ctx.fillStyle = "#d8fff7";
    ctx.font = "24px Arial";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for radar samples", cx, cy - 28);
    ctx.font = "16px Arial";
    ctx.fillText("Run a scan, then refresh or keep live mode open.", cx, cy + 8);
    document.getElementById("summary").textContent = "No radar scan samples are available yet.";
    document.getElementById("frameJson").textContent = "{}";
    document.getElementById("statFrame").textContent = "0";
    document.getElementById("statAngle").textContent = "0 deg";
    document.getElementById("statDetections").textContent = "0";
    document.getElementById("statSamples").textContent = "0";
    document.getElementById("statStatus").textContent = currentData.scan_status || "idle";
    updateDetectionList({}, [], 0, 0);
    return;
  }

  const start = Math.max(0, frameIndex - 22);
  for (let i = start; i <= frameIndex; i++) {
    drawRecord(records[i], i, records.length, i === frameIndex);
  }

  const current = records[frameIndex] || {};
  drawSensorLabels(current, frameIndex, records.length);
  const detections = detectionPoints(current, frameIndex, records.length);
  document.getElementById("summary").textContent =
    (LIVE_MODE ? "Live radar view. " : "Replay video frame. ") +
    "Frame " + (frameIndex + 1) + " of " + records.length +
    ", angle " + toNumber(current.rotation_angle_degrees, 0).toFixed(1) +
    " degrees, detections in frame: " + detections.length + ".";
  document.getElementById("statFrame").textContent = (frameIndex + 1) + " / " + records.length;
  document.getElementById("statAngle").textContent = toNumber(current.rotation_angle_degrees, 0).toFixed(1) + " deg";
  document.getElementById("statDetections").textContent = String(detections.length);
  document.getElementById("statSamples").textContent = String(records.length);
  document.getElementById("statStatus").textContent = currentData.scan_status || "unknown";
  updateDetectionList(current, detections, frameIndex, records.length);
  document.getElementById("frameJson").textContent = JSON.stringify(current, null, 2);
}

function play() {
  if (timer) return;
  document.getElementById("playPause").textContent = "Pause";
  timer = setInterval(() => {
    if (!records.length) {
      drawFrame(0);
      return;
    }
    const next = frameIndex >= records.length - 1 ? 0 : frameIndex + 1;
    drawFrame(next);
  }, Number(document.getElementById("speed").value));
}

function pause() {
  if (timer) clearInterval(timer);
  timer = null;
  document.getElementById("playPause").textContent = "Play";
}

function downloadJson() {
  const blob = new Blob([JSON.stringify(currentData, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = JSON_FILE_NAME;
  link.click();
  URL.revokeObjectURL(link.href);
}

function downloadPng() {
  const link = document.createElement("a");
  link.href = canvas.toDataURL("image/png");
  link.download = "snare_radar_frame_" + (frameIndex + 1) + ".png";
  link.click();
}

async function startScanNow() {
  if (!LIVE_MODE) return;
  const button = document.getElementById("runScan");
  button.disabled = true;
  button.textContent = "Starting Scan...";
  document.getElementById("summary").textContent = "Run Scan Now clicked. Sending scan request to the Pico...";
  document.getElementById("statStatus").textContent = "starting";
  try {
    const response = await fetch("/run-live-scan?ts=" + Date.now(), {cache: "no-store"});
    const result = await response.json();
    document.getElementById("summary").textContent = result.message || "Scan request sent.";
    document.getElementById("statStatus").textContent = result.status || "starting";
    play();
    setTimeout(refreshLive, 400);
  } catch (error) {
    document.getElementById("summary").textContent = "Scan request failed. Keep the phone connected to SNARE_Device_101.";
    document.getElementById("statStatus").textContent = "request failed";
  }
  setTimeout(() => {
    button.disabled = false;
    button.textContent = "Run Scan Now";
  }, 1500);
}

async function stopScanNow() {
  if (!LIVE_MODE) return;
  const button = document.getElementById("stopScan");
  button.disabled = true;
  button.textContent = "Stopping...";
  try {
    const response = await fetch("/stop-live-scan?ts=" + Date.now(), {
      method: "POST",
      cache: "no-store"
    });
    const result = await response.json();
    document.getElementById("summary").textContent = result.message || "Stop request sent.";
    setTimeout(refreshLive, 700);
  } catch (error) {
    document.getElementById("summary").textContent = "Stop request failed. Keep the phone connected to SNARE_Device_101.";
  }
  setTimeout(() => {
    button.disabled = false;
    button.textContent = "Stop Live Scan";
  }, 1500);
}

async function refreshLive() {
  if (!LIVE_MODE) return;
  try {
    const response = await fetch("/live.json?ts=" + Date.now(), {cache: "no-store"});
    currentData = await response.json();
    records = collectRecords(currentData);
    drawFrame(Math.max(records.length - 1, 0));
    if (currentData.message && (currentData.scan_status === "starting" || currentData.scan_status === "running" || currentData.scan_status === "complete" || currentData.scan_status === "stopped")) {
      document.getElementById("summary").textContent = currentData.message;
    }
  } catch (error) {
    document.getElementById("summary").textContent = "Refreshing live radar... If this stays here, stay connected to SNARE_Device_101 and refresh the page.";
    document.getElementById("statStatus").textContent = "refreshing";
  }
}

document.getElementById("playPause").addEventListener("click", () => timer ? pause() : play());
document.getElementById("previous").addEventListener("click", () => drawFrame(frameIndex - 1));
document.getElementById("next").addEventListener("click", () => drawFrame(frameIndex + 1));
document.getElementById("frameSlider").addEventListener("input", (event) => drawFrame(Number(event.target.value)));
document.getElementById("speed").addEventListener("change", () => {
  if (timer) {
    pause();
    play();
  }
});
document.getElementById("downloadJson").addEventListener("click", downloadJson);
document.getElementById("downloadPng").addEventListener("click", downloadPng);
document.getElementById("runScan").addEventListener("click", startScanNow);
document.getElementById("stopScan").addEventListener("click", stopScanNow);
if (!LIVE_MODE) {
  document.getElementById("runScan").style.display = "none";
  document.getElementById("stopScan").style.display = "none";
}

drawFrame(records.length ? records.length - 1 : 0);
if (LIVE_MODE) {
  setInterval(refreshLive, 1000);
  refreshLive();
}
</script>
</body>
</html>"""

    return (
        html
        .replace("__SNARE_DATA__", _safe_script_json(payload))
        .replace("__TITLE__", title)
        .replace("__LIVE_MODE__", "true" if live_mode else "false")
        .replace("__JSON_FILE_NAME__", json_file_name)
    )


def build_radar_replay_html(records):
    payload = {
        "records": records or [],
        "geometry": getattr(config, "SENSOR_GEOMETRY", {}),
        "max_distance_cm": getattr(config, "GRAPH_MAX_DISTANCE_CM", 500),
        "rotation_time_seconds": getattr(config, "ROTATION_TIME_SECONDS", 90),
    }
    return _build_radar_player_html(
        payload,
        "SNARE Radar Replay Video",
        live_mode=False,
        json_file_name=getattr(config, "RADAR_JSON_EXPORT_FILE", "snare_radar_scan_data.json"),
    )


def build_live_radar_html(payload):
    payload = payload or {}
    if "geometry" not in payload and "sensor_geometry" not in payload:
        payload["geometry"] = getattr(config, "SENSOR_GEOMETRY", {})
    if "max_distance_cm" not in payload:
        payload["max_distance_cm"] = getattr(config, "GRAPH_MAX_DISTANCE_CM", 500)
    return _build_radar_player_html(
        payload,
        "SNARE Live Radar",
        live_mode=True,
        json_file_name=getattr(config, "LIVE_SCAN_EXPORT_FILE", "snare_live_scan_data.json"),
    )


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


def build_terminal_scan_image(payload, width=61, height=31):
    records = _records_from_payload(payload)
    if not records:
        return "[SNARE LIVE IMAGE]\n(no live scan samples yet)"

    width = max(31, width)
    height = max(17, height)
    cx = width // 2
    cy = height // 2
    rx = (width - 7) / 2
    ry = (height - 5) / 2
    max_distance = _to_number(getattr(config, "GRAPH_MAX_DISTANCE_CM", 500), 500)
    grid = [[" " for _ in range(width)] for _ in range(height)]

    # Three distance rings give the terminal view a radar feel without requiring graphics libraries.
    for y in range(height):
        for x in range(width):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            distance = math.sqrt(dx * dx + dy * dy)
            if abs(distance - 1) < 0.08:
                grid[y][x] = ","
            elif abs(distance - 0.66) < 0.055:
                grid[y][x] = "."
            elif abs(distance - 0.33) < 0.045:
                grid[y][x] = "'"

    _mark(grid, cx, 0, "N")
    _mark(grid, cx, height - 1, "S")
    _mark(grid, 0, cy, "W")
    _mark(grid, width - 1, cy, "E")

    latest = records[-1]
    latest_angle = _to_number(latest.get("rotation_angle_degrees"), 0)

    trail_start = max(0, len(records) - 12)
    for trail_index in range(trail_start, len(records)):
        record = records[trail_index]
        angle = _to_number(record.get("rotation_angle_degrees"), 0)
        line_x, line_y = _point_from_angle(angle, 1, cx, cy, rx, ry)
        if trail_index == len(records) - 1:
            trail_char = "+"
        elif trail_index >= len(records) - 5:
            trail_char = "-"
        else:
            trail_char = ":"
        _line(grid, cx, cy, line_x, line_y, trail_char)

    plot_records = records[-40:]
    plot_offset = len(records) - len(plot_records)
    for local_index, record in enumerate(plot_records):
        index = plot_offset + local_index
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

    geometry = getattr(config, "SENSOR_GEOMETRY", {})
    latest_readings = latest.get("sensor_readings", {})
    for sensor_name, sensor in geometry.items():
        angle = _sensor_angle(latest, sensor_name, len(records) - 1, len(records))
        x, y = _point_from_angle(angle, 1.07, cx, cy, rx, ry)
        label = sensor_name[-1] if sensor_name.startswith("ultra") else ("A" if sensor_name == "ir1" else "B")
        _mark(grid, x, y, label)

    _mark(grid, cx, cy, "D")
    lines = ["".join(row).rstrip() for row in grid]
    detection_count = 0
    for index, record in enumerate(records):
        detection_count += len(_detection_points(record, index, len(records)))
    latest_points = _detection_points(latest, len(records) - 1, len(records))
    header = "[SNARE LIVE IMAGE] samples={} detections={} angle={} progress={}%".format(
        len(records),
        detection_count,
        _to_number(latest.get("rotation_angle_degrees"), 0),
        _to_number(latest.get("progress_percent"), 0),
    )
    range_line = "Range rings: {} cm, {} cm, {} cm | Sweep trail: : old, - recent, + current".format(
        int(max_distance * 0.33),
        int(max_distance * 0.66),
        int(max_distance),
    )
    legend = "D=device  o=ultrasonic distance  U=ultrasonic hit  I=IR hit  X=confirmed  N/E/S/W=compass"

    sensor_lines = []
    for sensor_name in ("ultra1", "ultra2", "ultra3", "ultra4", "ir1", "ir2"):
        reading = latest_readings.get(sensor_name, {})
        if not reading:
            continue
        angle = _to_number(reading.get("angle_degrees"), _sensor_angle(latest, sensor_name, len(records) - 1, len(records)))
        status = reading.get("status", "No data")
        if reading.get("type") == "ultrasonic":
            distance = reading.get("distance_cm")
            distance_text = "none" if distance is None else "{:.1f} cm".format(_to_number(distance, 0))
            sensor_lines.append("{} @ {:.1f} deg | {} | {}".format(sensor_name, angle, distance_text, status))
        elif reading.get("type") == "ir":
            temps = reading.get("temperatures_c") or []
            if temps:
                temp_text = "min {:.1f} C max {:.1f} C".format(_to_number(min(temps), 0), _to_number(max(temps), 0))
            else:
                temp_text = "no temp array"
            sensor_lines.append("{} @ {:.1f} deg | {} | {}".format(sensor_name, angle, temp_text, status))

    detection_lines = []
    if latest_points:
        for point in latest_points[:8]:
            distance = point.get("distance_cm")
            distance_text = "no distance" if distance is None else "{:.1f} cm".format(_to_number(distance, 0))
            detection_lines.append(
                "{} {} @ {:.1f} deg | {}".format(
                    point.get("sensor_type", "sensor").upper(),
                    point.get("sensor", ""),
                    _to_number(point.get("angle_degrees"), latest_angle),
                    distance_text,
                )
            )
    else:
        detection_lines.append("No detections in the latest frame.")

    return (
        header
        + "\n"
        + "\n".join(lines)
        + "\n"
        + range_line
        + "\n"
        + legend
        + "\n[LATEST SENSOR READINGS]\n"
        + "\n".join(sensor_lines or ["No latest sensor readings available."])
        + "\n[LATEST DETECTIONS]\n"
        + "\n".join(detection_lines)
    )
