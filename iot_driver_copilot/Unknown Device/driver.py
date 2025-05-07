import os
import json
import random
from flask import Flask, jsonify, Response

# Configuration from environment variables
DEVICE_NAME = os.environ.get('DEVICE_NAME', 'Unknown Device')
DEVICE_MODEL = os.environ.get('DEVICE_MODEL', 'part1(4#), part2(3#), part3(14#)')
MANUFACTURER = os.environ.get('MANUFACTURER', 'Unknown')
DEVICE_TYPE = os.environ.get('DEVICE_TYPE', 'Sensor')
HTTP_HOST = os.environ.get('HTTP_HOST', '0.0.0.0')
HTTP_PORT = int(os.environ.get('HTTP_PORT', '8080'))

app = Flask(__name__)

# Dummy function to simulate reading from the sensor device
def read_sensor_data():
    # Data points: X, Y, Rz, 18°–44°, 55mm–135mm, 258.00mm, 110.00mm, 181mm, 0–65535
    sensor_data = {
        "X": round(random.uniform(-100.0, 100.0), 2),
        "Y": round(random.uniform(-100.0, 100.0), 2),
        "Rz": round(random.uniform(-180.0, 180.0), 2),
        "angle_deg": round(random.uniform(18.0, 44.0), 2),
        "zoom_mm": round(random.uniform(55.0, 135.0), 2),
        "custom1_mm": 258.00,
        "custom2_mm": 110.00,
        "custom3_mm": 181.00,
        "raw_value": random.randint(0, 65535)
    }
    return sensor_data

@app.route('/read', methods=['GET'])
def get_sensor_data():
    sensor_data = read_sensor_data()
    return jsonify({
        "device": {
            "name": DEVICE_NAME,
            "model": DEVICE_MODEL,
            "manufacturer": MANUFACTURER,
            "type": DEVICE_TYPE
        },
        "data": sensor_data
    })

if __name__ == '__main__':
    app.run(host=HTTP_HOST, port=HTTP_PORT)