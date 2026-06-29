import json
import os
import tempfile
from urllib.parse import urlparse, urlunparse
from flask import Flask, request, jsonify, send_from_directory, send_file, abort
import requests
from flask import Response, stream_with_context
from datetime import datetime
import subprocess
import threading
import hashlib
import time
from pathlib import Path
from webcam_manager import Go2RtcManager
import socket

app = Flask(__name__)

rtc_manager = Go2RtcManager()

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

import uuid

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    global rtc_manager

    data = request.json

    cfg = load_config()
    if cfg.get("go2rtc_path") != data.get("go2rtc_path"):
        cfg["go2rtc_path"] = data.get("go2rtc_path")
        rtc_manager = Go2RtcManager(binary_name=cfg["go2rtc_path"])

    initial_cameras = load_cameras_from_config()
    if initial_cameras:
        rtc_manager.start(initial_cameras, go2rtc_url=cfg.get("go2rtc_url", "http://localhost:1984/api/webrtc"))

    for grid in data.get("grids", []):
        if "uuid" not in grid or not grid["uuid"]:
            grid["uuid"] = str(uuid.uuid4())

    with open("config.json", "w") as f:
        json.dump(data, f, indent=2)


    return {"status": "ok"}


@app.route("/api/test_rtsp", methods=["POST"])
def api_test_rtsp():
    data = request.get_json(force=True)
    rtsp_url = data.get("rtsp_url")
    
    if not rtsp_url:
        return jsonify({"ok": False, "error": "No URL"}), 400
    
    try:
        cfg = load_config()
        go2rtc_url = cfg.get("go2rtc_url", "http://localhost:1984/api/webrtc")
        
        # Καθαρισμός του URL για τη χρήση του API
        if go2rtc_url.endswith("/webrtc"):
            go2rtc_url = go2rtc_url[:-7]
        elif go2rtc_url.endswith("/webrtc/"):
            go2rtc_url = go2rtc_url[:-8]
                                
        # 1. Βασικό Network Validation (TCP Check)
        parsed = urlparse(rtsp_url)
        if parsed.scheme.lower() not in ["rtsp", "rtsps"]:
            return jsonify({"ok": False, "error": "Invalid protocol. Must be RTSP"}), 400
            
        hostname = parsed.hostname
        port = parsed.port if parsed.port is not None else 554
        
        print(f"[RTSP Test] Checking connectivity to {hostname}:{port}...")
        with socket.create_connection((hostname, port), timeout=2.0):
            pass
        print(f"[RTSP Test] Successfully connected to {hostname}:{port}")

        # 2. Λήψη των υπαρχόντων streams από το go2rtc
        status_response = requests.get(f"{go2rtc_url}/streams", timeout=2.0)
        if status_response.status_code != 200:
            return jsonify({"ok": False, "error": "Could not connect to go2rtc API"}), 503
            
        current_streams = status_response.json()

        # 3. Έλεγχος αν το RTSP URL υπάρχει ήδη καταχωρημένο σε κάποιο stream
        for stream_name, stream_info in current_streams.items():
            # Το go2rtc αποθηκεύει το URL στους producers
            producers = stream_info.get("producers", [])
            for producer in producers:
                if producer.get("url") == rtsp_url:
                    return jsonify({
                        "ok": True,
                        "message": f"Camera already exists and is active under the name: '{stream_name}'",
                        "details": {
                            "stream_name": stream_name,
                            "producers_count": len(producers)
                        }
                    }), 200

        # 4. Αν ΔΕΝ υπάρχει, δημιουργούμε ένα εγγυημένα ΜΟΝΑΔΙΚΟ όνομα (UUID) για το τεστ
        unique_id = str(uuid.uuid4())[:8]
        temp_stream_name = f"test_cam_{unique_id}"
        
        # Προσθήκη του stream δυναμικά στο go2rtc μέσω PUT
        add_stream_url = f"{go2rtc_url}/streams?src={temp_stream_name}&dst={rtsp_url}"
        add_response = requests.put(add_stream_url, timeout=3.0)
        
        if add_response.status_code != 200:
            return jsonify({"ok": False, "error": "Failed to register stream in go2rtc"}), 502

        # Αναμονή για να προλάβει το go2rtc να συνδεθεί
        time.sleep(1.5)

        # Έλεγχος της κατάστασης του νέου, μοναδικού stream
        check_response = requests.get(f"{go2rtc_url}/streams", timeout=2.0)
        
        # Καθαρισμός του προσωρινού stream αμέσως μετά τον έλεγχο
        requests.delete(f"{go2rtc_url}/streams?src={temp_stream_name}", timeout=2.0)

        if check_response.status_code == 200:
            latest_streams = check_response.json()
            cam_info = latest_streams.get(temp_stream_name, {})
            producers = cam_info.get("producers", [])
            
            if producers:
                return jsonify({
                    "ok": True,
                    "message": "Stream verification successful!",
                    "details": {"producers_count": len(producers)}
                }), 200
            else:
                return jsonify({
                    "ok": False,
                    "error": "Authentication failed or invalid RTSP path. Camera rejected go2rtc."
                }), 401

        return jsonify({"ok": False, "error": "Could not verify stream status"}), 500

    except socket.error:
        return jsonify({"ok": False, "error": "Camera is offline or RTSP port is closed."}), 502
    except requests.exceptions.RequestException as e:
        return jsonify({"ok": False, "error": "go2rtc API is unreachable", "details": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": "Internal error", "details": str(e)}), 500


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


# --- MP4 stream manager for RTSP -> progressive MP4 output ---
MP4_ROOT = Path(tempfile.gettempdir()) / 'tvmosaic_mp4'
MP4_ROOT.mkdir(parents=True, exist_ok=True)

mp4_streams = {}
mp4_lock = threading.Lock()

# --- Combined grid stream manager for tiled video output ---
GRID_ROOT = Path(tempfile.gettempdir()) / 'tvmosaic_grid'
GRID_ROOT.mkdir(parents=True, exist_ok=True)

grid_streams = {}
grid_lock = threading.Lock()

CELL_WIDTH = 320
CELL_HEIGHT = 180


def _stream_id_for_url(url: str) -> str:
    h = hashlib.sha1(url.encode('utf-8')).hexdigest()
    return h

'''
# --- HLS stream manager for RTSP -> HLS conversion (requires ffmpeg) ---
HLS_ROOT = Path(tempfile.gettempdir()) / 'tvmosaic_hls'
HLS_ROOT.mkdir(parents=True, exist_ok=True)


# Map stream_id -> { 'url': rtsp_url, 'proc': Popen, 'dir': Path }
hls_streams = {}
hls_lock = threading.Lock()


def start_hls_for_url(rtsp_url: str):
    sid = _stream_id_for_url(rtsp_url)
    d = HLS_ROOT / sid
    d.mkdir(parents=True, exist_ok=True)

    with hls_lock:
        info = hls_streams.get(sid)
        if info and info.get('proc') and info['proc'].poll() is None:
            # already running — update last_used and return
            info['last_used'] = time.time()
            return sid

        # remove previous generated files
        for f in d.glob('*'):
            try:
                f.unlink()
            except Exception:
                pass

        # Build ffmpeg command. For RTSP inputs we re-encode to provide
        # stable frame/keyframe intervals and predictable segments for browsers.
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'info']
        if rtsp_url.startswith('rtsp://'):
            # RTSP: request TCP transport and re-encode video to h264 with
            # low-latency settings so browsers can append segments reliably.
            cmd += ['-rtsp_transport', 'tcp', '-i', rtsp_url,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
                    '-r', '25', '-g', '50', '-keyint_min', '50', '-b:v', '1200k',
                    '-c:a', 'aac', '-b:a', '96k']
        else:
            # HTTP / file inputs: copy video where possible to save CPU.
            cmd += ['-i', rtsp_url, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k']

        cmd += [
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '6',
            '-hls_flags', 'delete_segments+append_list',
                '-hls_segment_type', 'fmp4',
                '-hls_fmp4_init_filename', 'init.mp4',
            '-hls_allow_cache', '0',
            str(d / 'index.m3u8')
        ]

        # Start ffmpeg and capture stderr to a log for debugging
        log_path = d / 'ffmpeg.log'
        logfh = open(log_path, 'ab')
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=logfh)

        # wait up to ~10s for the playlist to appear
        for _ in range(20):
            if (d / 'index.m3u8').exists() and (d / 'index.m3u8').stat().st_size > 0:
                break
            time.sleep(0.5)

        hls_streams[sid] = {
            'url': rtsp_url,
            'proc': proc,
            'dir': d,
            'log': str(log_path),
            'logfh': logfh,
            'last_used': time.time()
        }

        # watcher: remove mapping and close log when process exits
        def _watch():
            while True:
                ret = proc.poll()
                if ret is None:
                    time.sleep(1)
                    continue
                with hls_lock:
                    entry = hls_streams.get(sid)
                    if entry and entry.get('proc') is proc:
                        try:
                            lf = entry.get('logfh')
                            if lf:
                                lf.close()
                        except Exception:
                            pass
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
        # close log file handle if present
        try:
            lf = info.get('logfh')
            if lf:
                lf.close()
        except Exception:
            pass
        hls_streams.pop(sid, None)
    return True
'''

def build_tvh_input_url(cfg, channel_uuid: str):
    base = (cfg.get('tvheadend_url') or '').rstrip('/')
    if not base or not channel_uuid:
        return None

    url = f"{base}/stream/channel/{channel_uuid}?profile=matroska" #webtv-mp4"
    username = cfg.get('tvh_username')
    password = cfg.get('tvh_password')
    if username and password:
        parsed = urlparse(url)
        auth_netloc = f"{username}:{password}@{parsed.hostname}"
        if parsed.port:
            auth_netloc += f":{parsed.port}"
        parsed = parsed._replace(netloc=auth_netloc)
        url = urlunparse(parsed)
    return url


def start_grid_for_uuid(grid_uuid: str):
    cfg = load_config()
    grids = cfg.get('grids', []) or []
    # DEBUG PRINTS - Θα φανούν στο τερματικό που τρέχει η Flask
    print(f"=== DEBUG: Zητήθηκε το Grid UUID: {grid_uuid} ===")
    print(f"=== DEBUG: Διαθέσιμα UUIDs στο config: {[g.get('uuid') for g in grids]} ===")

    grid = next((g for g in grids if g.get('uuid') == grid_uuid), None)
    if not grid:
        raise ValueError(f'Grid {grid_uuid} not found in config')

    rows = int(grid.get('rows', 1))
    cols = int(grid.get('cols', 1))
    if rows < 1 or cols < 1:
        raise ValueError('Grid rows and cols must be positive')

    sid = grid_uuid
    d = GRID_ROOT / sid
    d.mkdir(parents=True, exist_ok=True)

    with grid_lock:
        info = grid_streams.get(sid)
        if info and info.get('proc') and info['proc'].poll() is None:
            info['last_used'] = time.time()
            return sid

        for f in d.glob('*'):
            try:
                f.unlink()
            except Exception:
                pass

        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'info', 
            '-fflags', '+genpts+discardcorrupt+nobuffer', # Απόρριψη κατεστραμμένων πακέτων αμέσως
            '-flags', 'low_delay'
        ]

        cells = grid.get('cells', []) or []
        print(f"=== DEBUG: Βρέθηκαν {len(cells)} cells για αυτό το grid ===")
        print(f"=== DEBUG: Περιεχόμενο cells: {cells} ===")
        sources = []

        for r in range(rows):
            for c in range(cols):
                # Μετατροπή των row/col του cell_cfg σε int για ασφαλή σύγκριση
                cell_cfg = next((x for x in cells if int(x.get('row', -1)) == r and int(x.get('col', -1)) == c), None)
                if cell_cfg and cell_cfg.get('source_type') == 'rtsp' and cell_cfg.get('rtsp_url'):
                    sources.append(cell_cfg.get('rtsp_url'))
                elif cell_cfg and cell_cfg.get('channel_uuid'):
                    tvh_url = build_tvh_input_url(cfg, cell_cfg.get('channel_uuid'))
                    sources.append(tvh_url)
                else:
                    sources.append(None)

        for idx, source in enumerate(sources):
            if source is None:
                cmd += ['-f', 'lavfi', '-i', f'color=size={CELL_WIDTH}x{CELL_HEIGHT}:rate=25:color=black']
            else:
                cmd += [
                    '-timeout', '5000000',
                    '-fflags', '+discardcorrupt+nobuffer+genpts',
                    '-flags', 'low_delay'
                ]
                if source.startswith('rtsp://'):
                    cmd += ['-rtsp_transport', 'tcp']
                
                # Υβριδικό σύστημα: Τα πρώτα 3 streams πάνε στην GPU, τα υπόλοιπα στην CPU
                # Αυτό αποτρέπει το V4L2 capture poll unexpected timeout (crash)
                if idx < 3:
                    cmd += ['-c:v', 'h264_v4l2m2m']
                
                cmd += ['-i', source]

        # 2. Φίλτρα με εξαναγκασμό FPS (Διορθώνει τα σφάλματα συγχρονισμού)
        filter_parts = []
        for idx in range(len(sources)):
            filter_parts.append(
                f'[{idx}:v]fps=fps=25,setpts=PTS-STARTPTS,scale={CELL_WIDTH}:{CELL_HEIGHT}:force_original_aspect_ratio=decrease,pad={CELL_WIDTH}:{CELL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v{idx}]'
            )

        layout_entries = []
        for r in range(rows):
            for c in range(cols):
                x = c * CELL_WIDTH
                y = r * CELL_HEIGHT
                layout_entries.append(f'{x}_{y}')

        stacked_inputs = ''.join(f'[v{i}]' for i in range(len(sources)))
        layout = '|'.join(layout_entries)
        filter_parts.append(f'{stacked_inputs}xstack=inputs={len(sources)}:layout={layout}:fill=black[vout]')
        filter_complex = ';'.join(filter_parts)

        # rpi cannot decode and re-encode multiple streams in one stream in software or hardware efficiently
        # You need to use a mini pc or server, with a gpu to do this. Only then will grid3 work correctly.
        # If so, change the following params according to your gpu (e.g. h264_nvenc, h264_qsv, etc.)
        cmd += [
            '-filter_complex', filter_complex,
            '-map', '[vout]',
            '-c:v', 'h264_v4l2m2m',          # Hardware Encoder για την έξοδο
            '-num_output_buffers', '32',
            '-r', '25',
            '-g', '25',                      # 1 keyframe ανά δευτερόλεπτο
            '-b:v', '800k',                  # Χαμηλό bitrate, ιδανικό για RPi 1GB
            '-maxrate', '1000k',
            '-bufsize', '800k',
            '-pix_fmt', 'yuv420p',
            '-an',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-y',
            str(d / 'stream.mp4')
        ]

        log_path = d / 'ffmpeg.log'
        logfh = open(log_path, 'ab')
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=logfh)

        for _ in range(40):
            if (d / 'stream.mp4').exists() and (d / 'stream.mp4').stat().st_size > 1024:
                break
            time.sleep(0.5)

        grid_streams[sid] = {
            'proc': proc,
            'dir': d,
            'log': str(log_path),
            'logfh': logfh,
            'last_used': time.time()
        }

        def _watch():
            while True:
                ret = proc.poll()
                if ret is None:
                    time.sleep(1)
                    continue
                with grid_lock:
                    entry = grid_streams.get(sid)
                    if entry and entry.get('proc') is proc:
                        try:
                            lf = entry.get('logfh')
                            if lf:
                                lf.close()
                        except Exception:
                            pass
                        grid_streams.pop(sid, None)
                break

        threading.Thread(target=_watch, daemon=True).start()
        return sid


