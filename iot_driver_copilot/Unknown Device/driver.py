import os
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Environment variable configuration
DEVICE_NAME = os.environ.get('DEVICE_NAME', 'Unknown Device')
DEVICE_MODEL = os.environ.get('DEVICE_MODEL', 'part1(4#), part2(3#), part3(14#)')
MANUFACTURER = os.environ.get('MANUFACTURER', 'Unknown')
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('SERVER_PORT', '8080'))

# Simulated sensor data ranges
SENSOR_RANGES = {
    'X': (-1000.0, 1000.0),      # Example range
    'Y': (-1000.0, 1000.0),      # Example range
    'Rz': (-180.0, 180.0),       # Example range
    'Angle': (18.0, 44.0),       # 18°–44°
    'Zoom': (55.0, 135.0),       # 55mm–135mm
    'Length1': (258.0, 258.0),   # fixed at 258.00mm
    'Length2': (110.0, 110.0),   # fixed at 110.00mm
    'Length3': (181.0, 181.0),   # fixed at 181mm
    'Raw': (0, 65535)            # 0–65535
}

# Internal storage for latest sensor data (simulate "latest" values)
_latest_sensor_data = {}
_data_lock = threading.Lock()

def _simulate_sensor_data():
    while True:
        new_data = {
            'X': round(random.uniform(*SENSOR_RANGES['X']), 3),
            'Y': round(random.uniform(*SENSOR_RANGES['Y']), 3),
            'Rz': round(random.uniform(*SENSOR_RANGES['Rz']), 3),
            'Angle': round(random.uniform(*SENSOR_RANGES['Angle']), 2),
            'Zoom': round(random.uniform(*SENSOR_RANGES['Zoom']), 2),
            'Length1': SENSOR_RANGES['Length1'][0],
            'Length2': SENSOR_RANGES['Length2'][0],
            'Length3': SENSOR_RANGES['Length3'][0],
            'Raw': random.randint(*SENSOR_RANGES['Raw']),
            'device_name': DEVICE_NAME,
            'device_model': DEVICE_MODEL,
            'manufacturer': MANUFACTURER,
            'timestamp': time.time()
        }
        with _data_lock:
            _latest_sensor_data.clear()
            _latest_sensor_data.update(new_data)
        time.sleep(0.5)  # Simulate a sensor update rate

class SensorHTTPRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_GET(self):
        if self.path == '/read':
            with _data_lock:
                resp = dict(_latest_sensor_data)
            self._set_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

def run_http_server():
    server_address = (SERVER_HOST, SERVER_PORT)
    httpd = HTTPServer(server_address, SensorHTTPRequestHandler)
    httpd.serve_forever()

if __name__ == '__main__':
    t = threading.Thread(target=_simulate_sensor_data, daemon=True)
    t.start()
    run_http_server()