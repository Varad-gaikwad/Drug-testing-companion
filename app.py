import os
import json
import hashlib
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import joblib
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Where the SQLite file lives. Locally this is ./records.db.
# On Render, set DB_PATH=/var/data/records.db AND attach a paid Disk at /var/data,
# otherwise the database is wiped on every deploy/restart.
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "records.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Render servers run in UTC. Pin timestamps to IST so they match your local runs.
TZ = ZoneInfo(os.environ.get("APP_TZ", "Asia/Kolkata"))

# Only these file types can be served to the browser. Everything else
# (records.db, app.py, the .joblib model, .env) returns 404.
ALLOWED_STATIC = {
    ".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".webp", ".woff", ".woff2", ".webmanifest",
}

model = joblib.load(os.path.join(BASE_DIR, "marquis_classifier.joblib"))


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS tests (
        id TEXT PRIMARY KEY, timestamp TEXT, hsv TEXT,
        label TEXT, outcome TEXT, record_hash TEXT,
        officer_id TEXT, lat REAL, lon REAL, prev_hash TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS officers (
        officer_id TEXT PRIMARY KEY, password_hash TEXT
    )""")
    return conn


def get_last_hash(conn):
    row = conn.execute("SELECT record_hash FROM tests ORDER BY rowid DESC LIMIT 1").fetchone()
    return row[0] if row else "GENESIS"


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/classify", methods=["POST"])
def classify():
    data = request.json  # expects {"H":.., "S":.., "V":..}
    features = [[data["H"], data["S"], data["V"]]]

    predicted_label = model.predict(features)[0]
    conf_scores = model.predict_proba(features)[0]
    confidence = float(max(conf_scores))

    if confidence < 0.65:
        outcome = "INCONCLUSIVE"
        outcome_detail = "Ambiguous Reaction / Insufficient Contrast"
    elif predicted_label == "no_reaction":
        outcome = "NEGATIVE"
        outcome_detail = "No Controlled Substance Detected (Clear)"
    else:
        outcome = "POSITIVE"
        readable_drug = predicted_label.replace("_", " ").upper()
        outcome_detail = f"Presumptive Positive: {readable_drug}"

    return jsonify({
        "outcome": outcome,
        "outcome_detail": outcome_detail,
        "detected_substance": predicted_label
    })


@app.route("/record", methods=["POST"])
def record():
    data = request.json
    now = datetime.now(TZ)
    local_now = now.strftime("%Y-%m-%d %H:%M:%S")
    test_id = hashlib.sha256(str(now).encode()).hexdigest()[:12]

    outcome = data.get("outcome", "POSITIVE")
    label = data.get("detected_substance", data.get("label", "unknown"))
    officer_id = data.get("officer_id", "unspecified")

    location = data.get("location", {}) or {}
    lat = location.get("lat")
    lon = location.get("lon")

    conn = get_db()
    try:
        # Take the write lock BEFORE reading the last hash. Without this, two
        # simultaneous requests can read the same prev_hash and break the chain.
        conn.execute("BEGIN IMMEDIATE")
        prev_hash = get_last_hash(conn)

        record_obj = {
            "id": test_id,
            "timestamp": local_now,
            "hsv": [data["H"], data["S"], data["V"]],
            "label": label,
            "outcome": outcome,
            "officer_id": officer_id,
            "lat": lat,
            "lon": lon,
            "prev_hash": prev_hash
        }
        record_hash = hashlib.sha256(json.dumps(record_obj, sort_keys=True).encode()).hexdigest()

        conn.execute(
            "INSERT INTO tests (id, timestamp, hsv, label, outcome, record_hash, officer_id, lat, lon, prev_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (test_id, local_now, json.dumps(record_obj["hsv"]),
             label, outcome, record_hash, officer_id, lat, lon, prev_hash)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({"test_id": test_id, "hash": record_hash, "prev_hash": prev_hash, "timestamp": local_now})


@app.route("/officer/<officer_id>/tests", methods=["GET"])
def officer_tests(officer_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, timestamp, hsv, label, outcome, record_hash FROM tests WHERE officer_id=? ORDER BY timestamp DESC",
        (officer_id,)
    ).fetchall()
    results = [{
        "id": r[0], "timestamp": r[1], "hsv": json.loads(r[2]),
        "label": r[3], "outcome": r[4], "hash": r[5]
    } for r in rows]
    return jsonify({"officer_id": officer_id, "test_count": len(results), "tests": results})


@app.route("/")
def serve_login():
    return send_from_directory(BASE_DIR, "login.html")


@app.route("/<path:filename>")
def serve_static(filename):
    if os.path.splitext(filename)[1].lower() not in ALLOWED_STATIC:
        abort(404)
    return send_from_directory(BASE_DIR, filename)


@app.route("/records", methods=["GET"])
def get_all_records():
    conn = get_db()
    cursor = conn.cursor()
    try:
        rows = cursor.execute("SELECT id, timestamp, hsv, label, outcome, record_hash FROM tests ORDER BY timestamp DESC").fetchall()
    except sqlite3.OperationalError:
        rows = cursor.execute("SELECT id, timestamp, hsv, label, 'POSITIVE', record_hash FROM tests ORDER BY timestamp DESC").fetchall()

    records = []
    for r in rows:
        records.append({
            "id": r[0],
            "timestamp": r[1],
            "hsv": json.loads(r[2]),
            "label": r[3],
            "outcome": r[4],
            "hash": r[5]
        })
    return jsonify({"count": len(records), "records": records})


@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    officer_id = data.get("officer_id", "").strip()
    password = data.get("password", "")
    if not officer_id or not password:
        return jsonify({"error": "officer_id and password required"}), 400

    conn = get_db()
    existing = conn.execute("SELECT * FROM officers WHERE officer_id=?", (officer_id,)).fetchone()
    if existing:
        return jsonify({"error": "officer_id already exists"}), 409

    password_hash = generate_password_hash(password)
    conn.execute("INSERT INTO officers VALUES (?,?)", (officer_id, password_hash))
    conn.commit()
    return jsonify({"message": "account created", "officer_id": officer_id})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    officer_id = data.get("officer_id", "").strip()
    password = data.get("password", "")

    conn = get_db()
    row = conn.execute("SELECT * FROM officers WHERE officer_id=?", (officer_id,)).fetchone()
    if not row or not check_password_hash(row[1], password):
        return jsonify({"error": "invalid credentials"}), 401

    return jsonify({"message": "login successful", "officer_id": officer_id})


@app.route("/verify/<test_id>", methods=["GET"])
def verify(test_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, timestamp, hsv, label, outcome, officer_id, lat, lon, prev_hash, record_hash FROM tests WHERE id=?",
        (test_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    record_obj = {
        "id": row[0],
        "timestamp": row[1],
        "hsv": json.loads(row[2]),
        "label": row[3],
        "outcome": row[4],
        "officer_id": row[5],
        "lat": row[6],
        "lon": row[7],
        "prev_hash": row[8]
    }
    stored_hash = row[9]
    recomputed_hash = hashlib.sha256(json.dumps(record_obj, sort_keys=True).encode()).hexdigest()

    return jsonify({
        "match": recomputed_hash == stored_hash,
        "record": record_obj,
        "hash": stored_hash
    })


@app.route("/verify_chain", methods=["GET"])
def verify_chain():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, timestamp, hsv, label, outcome, officer_id, lat, lon, prev_hash, record_hash FROM tests ORDER BY rowid ASC"
    ).fetchall()

    expected_prev = "GENESIS"
    for row in rows:
        record_obj = {
            "id": row[0],
            "timestamp": row[1],
            "hsv": json.loads(row[2]),
            "label": row[3],
            "outcome": row[4],
            "officer_id": row[5],
            "lat": row[6],
            "lon": row[7],
            "prev_hash": row[8]
        }
        recomputed = hashlib.sha256(json.dumps(record_obj, sort_keys=True).encode()).hexdigest()

        if recomputed != row[9] or row[8] != expected_prev:
            return jsonify({
                "valid": False,
                "broken_at": row[0],
                "checked": len(rows)
            })
        expected_prev = row[9]

    return jsonify({"valid": True, "chain_length": len(rows)})


if __name__ == "__main__":
    # Local development only. Render runs the app through gunicorn instead.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )
