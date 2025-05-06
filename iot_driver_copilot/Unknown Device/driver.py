import os
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configuration from environment variables
DEVICE_IP = os.environ.get('DEVICE_IP', '127.0.0.1')
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('SERVER_PORT', '8080'))

# Simulate reading from device (as protocol and API are unknown)
# Data points: X, Y, Rz, 18°–44°, 55mm–135mm, 258.00mm, 110.00mm, 181mm, 0–65535
DATA_POINTS = [
    ('X', -1000.0, 1000.0),              # Example: X in mm
    ('Y', -1000.0, 1000.0),              # Example: Y in mm
    ('Rz', -180.0, 180.0),               # Example: Rotation in degrees
    ('angle', 18.0, 44.0),               # Angle in degrees
    ('zoom_mm', 55.0, 135.0),            # Zoom in mm
    ('fixed1_mm', 258.00, 258.00),       # Fixed value
    ('fixed2_mm', 110.00, 110.00),       # Fixed value
    ('fixed3_mm', 181.00, 181.00),       # Fixed value
    ('raw', 0, 65535),                   # Raw integer
]

class DeviceData:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self._generate_fake_data()

    def _generate_fake_data(self):
        values = {}
        for name, vmin, vmax in DATA_POINTS:
            if vmin == vmax:
                value = vmin
            elif isinstance(vmin, float) or isinstance(vmax, float):
                value = round(random.uniform(vmin, vmax), 2)
            else:
                value = random.randint(int(vmin), int(vmax))
            values[name] = value
        return values

    def refresh(self):
        with self.lock:
            self.data = self._generate_fake_data()

    def get_data(self):
        with self.lock:
            return dict(self.data)

device_data = DeviceData()

def device_data_refresher():
    while True:
        device_data.refresh()
        time.sleep(1)  # Simulate real-time sensor reading

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/read':
            data = device_data.get_data()
            response = {
                "device_name": "Unknown Device",
                "device_model": "part1(4#), part2(3#), part3(14#)",
                "manufacturer": "Unknown",
                "device_type": "Sensor",
                "data": data
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'404 Not Found')

    def log_message(self, format, *args):
        return  # Suppress default HTTP logging

if __name__ == '__main__':
    t = threading.Thread(target=device_data_refresher, daemon=True)
    t.start()
    server = HTTPServer((SERVER_HOST, SERVER_PORT), SimpleHTTPRequestHandler)
    print(f"Sensor HTTP server running at http://{SERVER_HOST}:{SERVER_PORT}/read")
    server.serve_forever()