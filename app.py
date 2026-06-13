import json
import os
from flask import Flask, request, jsonify, send_from_directory, send_file, abort
import requests
from flask import Response, stream_with_context
from datetime import datetime
import subprocess
import threading
import hashlib
import time
from pathlib import Path

app = Flask(__name__)

CONFIG_FILE = "config.json"

def format_ts(ts): 
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        # default config
        return {
            "tvheadend_url": "http://192.168.3.104:9981",
            "grid_rows": 3,
            "grid_cols": 4,
            "cells": []  # list of {"row":0,"col":0,"channel_uuid":null}
        }
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/grid")
def grid_page():
    return send_from_directory("static", "grid.html")

@app.route("/grid2")
def grid2_page():
    return send_from_directory("static", "grid2.html")

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
        cfg = load_config()
        return jsonify(cfg)

# @app.route("/api/settings", methods=["GET", "POST"])
# def api_settings():
#     data = request.get_json(force=True)
#     cfg = load_config()

#     cfg["tvheadend_url"] = data.get("tvheadend_url", cfg.get("tvheadend_url"))
#     cfg["tvh_username"] = data.get("tvh_username", cfg.get("tvh_username"))
#     cfg["tvh_password"] = data.get("tvh_password", cfg.get("tvh_password"))

#     cfg["grid_rows"] = int(data.get("grid_rows", cfg["grid_rows"]))
#     cfg["grid_cols"] = int(data.get("grid_cols", cfg["grid_cols"]))
#     cfg["cells"] = data.get("cells", cfg.get("cells", []))

#     save_config(cfg)
#     return jsonify({"status": "ok"})

import uuid

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.json

    for grid in data.get("grids", []):
        if "uuid" not in grid or not grid["uuid"]:
            grid["uuid"] = str(uuid.uuid4())

    with open("config.json", "w") as f:
        json.dump(data, f, indent=2)

    return {"status": "ok"}



@app.route("/api/test_connection", methods=["POST"])
def api_test_connection():
    data = request.get_json(force=True)
    tvh_url = data.get("tvheadend_url")
    if not tvh_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    tvh_username = data.get("tvh_username") 
    tvh_password = data.get("tvh_password")
    try:
        r = requests.get(
            tvh_url.rstrip("/") + "/api/serverinfo",
            auth=(tvh_username, tvh_password) if tvh_password else None,
            timeout=3
        )
        if r.status_code == 200:
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/api/test_rtsp", methods=["POST"])
def api_test_rtsp():
    data = request.get_json(force=True)
    rtsp_url = data.get("rtsp_url")
    
    if not rtsp_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    
    try:
        # Use ffprobe to test if stream is accessible
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', 
             rtsp_url],
            timeout=5,
            capture_output=True
        )
        
        if result.returncode == 0:
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": "Stream not accessible"}), 200
    
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Connection timeout"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/api/channels", methods=["POST"])
def api_channels():
    data = request.get_json(force=True)
    tvh_url = data.get("tvheadend_url")
    if not tvh_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    tvh_username = data.get("tvh_username") 
    tvh_password = data.get("tvh_password")
    try:
        r = requests.get(
            tvh_url.rstrip("/") + "/api/channel/grid?limit=999",
            auth=(tvh_username, tvh_password) if tvh_password else None,
            timeout=5
        )
        r.raise_for_status()
        j = r.json()
        entries = j.get("entries", [])
        channels = [
            {
                "uuid": e.get("uuid"),
                "name": e.get("name"),
                "number": e.get("number"), 
                "chid": e.get("chid")
            }
            for e in entries
        ]
        return jsonify({"ok": True, "channels": channels})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200
    
@app.route("/api/audioinfo", methods=["POST"])
def api_audioinfo():
    data = request.get_json(force=True)
    tvh_url = data.get("tvheadend_url")

    if not tvh_url:
        return jsonify({"ok": False, "error": "No URL"}), 400

    try:
        url = tvh_url.rstrip("/") + "/api/stream/list"
        r = requests.get(url, timeout=5)
        r.raise_for_status()

        j = r.json()
        entries = j.get("entries", [])

        # Map: channel_uuid → audio codec
        audio_map = {}

        for e in entries:
            if e.get("type") != "Audio":
                continue

            codec = e.get("codec")
            channel_uuid = e.get("channel_uuid")

            if channel_uuid and codec:
                audio_map[channel_uuid] = codec.lower()

        return jsonify({"ok": True, "audio": audio_map})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/epg/all")
