import os
import subprocess
import json
import sqlite3
import threading
import time
import logging
import re
from datetime import datetime
from flask import Flask, render_template, jsonify, request, redirect, url_for, g
from dotenv import load_dotenv
import schedule
import requests

# --- Basic Setup ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Environment Variables & Constants ---
TEST_RATE_SECONDS = int(os.getenv("TEST_RATE", 600))
APP_PORT = int(os.getenv("PORT", 2029))
FFPROBE_TIMEOUT = int(os.getenv("FFPROBE_TIMEOUT", 15))
DB_PATH = "/app/data/streams.db"
FRAMES_DIR = "/app/static/frames"
FFMPEG_LOG_PATH = "/app/data/ffmpeg.log"

# --- Database Initialization and Management ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS m3u_sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stream_data (
                id INTEGER PRIMARY KEY, timestamp DATETIME, source_id INTEGER, stream_name TEXT,
                is_available INTEGER, resolution_h INTEGER, frame_rate REAL, load_time_ms REAL,
                logo_url TEXT,
                FOREIGN KEY (source_id) REFERENCES m3u_sources (id) ON DELETE CASCADE
            )""")
        conn.commit()
    logging.info("Database initialized.")

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

# --- M3U Content Fetching and Parsing ---
def get_m3u_content(source_url):
    if source_url.startswith(('http://', 'https://')):
        try:
            response = requests.get(source_url, timeout=10); response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logging.error(f"Failed to download M3U from {source_url}: {e}")
            return None
    return None

def parse_m3u(m3u_content):
    streams = []
    if not m3u_content: return streams
    lines = m3u_content.strip().split('\n')
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF"):
            try:
                stream_name = line.split(',')[-1].strip()
                stream_url = lines[i+1].strip()

                logo_match = re.search(r'tvg-logo="([^"]+)"', line)
                logo_url = logo_match.group(1) if logo_match else None

                if stream_url and not stream_url.startswith("#"):
                    streams.append({'name': stream_name, 'url': stream_url, 'logo_url': logo_url})
            except IndexError: logging.warning(f"Could not parse M3U line: {line}")
    return streams

# --- Stream Probing and Data Logging ---
def check_stream(stream, source_id):
    logging.info(f"Probing stream: {stream['name']} from source ID: {source_id}")
    ffprobe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-select_streams', 'v:0', '-i', stream['url']]
    is_available, height, frame_rate, load_time_ms = False, 0, 0.0, 0.0
    start_time = time.monotonic()
    try:
        result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT)
        load_time_ms = (time.monotonic() - start_time) * 1000
        if result.returncode == 0 and result.stdout:
            stream_info = json.loads(result.stdout)['streams'][0]
            height = int(stream_info.get('height', 0)); fr_str = stream_info.get('avg_frame_rate', '0/1')
            if '/' in fr_str: num, den = map(int, fr_str.split('/')); frame_rate = float(num / den) if den != 0 else 0.0
            else: frame_rate = float(fr_str)
            is_available = True; logging.info(f"SUCCESS: {stream['name']} ({height}p) in {load_time_ms:.0f}ms")
            capture_frame(stream, source_id)
        else:
            logging.warning(f"FAILURE: {stream['name']} unavailable. See ffmpeg.log.")
            with open(FFMPEG_LOG_PATH, 'a') as ff_log: ff_log.write(f"\n--- FFPROBE LOG: {datetime.utcnow()} for {stream['name']} ---\n{result.stderr}\n")
    except subprocess.TimeoutExpired:
        load_time_ms = (time.monotonic() - start_time) * 1000
        logging.error(f"Command for {stream['name']} timed out after {FFPROBE_TIMEOUT}s")
    except Exception as e:
        load_time_ms = (time.monotonic() - start_time) * 1000
        logging.error(f"Error probing {stream['name']}: {e}")
    log_to_db(source_id, stream['name'], is_available, height, frame_rate, load_time_ms, stream['logo_url'])

def capture_frame(stream, source_id):
    safe_stream_name = "".join(c for c in stream['name'] if c.isalnum() or c in (' ', '.')).rstrip()
    output_filename = f"s{source_id}_{safe_stream_name}.jpg"
    output_path = os.path.join(FRAMES_DIR, output_filename)
    os.makedirs(FRAMES_DIR, exist_ok=True)
    ffmpeg_cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', stream['url'], '-vframes', '1', output_path]
    try:
        with open(FFMPEG_LOG_PATH, 'a') as ffmpeg_log:
            ffmpeg_log.write(f"\n--- FFMPEG CAPTURE LOG: {datetime.utcnow()} for {stream['name']} ---\n")
            subprocess.run(ffmpeg_cmd, timeout=FFPROBE_TIMEOUT, stderr=ffmpeg_log)
    except Exception as e: logging.error(f"Failed to run ffmpeg for {stream['name']}: {e}")

def log_to_db(source_id, name, available, height, fr, load_time_ms, logo_url):
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO stream_data (source_id, timestamp, stream_name, is_available, resolution_h, frame_rate, load_time_ms, logo_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,(source_id, datetime.utcnow(), name, int(available), height, fr, load_time_ms, logo_url))
    db.commit(); db.close()

# --- Scheduler and Background Tasks ---
def run_single_source_check(source_id):
    logging.info(f"--- Triggering immediate check for new source ID: {source_id} ---")
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    source = db.execute("SELECT * FROM m3u_sources WHERE id = ?", (source_id,)).fetchone(); db.close()
    if source:
        m3u_content = get_m3u_content(source['url'])
        streams_to_check = parse_m3u(m3u_content)
        for stream in streams_to_check: check_stream(stream, source['id'])
    logging.info(f"--- Immediate check finished for source ID: {source_id} ---")

def run_all_checks():
    logging.info("--- Starting scheduled run of all M3U sources ---")
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    sources = db.execute("SELECT * FROM m3u_sources").fetchall(); db.close()
    if not sources: logging.warning("No M3U sources in database. Skipping check run."); return
    for source in sources:
        logging.info(f"Checking source: {source['name']} (ID: {source['id']})")
        m3u_content = get_m3u_content(source['url'])
        streams_to_check = parse_m3u(m3u_content)
        for stream in streams_to_check: check_stream(stream, source['id'])
    logging.info("--- Scheduled run finished ---")

def run_scheduler():
    logging.info(f"Scheduler started. Will run checks every {TEST_RATE_SECONDS} seconds.")
    run_all_checks()
    schedule.every(TEST_RATE_SECONDS).seconds.do(run_all_checks)
    while True: schedule.run_pending(); time.sleep(1)

# --- Flask Application ---
app = Flask(__name__)
init_db()

@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None: db.close()

@app.context_processor
def inject_nav_sources():
    db = get_db()
    sources = db.execute("SELECT id, name FROM m3u_sources ORDER BY name").fetchall()
    return dict(nav_sources=sources)

@app.errorhandler(404)
def not_found_error(error): return render_template('404.html'), 404

# --- NEW AND MODIFIED ROUTES ---
@app.route('/')
def overview_dashboard():
    db = get_db()
    sources = db.execute("SELECT id, name FROM m3u_sources ORDER BY name").fetchall()

    dashboard_data = []
    for source in sources:
        stats = db.execute("""
            SELECT COUNT(id) AS total_runs, SUM(is_available) AS successful_runs
            FROM stream_data WHERE source_id = ? AND timestamp >= datetime('now', '-24 hours')
        """, (source['id'],)).fetchone()

        streams = db.execute("""
            SELECT stream_name, is_available, logo_url
            FROM stream_data
            WHERE id IN (
                SELECT MAX(id) FROM stream_data WHERE source_id = ? GROUP BY stream_name
            )
            ORDER BY stream_name
        """, (source['id'],)).fetchall()

        dashboard_data.append({
            'id': source['id'], 'name': source['name'], 'stats': stats, 'streams': streams
        })

    return render_template('index.html', dashboard_data=dashboard_data)

@app.route('/add', methods=['GET', 'POST'])
def add_m3u():
    if request.method == 'POST':
        name = request.form['name']; url = request.form['url'].strip()
        if not name or not url: return redirect(url_for('add_m3u'))
        db = get_db(); cursor = db.cursor()
        try:
            cursor.execute("INSERT INTO m3u_sources (name, url) VALUES (?, ?)", (name, url))
            new_id = cursor.lastrowid; db.commit()
            threading.Thread(target=run_single_source_check, args=(new_id,)).start()
        except sqlite3.IntegrityError: logging.warning(f"Attempted to add duplicate URL: {url}")
        return redirect(url_for('overview_dashboard'))
    return render_template('add_m3u.html')

@app.route('/edit/<int:source_id>', methods=['GET', 'POST'])
def edit_m3u(source_id):
    db = get_db()
    source = db.execute("SELECT * FROM m3u_sources WHERE id = ?", (source_id,)).fetchone()
    if not source: return render_template('404.html'), 404
    if request.method == 'POST':
        name = request.form['name']; url = request.form['url'].strip()
        if name and url:
            db.execute("UPDATE m3u_sources SET name = ?, url = ? WHERE id = ?", (name, url, source_id))
            db.commit()
            return redirect(url_for('overview_dashboard'))
    return render_template('edit_m3u.html', source=source)

@app.route('/delete/<int:source_id>', methods=['POST'])
def delete_m3u(source_id):
    db = get_db()
    db.execute("DELETE FROM m3u_sources WHERE id = ?", (source_id,)); db.commit()
    logging.info(f"Deleted M3U source with ID: {source_id}")
    return redirect(url_for('overview_dashboard'))

@app.route('/compare', methods=['GET', 'POST'])
def compare_streams():
    db = get_db()
    sources = db.execute("SELECT id, name FROM m3u_sources ORDER BY name").fetchall()

    all_streams = []
    for source in sources:
        streams = db.execute("""
            SELECT stream_name, logo_url FROM stream_data WHERE id IN
            (SELECT MAX(id) FROM stream_data WHERE source_id = ? GROUP BY stream_name)
            ORDER BY stream_name
        """, (source['id'],)).fetchall()
        all_streams.append({'source_name': source['name'], 'source_id': source['id'], 'streams': streams})

    if request.method == 'POST':
        stream1_id = request.form.get('stream1')
        stream2_id = request.form.get('stream2')

        if stream1_id and stream2_id:
            s1_source_id, s1_name = stream1_id.split(':', 1)
            s2_source_id, s2_name = stream2_id.split(':', 1)
            return render_template('compare.html', all_streams=all_streams, s1_source_id=s1_source_id, s1_name=s1_name, s2_source_id=s2_source_id, s2_name=s2_name)

    return render_template('compare.html', all_streams=all_streams)

@app.route('/m3u/<int:source_id>')
def m3u_dashboard(source_id):
    db = get_db()
    source = db.execute("SELECT * FROM m3u_sources WHERE id = ?", (source_id,)).fetchone()
    if not source: return render_template('404.html'), 404

    streams = db.execute("""
        SELECT stream_name, logo_url
        FROM stream_data
        WHERE id IN (
            SELECT MAX(id) FROM stream_data WHERE source_id = ? GROUP BY stream_name
        )
        ORDER BY stream_name
    """, (source_id,)).fetchall()

    sanitized_streams = []
    for stream in streams:
        safe_name = "".join(c for c in stream['stream_name'] if c.isalnum() or c in (' ', '.')).rstrip()
        sanitized_streams.append({
            "name": stream['stream_name'],
            "id": "".join(c for c in stream['stream_name'] if c.isalnum()),
            "logo_url": stream['logo_url'],
            "frame_filename": f"s{source_id}_{safe_name}.jpg"
        })
    return render_template('m3u_dashboard.html', source=source, streams=sanitized_streams)

@app.route('/data/<int:source_id>/<stream_name>')
def data(source_id, stream_name):
    db = get_db()
    rows = db.execute("SELECT timestamp, is_available, resolution_h, frame_rate, load_time_ms FROM stream_data WHERE source_id = ? AND stream_name = ? AND timestamp >= datetime('now', '-1 day') ORDER BY timestamp",(source_id, stream_name)).fetchall()
    results = { "timestamps": [], "availability": [], "resolutions": [], "framerates": [], "load_times": [] }
    for row in rows:
        utc_timestamp_str = row['timestamp'] + 'Z'
        results["timestamps"].append(utc_timestamp_str); results["availability"].append(row['is_available']); results["resolutions"].append(row['resolution_h']); results["framerates"].append(row['frame_rate']); results["load_times"].append(row['load_time_ms'])
    return jsonify(results)

# --- Gunicorn Logging and Scheduler Startup ---
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error'); app.logger.handlers = gunicorn_logger.handlers; app.logger.setLevel(gunicorn_logger.level)
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True); scheduler_thread.start()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=APP_PORT, debug=True)
