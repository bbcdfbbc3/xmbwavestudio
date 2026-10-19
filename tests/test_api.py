import errno
import time

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient

from xmbwavestudio.exports import CHUNK_SIZE, ExportJob
from xmbwavestudio.models import OutputConfig, SceneConfig
from xmbwavestudio.server import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def request(width=32, height=32, duration=1, fps=30):
    return {"scene": SceneConfig().model_dump(), "output": {
        "kind": "video", "width": width, "height": height, "duration": duration, "fps": fps,
    }}


def create(client, **kwargs):
    response = client.post("/api/exports", json=request(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def transmit(client, job_id, width=32, height=32, count=30):
    # Asymmetric RGB blocks check channel order, vertical orientation and edge padding.
    top = bytes([235, 40, 45, 255]) * width
    bottom = bytes([25, 40, 230, 255]) * width
    frame = bottom * (height // 2) + top * (height - height // 2)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        assert ws.receive_json()["type"] == "ready"
        for index in range(count):
            ws.send_json({"type": "frame", "index": index})
            for offset in range(0, len(frame), CHUNK_SIZE):
                ws.send_bytes(frame[offset:offset + CHUNK_SIZE])
            assert ws.receive_json()["index"] == index
        assert ws.receive_json()["type"] == "encoding"
        result = ws.receive_json()
        assert result["type"] == "completed", result
    return result


def test_catalog_and_offline_assets(client):
    data = client.get("/api/presets").json()
    assert data["encoder"]["available"]
    assert len(data["devices"]) == 28
    assert sum(device["brand"] == "Galaxy" for device in data["devices"]) == 21
    assert len({device["id"] for device in data["devices"]}) == 28
    assert {style["id"] for style in data["styles"]} == {"psp-classic", "psp-original", "ps3"}
    assert all(device["source"].startswith("https://") for device in data["devices"])
    for asset in ["/", "/static/js/app.js", "/static/vendor/three.module.min.js",
                  "/static/vendor/three.core.min.js"]:
        assert client.get(asset).status_code == 200


@pytest.mark.parametrize("key,value", [("width", 0), ("height", 2.5), ("duration", 0),
                                         ("duration", 1.5), ("fps", 24)])
def test_rejects_invalid_output(client, key, value):
    payload = request()
    payload["output"][key] = value
    assert client.post("/api/exports", json=payload).status_code == 422


def test_unlimited_duration_and_strict_scene_validation(client):
    assert OutputConfig(duration=36000).frame_count == 1_080_000
    payload = request()
    payload["scene"]["speed"] = -1
    assert client.post("/api/exports", json=payload).status_code == 422
    payload["scene"]["speed"] = 1
    payload["scene"]["color"] = "not-a-color"
    assert client.post("/api/exports", json=payload).status_code == 422


@pytest.mark.parametrize("size", [0, -1, 0.24, 4.01])
def test_rejects_invalid_particle_size(client, size):
    payload = request()
    payload["scene"]["particle_size"] = size
    assert client.post("/api/exports", json=payload).status_code == 422


def test_particle_size_optional_for_old_clients_and_bounded_for_new_clients(client):
    payload = request()
    payload["scene"].pop("particle_size")
    response = client.post("/api/exports", json=payload)
    assert response.status_code == 201
    client.delete(f"/api/exports/{response.json()['id']}")
    for size in [0.25, 1, 4]:
        payload["scene"]["particle_size"] = size
        response = client.post("/api/exports", json=payload)
        assert response.status_code == 201
        client.delete(f"/api/exports/{response.json()['id']}")


@pytest.mark.parametrize("width,height,fps", [(32, 32, 30), (33, 35, 60), (1, 1, 30)])
def test_real_h264_encoding(client, tmp_path, width, height, fps):
    job_id = create(client, width=width, height=height, fps=fps)
    assert client.get(f"/api/exports/{job_id}/download").status_code == 409
    result = transmit(client, job_id, width, height, fps)
    video = tmp_path / "wave.mp4"
    download = client.get(result["download_url"])
    video.write_bytes(download.content)
    assert download.headers["content-type"] == "video/mp4"
    assert "attachment" in download.headers["content-disposition"]
    reader = imageio_ffmpeg.read_frames(str(video))
    metadata = next(reader)
    assert metadata["size"] == (width + width % 2, height + height % 2)
    assert metadata["fps"] == fps
    assert metadata["codec"] == "h264"
    frames = list(reader)
    assert len(frames) == fps
    assert abs(metadata["duration"] - 1) < 0.01
    if width > 2:
        top_pixel = frames[0][:3]
        assert top_pixel[0] > top_pixel[2] + 100, "top-down orientation or RGB channels changed"
        bottom_pixel = frames[0][-3:]
        assert bottom_pixel[2] > bottom_pixel[0] + 100
        # Padded last column repeats its neighbor instead of introducing a black border.
        if width % 2:
            last = (width + 1) * 3
            assert max(abs(a-b) for a, b in zip(frames[0][last-3:last], frames[0][last-6:last-3])) < 30
    assert client.get(f"/api/exports/{job_id}").json()["status"] == "completed"


def test_one_job_at_a_time_and_ready_cancel(client):
    job_id = create(client)
    assert client.post("/api/exports", json=request()).status_code == 409
    assert client.delete(f"/api/exports/{job_id}").json()["status"] == "cancelled"
    assert create(client) != job_id


def test_disconnect_kills_encoder_and_removes_partial(client, app):
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        assert ws.receive_json()["type"] == "ready"
        job = app.state.exports.jobs[job_id]
        assert job.process.poll() is None
        ws.send_json({"type": "frame", "index": 0})
        ws.send_bytes(bytes(20))  # Leave a frame incomplete, then close the tab.
    for _ in range(100):
        if job.status == "error" and job.process.poll() is not None and not job.path.exists():
            break
        time.sleep(0.01)
    assert job.status == "error"
    assert job.error_code == "connection_lost"
    assert job.process.poll() is not None
    assert not job.path.exists()


@pytest.mark.parametrize("header", [{"type": "frame", "index": 1}, [], {"type": "frame", "index": True}])
def test_frame_order_validation(client, app, header):
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        ws.receive_json()
        ws.send_json(header)
        assert ws.receive_json()["type"] == "error"
    assert app.state.exports.jobs[job_id].process.poll() is not None


def test_rejects_extra_frame_bytes(client):
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        ws.receive_json()
        ws.send_json({"type": "frame", "index": 0})
        ws.send_bytes(bytes(32 * 32 * 4 + 1))
        assert ws.receive_json()["type"] == "error"


@pytest.mark.parametrize("binary", [False, True])
def test_malformed_frame_header_is_reclaimed(client, app, binary):
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        ws.receive_json()
        if binary:
            ws.send_bytes(b"not a JSON header")
        else:
            ws.send_text("not JSON")
        assert ws.receive_json()["type"] == "error"
    assert app.state.exports.jobs[job_id].process.poll() is not None


def test_disk_failure_is_reported_and_allows_retry(client, app, monkeypatch):
    def disk_full(self, chunk):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(ExportJob, "write", disk_full)
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        ws.receive_json()
        ws.send_json({"type": "frame", "index": 0})
        ws.send_bytes(bytes(32 * 32 * 4))
        result = ws.receive_json()
        assert result["error_code"] == "disk_full"
    assert not app.state.exports.jobs[job_id].path.exists()
    assert create(client) != job_id


def test_cancel_running_encoder(client, app):
    job_id = create(client)
    with client.websocket_connect(f"/api/exports/{job_id}/frames") as ws:
        ws.receive_json()
        assert client.delete(f"/api/exports/{job_id}").json()["status"] == "cancelled"
    assert app.state.exports.jobs[job_id].process.poll() is not None


def test_local_origin_and_missing_job(client):
    assert client.post("/api/exports", json=request(), headers={"Origin": "https://other.example"}).status_code == 403
    assert client.get("/api/exports/unknown").status_code == 404
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400


def test_session_cleanup_and_unconnected_expiry():
    app = create_app()
    with TestClient(app) as client:
        job_id = create(client)
        job = app.state.exports.jobs[job_id]
        root = app.state.exports.root
        job.created -= 50
        app.state.exports.expire_unconnected()
        assert job.status == "error"
        assert job.error_code == "connection_lost"
    assert not root.exists()


def test_shutdown_stops_active_encoder_and_deletes_completed_files():
    app = create_app()
    with TestClient(app) as client:
        completed_id = create(client)
        transmit(client, completed_id)
        completed = app.state.exports.jobs[completed_id]
        active_id = create(client)
        active = app.state.exports.jobs[active_id]
        active.start()
        root = app.state.exports.root
        assert completed.path.is_file()
        assert active.process.poll() is None
    assert active.process.poll() is not None
    assert not root.exists()
