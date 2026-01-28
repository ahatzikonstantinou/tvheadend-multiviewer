import json
import os
from flask import Flask, request, jsonify, send_from_directory
import requests
from datetime import datetime

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7070, debug=True)