'''
def start_mp4_for_url(rtsp_url: str):
    sid = _stream_id_for_url(rtsp_url)
    d = MP4_ROOT / sid
    d.mkdir(parents=True, exist_ok=True)

    with mp4_lock:
        info = mp4_streams.get(sid)
        if info and info.get('proc') and info['proc'].poll() is None:
            info['last_used'] = time.time()
            return sid

        for f in d.glob('*'):
            try:
                f.unlink()
            except Exception:
                pass

        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'info', '-fflags', '+genpts']
        if rtsp_url.startswith('rtsp://'):
            cmd += ['-rtsp_transport', 'tcp', '-i', rtsp_url]
        else:
            cmd += ['-i', rtsp_url]

        cmd += [
            '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency',
            '-r', '25', '-g', '50', '-keyint_min', '50', '-b:v', '1200k',
            '-c:a', 'aac', '-b:a', '96k',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-y', str(d / 'stream.mp4')
        ]

        log_path = d / 'ffmpeg.log'
        logfh = open(log_path, 'ab')
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=logfh)

        for _ in range(20):
            if (d / 'stream.mp4').exists() and (d / 'stream.mp4').stat().st_size > 1024:
                break
            time.sleep(0.5)

        mp4_streams[sid] = {
            'url': rtsp_url,
            'proc': proc,
            'dir': d,
            'log': str(log_path),
            'logfh': logfh,
            'last_used': time.time()
        }

        def _watch():
            while True:
                ret = proc.poll()
                if ret is None:
                    time.sleep(1)
                    continue
                with mp4_lock:
                    entry = mp4_streams.get(sid)
                    if entry and entry.get('proc') is proc:
                        try:
                            lf = entry.get('logfh')
                            if lf:
                                lf.close()
                        except Exception:
                            pass
                        mp4_streams.pop(sid, None)
                break

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

        return sid


#used in grid2.html
@app.route('/stream/mp4/start', methods=['POST'])
def api_start_mp4():
    data = request.get_json(force=True)
    rtsp_url = data.get('rtsp_url')
    source_url = data.get('source_url')

    url = rtsp_url or source_url
    if not url:
        return jsonify({'ok': False, 'error': 'No rtsp_url or source_url provided'}), 400

    try:
        sid = start_mp4_for_url(url)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    stream_url = f'/stream/mp4/{sid}/stream.mp4'
    return jsonify({'ok': True, 'stream_id': sid, 'stream_url': stream_url})


#used in grid2.html
@app.route('/stream/mp4/<sid>/stream.mp4')
def serve_mp4(sid):
    d = MP4_ROOT / sid
    if not d.exists():
        return abort(404)
    fpath = d / 'stream.mp4'
    if not fpath.exists():
        return abort(404)

    info = mp4_streams.get(sid)
    proc = info.get('proc') if info else None

    def generate():
        with open(fpath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if chunk:
                    yield chunk
                    continue
                if proc is not None and proc.poll() is not None:
                    # FFmpeg finished and no more data is available
                    break
                time.sleep(0.1)

    resp = Response(stream_with_context(generate()), mimetype='video/mp4')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp
'''


