import errno
import io
import time
from concurrent.futures import Future

import imageio_ffmpeg
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from xmbwavestudio.exports import ExportJob, select_encoder
from xmbwavestudio.models import OutputConfig, SceneConfig
from xmbwavestudio.server import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def request(width=32, height=32, duration=1, fps=30, encoder="software", style="ps3"):
    return {"scene": SceneConfig(style=style).model_dump(), "output": {
        "kind": "video", "width": width, "height": height, "duration": duration,
        "fps": fps, "encoder": encoder,
    }}


def create(client, **kwargs):
    response = client.post("/api/exports", json=request(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def produce(client, job_id):
    # No pixels, timestamps or frame headers are sent by the client.
    with client.websocket_connect(f"/api/exports/{job_id}/progress") as ws:
        assert ws.receive_json()["type"] == "ready"
        while True:
            result = ws.receive_json()
            if result["status"] not in {"ready", "rendering", "encoding"}:
                return result


def wait_stopped(job):
    if job.worker:
        job.worker.join(timeout=10)
        assert not job.worker.is_alive()
    for _ in range(100):
        if job.status not in {"ready", "rendering", "encoding"}:
            break
        time.sleep(.01)
    assert job.status not in {"ready", "rendering", "encoding"}
    assert not job.process or job.process.poll() is not None
    assert not job.path.exists()


def test_catalog_and_offline_assets(client):
    data = client.get("/api/presets").json()
    assert data["encoder"]["available"]
    assert data["gpu"]["available"], data["gpu"]
    assert data["gpu"]["max_size"] >= 4096
    assert len(data["devices"]) == 28
    assert sum(device["brand"] == "Galaxy" for device in data["devices"]) == 21
    assert len({device["id"] for device in data["devices"]}) == 28
    assert {style["id"] for style in data["styles"]} == {"psp-classic", "psp-original", "ps3"}
    for asset in ["/", "/static/js/app.js", "/static/js/preview-client.js"]:
        assert client.get(asset).status_code == 200


@pytest.mark.parametrize("key,value", [("width", 0), ("height", 2.5), ("duration", 0),
                                     ("duration", 1.5), ("fps", 24), ("encoder", "invalid")])
def test_invalid_output(client, key, value):
    payload = request()
    payload["output"][key] = value
    assert client.post("/api/exports", json=payload).status_code == 422


@pytest.mark.parametrize("key,value", [("particle_size", .24), ("particle_size", 4.01),
                                     ("layer_motion", -.05), ("layer_motion", 2.05),
                                     ("speed", -1), ("color", "wrong")])
def test_invalid_scene(client, key, value):
    payload = request()
    payload["scene"][key] = value
    assert client.post("/api/exports", json=payload).status_code == 422


@pytest.mark.parametrize("key", ["layer_motion", "particle_size", "speed"])
@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan")])
def test_scene_numbers_must_be_finite(key, value):
    with pytest.raises(ValueError):
        SceneConfig(**{key: value})


def test_old_requests_and_long_duration(client):
    assert OutputConfig(duration=36000).frame_count == 1_080_000
    payload = request()
    payload["scene"].pop("layer_motion")
    payload["scene"].pop("particle_size")
    response = client.post("/api/exports", json=payload)
    assert response.status_code == 201
    assert SceneConfig.model_validate(payload["scene"]).layer_motion == 1


@pytest.mark.parametrize("style", ["psp-classic", "psp-original", "ps3"])
def test_same_preview_jpeg_and_websocket_renderer(client, style):
    payload = {**request(width=127, height=129, style=style), "time": 2.5}
    jpeg = client.post("/api/images", json=payload)
    assert jpeg.status_code == 200
    assert Image.open(io.BytesIO(jpeg.content)).size == (127, 129)
    preview = {**payload, "width": 127, "height": 129}
    assert client.post("/api/preview", json=preview).content == jpeg.content
    with client.websocket_connect("/api/preview") as ws:
        ws.send_json(preview)
        assert ws.receive_bytes() == jpeg.content
        ws.send_json({**preview, "width": 0})
        assert ws.receive_json()["error"]
        ws.send_json(preview)
        assert ws.receive_bytes() == jpeg.content


@pytest.mark.parametrize("style,width,height,fps", [
    ("ps3", 32, 32, 30), ("psp-classic", 127, 129, 60),
    ("psp-original", 128, 72, 30), ("ps3", 1, 1, 30),
])
def test_real_server_rendered_h264(client, tmp_path, style, width, height, fps):
    payload = request(width=width, height=height, fps=fps, style=style)
    jpeg = client.post("/api/images", json={**payload, "time": 0}).content
    job_id = create(client, width=width, height=height, fps=fps, style=style)
    assert client.get(f"/api/exports/{job_id}/download").status_code == 409
    result = produce(client, job_id)
    assert result["status"] == "completed", result
    video = tmp_path / "wave.mp4"
    video.write_bytes(client.get(result["download_url"]).content)
    reader = imageio_ffmpeg.read_frames(str(video))
    metadata = next(reader)
    size = (width + width % 2, height + height % 2)
    assert metadata["size"] == size
    assert metadata["fps"] == fps and metadata["codec"] == "h264"
    assert "bt709/bt709/iec61966-2-1" in metadata["pix_fmt"]
    frames = list(reader)
    assert len(frames) == fps and abs(metadata["duration"] - 1) < .01
    first = np.frombuffer(frames[0], np.uint8).reshape(size[1], size[0], 3)
    original = np.asarray(Image.open(io.BytesIO(jpeg))).astype(float)
    # Compare the actual scene, orientation and RGB order, allowing H.264 chroma loss.
    assert np.abs(first[:height, :width].astype(float) - original).mean() < 4
    if width % 2 and width > 1:
        assert np.abs(first[:, -1].astype(float) - first[:, -2]).mean() < 5


def test_auto_encoder_color_tags(client, tmp_path):
    job_id = create(client, width=256, height=256, encoder="auto")
    result = produce(client, job_id)
    assert result["status"] == "completed", result
    video = tmp_path / "hardware.mp4"
    video.write_bytes(client.get(result["download_url"]).content)
    reader = imageio_ffmpeg.read_frames(str(video))
    metadata = next(reader)
    assert "bt709/bt709/iec61966-2-1" in metadata["pix_fmt"]
    reader.close()


def test_busy_and_cancel(client, app):
    job_id = create(client, duration=600)
    assert client.post("/api/exports", json=request()).status_code == 409
    assert client.post("/api/images", json=request()).status_code == 409
    with client.websocket_connect(f"/api/exports/{job_id}/progress") as ws:
        ws.receive_json()
        assert client.delete(f"/api/exports/{job_id}").json()["status"] == "cancelled"
    wait_stopped(app.state.exports.jobs[job_id])
    assert create(client) != job_id


def test_tab_disconnect_reclaims_worker(client, app):
    job_id = create(client, duration=600)
    with client.websocket_connect(f"/api/exports/{job_id}/progress") as ws:
        ws.receive_json()
        ws.receive_json()
    job = app.state.exports.jobs[job_id]
    for _ in range(100):
        if job.status == "error":
            break
        time.sleep(.01)
    wait_stopped(job)
    assert job.error_code == "connection_lost"


def test_disk_failure_and_retry(client, app, monkeypatch):
    def disk_full(self, chunk):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(ExportJob, "write", disk_full)
    job_id = create(client)
    assert produce(client, job_id)["error_code"] == "disk_full"
    wait_stopped(app.state.exports.jobs[job_id])
    assert create(client) != job_id


def test_gpu_failure_cleans_encoder(client, app, monkeypatch):
    job_id = create(client)
    submit = app.state.renderer.submit

    def fail_render(method, *args, **kwargs):
        if method != "render":
            return submit(method, *args, **kwargs)
        future = Future()
        future.set_exception(RuntimeError("simulated context loss"))
        return future
    monkeypatch.setattr(app.state.renderer, "submit", fail_render)
    assert produce(client, job_id)["error_code"] == "gpu_error"
    wait_stopped(app.state.exports.jobs[job_id])


def test_gpu_size_and_unavailable_errors(client, app, monkeypatch):
    maximum = app.state.renderer.info["max_size"]
    assert client.post("/api/exports", json=request(width=maximum + 1)).status_code == 422
    with monkeypatch.context() as patch:
        patch.setattr(app.state.renderer, "renderer", None)
        patch.setattr(app.state.renderer, "error", "GPU unavailable")
        assert client.post("/api/images", json=request()).status_code == 503


def test_encoder_probe_fallback(monkeypatch):
    import xmbwavestudio.exports as module

    def unavailable(*args, **kwargs):
        raise OSError("unsupported device")
    monkeypatch.setattr(module.subprocess, "run", unavailable)
    select_encoder.cache_clear()
    assert select_encoder("missing", 256, 256, "NVIDIA") == "libx264"
    assert select_encoder("missing", 256, 256, "NVIDIA", "software") == "libx264"


def test_loopback_and_missing_job(client):
    assert client.post("/api/exports", json=request(), headers={
        "Origin": "https://other.example"}).status_code == 403
    assert client.get("/api/exports/unknown").status_code == 404
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400


def test_session_cleanup_and_ready_expiry():
    app = create_app()
    with TestClient(app) as client:
        job_id = create(client)
        job = app.state.exports.jobs[job_id]
        root = app.state.exports.root
        job.created -= 50
        app.state.exports.expire_unconnected()
        assert job.error_code == "connection_lost"
        completed_id = create(client)
        assert produce(client, completed_id)["status"] == "completed"
        active = app.state.exports.jobs[create(client, duration=600)]
        active.launch(app.state.renderer)
    assert not root.exists()
    assert not active.worker.is_alive()
    assert not active.process or active.process.poll() is not None
