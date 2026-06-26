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

# --- HLS stream manager for RTSP -> HLS conversion (requires ffmpeg) ---
HLS_ROOT = Path(tempfile.gettempdir()) / 'tvmosaic_hls'
HLS_ROOT.mkdir(parents=True, exist_ok=True)

# Map stream_id -> { 'url': rtsp_url, 'proc': Popen, 'dir': Path }
hls_streams = {}
hls_lock = threading.Lock()

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7070, debug=True)