#used in grid3.html
@app.route('/stream/grid/<grid_uuid>/stream.mp4')
def serve_grid_stream(grid_uuid):
    try:
        sid = start_grid_for_uuid(grid_uuid)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    d = GRID_ROOT / sid
    fpath = d / 'stream.mp4'

    info = grid_streams.get(sid)
    proc = info.get('proc') if info else None

    def generate_grid():
        # Περιμένουμε να ξεκινήσει να γράφεται το αρχείο
        timeout = 20
        start_time = time.time()
        while not fpath.exists() or fpath.stat().st_size < 4096: # Περιμένουμε τουλάχιστον 4KB
            if time.time() - start_time > timeout:
                return
            if proc is not None and proc.poll() is not None:
                return
            time.sleep(0.1)

        with open(fpath, 'rb') as f:
            while True:
                chunk = f.read(16384) # Μικρότερο chunk (32KB) για πιο ομαλή ροή
                if chunk:
                    yield chunk
                    time.sleep(0.01) # Μικρή καθυστέρηση για σταθερό playback στον browser
                    continue
                
                if proc is not None and proc.poll() is None:
                    time.sleep(0.1) # Περιμένουμε το Pi να γράψει τα επόμενα frames
                    continue
                
                remaining = f.read()
                if remaining:
                    yield remaining
                break

    resp = Response(stream_with_context(generate_grid()), mimetype='video/mp4')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/grid3')
