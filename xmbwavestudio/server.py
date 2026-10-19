"""Loopback-only editor and frame-streaming API."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .exports import ACTIVE_STATES, CHUNK_SIZE, ExportManager
from .models import STYLE_PRESETS, ExportRequest

PACKAGE = Path(__file__).resolve().parent


def same_origin(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True  # Non-browser clients, including local tests.
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == host


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = await asyncio.to_thread(ExportManager)
        app.state.exports = manager

        async def reap():
            while True:
                await asyncio.sleep(5)
                await asyncio.to_thread(manager.expire_unconnected)

        reaper = asyncio.create_task(reap())
        try:
            yield
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            await asyncio.to_thread(manager.close)

    app = FastAPI(title="XMB Wave Studio", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not same_origin(
            request.headers.get("origin"), request.headers.get("host")
        ):
            return JSONResponse({"detail": "로컬 대시보드에서 요청해 주세요."}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def get_job(job_id: str):
        job = app.state.exports.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "해당 제작 작업을 찾을 수 없습니다.")
        return job

    @app.get("/api/health")
    async def health():
        return {"app": "xmbwavestudio", "version": __version__}

    @app.get("/api/presets")
    async def presets():
        manager = app.state.exports
        devices = json.loads((PACKAGE / "data" / "devices.json").read_text(encoding="utf-8"))
        return {
            "styles": STYLE_PRESETS, "devices": devices,
            "palette": ["#3264c5", "#7958b6", "#ca6ba1", "#c44243", "#d5833b", "#b9a058",
                        "#6a9f58", "#408d86", "#425f97", "#758598", "#b9b9b9", "#252535"],
            "encoder": {"available": bool(manager.executable), "error": manager.encoder_error},
            "version": __version__,
        }

    @app.post("/api/exports", status_code=201)
    async def create_export(request: ExportRequest):
        if request.output.kind != "video":
            raise HTTPException(422, "이 API는 영상 제작용입니다. JPEG는 브라우저에서 저장합니다.")
        try:
            job = app.state.exports.create(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return job.snapshot()

    @app.get("/api/exports/{job_id}")
    async def export_status(job_id: str):
        return get_job(job_id).snapshot()

    @app.delete("/api/exports/{job_id}")
    async def cancel_export(job_id: str):
        job = get_job(job_id)
        await asyncio.to_thread(job.stop)
        return job.snapshot()

    @app.get("/api/exports/{job_id}/download")
    async def download(job_id: str):
        job = get_job(job_id)
        if job.status != "completed" or not job.path.is_file():
            raise HTTPException(409, "아직 다운로드할 수 있는 파일이 없습니다.")
        output = job.request.output
        width, height = output.encoded_size
        filename = f"xmb-{job.request.scene.style}-{width}x{height}-{output.duration}s.mp4"
        return FileResponse(job.path, media_type="video/mp4", filename=filename)

    @app.websocket("/api/exports/{job_id}/frames")
    async def frames(websocket: WebSocket, job_id: str):
        if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        job = app.state.exports.jobs.get(job_id)
        if not job or job.connected or job.status != "ready":
            await websocket.close(code=1008)
            return
        job.connected = True
        await websocket.accept()
        try:
            await asyncio.to_thread(job.start)
            await websocket.send_json({"type": "ready", "chunk_size": CHUNK_SIZE, **job.snapshot()})
            output = job.request.output
            frame_bytes = output.width * output.height * 4
            for index in range(output.frame_count):
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect()
                if not isinstance(message.get("text"), str):
                    raise TypeError("프레임 헤더는 JSON 텍스트여야 합니다.")
                header = json.loads(message["text"])
                if not isinstance(header, dict):
                    raise TypeError("프레임 헤더가 올바르지 않습니다.")
                if header.get("type") != "frame" or type(header.get("index")) is not int or (
                    header["index"] != index
                ):
                    raise ValueError("프레임 순서가 일치하지 않습니다.")
                remaining = frame_bytes
                while remaining:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    chunk = message.get("bytes")
                    if not chunk or len(chunk) > min(CHUNK_SIZE, remaining):
                        raise ValueError("프레임 데이터 크기가 올바르지 않습니다.")
                    await asyncio.to_thread(job.write, chunk)
                    remaining -= len(chunk)
                job.frames += 1
                await websocket.send_json({"type": "ack", "index": index, **job.snapshot()})
            await websocket.send_json({"type": "encoding", **job.snapshot()})

            # A tab closing during MP4 finalization must also stop the encoder.
            finishing = asyncio.create_task(asyncio.to_thread(job.finish))
            disconnect = asyncio.create_task(websocket.receive())
            try:
                done, _ = await asyncio.wait(
                    {finishing, disconnect}, return_when=asyncio.FIRST_COMPLETED
                )
                if disconnect in done:
                    await asyncio.to_thread(
                        job.stop, "브라우저 연결이 종료되어 제작을 중단했습니다.", "connection_lost"
                    )
                    await finishing
                    return
                await finishing
            finally:
                disconnect.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await disconnect
            await websocket.send_json({"type": "completed", **job.snapshot()})
        except WebSocketDisconnect:
            await asyncio.to_thread(
                job.stop, "브라우저 연결이 종료되어 제작을 중단했습니다.", "connection_lost"
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            if job.status in ACTIVE_STATES:
                await asyncio.to_thread(job.fail, exc)
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "error", **job.snapshot()})
        finally:
            if job.status in ACTIVE_STATES:
                await asyncio.to_thread(job.stop)
            with contextlib.suppress(Exception):
                await websocket.close()

    @app.get("/")
    async def index():
        return FileResponse(PACKAGE / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    return app
