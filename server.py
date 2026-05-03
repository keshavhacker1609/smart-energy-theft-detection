from flask import Flask, request, jsonify, render_template
from datetime import datetime
from collections import deque

import config

app = Flask(__name__)

meter_data  = {}
reading_log = deque(maxlen=config.LOG_MAX_ENTRIES)

def assess(expected, actual):
    if expected <= 0:
        return "LOW", "NORMAL"
    ratio = actual / expected
    if ratio > config.THEFT_THRESHOLD:
        return "HIGH", "THEFT DETECTED"
    if ratio > config.MEDIUM_THRESHOLD:
        return "MEDIUM", "SUSPICIOUS"
    return "LOW", "NORMAL"

@app.route("/")
def dashboard():
    return render_template("index.html")

@app.route("/config")
def get_config():
    return jsonify({
        "chart_max_points": config.CHART_MAX_POINTS,
        "chart_meter_id":   config.CHART_METER_ID,
        "theft_threshold":  config.THEFT_THRESHOLD,
        "medium_threshold": config.MEDIUM_THRESHOLD,
        "meters":           list(config.METERS.keys()),
    })

@app.route("/data", methods=["POST"])
def receive_data():
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "no data"}), 400

    meter_id = payload.get("meter_id")
    expected = payload.get("expected")
    actual   = payload.get("actual")

    if not all([meter_id, expected is not None, actual is not None]):
        return jsonify({"error": "missing fields"}), 400

    try:
        expected = float(expected)
        actual   = float(actual)
    except (TypeError, ValueError):
        return jsonify({"error": "expected and actual must be numbers"}), 400

    risk_level, status = assess(expected, actual)
    deviation = round((actual - expected) / expected * 100, 1) if expected else 0

    record = {
        "meter_id":  meter_id,
        "expected":  round(expected, 2),
        "actual":    round(actual, 2),
        "deviation": deviation,
        "status":    status,
        "risk":      risk_level,
        "time":      datetime.now().strftime("%H:%M:%S"),
        "date":      datetime.now().strftime("%d %b"),
        "source":    payload.get("source", "simulator"),  # "simulator" or "manual"
    }

    meter_data[meter_id] = record
    reading_log.appendleft(dict(record))  # newest first

    print(f"[{meter_id}] {actual} / {expected}  deviation={deviation}%  → {risk_level}")
    return jsonify({"status": status, "risk": risk_level, "deviation": deviation}), 200

@app.route("/get-data")
def get_data():
    return jsonify(list(meter_data.values()))

@app.route("/get-log")
def get_log():
    limit = request.args.get("limit", 15, type=int)
    return jsonify(list(reading_log)[:limit])

@app.route("/stats")
def stats():
    entries = list(meter_data.values())
    return jsonify({
        "total_meters":  len(entries),
        "theft_count":   sum(1 for e in entries if e["risk"] == "HIGH"),
        "suspicious":    sum(1 for e in entries if e["risk"] == "MEDIUM"),
        "normal_count":  sum(1 for e in entries if e["risk"] == "LOW"),
        "log_entries":   len(reading_log),
    })

if __name__ == "__main__":
    print(f"Server → http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=config.DEBUG)
