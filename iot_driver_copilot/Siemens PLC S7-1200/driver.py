import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import threading

try:
    from snap7.client import Client as Snap7Client
    import snap7.util
    import snap7.types
except ImportError:
    raise ImportError("snap7 library is required. Install with 'pip install python-snap7'.")

# Configuration from environment variables
PLC_IP = os.environ.get('PLC_IP', '127.0.0.1')
PLC_PORT = int(os.environ.get('PLC_PORT', 102))
PLC_RACK = int(os.environ.get('PLC_RACK', 0))
PLC_SLOT = int(os.environ.get('PLC_SLOT', 1))
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('SERVER_PORT', 8080))

# Snap7 connection singleton (threadsafe)
class PLCConnection:
    _lock = threading.Lock()
    _client = None

    @classmethod
    def get_client(cls):
        with cls._lock:
            if cls._client is None:
                cls._client = Snap7Client()
                cls._client.connect(PLC_IP, PLC_RACK, PLC_SLOT, PLC_PORT)
            elif not cls._client.get_connected():
                cls._client.connect(PLC_IP, PLC_RACK, PLC_SLOT, PLC_PORT)
            return cls._client

    @classmethod
    def close(cls):
        with cls._lock:
            if cls._client:
                cls._client.disconnect()
                cls._client = None

def plc_read_area(area, db_number, start, size, data_type):
    client = PLCConnection.get_client()
    data = client.read_area(area, db_number, start, size)
    if data_type == 'BOOL':
        return snap7.util.get_bool(data, 0, 0)
    elif data_type == 'INT':
        return snap7.util.get_int(data, 0)
    elif data_type == 'DINT':
        return snap7.util.get_dint(data, 0)
    elif data_type == 'REAL':
        return snap7.util.get_real(data, 0)
    else:
        return list(data)

def plc_write_area(area, db_number, start, value, data_type):
    client = PLCConnection.get_client()
    if data_type == 'BOOL':
        data = bytearray(1)
        snap7.util.set_bool(data, 0, 0, bool(value))
        client.write_area(area, db_number, start, data)
    elif data_type == 'INT':
        data = bytearray(2)
        snap7.util.set_int(data, 0, int(value))
        client.write_area(area, db_number, start, data)
    elif data_type == 'DINT':
        data = bytearray(4)
        snap7.util.set_dint(data, 0, int(value))
        client.write_area(area, db_number, start, data)
    elif data_type == 'REAL':
        data = bytearray(4)
        snap7.util.set_real(data, 0, float(value))
        client.write_area(area, db_number, start, data)
    else:
        raise ValueError("Unsupported data_type for write")

class SiemensPLCHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status_code=200, content_type='application/json'):
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/read':
            params = parse_qs(parsed.query)
            try:
                area_str = params.get('area', ['DB'])[0]
                db_number = int(params.get('db', [1])[0])
                start = int(params.get('start', [0])[0])
                size = int(params.get('size', [2])[0])
                data_type = params.get('data_type', ['INT'])[0]

                area_map = {
                    'DB': snap7.types.Areas.DB,
                    'PE': snap7.types.Areas.PE,
                    'PA': snap7.types.Areas.PA,
                    'MK': snap7.types.Areas.MK
                }
                area = area_map.get(area_str.upper())
                if area is None:
                    raise ValueError("Invalid area")

                value = plc_read_area(area, db_number, start, size, data_type)
                resp = {'success': True, 'value': value}
                self._set_headers()
                self.wfile.write(json.dumps(resp).encode())
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('content-length', 0))
        raw = self.rfile.read(length) if length > 0 else b''
        try:
            payload = json.loads(raw.decode()) if raw else {}
        except Exception:
            payload = {}

        if parsed.path == '/write':
            try:
                area_str = payload.get('area', 'DB')
                db_number = int(payload.get('db', 1))
                start = int(payload.get('start', 0))
                data_type = payload.get('data_type', 'INT')
                value = payload['value']

                area_map = {
                    'DB': snap7.types.Areas.DB,
                    'PE': snap7.types.Areas.PE,
                    'PA': snap7.types.Areas.PA,
                    'MK': snap7.types.Areas.MK
                }
                area = area_map.get(area_str.upper())
                if area is None:
                    raise ValueError("Invalid area")

                plc_write_area(area, db_number, start, value, data_type)
                self._set_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

        elif parsed.path == '/ctrl':
            try:
                # Control an output (digital or analog)
                # Expected payload: area, db, start, data_type, value
                area_str = payload.get('area', 'PA')
                db_number = int(payload.get('db', 0))
                start = int(payload.get('start', 0))
                data_type = payload.get('data_type', 'BOOL')
                value = payload['value']

                area_map = {
                    'DB': snap7.types.Areas.DB,
                    'PE': snap7.types.Areas.PE,
                    'PA': snap7.types.Areas.PA,
                    'MK': snap7.types.Areas.MK
                }
                area = area_map.get(area_str.upper())
                if area is None:
                    raise ValueError("Invalid area")

                plc_write_area(area, db_number, start, value, data_type)
                self._set_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode())

    def log_message(self, format, *args):
        # Silence standard logging
        return

def run():
    server = HTTPServer((SERVER_HOST, SERVER_PORT), SiemensPLCHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PLCConnection.close()
        server.server_close()

if __name__ == '__main__':
    run()