def get_all_epg():
    cfg = load_config()    
    tvh_url = cfg["tvheadend_url"]
    if not tvh_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    tvh_username = cfg["tvh_username"]
    tvh_password = cfg["tvh_password"]
    try:
        response = requests.get(
            tvh_url.rstrip("/") + "/api/epg/events/grid",
            auth=(tvh_username, tvh_password) if tvh_password else None,
            timeout=5
        )
        response.raise_for_status()

        data = response.json()

        # Tvheadend returns {"entries": [...], "total": ...}
        programs = data.get("entries", [])
        
        enriched = []
        for p in programs:
            start = p.get("start")
            stop = p.get("stop")

            p["start_str"] = format_ts(start) if start else None
            p["stop_str"] = format_ts(stop) if stop else None

            enriched.append(p)

        return jsonify({
            "status": "ok",
            "count": len(enriched),
            "programs": enriched
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# tvh_proxy is a simple proxy endpoint that takes a channel UUID, constructs the stream URL for that channel, and proxies the stream back to the client. This is used to work around CORS issues when trying to access the TVHeadend stream directly from the browser. However, it causes continues freeze-ups in all streams.
@app.route('/tvh_proxy/<channel_uuid>')
def tvh_proxy(channel_uuid):
    cfg = load_config()    
    tvh_url = cfg["tvheadend_url"]
    if not tvh_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    tvh_username = cfg["tvh_username"]
    tvh_password = cfg["tvh_password"]
    tvh_url = f"{tvh_url}/stream/channel/{channel_uuid}?profile=webtv-mp4"
    
    req = requests.get(
        tvh_url, 
        stream=True, 
        #auth=None,
        auth=(tvh_username, tvh_password),
        timeout=15
    )
    
    # Διοχετεύουμε το stream απευθείας στον browser bit-by-bit
    return Response(
        stream_with_context(req.iter_content(chunk_size=1024)),
        content_type=req.headers.get('content-type'),
        status=req.status_code
    )        

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7070, debug=True)

# --- HLS stream manager for RTSP -> HLS conversion (requires ffmpeg) ---
HLS_ROOT = Path('/tmp/tvmosaic_hls')
HLS_ROOT.mkdir(parents=True, exist_ok=True)

# Map stream_id -> { 'url': rtsp_url, 'proc': Popen, 'dir': Path }
hls_streams = {}
hls_lock = threading.Lock()

def _stream_id_for_url(url: str) -> str:
    h = hashlib.sha1(url.encode('utf-8')).hexdigest()
    return h

def start_hls_for_url(rtsp_url: str):
    sid = _stream_id_for_url(rtsp_url)
    d = HLS_ROOT / sid
    d.mkdir(parents=True, exist_ok=True)

    with hls_lock:
        info = hls_streams.get(sid)
        if info and info.get('proc') and info['proc'].poll() is None:
            # already running
            return sid

        # remove previous files
        for f in d.glob('*'):
            try:
                f.unlink()
            except Exception:
                pass

        # ffmpeg command: use TCP for RTSP transport, copy video codec, encode audio to aac
        cmd = [
            'ffmpeg', '-rtsp_transport', 'tcp', '-i', rtsp_url,
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k',
            '-f', 'hls',
            '-hls_time', '2',
            '-hls_list_size', '3',
            '-hls_flags', 'delete_segments+append_list',
            '-hls_allow_cache', '0',
            str(d / 'index.m3u8')
        ]

        # Start ffmpeg
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        hls_streams[sid] = {
            'url': rtsp_url,
            'proc': proc,
            'dir': d,
            'last_used': time.time()
        }

        # Start a watcher thread to restart if ffmpeg exits
        def _watch():
            while True:
                ret = proc.poll()
                if ret is None:
                    time.sleep(1)
                    continue
                # process exited; remove mapping
                with hls_lock:
                    entry = hls_streams.get(sid)
                    if entry and entry.get('proc') is proc:
                        hls_streams.pop(sid, None)
                break

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

        return sid

def stop_hls_for_id(sid: str):
    with hls_lock:
        info = hls_streams.get(sid)
        if not info:
            return False
        proc = info.get('proc')
        try:
            proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        hls_streams.pop(sid, None)
    return True


@app.route('/stream/hls/start', methods=['POST'])
def api_start_hls():
    data = request.get_json(force=True)
    rtsp_url = data.get('rtsp_url')
    if not rtsp_url:
        return jsonify({'ok': False, 'error': 'No rtsp_url provided'}), 400

    sid = start_hls_for_url(rtsp_url)
    playlist_url = f'/stream/hls/{sid}/index.m3u8'
    return jsonify({'ok': True, 'stream_id': sid, 'playlist': playlist_url})


@app.route('/stream/hls/<sid>/<path:filename>')
def serve_hls(sid, filename):
    d = HLS_ROOT / sid
    if not d.exists():
        return abort(404)
    fpath = d / filename
    if not fpath.exists():
        return abort(404)
    # serve file
    return send_from_directory(str(d), filename)

