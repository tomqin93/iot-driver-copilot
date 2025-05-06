import os
import json
import random
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configuration from environment variables
HTTP_HOST = os.getenv('HTTP_HOST', '0.0.0.0')
HTTP_PORT = int(os.getenv('HTTP_PORT', '8080'))

# Sensor Data Simulation (since protocol and device communication are unknown)
class SensorDataSimulator:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self._generate_data()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._update_data, daemon=True)
        self._thread.start()

    def _generate_data(self):
        return {
            "X": round(random.uniform(-1000, 1000), 2),
            "Y": round(random.uniform(-1000, 1000), 2),
            "Rz": round(random.uniform(-180, 180), 2),
            "angle_deg": round(random.uniform(18, 44), 2),               # 18°–44°
            "length_min_mm": random.randint(55, 135),                    # 55mm–135mm
            "length_fixed1_mm": 258.00,
            "length_fixed2_mm": 110.00,
            "length_fixed3_mm": 181.00,
            "range_value": random.randint(0, 65535)
        }

    def _update_data(self):
        while not self._stop_event.is_set():
            with self.lock:
                self.data = self._generate_data()
            time.sleep(1)  # simulate new sensor data every second

    def get_data(self):
        with self.lock:
            return dict(self.data)

    def stop(self):
        self._stop_event.set()
        self._thread.join()

simulator = SensorDataSimulator()

# HTTP Handler
class SensorHTTPRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_GET(self):
        if self.path == '/read':
            data = simulator.get_data()
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "data": data
            }).encode('utf-8'))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode('utf-8'))

    def log_message(self, format, *args):
        return  # Suppress default logging

def run():
    server_address = (HTTP_HOST, HTTP_PORT)
    httpd = HTTPServer(server_address, SensorHTTPRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        simulator.stop()
        httpd.server_close()

if __name__ == '__main__':
    run()