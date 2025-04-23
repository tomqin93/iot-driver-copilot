import os
import base64
import requests
import threading
import queue
import time
from flask import Flask, Response, request, jsonify, stream_with_context, abort

app = Flask(__name__)

# Config from environment variables
CAMERA_IP = os.environ.get('DAHUA_IP')
CAMERA_RTSP_PORT = os.environ.get('DAHUA_RTSP_PORT', '554')
CAMERA_HTTP_PORT = os.environ.get('DAHUA_HTTP_PORT', '80')
CAMERA_USER = os.environ.get('DAHUA_USER', 'admin')
CAMERA_PASS = os.environ.get('DAHUA_PASS', 'admin')
SERVER_HOST = os.environ.get('DRIVER_HTTP_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('DRIVER_HTTP_PORT', '8080'))
CAMERA_CHANNEL = os.environ.get('DAHUA_CHANNEL', '1')
CAMERA_STREAM = os.environ.get('DAHUA_STREAM', '0')

RTSP_URL = f'rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{CAMERA_RTSP_PORT}/cam/realmonitor?channel={CAMERA_CHANNEL}&subtype={CAMERA_STREAM}'
SNAPSHOT_URL = f'http://{CAMERA_IP}:{CAMERA_HTTP_PORT}/cgi-bin/snapshot.cgi?channel={CAMERA_CHANNEL}'
STATUS_URL = f'http://{CAMERA_IP}:{CAMERA_HTTP_PORT}/cgi-bin/magicBox.cgi?action=getSystemInfo'
PTZ_URL = f'http://{CAMERA_IP}:{CAMERA_HTTP_PORT}/cgi-bin/ptz.cgi'
RECORD_URL = f'http://{CAMERA_IP}:{CAMERA_HTTP_PORT}/cgi-bin/configManager.cgi?action=setConfig&Record'

def dahua_auth():
    return (CAMERA_USER, CAMERA_PASS)

def stream_rtsp_mjpeg(rtsp_url):
    import cv2
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError('Could not open RTSP stream')
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Encode frame as JPEG
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            # Serve as multipart MJPEG
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    finally:
        cap.release()

@app.route('/status', methods=['GET'])
def status():
    try:
        r = requests.get(STATUS_URL, auth=dahua_auth(), timeout=5)
        r.raise_for_status()
        return Response(r.content, mimetype='application/xml')
    except Exception as e:
        return jsonify({'error': str(e)}), 502

@app.route('/record', methods=['POST'])
def record():
    mode = request.json.get('mode', '').lower()
    if mode not in ['start', 'stop']:
        return jsonify({'error': 'mode must be "start" or "stop"'}), 400
    rec_flag = 'true' if mode == 'start' else 'false'
    url = f'http://{CAMERA_IP}:{CAMERA_HTTP_PORT}/cgi-bin/configManager.cgi?action=setConfig&Record.Enable={rec_flag}'
    try:
        r = requests.get(url, auth=dahua_auth(), timeout=5)
        r.raise_for_status()
        return jsonify({'result': 'ok', 'mode': mode})
    except Exception as e:
        return jsonify({'error': str(e)}), 502

@app.route('/snap', methods=['GET'])
def snap():
    try:
        r = requests.get(SNAPSHOT_URL, auth=dahua_auth(), stream=True, timeout=5)
        r.raise_for_status()
        return Response(r.content, mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 502

@app.route('/ptz', methods=['POST'])
def ptz():
    data = request.json
    action = data.get('action')
    param = []
    if action == 'left':
        param = ['action=control', 'code=Left', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'right':
        param = ['action=control', 'code=Right', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'up':
        param = ['action=control', 'code=Up', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'down':
        param = ['action=control', 'code=Down', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'zoom_in':
        param = ['action=control', 'code=ZoomTele', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'zoom_out':
        param = ['action=control', 'code=ZoomWide', 'arg1=0', 'arg2=1', 'arg3=0']
    elif action == 'stop':
        param = ['action=control', 'code=Stop', 'arg1=0', 'arg2=0', 'arg3=0']
    else:
        return jsonify({'error': 'Invalid PTZ action'}), 400
    url = f"{PTZ_URL}?{'&'.join(param)}"
    try:
        r = requests.get(url, auth=dahua_auth(), timeout=5)
        r.raise_for_status()
        return jsonify({'result': 'ok', 'action': action})
    except Exception as e:
        return jsonify({'error': str(e)}), 502

@app.route('/stream', methods=['GET'])
def stream():
    try:
        return Response(
            stream_with_context(stream_rtsp_mjpeg(RTSP_URL)),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 502

if __name__ == '__main__':
    import cv2
    app.run(host=SERVER_HOST, port=SERVER_PORT, threaded=True)