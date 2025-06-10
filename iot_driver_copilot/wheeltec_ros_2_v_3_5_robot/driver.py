import os
import sys
import time
import yaml
import threading

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
import paho.mqtt.client as mqtt

# Constants for EdgeDevice CRD
EDGEDEVICE_GROUP = "shifu.edgenesis.io"
EDGEDEVICE_VERSION = "v1alpha1"
EDGEDEVICE_PLURAL = "edgedevices"

PHASE_PENDING = "Pending"
PHASE_RUNNING = "Running"
PHASE_FAILED = "Failed"
PHASE_UNKNOWN = "Unknown"

INSTRUCTION_PATH = "/etc/edgedevice/config/instructions"

def get_env_var(name, required=True, default=None):
    value = os.getenv(name)
    if value is None and required:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value if value is not None else default

class EdgeDeviceStatusManager:
    def __init__(self, name, namespace):
        config.load_incluster_config()
        self.api = client.CustomObjectsApi()
        self.name = name
        self.namespace = namespace
        self._lock = threading.Lock()

    def get_edgedevice(self):
        return self.api.get_namespaced_custom_object(
            group=EDGEDEVICE_GROUP,
            version=EDGEDEVICE_VERSION,
            namespace=self.namespace,
            plural=EDGEDEVICE_PLURAL,
            name=self.name
        )

    def get_address(self):
        ed = self.get_edgedevice()
        try:
            return ed['spec']['address']
        except KeyError:
            return None

    def update_phase(self, phase):
        with self._lock:
            # Patch only the status.phase field
            body = {"status": {"edgeDevicePhase": phase}}
            try:
                self.api.patch_namespaced_custom_object_status(
                    group=EDGEDEVICE_GROUP,
                    version=EDGEDEVICE_VERSION,
                    namespace=self.namespace,
                    plural=EDGEDEVICE_PLURAL,
                    name=self.name,
                    body=body
                )
            except ApiException as e:
                print(f"Failed to update status: {e}", file=sys.stderr)

class InstructionLoader:
    def __init__(self, path):
        self.instructions = {}
        self._load(path)

    def _load(self, path):
        try:
            with open(path, "r") as f:
                self.instructions = yaml.safe_load(f)
        except Exception as e:
            print(f"Failed to load instructions: {e}", file=sys.stderr)
            self.instructions = {}

    def get_api_settings(self, api_name):
        return self.instructions.get(api_name, {}).get('protocolPropertyList', {})

class MQTTDeviceShifu:
    def __init__(self):
        self.edgedevice_name = get_env_var("EDGEDEVICE_NAME")
        self.edgedevice_namespace = get_env_var("EDGEDEVICE_NAMESPACE")
        self.mqtt_broker_address = get_env_var("MQTT_BROKER_ADDRESS")
        self.status_manager = EdgeDeviceStatusManager(self.edgedevice_name, self.edgedevice_namespace)
        self.address = self.status_manager.get_address()
        self.instruction_loader = InstructionLoader(INSTRUCTION_PATH)
        self.client = None
        self.connected = False
        self._client_id = f"wheeletec-shifu-{self.edgedevice_name}"
        self._connect_lock = threading.Lock()
        self._phase_thread = threading.Thread(target=self._monitor_phase, daemon=True)
        self._phase_thread.start()
        self._init_mqtt()

    def _init_mqtt(self):
        self.client = mqtt.Client(client_id=self._client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # MQTT username/password support if needed via env vars
        mqtt_username = os.getenv("MQTT_USERNAME")
        mqtt_password = os.getenv("MQTT_PASSWORD")
        if mqtt_username:
            self.client.username_pw_set(mqtt_username, mqtt_password)

        broker_host, broker_port = self._parse_broker_address(self.mqtt_broker_address)
        try:
            self.status_manager.update_phase(PHASE_PENDING)
            self.client.connect(broker_host, broker_port, keepalive=60)
            threading.Thread(target=self.client.loop_forever, daemon=True).start()
        except Exception as e:
            print(f"MQTT connect failed: {e}", file=sys.stderr)
            self.status_manager.update_phase(PHASE_FAILED)

    def _parse_broker_address(self, address):
        # Accepts "host:port"
        if ":" in address:
            host, port = address.split(":", 1)
            return host, int(port)
        return address, 1883  # default MQTT port

    def _on_connect(self, client, userdata, flags, rc):
        with self._connect_lock:
            if rc == 0:
                self.connected = True
                self.status_manager.update_phase(PHASE_RUNNING)
            else:
                self.connected = False
                self.status_manager.update_phase(PHASE_FAILED)

    def _on_disconnect(self, client, userdata, rc):
        with self._connect_lock:
            self.connected = False
            self.status_manager.update_phase(PHASE_PENDING if rc != 0 else PHASE_UNKNOWN)

    def _monitor_phase(self):
        # Periodically check if still connected and update status
        while True:
            with self._connect_lock:
                if self.client is None:
                    self.status_manager.update_phase(PHASE_UNKNOWN)
                elif self.connected:
                    self.status_manager.update_phase(PHASE_RUNNING)
                else:
                    self.status_manager.update_phase(PHASE_PENDING)
            time.sleep(10)

    def publish_cmd_vel(self, direction):
        """
        direction: one of 'forward', 'backward', 'left', 'right'
        """
        if not self.connected:
            return {"error": "MQTT client not connected"}, 503

        # Load settings for API
        api_settings = self.instruction_loader.get_api_settings("device/commands/cmd_vel")
        topic = "device/commands/cmd_vel"
        qos = int(api_settings.get("qos", 1))  # default 1

        # Default speed values, can be overridden by settings
        linear_speed = float(api_settings.get("linear_speed", 0.2))
        angular_speed = float(api_settings.get("angular_speed", 0.5))

        # Compose cmd_vel message in ROS2 Twist format (as JSON for MQTT)
        # ROS2 Twist msg: { "linear": {"x": ..., "y": ..., "z": ...}, "angular": {"x": ..., "y": ..., "z": ...} }
        linear = {"x": 0, "y": 0, "z": 0}
        angular = {"x": 0, "y": 0, "z": 0}

        if direction == "forward":
            linear["x"] = linear_speed
        elif direction == "backward":
            linear["x"] = -linear_speed
        elif direction == "left":
            angular["z"] = angular_speed
        elif direction == "right":
            angular["z"] = -angular_speed
        else:
            return {"error": "Invalid direction. Use forward/backward/left/right"}, 400

        payload = {
            "linear": linear,
            "angular": angular
        }

        try:
            import json
            result = self.client.publish(topic, json.dumps(payload), qos=qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                return {"status": "published", "topic": topic, "payload": payload}, 200
            else:
                return {"error": f"Publish failed: {result.rc}"}, 500
        except Exception as e:
            return {"error": f"Exception: {e}"}, 500

# API server (flask style) for handling control
from flask import Flask, request, jsonify

app = Flask(__name__)
driver = MQTTDeviceShifu()

@app.route("/device/commands/cmd_vel", methods=["POST"])
def api_cmd_vel():
    data = request.json
    if not data or "direction" not in data:
        return jsonify({"error": "Missing 'direction' in payload"}), 400
    direction = data["direction"]
    return jsonify(*driver.publish_cmd_vel(direction))

if __name__ == "__main__":
    port = int(os.getenv("SHIFU_HTTP_PORT", "8080"))
    app.run(host='0.0.0.0', port=port)