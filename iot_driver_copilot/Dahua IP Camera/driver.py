import os
import io
import base64
import threading
import requests
import time
from flask import Flask, Response, request, jsonify, stream_with_context

import cv2
import numpy as np

# Configuration from environment variables
CAMERA_HOST = os.environ.get("DAHUA_CAMERA_HOST", "192.168.1.100")
CAMERA_RTSP_PORT = int(os.environ.get("DAHUA_CAMERA_RTSP_PORT", "554"))
CAMERA_RTSP_PATH = os.environ.get("DAHUA_CAMERA_RTSP_PATH", "cam/realmonitor?channel=1&subtype=0")
CAMERA_USER = os.environ.get("DAHUA_CAMERA_USER", "admin")
CAMERA_PASS = os.environ.get("DAHUA_CAMERA_PASS", "admin")
CAMERA_HTTP_PORT = int(os.environ.get("DAHUA_CAMERA_HTTP_PORT", "80"))

SERVER_HOST = os.environ.get("DRIVER_HTTP_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("DRIVER_HTTP_PORT", "8080"))

PTZ_PATH = os.environ.get("DAHUA_CAMERA_PTZ_PATH", "cgi-bin/ptz.cgi")
RECORD_PATH = os.environ.get("DAHUA_CAMERA_RECORD_PATH", "cgi-bin/configManager.cgi?action=setConfig&VideoInRecord[0].Mode=")
STATUS_PATH = os.environ.get("DAHUA_CAMERA_STATUS_PATH", "cgi-bin/magicBox.cgi?action=getSystemInfo")
SNAP_PATH = os.environ.get("DAHUA_CAMERA_SNAP_PATH", "cgi-bin/snapshot.cgi?channel=1")

RTSP_URL = f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_HOST}:{CAMERA_RTSP_PORT}/{CAMERA_RTSP_PATH}"

app = Flask(__name__)

# MJPEG streaming generator
def mjpeg_stream():
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b"\xff\xd8\xff\xe0" + b"\r\n"
        return
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            ret2, jpeg = cv2.imencode('.jpg', frame)
            if not ret2:
                continue
            frame_bytes = jpeg.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
    finally:
        cap.release()

# Snapshot fetcher
def fetch_snapshot():
    url = f"http://{CAMERA_HOST}:{CAMERA_HTTP_PORT}/{SNAP_PATH}"
    try:
        resp = requests.get(url, auth=(CAMERA_USER, CAMERA_PASS), timeout=5, stream=True)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception:
        return None

# Status fetcher
def fetch_status():
    url = f"http://{CAMERA_HOST}:{CAMERA_HTTP_PORT}/{STATUS_PATH}"
    try:
        resp = requests.get(url, auth=(CAMERA_USER, CAMERA_PASS), timeout=5)
        if resp.status_code == 200:
            # Dahua returns plain text with key=value lines; convert to dict
            data = {}
            for line in resp.text.splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    data[k.strip()] = v.strip()
            return data
        return {"error": "Failed to fetch"}
    except Exception as e:
        return {"error": str(e)}

# Recording control
def set_recording(action):
    # action: 'start' or 'stop'
    # Mode=Manual for start, Mode=Off for stop
    mode = "Manual" if action == "start" else "Off"
    url = f"http://{CAMERA_HOST}:{CAMERA_HTTP_PORT}/cgi-bin/configManager.cgi?action=setConfig&VideoInRecord[0].Mode={mode}"
    try:
        resp = requests.get(url, auth=(CAMERA_USER, CAMERA_PASS), timeout=5)
        if resp.status_code == 200:
            return {"success": True, "mode": mode}
        return {"success": False, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}

# PTZ control
def ptz_control(direction=None, action=None, speed=5, zoom=None):
    # direction: up, down, left, right; action: start/stop; zoom: in/out
    params = []
    if direction in ("up", "down", "left", "right"):
        params.append(f"action={action or 'start'}")
        params.append(f"channel=1")
        params.append(f"code={direction}")
        params.append(f"arg1=0&arg2=0&arg3={speed}")
    elif zoom in ("in", "out"):
        params.append(f"action={action or 'start'}")
        params.append(f"channel=1")
        params.append(f"code={'ZoomTele' if zoom == 'in' else 'ZoomWide'}")
        params.append(f"arg1=0&arg2=0&arg3={speed}")
    else:
        return {"error": "Invalid PTZ parameters"}
    url = f"http://{CAMERA_HOST}:{CAMERA_HTTP_PORT}/{PTZ_PATH}?" + "&".join(params)
    try:
        resp = requests.get(url, auth=(CAMERA_USER, CAMERA_PASS), timeout=5)
        if resp.status_code == 200:
            return {"success": True}
        return {"success": False, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route("/status", methods=["GET"])
def api_status():
    data = fetch_status()
    # Add connection and recording status
    data['connection'] = "connected"
    data['recording'] = "unknown"
    return jsonify(data)

@app.route("/record", methods=["POST"])
def api_record():
    body = request.json or {}
    action = body.get("action", "").lower()
    if action not in ("start", "stop"):
        return jsonify({"error": "Invalid action, must be 'start' or 'stop'"}), 400
    result = set_recording(action)
    return jsonify(result)

@app.route("/ptz", methods=["POST"])
def api_ptz():
    body = request.json or {}
    direction = body.get("direction")
    action = body.get("action", "start")
    speed = int(body.get("speed", 5))
    zoom = body.get("zoom")
    result = ptz_control(direction=direction, action=action, speed=speed, zoom=zoom)
    return jsonify(result)

@app.route("/snap", methods=["GET"])
def api_snap():
    img = fetch_snapshot()
    if img:
        return Response(img, mimetype="image/jpeg")
    return jsonify({"error": "Failed to capture snapshot"}), 500

@app.route("/stream", methods=["GET"])
def api_stream():
    return Response(
        stream_with_context(mjpeg_stream()),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT, threaded=True)