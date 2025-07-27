import os
import threading
import time
from io import BytesIO

from flask import Flask, Response, request, jsonify
import cv2

# ====== Configuration from environment variables ======
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))

DEFAULT_WIDTH = int(os.environ.get("CAMERA_DEFAULT_WIDTH", "640"))
DEFAULT_HEIGHT = int(os.environ.get("CAMERA_DEFAULT_HEIGHT", "480"))
DEFAULT_FPS = int(os.environ.get("CAMERA_DEFAULT_FPS", "24"))

# ====== Camera Control State ======
class CameraControl:
    def __init__(self):
        self.capture = None
        self.lock = threading.Lock()
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.fps = DEFAULT_FPS
        self.streaming = False
        self.last_frame = None
        self.stop_thread = False
        self.thread = None

    def start_capture(self):
        with self.lock:
            if self.streaming:
                return
            self.capture = cv2.VideoCapture(CAMERA_INDEX)
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.capture.set(cv2.CAP_PROP_FPS, self.fps)
            self.stop_thread = False
            self.streaming = True
            self.thread = threading.Thread(target=self._update_frames, daemon=True)
            self.thread.start()

    def stop_capture(self):
        with self.lock:
            self.stop_thread = True
            self.streaming = False
            if self.capture:
                self.capture.release()
                self.capture = None
            self.last_frame = None

    def set_resolution(self, width, height):
        with self.lock:
            self.width = int(width)
            self.height = int(height)
            if self.capture:
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def set_fps(self, fps):
        with self.lock:
            self.fps = int(fps)
            if self.capture:
                self.capture.set(cv2.CAP_PROP_FPS, self.fps)

    def _update_frames(self):
        while not self.stop_thread:
            with self.lock:
                if self.capture and self.capture.isOpened():
                    ret, frame = self.capture.read()
                    if ret:
                        ret, jpeg = cv2.imencode('.jpg', frame)
                        if ret:
                            self.last_frame = jpeg.tobytes()
            time.sleep(1.0 / self.fps if self.fps > 0 else 0.04)

    def get_frame(self):
        with self.lock:
            return self.last_frame

    def is_streaming(self):
        with self.lock:
            return self.streaming

# ====== Flask App ======
app = Flask(__name__)
camera = CameraControl()

@app.route('/capture/start', methods=['POST'])
def start_capture():
    camera.start_capture()
    return jsonify({"status": "started"}), 200

@app.route('/capture/stop', methods=['POST'])
def stop_capture():
    camera.stop_capture()
    return jsonify({"status": "stopped"}), 200

@app.route('/camera/res', methods=['PUT'])
def set_resolution():
    data = request.get_json(force=True)
    width = data.get('width')
    height = data.get('height')
    if not width or not height:
        return jsonify({"error": "Missing width or height parameter"}), 400
    camera.set_resolution(width, height)
    return jsonify({"status": "resolution updated", "width": width, "height": height}), 200

@app.route('/camera/fps', methods=['PUT'])
def set_fps():
    data = request.get_json(force=True)
    fps = data.get('fps')
    if not fps:
        return jsonify({"error": "Missing fps parameter"}), 400
    camera.set_fps(fps)
    return jsonify({"status": "fps updated", "fps": fps}), 200

@app.route('/stream', methods=['GET'])
def stream():
    mode = request.args.get('mode', 'mjpeg')
    if not camera.is_streaming():
        return jsonify({"error": "Camera is not streaming. Please start capture first."}), 400
    if mode == 'mjpeg':
        return Response(mjpeg_generator(),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    else:
        frame = camera.get_frame()
        if frame is None:
            return jsonify({"error": "No frame available"}), 503
        return Response(frame, mimetype='image/jpeg')

def mjpeg_generator():
    while camera.is_streaming():
        frame = camera.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.01)

if __name__ == "__main__":
    app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True)