def grid3_page():
    return send_from_directory('static', 'grid3.html')

'''
@app.route('/stream/hls/<sid>/<path:filename>')
def serve_hls(sid, filename):
    d = HLS_ROOT / sid
    if not d.exists():
        return abort(404)
    fpath = d / filename
    if not fpath.exists():
        return abort(404)
    # serve file
    resp = send_from_directory(str(d), filename)
    # prevent aggressive caching by browsers
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/stream/hls/status/<sid>')
def hls_status(sid):
    d = HLS_ROOT / sid
    if not d.exists():
        return jsonify({'ok': False, 'error': 'no such sid'}), 404
    playlist = d / 'index.m3u8'
    has_playlist = playlist.exists() and playlist.stat().st_size > 0
    has_segments = any(d.glob('*.m4s')) or (d / 'init.mp4').exists()
    return jsonify({'ok': True, 'sid': sid, 'has_playlist': has_playlist, 'has_segments': has_segments})
'''


# RTC code
#

def load_cameras_from_config():
    cameras = {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            config_data = json.load(f)
            
        grids = config_data.get("grids", [])
        camera_index = 1
        
        for grid in grids:            
            cells = grid.get("cells", [])
            for cell in cells:
                if cell.get("source_type") == "rtsp":
                    raw_url = cell.get("rtsp_url", "")
                    
                    # Καθαρισμός του URL από το "Video url - " αν υπάρχει
                    if "rtsp://" in raw_url:
                        clean_url = "rtsp://" + raw_url.split("rtsp://")[1]
                        
                        # Build go2rtc stream list
                        # stream_list = [clean_url]
                        stream_list = [f"ffmpeg:{clean_url}#video=copy#audio=opus"]

                        # if "live0" in clean_url:  # heuristic for AAC cameras
                        #     stream_list.append("ffmpeg:audio=opus")
                        
                        # Δημιουργία ID κάμερας (π.χ. camera1, camera2...)
                        cam_id = f"camera{camera_index}"
                        cameras[cam_id] = stream_list
                        camera_index += 1
                        
    except (FileNotFoundError, json.JSONDecodeError, IndexError) as e:
        print(f"Σφάλμα κατά την επεξεργασία του αρχείου ρυθμίσεων: {e}")
        
    return cameras
    

@app.route('/api/stream/<camera_id>', methods=['POST'])
def stream_signaling(camera_id):
    """Μεσολαβεί για την ανταλλαγή WebRTC SDP μεταξύ frontend και go2rtc"""
    go2rtc_url = None
    try:
        with open(CONFIG_FILE, 'r') as f:
            config_data = json.load(f)
        go2rtc_url = config_data.get("go2rtc_url", "http://192.168.3.104:1984/api/webrtc")
    except (FileNotFoundError, json.JSONDecodeError, IndexError) as e:
        print(f"Σφάλμα κατά την επεξεργασία του αρχείου ρυθμίσεων: {e}")
        
    if not go2rtc_url:
        return jsonify({"error": "Η διεύθυνση go2rtc δεν έχει ρυθμιστεί"}), 500
    
    if camera_id == "test_connection":
        try:
            test_url = request.args.get('go2rtc_url')
            print(f"Δοκιμή σύνδεσης στο go2rtc API: {test_url}")
            test_url = f"{urlparse(test_url).scheme}://{urlparse(test_url).netloc}/api"
            print(f"Δοκιμή σύνδεσης στο go2rtc API: {test_url}")
            requests.get(test_url, timeout=2)
            return jsonify({"status": "connected"}), 200
        except Exception:
            return jsonify({"error": "go2rtc binary is not running"}), 500

    # Ασφαλής έλεγχος ύπαρξης κάμερας
    cameras = load_cameras_from_config()
    
    # Μετατροπή σε λίστα κλειδιών αν το cameras είναι dictionary, για να δουλεύει ομοιόμορφα το 'in'
    camera_keys = cameras.keys() if isinstance(cameras, dict) else cameras
    
    if camera_id not in camera_keys:
        return jsonify({"error": f"Η κάμερα '{camera_id}' δεν βρέθηκε στις ρυθμίσεις"}), 404
        
    frontend_sdp = request.data
    
    try:
        # Αποστολή του Offer στο go2rtc
        response = requests.post(
            f"{go2rtc_url}?src={camera_id}",
            data=frontend_sdp,
            headers={'Content-Type': 'text/plain'},
            timeout=5
        )
        
        print(f"Response: {response.text}")
        if response.status_code != 200:
            print(f"Το go2rtc επέστρεψε σφάλμα {response.status_code}: {response.text}")
            return jsonify({"error": f"go2rtc error: {response.text}"}), response.status_code

        print(f"Επιτυχές Signaling Handshake για την κάμερα: {camera_id}")

        # Επιστροφή του SDP Answer ως καθαρό Response με text/plain
        return Response(
            response.content, # Επιστροφή ως bytes για διατήρηση του \r\n
            status=response.status_code, 
            mimetype='text/plain'
        )
        
    except requests.exceptions.ConnectionError:
        # Επιστρέφει ένα καθαρό σφάλμα 502 αντί για crash 500
        return jsonify({"error": "go2rtc does not answer.", "code": "GO2RTC_OFFLINE"}), 502
    except requests.exceptions.RequestException as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to contact go2rtc: {str(e)}"}), 500


#
#end of RTC code

if __name__ == "__main__":
    cfg = load_config()
    initial_cameras = load_cameras_from_config()
    if initial_cameras:
        rtc_manager = Go2RtcManager(binary_name=cfg.get("go2rtc_path", "go2rtc_linux_arm64"))
        rtc_manager.start(
            initial_cameras, 
            go2rtc_url=cfg.get("go2rtc_url", "http://localhost:1984/api/webrtc"))
    else:
        print("ΠΡΟΕΙΔΟΠΟΙΗΣΗ: Δεν βρέθηκαν κάμερες για να ξεκινήσει το go2rtc.")

    app.run(host="0.0.0.0", port=7070, use_reloader=False, debug=True)

