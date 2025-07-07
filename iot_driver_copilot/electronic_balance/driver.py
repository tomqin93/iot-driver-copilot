import os
import serial
import threading
from flask import Flask, jsonify, Response
import time

# Configuration from environment variables
SERIAL_PORT = os.environ.get('DEVICE_SERIAL_PORT', '/dev/ttyUSB0')
SERIAL_BAUDRATE = int(os.environ.get('DEVICE_SERIAL_BAUDRATE', '9600'))
SERIAL_BYTESIZE = int(os.environ.get('DEVICE_SERIAL_BYTESIZE', '8'))
SERIAL_PARITY = os.environ.get('DEVICE_SERIAL_PARITY', 'N')
SERIAL_STOPBITS = int(os.environ.get('DEVICE_SERIAL_STOPBITS', '1'))
SERIAL_TIMEOUT = float(os.environ.get('DEVICE_SERIAL_TIMEOUT', '1.0'))

HTTP_HOST = os.environ.get('HTTP_HOST', '0.0.0.0')
HTTP_PORT = int(os.environ.get('HTTP_PORT', '8080'))

app = Flask(__name__)

# Shared state for last read
latest_data = {
    "raw": "",
    "weight": None,
    "decimal_position": None,
    "status_bits": None,
    "timestamp": None,
}
lock = threading.Lock()

def parse_rs232_line(line):
    # Example: "+00123.45 g\r\n"
    try:
        line = line.strip()
        # Find weight and unit
        if not line:
            return None, None, None
        if line[0] in '+-':
            sign = 1 if line[0] == '+' else -1
            line_body = line[1:]
        else:
            sign = 1
            line_body = line
        # Extract weight and unit
        parts = line_body.split()
        if len(parts) < 2:
            return None, None, None
        weight_str, unit = parts[0], parts[1]
        # Find decimal position
        if '.' in weight_str:
            decimal_pos = len(weight_str) - weight_str.index('.') - 1
        else:
            decimal_pos = 0
        weight = sign * float(weight_str)
        # Status bits generally not available in plain RS232 text, set None
        return weight, decimal_pos, None
    except Exception:
        return None, None, None

def serial_reader():
    global latest_data
    try:
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=SERIAL_BAUDRATE,
            bytesize=SERIAL_BYTESIZE,
            parity=SERIAL_PARITY,
            stopbits=SERIAL_STOPBITS,
            timeout=SERIAL_TIMEOUT
        )
    except Exception as e:
        print("Error opening serial port:", e)
        return

    while True:
        try:
            line = ser.readline().decode(errors='ignore')
            if not line:
                continue
            weight, decimal_position, status_bits = parse_rs232_line(line)
            with lock:
                latest_data["raw"] = line
                latest_data["weight"] = weight
                latest_data["decimal_position"] = decimal_position
                latest_data["status_bits"] = status_bits
                latest_data["timestamp"] = time.time()
        except Exception:
            continue

@app.route('/read', methods=['GET'])
def read_weight():
    with lock:
        resp = {
            "weight": latest_data["weight"],
            "decimal_position": latest_data["decimal_position"],
            "status_bits": latest_data["status_bits"],
            "timestamp": latest_data["timestamp"],
        }
    return jsonify(resp)

def main():
    thread = threading.Thread(target=serial_reader, daemon=True)
    thread.start()
    app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True)

if __name__ == '__main__':
    main()