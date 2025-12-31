import json
import logging
import signal
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any

from config import load_config, Config
from modbus_device import ModbusDisplayModule


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.status: Dict[str, Any] = {
            "connected": False,
            "last_update_ts": None,
        }
        self.mapping_ranges = []  # local ranges

    def update_status(self, data: Dict[str, Any]):
        with self.lock:
            self.status.update(data)
            self.status["last_update_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.status["connected"] = True

    def set_disconnected(self):
        with self.lock:
            self.status["connected"] = False
            self.status["last_update_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.status)

    def set_mapping_ranges(self, ranges):
        with self.lock:
            self.mapping_ranges = list(ranges)


class RequestHandler(BaseHTTPRequestHandler):
    # Silence default logs; we'll log structured
    def log_message(self, format: str, *args):
        logging.info("HTTP %s - %s", self.address_string(), format % args)

    def _send_json(self, status_code: int, obj: Dict[str, Any]):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            raise

    # Endpoints:
    # GET /status
    # POST /display/value
    # POST /display/ascii
    # PUT /mode
    # PUT /modbus/config
    # PUT /mapping/ranges

    def do_GET(self):
        if self.path == "/status":
            status = STATE.get_status()
            self._send_json(200, status)
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/display/value":
            try:
                body = self._read_json()
                if "value" not in body:
                    return self._send_json(400, {"error": "Missing 'value'"})
                val = body["value"]
                DEVICE.set_display_value(val)
                STATE.update_status({"display_value": val})
                return self._send_json(200, {"ok": True, "value": val, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            except Exception as e:
                logging.exception("/display/value error: %s", e)
                return self._send_json(500, {"error": str(e)})
        elif self.path == "/display/ascii":
            try:
                body = self._read_json()
                text = body.get("ascii", None)
                if text is None or not isinstance(text, str):
                    return self._send_json(400, {"error": "Missing or invalid 'ascii'"})
                if not (1 <= len(text) <= 6):
                    return self._send_json(400, {"error": "'ascii' must be 1..6 characters"})
                DEVICE.set_display_ascii(text)
                STATE.update_status({"display_ascii_1_6": text})
                return self._send_json(200, {"ok": True, "ascii": text, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            except Exception as e:
                logging.exception("/display/ascii error: %s", e)
                return self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_PUT(self):
        if self.path == "/mode":
            try:
                body = self._read_json()
                if "mode" not in body:
                    return self._send_json(400, {"error": "Missing 'mode'"})
                DEVICE.set_mode(int(body["mode"]))
                STATE.update_status({"mode": int(body["mode"])})
                return self._send_json(200, {"ok": True, "mode": int(body["mode"])})
            except Exception as e:
                logging.exception("/mode error: %s", e)
                return self._send_json(500, {"error": str(e)})
        elif self.path == "/modbus/config":
            try:
                body = self._read_json()
                required = ["target_slave_id", "function_code", "target_register_addr", "target_data_type"]
                if not all(k in body for k in required):
                    return self._send_json(400, {"error": f"Missing fields, required: {required}"})
                DEVICE.set_modbus_config(
                    target_slave_id=int(body["target_slave_id"]),
                    function_code=int(body["function_code"]),
                    target_register_addr=int(body["target_register_addr"]),
                    target_data_type=int(body["target_data_type"]),
                )
                STATE.update_status({
                    "target_slave_id": int(body["target_slave_id"]),
                    "function_code": int(body["function_code"]),
                    "target_register_addr": int(body["target_register_addr"]),
                    "target_data_type": int(body["target_data_type"]),
                })
                return self._send_json(200, {"ok": True})
            except Exception as e:
                logging.exception("/modbus/config error: %s", e)
                return self._send_json(500, {"error": str(e)})
        elif self.path == "/mapping/ranges":
            try:
                body = self._read_json()
                ranges = body.get("ranges")
                if ranges is None or not isinstance(ranges, list):
                    return self._send_json(400, {"error": "Missing or invalid 'ranges' (list of objects)"})
                DEVICE.set_mapping_ranges(ranges)
                STATE.set_mapping_ranges(ranges)
                return self._send_json(200, {"ok": True, "count": len(ranges)})
            except Exception as e:
                logging.exception("/mapping/ranges error: %s", e)
                return self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})


def collection_loop(cfg: Config, device: ModbusDisplayModule, state: SharedState, stop_evt: threading.Event):
    backoff = cfg.connect_backoff_min_ms / 1000.0
    while not stop_evt.is_set():
        try:
            if not device.is_connected():
                if device.connect():
                    logging.info("Connected to device, starting polling")
                    backoff = cfg.connect_backoff_min_ms / 1000.0
                else:
                    logging.warning("Device connect failed, retrying in %.2fs", backoff)
                    stop_evt.wait(backoff)
                    backoff = min(backoff * 2.0, cfg.connect_backoff_max_ms / 1000.0)
                    continue
            # Read status
            try:
                status = device.read_status()
                state.update_status(status)
                logging.debug("Polled status: %s", status)
                stop_evt.wait(cfg.read_poll_interval_ms / 1000.0)
            except Exception as e:
                logging.error("Status read failed: %s", e)
                device.close()
                state.set_disconnected()
                # exponential backoff on next loop
                backoff = min(max(backoff * 2.0, cfg.connect_backoff_min_ms / 1000.0), cfg.connect_backoff_max_ms / 1000.0)
                stop_evt.wait(backoff)
        except Exception as e:
            logging.exception("Collection loop error: %s", e)
            stop_evt.wait(cfg.read_poll_interval_ms / 1000.0)


def main():
    cfg = load_config()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    global DEVICE, STATE
    DEVICE = ModbusDisplayModule(cfg)
    STATE = SharedState()

    stop_evt = threading.Event()

    t = threading.Thread(target=collection_loop, args=(cfg, DEVICE, STATE, stop_evt), daemon=True)
    t.start()

    httpd = ThreadingHTTPServer((cfg.http_host, cfg.http_port), RequestHandler)

    def shutdown(signum=None, frame=None):
        logging.info("Shutting down...")
        stop_evt.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            DEVICE.close()
        except Exception:
            pass

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logging.info("HTTP server listening on %s:%d", cfg.http_host, cfg.http_port)
    try:
        httpd.serve_forever()
    finally:
        shutdown()
        t.join(timeout=5)
        logging.info("Exited cleanly")


if __name__ == "__main__":
    main()
