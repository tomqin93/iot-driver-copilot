import os
import json
import threading
import time
import base64
import queue
from typing import Callable, Optional

import paho.mqtt.client as mqtt

class USBCameraMQTTDriver:
    def __init__(self):
        self.broker_address = os.environ.get("MQTT_BROKER_ADDRESS")
        if not self.broker_address:
            raise EnvironmentError("MQTT_BROKER_ADDRESS environment variable is required")
        self.client_id = os.environ.get("MQTT_CLIENT_ID", "usb_camera_shifu")
        self.username = os.environ.get("MQTT_USERNAME")
        self.password = os.environ.get("MQTT_PASSWORD")
        self.keepalive = int(os.environ.get("MQTT_KEEPALIVE", 60))
        self._client = mqtt.Client(client_id=self.client_id, clean_session=True)
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._subscriptions = {}
        self._msg_queues = {}
        self._connect_lock = threading.Lock()
        self._connected = threading.Event()
        self._connect()
        self._listen_thread = threading.Thread(target=self._loop_forever, daemon=True)
        self._listen_thread.start()

    def _connect(self):
        with self._connect_lock:
            if not self._connected.is_set():
                self._client.connect(self.broker_address.split(':')[0], int(self.broker_address.split(':')[1]), self.keepalive)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
        else:
            self._connected.clear()

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()

    def _loop_forever(self):
        while True:
            try:
                self._client.loop_forever()
            except Exception:
                time.sleep(2)
                self._connect()

    def _on_message(self, client, userdata, msg):
        if msg.topic in self._subscriptions:
            callback = self._subscriptions[msg.topic]
            try:
                payload = json.loads(msg.payload.decode())
            except Exception:
                payload = msg.payload
            callback(payload)
        if msg.topic in self._msg_queues:
            try:
                self._msg_queues[msg.topic].put_nowait(msg)
            except Exception:
                pass

    # ========== SUBSCRIBE ==========

    def subscribe_to_audio_stream(self, callback: Callable[[dict], None]):
        """
        Subscribe to the audio stream telemetry.
        Payload: { audio_data: base64, timestamp: ... }
        """
        topic = "device/camera/audio"
        self._subscriptions[topic] = callback
        self._client.subscribe(topic, qos=1)

    def subscribe_to_video_stream(self, callback: Callable[[dict], None]):
        """
        Subscribe to the video stream telemetry.
        Payload: { video_frame: base64, timestamp: ..., format: ... }
        """
        topic = "device/camera/video"
        self._subscriptions[topic] = callback
        self._client.subscribe(topic, qos=1)

    # ========== PUBLISH ==========

    def adjust_resolution(self, width: int, height: int):
        """
        Publish a command to adjust camera resolution.
        Payload: { "width": ..., "height": ... }
        """
        topic = "device/camera/resolution/adjust"
        payload = {"width": width, "height": height}
        self._client.publish(topic, json.dumps(payload), qos=1)

    def start_capture(self, capture_mode: Optional[str] = None, duration: Optional[int] = None):
        """
        Publish command to start camera capture process.
        Optional payload parameters: capture_mode, duration
        """
        topic = "device/camera/capture/start"
        payload = {}
        if capture_mode:
            payload["capture_mode"] = capture_mode
        if duration:
            payload["duration"] = duration
        self._client.publish(topic, json.dumps(payload), qos=1)

    def stop_capture(self):
        """
        Publish command to stop camera capture.
        """
        topic = "device/camera/capture/stop"
        self._client.publish(topic, json.dumps({}), qos=1)

    def adjust_brightness(self, brightness: int):
        """
        Publish command to adjust camera brightness.
        Payload: { "brightness": ... }
        """
        topic = "device/camera/brightness/adjust"
        payload = {"brightness": brightness}
        self._client.publish(topic, json.dumps(payload), qos=1)

    def adjust_contrast(self, contrast: int):
        """
        Publish command to adjust camera contrast.
        Payload: { "contrast": ... }
        """
        topic = "device/camera/contrast/adjust"
        payload = {"contrast": contrast}
        self._client.publish(topic, json.dumps(payload), qos=1)

    # ========== FOR DEVICE SHIFU API ==========

    # The following methods are for deviceShifu to call (they use the above under-the-hood)

    def deviceShifu_subscribe_audio(self, user_callback: Callable[[dict], None]):
        """DeviceShifu uses this to subscribe to audio stream"""
        self.subscribe_to_audio_stream(user_callback)

    def deviceShifu_subscribe_video(self, user_callback: Callable[[dict], None]):
        """DeviceShifu uses this to subscribe to video stream"""
        self.subscribe_to_video_stream(user_callback)

    def deviceShifu_adjust_resolution(self, width: int, height: int):
        """DeviceShifu API for adjusting resolution"""
        self.adjust_resolution(width, height)

    def deviceShifu_start_capture(self, capture_mode: Optional[str] = None, duration: Optional[int] = None):
        """DeviceShifu API for starting capture"""
        self.start_capture(capture_mode, duration)

    def deviceShifu_stop_capture(self):
        """DeviceShifu API for stopping capture"""
        self.stop_capture()

    def deviceShifu_adjust_brightness(self, brightness: int):
        """DeviceShifu API for adjusting brightness"""
        self.adjust_brightness(brightness)

    def deviceShifu_adjust_contrast(self, contrast: int):
        """DeviceShifu API for adjusting contrast"""
        self.adjust_contrast(contrast)