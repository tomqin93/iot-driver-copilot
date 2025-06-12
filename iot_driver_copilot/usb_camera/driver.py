import os
import threading
import cv2
import time
from flask import Flask, Response, request, jsonify

# Configuration from environment variables
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
CAMERA_INDEX = int(os.environ.get("USB_CAMERA_INDEX", "0"))
DEFAULT_RESOLUTION = os.environ.get("USB_CAMERA_RESOLUTION", "640x480")

# Helper to parse resolution string "WIDTHxHEIGHT"
def parse_resolution(res_str):
    try:
        w, h = res_str.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 640, 480

class USBCameraManager:
    def __init__(self, camera_index, default_resolution):
        self.camera_index = camera_index
        self.width, self.height = parse_resolution(default_resolution)
        self.capture = None
        self.lock = threading.Lock()
        self.is_streaming = False
        self.frame = None
        self._thread = None
        self.brightness = None
        self.contrast = None

    def start_capture(self):
        with self.lock:
            if self.is_streaming:
                return True
            self.capture = cv2.VideoCapture(self.camera_index)
            if not self.capture.isOpened():
                self.capture = None
                return False
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if self.brightness is not None:
                self.capture.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness)
            if self.contrast is not None:
                self.capture.set(cv2.CAP_PROP_CONTRAST, self.contrast)
            self.is_streaming = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return True

    def _capture_loop(self):
        while self.is_streaming and self.capture and self.capture.isOpened():
            ret, frame = self.capture.read()
            if not ret:
                continue
            with self.lock:
                self.frame = frame
            time.sleep(0.01)
        with self.lock:
            self.is_streaming = False

    def stop_capture(self):
        with self.lock:
            self.is_streaming = False
            if self.capture:
                self.capture.release()
                self.capture = None
            self.frame = None

    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.frame)
            if not ret:
                return None
            return jpeg.tobytes()

    def set_brightness(self, value):
        with self.lock:
            self.brightness = value
            if self.capture:
                self.capture.set(cv2.CAP_PROP_BRIGHTNESS, value)
            return True

    def set_contrast(self, value):
        with self.lock:
            self.contrast = value
            if self.capture:
                self.capture.set(cv2.CAP_PROP_CONTRAST, value)
            return True

    def set_resolution(self, w, h):
        with self.lock:
            self.width, self.height = w, h
            if self.capture:
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            return True

app = Flask(__name__)
camera_manager = USBCameraManager(CAMERA_INDEX, DEFAULT_RESOLUTION)

@app.route("/camera/start", methods=["POST"])
def api_start_capture():
    success = camera_manager.start_capture()
    if success:
        return jsonify({"status": "started"}), 200
    else:
        return jsonify({"status": "failed", "reason": "Could not open camera"}), 500

def gen_mjpeg_stream():
    while camera_manager.is_streaming:
        frame = camera_manager.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.05)

@app.route("/camera/stream", methods=["GET"])
def api_stream():
    if not camera_manager.is_streaming:
        return jsonify({"status": "failed", "reason": "Camera not streaming"}), 503
    return Response(gen_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/camera/stop", methods=["POST"])
def api_stop_capture():
    camera_manager.stop_capture()
    return jsonify({"status": "stopped"}), 200

@app.route("/camera/brightness", methods=["PUT"])
def api_set_brightness():
    data = request.get_json(force=True)
    if "brightness" not in data:
        return jsonify({"status": "failed", "reason": "Missing brightness"}), 400
    val = float(data["brightness"])
    camera_manager.set_brightness(val)
    return jsonify({"status": "ok", "brightness": val}), 200

@app.route("/camera/contrast", methods=["PUT"])
def api_set_contrast():
    data = request.get_json(force=True)
    if "contrast" not in data:
        return jsonify({"status": "failed", "reason": "Missing contrast"}), 400
    val = float(data["contrast"])
    camera_manager.set_contrast(val)
    return jsonify({"status": "ok", "contrast": val}), 200

@app.route("/camera/res", methods=["PUT"])
def api_set_resolution():
    data = request.get_json(force=True)
    if "resolution" not in data:
        return jsonify({"status": "failed", "reason": "Missing resolution"}), 400
    try:
        w, h = parse_resolution(data["resolution"])
        camera_manager.set_resolution(w, h)
        return jsonify({"status": "ok", "resolution": f"{w}x{h}"}), 200
    except Exception:
        return jsonify({"status": "failed", "reason": "Invalid resolution format"}), 400

if __name__ == "__main__":
    app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True)