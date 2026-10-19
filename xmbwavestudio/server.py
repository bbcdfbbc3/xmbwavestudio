"""Loopback editor: Python owns rendering; browsers receive only previews and status."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .exports import ACTIVE_STATES, ExportManager
from .models import STYLE_PRESETS, ExportRequest, ImageRequest, PreviewRequest
from .rendering import RenderService

PACKAGE = Path(__file__).resolve().parent


def same_origin(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == host


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        renderer = await asyncio.to_thread(RenderService)
        manager = await asyncio.to_thread(ExportManager, renderer)
        app.state.renderer = renderer
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
            await asyncio.to_thread(renderer.close)

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

    async def image_bytes(request: ImageRequest, preview=False):
        if app.state.exports.active:
            raise HTTPException(409, "영상 제작이 끝난 뒤 미리보기와 이미지를 만들 수 있습니다.")
        output = request.output
        width, height = ((request.width, request.height) if preview
                         else (output.width, output.height))
        format = request.format.upper() if preview else "JPEG"
        try:
            future = app.state.renderer.submit(
                "image", request.scene, request.time, width, height, output.duration,
                (output.width, output.height), format,
            )
            return await asyncio.wrap_future(future)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

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
            "encoder": {"available": bool(manager.executable), "error": manager.encoder_error,
                        "name": manager.default_encoder,
                        "hardware": manager.default_encoder not in {None, "libx264"}},
            "gpu": app.state.renderer.info, "version": __version__,
        }

    @app.post("/api/images")
    async def image(request: ImageRequest):
        data = await image_bytes(request)
        output = request.output
        filename = f"xmb-{request.scene.style}-{output.width}x{output.height}.jpg"
        return Response(data, media_type="image/jpeg", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        })

    @app.post("/api/preview")
    async def preview(request: PreviewRequest):
        return Response(await image_bytes(request, preview=True),
                        media_type=f"image/{request.format}")

    @app.websocket("/api/preview")
    async def live_preview(websocket: WebSocket):
        if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                try:
                    request = PreviewRequest.model_validate(await websocket.receive_json())
                    await websocket.send_bytes(await image_bytes(request, preview=True))
                except (ValidationError, HTTPException, ValueError, TypeError, KeyError) as exc:
                    await websocket.send_json({"error": str(exc.detail) if isinstance(
                        exc, HTTPException) else "미리보기 입력값을 확인해 주세요."})
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.post("/api/exports", status_code=201)
    async def create_export(request: ExportRequest):
        if request.output.kind != "video":
            raise HTTPException(422, "JPEG는 /api/images에서 저장합니다.")
        try:
            job = await asyncio.to_thread(app.state.exports.create, request)
        except ValueError as exc:
            raise HTTPException(409 if app.state.exports.active else 422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(507, "영상 작업을 만들 수 없습니다. 임시 폴더와 디스크 공간을 확인해 주세요.") from exc
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

    @app.websocket("/api/exports/{job_id}/progress")
    async def progress(websocket: WebSocket, job_id: str):
        if not same_origin(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        job = app.state.exports.jobs.get(job_id)
        if not job or job.connected or job.status != "ready":
            await websocket.close(code=1008)
            return
        job.connected = True
        await websocket.accept()
        disconnect = asyncio.create_task(websocket.receive())
        try:
            await websocket.send_json({"type": "ready", **job.snapshot()})
            job.launch(app.state.renderer)
            while True:
                snapshot = job.snapshot()
                await websocket.send_json({"type": snapshot["status"], **snapshot})
                if snapshot["status"] not in ACTIVE_STATES:
                    break
                done, _ = await asyncio.wait({disconnect}, timeout=.1)
                if done:
                    await asyncio.to_thread(job.stop,
                                            "브라우저 연결이 종료되어 제작을 중단했습니다.",
                                            "connection_lost")
                    break
        except (WebSocketDisconnect, OSError, RuntimeError):
            await asyncio.to_thread(job.stop, "브라우저 연결이 종료되었습니다.", "connection_lost")
        finally:
            disconnect.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await disconnect
            if job.status in ACTIVE_STATES:
                await asyncio.to_thread(job.stop)
            with contextlib.suppress(Exception):
                await websocket.close()

    @app.get("/")
    async def index():
        return FileResponse(PACKAGE / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    return app
