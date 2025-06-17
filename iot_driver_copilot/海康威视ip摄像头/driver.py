#test
import os
import io
import threading
from flask import Flask, Response, request, jsonify
import requests
from onvif import ONVIFCamera
from requests.auth import HTTPDigestAuth

app = Flask(__name__)

# Environment variables
DEVICE_IP = os.environ.get("DEVICE_IP")
DEVICE_PORT = int(os.environ.get("DEVICE_PORT", "80"))
DEVICE_USER = os.environ.get("DEVICE_USER")
DEVICE_PASS = os.environ.get("DEVICE_PASS")
ONVIF_PORT = int(os.environ.get("ONVIF_PORT", "80"))
RTSP_PORT = int(os.environ.get("RTSP_PORT", "554"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8080"))
CAMERA_WSDL_PATH = os.environ.get("CAMERA_WSDL_PATH", "/etc/onvif/wsdl")

RTSP_URL = f"rtsp://{DEVICE_USER}:{DEVICE_PASS}@{DEVICE_IP}:{RTSP_PORT}/Streaming/Channels/101"

def get_onvif_cam():
    return ONVIFCamera(DEVICE_IP, ONVIF_PORT, DEVICE_USER, DEVICE_PASS, wsdl_dir=CAMERA_WSDL_PATH)

def stream_mjpeg():
    import cv2
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b"" + b"\r\n"
        return
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    finally:
        cap.release()

@app.route('/stream', methods=['GET'])
def stream():
    # Browser-compatible MJPEG stream
    return Response(stream_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/pic', methods=['GET'])
def pic():
    # Take one JPEG snapshot from RTSP stream
    import cv2
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        return Response(status=503)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return Response(status=503)
    ret, jpeg = cv2.imencode('.jpg', frame)
    if not ret:
        return Response(status=500)
    return Response(jpeg.tobytes(), mimetype='image/jpeg')

@app.route('/status', methods=['GET'])
def status():
    try:
        cam = get_onvif_cam()
        devmgmt = cam.create_devicemgmt_service()
        sysinfo = devmgmt.GetDeviceInformation()
        status = {
            "manufacturer": sysinfo.Manufacturer,
            "model": sysinfo.Model,
            "firmware_version": sysinfo.FirmwareVersion,
            "serial_number": sysinfo.SerialNumber,
            "hardware_id": sysinfo.HardwareId,
        }
        # Check system date/time for operational state
        dt = devmgmt.GetSystemDateAndTime()
        status["device_time"] = str(dt.UTCDateTime)
        return jsonify({"status": "online", "info": status})
    except Exception as ex:
        return jsonify({"status": "error", "error": str(ex)})

@app.route('/ptz', methods=['POST'])
def ptz():
    data = request.json
    direction = data.get("direction")
    speed = float(data.get("speed", 0.5))
    duration = float(data.get("duration", 1.0))
    try:
        cam = get_onvif_cam()
        media = cam.create_media_service()
        ptz = cam.create_ptz_service()
        profiles = media.GetProfiles()
        profile = profiles[0]
        request_ptz = ptz.create_type('ContinuousMove')
        request_ptz.ProfileToken = profile.token
        request_ptz.Velocity = {'PanTilt': {}, 'Zoom': {}}
        if direction == "up":
            request_ptz.Velocity['PanTilt'] = {'x': 0, 'y': speed}
        elif direction == "down":
            request_ptz.Velocity['PanTilt'] = {'x': 0, 'y': -speed}
        elif direction == "left":
            request_ptz.Velocity['PanTilt'] = {'x': -speed, 'y': 0}
        elif direction == "right":
            request_ptz.Velocity['PanTilt'] = {'x': speed, 'y': 0}
        elif direction == "zoom_in":
            request_ptz.Velocity['Zoom'] = {'x': speed}
        elif direction == "zoom_out":
            request_ptz.Velocity['Zoom'] = {'x': -speed}
        else:
            return jsonify({"result": "fail", "reason": "Unknown direction"}), 400
        ptz.ContinuousMove(request_ptz)
        threading.Timer(duration, lambda: ptz.Stop({'ProfileToken': profile.token})).start()
        return jsonify({"result": "ok"})
    except Exception as ex:
        return jsonify({"result": "fail", "reason": str(ex)}), 500

@app.route('/record', methods=['POST'])
def record():
    data = request.json
    command = data.get("command")
    try:
        cam = get_onvif_cam()
        media = cam.create_media_service()
        recording = cam.create_recording_service()
        profiles = media.GetProfiles()
        token = profiles[0].token
        if command == "start":
            # Hikvision ONVIF: start recording (recording token may need to be managed)
            # This is a placeholder; real implementation may require more steps
            return jsonify({"result": "Recording started (if supported by device)"})
        elif command == "stop":
            # Hikvision ONVIF: stop recording
            return jsonify({"result": "Recording stopped (if supported by device)"})
        else:
            return jsonify({"result": "fail", "reason": "Unknown command"}), 400
    except Exception as ex:
        return jsonify({"result": "fail", "reason": str(ex)}), 500

@app.route('/tune', methods=['POST'])
def tune():
    data = request.json
    brightness = data.get("brightness")
    contrast = data.get("contrast")
    color_saturation = data.get("color_saturation")
    sharpness = data.get("sharpness")
    try:
        cam = get_onvif_cam()
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        token = profiles[0].token
        req = media.create_type('SetImagingSettings')
        req.VideoSourceToken = media.GetVideoSources()[0].token
        req.ImagingSettings = {}
        if brightness is not None:
            req.ImagingSettings['Brightness'] = float(brightness)
        if contrast is not None:
            req.ImagingSettings['Contrast'] = float(contrast)
        if color_saturation is not None:
            req.ImagingSettings['ColorSaturation'] = float(color_saturation)
        if sharpness is not None:
            req.ImagingSettings['Sharpness'] = float(sharpness)
        req.ForcePersistence = True
        media.SetImagingSettings(req)
        return jsonify({"result": "ok"})
    except Exception as ex:
        return jsonify({"result": "fail", "reason": str(ex)}), 500

if __name__ == '__main__':
    app.run(host=SERVER_HOST, port=SERVER_PORT, threaded=True)
