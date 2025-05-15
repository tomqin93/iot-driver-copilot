import os
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
import json

DEVICE_IP = os.getenv("DEVICE_IP", "192.168.123.161")
DEVICE_HTTP_PORT = os.getenv("DEVICE_HTTP_PORT", "9091")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
CAMERA_STREAM_PATH = os.getenv("CAMERA_STREAM_PATH", "/camera/stream")

DEVICE_API_BASE = f"http://{DEVICE_IP}:{DEVICE_HTTP_PORT}"

app = FastAPI()

async def fetch_camera_stream():
    url = f"{DEVICE_API_BASE}{CAMERA_STREAM_PATH}"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to connect to robot camera stream")
            async for chunk in response.aiter_bytes():
                yield chunk

@app.get("/camera/live")
async def camera_live():
    return StreamingResponse(fetch_camera_stream(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/motion")
async def motion(req: Request):
    body = await req.json()
    # Expected body example: {"direction": "forward", "gait": "trot"}
    url = f"{DEVICE_API_BASE}/api/motion"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=body)
        if resp.status_code != 200:
            return JSONResponse(status_code=502, content={"error": "Failed to send motion command", "detail": resp.text})
        return resp.json()

@app.post("/stop")
async def stop():
    url = f"{DEVICE_API_BASE}/api/emergency_stop"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url)
        if resp.status_code != 200:
            return JSONResponse(status_code=502, content={"error": "Failed to send stop command", "detail": resp.text})
        return resp.json()

@app.post("/voice")
async def voice(req: Request):
    body = await req.json()
    # Expected body example: {"command": "stand"}
    url = f"{DEVICE_API_BASE}/api/voice_command"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=body)
        if resp.status_code != 200:
            return JSONResponse(status_code=502, content={"error": "Failed to send voice command", "detail": resp.text})
        return resp.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)