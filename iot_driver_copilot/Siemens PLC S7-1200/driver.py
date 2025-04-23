import os
import json
import struct
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import threading
import socket

# Environment variables
PLC_IP = os.environ.get("PLC_IP", "192.168.0.1")
PLC_PORT = int(os.environ.get("PLC_PORT", "102"))
RACK = int(os.environ.get("PLC_RACK", "0"))
SLOT = int(os.environ.get("PLC_SLOT", "1"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8080"))

# S7 Protocol Constants
S7_ISO_PORT = PLC_PORT
MAX_PDU_LENGTH = 480

class S7Client:
    def __init__(self, ip, port, rack, slot):
        self.ip = ip
        self.port = port
        self.rack = rack
        self.slot = slot
        self.sock = None
        self.connected = False
        self.pdu_length = MAX_PDU_LENGTH

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), timeout=5)
        # ISO-on-TCP COTP Connection Request
        cotp_conn_req = bytes.fromhex(
            '03000016'      # TPKT+COTP header
            '11e00000001200c1020100c2020102c0010a'
        )
        self.sock.sendall(cotp_conn_req)
        self.sock.recv(1024)
        # S7 Communication Setup
        s7_comm_req = b'\x03\x00\x00\x19\x02\xf0\x80\x32\x01\x00\x00\x00\x01\x00\xc1\x02' + \
                      bytes([0x01, self.rack * 0x20 + self.slot]) + b'\xc2\x02\x03\x00\xc0\x01\x0a'
        self.sock.sendall(s7_comm_req)
        self.sock.recv(1024)
        self.connected = True

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
        self.connected = False

    def _ensure_connected(self):
        if not self.connected:
            self.connect()

    def _s7_request(self, s7data):
        self._ensure_connected()
        # TPKT+COTP
        tpkt = b'\x03\x00' + struct.pack(">H", len(s7data)+4)
        cotp = b'\x02\xf0\x80'
        packet = tpkt + cotp + s7data
        self.sock.sendall(packet)
        resp = self.sock.recv(4096)
        return resp

    def read_area(self, area, db_number, start, size):
        # area: int (see S7 spec), db_number: int, start: int, size: int
        # S7 READ request
        s7_header = b'\x32\x07\x00\x00\x00\x01\x00\x0e\x00\x00\x04\x01'  # S7 header + params
        params = b'\x12\x0a\x10' + bytes([area]) + struct.pack(">H", db_number) + struct.pack(">I", start)[1:] + struct.pack(">H", size)
        s7data = s7_header + params
        resp = self._s7_request(s7data)
        # Extract data from S7 response
        if resp and resp[21] == 0xff:
            data_start = 25
            return resp[data_start:data_start+size]
        else:
            raise Exception('PLC Read Error')

    def write_area(self, area, db_number, start, data):
        # area: int, db_number: int, start: int, data: bytes
        size = len(data)
        s7_header = b'\x32\x07\x00\x00\x00\x01\x00\x0e\x00\x00\x05\x01'
        params = b'\x12\x0a\x10' + bytes([area]) + struct.pack(">H", db_number) + struct.pack(">I", start)[1:] + struct.pack(">H", size)
        data_header = b'\x00\x04\x00' + struct.pack(">H", size) + data
        s7data = s7_header + params + data_header
        resp = self._s7_request(s7data)
        if resp and resp[21] == 0xff:
            return True
        else:
            raise Exception('PLC Write Error')

    # Helper methods for digital/analog IO (for brevity, only DB and Q outputs for /ctrl)
    def read_db(self, db_number, start, size):
        return self.read_area(0x84, db_number, start, size)

    def write_db(self, db_number, start, data):
        return self.write_area(0x84, db_number, start, data)

    def read_output(self, start, size):
        return self.read_area(0x82, 0, start, size)

    def write_output(self, start, data):
        return self.write_area(0x82, 0, start, data)

# HTTP Server
class PLCRequestHandler(BaseHTTPRequestHandler):
    plc = S7Client(PLC_IP, S7_ISO_PORT, RACK, SLOT)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/read":
            self.handle_read(parsed)
        else:
            self.send_error(404, "Endpoint not found.")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/write":
            self.handle_write()
        elif parsed.path == "/ctrl":
            self.handle_ctrl()
        else:
            self.send_error(404, "Endpoint not found.")

    def handle_read(self, parsed):
        try:
            params = parse_qs(parsed.query)
            area = params.get("area", [None])[0]
            db = int(params.get("db", [0])[0])
            start = int(params.get("start", [0])[0])
            size = int(params.get("size", [1])[0])
            if area is None:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing 'area' parameter.")
                return

            if area.upper() == "DB":
                data = self.plc.read_db(db, start, size)
            elif area.upper() == "Q":
                data = self.plc.read_output(start, size)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Unsupported area (use DB or Q only in this driver).")
                return

            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def handle_write(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            req = json.loads(body)
            area = req.get("area")
            db = int(req.get("db", 0))
            start = int(req.get("start", 0))
            value = req.get("value")
            if not area or value is None:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing 'area' or 'value'.")
                return
            data = bytes(value) if isinstance(value, list) else bytes([value])
            if area.upper() == "DB":
                self.plc.write_db(db, start, data)
            elif area.upper() == "Q":
                self.plc.write_output(start, data)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Unsupported area (use DB or Q only in this driver).")
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Write OK")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def handle_ctrl(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            req = json.loads(body)
            output = int(req.get("output", 0))
            state = int(req.get("state", 0))
            # Only support Q area (outputs) for /ctrl
            byte_index = output // 8
            bit_index = output % 8
            current = bytearray(self.plc.read_output(byte_index, 1))
            if state:
                current[0] |= (1 << bit_index)
            else:
                current[0] &= ~(1 << bit_index)
            self.plc.write_output(byte_index, current)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Control OK")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        # Silence HTTP server logging
        pass

def run_server():
    server = HTTPServer((SERVER_HOST, SERVER_PORT), PLCRequestHandler)
    print(f"PLC S7-1200 HTTP driver running at http://{SERVER_HOST}:{SERVER_PORT}")
    server.serve_forever()

if __name__ == "__main__":
    run_server()