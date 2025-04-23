import os
import io
import json
import asyncio
import base64
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, Request, Response, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

app = FastAPI()

# Read configuration from environment variables
CAMERA_HOST = os.environ.get("CAMERA_HOST", "127.0.0.1")
CAMERA_RTSP_PORT = int(os.environ.get("CAMERA_RTSP_PORT", 554))
CAMERA_HTTP_PORT = int(os.environ.get("CAMERA_HTTP_PORT", 80))
CAMERA_USER = os.environ.get("CAMERA_USER", "admin")
CAMERA_PASSWORD = os.environ.get("CAMERA_PASSWORD", "12345")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", 8000))
STREAM_CHANNEL = os.environ.get("CAMERA_STREAM_CHANNEL", "101")  # default main stream
PTZ_TIMEOUT = int(os.environ.get("PTZ_TIMEOUT", 5))  # seconds for PTZ request timeout

def get_rtsp_url():
    user_enc = quote_plus(CAMERA_USER)
    pwd_enc = quote_plus(CAMERA_PASSWORD)
    return f"rtsp://{user_enc}:{pwd_enc}@{CAMERA_HOST}:{CAMERA_RTSP_PORT}/Streaming/Channels/{STREAM_CHANNEL}"

def get_camera_base_http():
    return f"http://{CAMERA_HOST}:{CAMERA_HTTP_PORT}"

def get_auth_header():
    credentials = f"{CAMERA_USER}:{CAMERA_PASSWORD}"
    b64 = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {b64}"}

async def fetch_camera_config():
    url = f"{get_camera_base_http()}/ISAPI/System/configurationData"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=get_auth_header(), timeout=5)
        resp.raise_for_status()
        return resp.text

async def update_camera_config(config_data: dict):
    url = f"{get_camera_base_http()}/ISAPI/System/configurationData"
    async with httpx.AsyncClient() as client:
        resp = await client.put(url, data=json.dumps(config_data), headers={**get_auth_header(), "Content-Type": "application/json"}, timeout=5)
        resp.raise_for_status()
        return resp.text

async def fetch_snapshot():
    url = f"{get_camera_base_http()}/ISAPI/Streaming/channels/{STREAM_CHANNEL}/picture"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=get_auth_header(), timeout=5)
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", "image/jpeg")

async def send_ptz_command(ptz_payload: dict):
    url = f"{get_camera_base_http()}/ISAPI/PTZCtrl/channels/{STREAM_CHANNEL}/continuous"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=json.dumps(ptz_payload), headers={**get_auth_header(), "Content-Type": "application/json"}, timeout=PTZ_TIMEOUT)
        resp.raise_for_status()
        return resp.text

# --- Video Stream Proxy ---
# Use OpenCV for RTSP -> MJPEG conversion, as many browsers support MJPEG-over-HTTP.
import cv2
from starlette.concurrency import run_in_threadpool

def mjpeg_frame_generator(rtsp_url):
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        raise RuntimeError("Could not open RTSP stream")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n'
            )
    finally:
        cap.release()

@app.get("/stream", summary="Retrieves the live video stream")
async def stream():
    rtsp_url = get_rtsp_url()
    generator = lambda: mjpeg_frame_generator(rtsp_url)
    return StreamingResponse(run_in_threadpool(generator), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/capture", summary="Captures a current image snapshot")
async def capture():
    try:
        img_bytes, content_type = await fetch_snapshot()
        return Response(content=img_bytes, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Snapshot failed: {e}")

@app.get("/config", summary="Retrieves camera configuration and status")
async def get_config():
    try:
        config_text = await fetch_camera_config()
        # Try to parse as JSON to pretty-print if possible
        try:
            config_obj = json.loads(config_text)
            return JSONResponse(content=config_obj)
        except Exception:
            return Response(content=config_text, media_type="application/xml")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to get config: {e}")

@app.put("/config", summary="Updates the camera's configuration settings")
async def put_config(request: Request):
    try:
        config_data = await request.json()
        resp = await update_camera_config(config_data)
        return Response(content=resp, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Config update failed: {e}")

@app.post("/ptz", summary="Sends pan-tilt-zoom (PTZ) commands")
async def ptz(request: Request):
    try:
        ptz_payload = await request.json()
        resp = await send_ptz_command(ptz_payload)
        return Response(content=resp, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PTZ command failed: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)