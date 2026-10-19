"""Native GPU frames piped directly to FFmpeg, with at most two frames in flight."""

import errno
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg

from .models import ExportRequest

ACTIVE_STATES = {"ready", "rendering", "encoding"}
ENCODERS = {
    "h264_nvenc": ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0"],
    "h264_qsv": ["-preset", "veryfast", "-global_quality", "18"],
    "h264_amf": ["-quality", "speed", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18"],
    "libx264": ["-preset", "medium", "-crf", "18"],
}


def hidden_process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def check_encoder() -> tuple[str | None, str | None]:
    try:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [executable, "-hide_banner", "-encoders"], capture_output=True, text=True,
            timeout=15, check=True, **hidden_process_options(),
        )
        if "libx264" not in result.stdout:
            return None, "설치된 FFmpeg에 H.264(libx264) 인코더가 없습니다."
        return executable, None
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return None, f"FFmpeg를 실행할 수 없습니다: {exc}"


@lru_cache(maxsize=64)
def select_encoder(executable, width, height, device, preference="auto"):
    """Probe actual hardware and dimensions, not just the FFmpeg encoder listing."""
    name = device.lower()
    candidate = ("h264_nvenc" if "nvidia" in name else "h264_qsv" if "intel" in name
                 else "h264_amf" if "amd" in name or "radeon" in name else None)
    if preference == "auto" and candidate:
        try:
            result = subprocess.run([
                executable, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-f", "lavfi", "-i", f"color=size={width}x{height}:rate=30",
                "-frames:v", "2", "-an", "-c:v", candidate, *ENCODERS[candidate],
                "-pix_fmt", "yuv420p", "-f", "null", "-",
            ], check=False, capture_output=True, timeout=15, **hidden_process_options())
            if result.returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass
    return "libx264"


class ExportJob:
    def __init__(self, request: ExportRequest, root: Path, executable: str, encoder="libx264"):
        self.id = uuid.uuid4().hex
        self.request = request
        self.executable = executable
        self.encoder = encoder
        self.folder = root / self.id
        self.folder.mkdir()
        self.path = self.folder / "wave.mp4"
        self.status = "ready"
        self.error: str | None = None
        self.error_code: str | None = None
        self.frames = 0
        self.created = time.monotonic()
        self.started: float | None = None
        self.finished: float | None = None
        self.process: subprocess.Popen | None = None
        self.stderr_thread: threading.Thread | None = None
        self.logs: deque[str] = deque(maxlen=32)
        self.connected = False
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.worker: threading.Thread | None = None

    def snapshot(self) -> dict:
        output = self.request.output
        elapsed = (self.finished or time.monotonic()) - (self.started or self.created)
        rate = self.frames / elapsed if elapsed > 0 and self.frames else 0
        return {
            "id": self.id, "status": self.status, "frames": self.frames,
            "total_frames": output.frame_count,
            "progress": self.frames / output.frame_count,
            "elapsed": round(elapsed, 2),
            "eta": round((output.frame_count - self.frames) / rate, 1) if rate else None,
            "width": output.encoded_size[0], "height": output.encoded_size[1],
            "error": self.error, "error_code": self.error_code,
            "encoder": self.encoder, "hardware_encoding": self.encoder != "libx264",
            "download_url": f"/api/exports/{self.id}/download"
            if self.status == "completed" else None,
        }

    def start(self):
        with self.lock:
            if self.status != "ready":
                raise RuntimeError("이미 시작되었거나 취소한 작업입니다.")
            output = self.request.output
            w, h = output.encoded_size
            filters = ["vflip"]  # Native OpenGL readback is bottom-up.
            if (w, h) != (output.width, output.height):
                filters += [
                    f"pad={w}:{h}:0:0",
                    f"fillborders=right={w-output.width}:bottom={h-output.height}:mode=smear",
                ]
            filters += ["scale=out_color_matrix=bt709:out_range=tv", "format=yuv420p"]
            command = [
                self.executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "rawvideo", "-pixel_format", "rgba", "-video_size",
                f"{output.width}x{output.height}", "-framerate", str(output.fps),
                "-i", "pipe:0", "-an", "-vf", ",".join(filters),
                "-c:v", self.encoder, *ENCODERS[self.encoder],
                "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
                "-color_primaries", "bt709", "-color_trc", "iec61966-2-1",
                # Some hardware encoders drop codec color fields; write H.264 VUI explicitly.
                "-bsf:v", ("h264_metadata=colour_primaries=1:transfer_characteristics=13:"
                           "matrix_coefficients=1:video_full_range_flag=0"),
                "-movflags", "+faststart", str(self.path),
            ]
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, bufsize=0, **hidden_process_options(),
            )
            self.stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
            self.stderr_thread.start()
            self.started = time.monotonic()
            self.status = "rendering"

    def launch(self, renderer):
        self.worker = threading.Thread(target=self._render, args=(renderer,), daemon=True,
                                       name=f"xmb-export-{self.id[:8]}")
        self.worker.start()

    def _render(self, renderer):
        pending = None
        try:
            self.start()
            output = self.request.output

            def frame(index):
                return renderer.submit("render", self.request.scene, index / output.fps,
                                       output.width, output.height, output.duration)

            pending = frame(0)
            for index in range(output.frame_count):
                if self.cancelled.is_set():
                    return
                try:
                    pixels = pending.result()
                except Exception as exc:  # noqa: BLE001 - GPU/driver errors cross this worker boundary.
                    self.stop(f"GPU 렌더링에 실패했습니다: {exc}", "gpu_error")
                    return
                if self.cancelled.is_set():
                    return
                # Render frame N+1 while the encoder consumes N. Never queue a whole movie.
                pending = frame(index + 1) if index + 1 < output.frame_count else None
                self.write(pixels)
                self.frames = index + 1
            if not self.cancelled.is_set():
                self.finish()
        except Exception as exc:  # noqa: BLE001 - A worker must always reclaim its encoder on failure.
            self.fail(exc)
        finally:
            if pending:
                pending.cancel()

    def _drain_stderr(self):
        assert self.process and self.process.stderr
        try:
            while chunk := self.process.stderr.read(2048):
                self.logs.append(chunk.decode("utf-8", errors="replace"))
        except OSError:
            pass

    def write(self, chunk: bytes):
        process = self.process
        if self.status != "rendering" or not process or not process.stdin:
            raise RuntimeError("제작이 중단되었습니다.")
        view = memoryview(chunk)
        while view:
            written = process.stdin.write(view)
            if not written:
                raise BrokenPipeError("인코더 연결이 종료되었습니다.")
            view = view[written:]

    def finish(self):
        with self.lock:
            if self.status != "rendering":
                raise RuntimeError("제작이 중단되었습니다.")
            self.status = "encoding"
        process = self.process
        assert process and process.stdin
        process.stdin.close()
        result = process.wait()
        if self.stderr_thread:
            self.stderr_thread.join(timeout=2)
        if process.stderr:
            process.stderr.close()
        with self.lock:
            if self.status == "cancelled":
                return
            if result != 0 or not self.path.exists() or self.path.stat().st_size == 0:
                raise RuntimeError("".join(self.logs) or "영상 파일을 완성하지 못했습니다.")
            self.status = "completed"
            self.finished = time.monotonic()

    def stop(self, error: str | None = None, code: str | None = None):
        with self.lock:
            if self.status not in ACTIVE_STATES:
                return
            self.status = "error" if error else "cancelled"
            self.error = error
            self.error_code = code
            self.finished = time.monotonic()
            self.cancelled.set()
        process = self.process
        if process:
            if process.poll() is None:
                process.kill()  # Break a blocked stdin write as well as normal rendering.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if self.stderr_thread:
                self.stderr_thread.join(timeout=2)
            for stream in (process.stdin, process.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self.path.unlink(missing_ok=True)

    def fail(self, exc: Exception):
        details = "".join(self.logs)
        if (isinstance(exc, OSError) and exc.errno == errno.ENOSPC) or (
            "no space" in details.lower() or "not enough space" in details.lower()
        ):
            self.stop("저장 공간이 부족합니다. 디스크 공간을 확보한 뒤 다시 제작해 주세요.", "disk_full")
        else:
            self.stop(f"영상 제작에 실패했습니다: {details[-1500:] or str(exc)}", "encoder_error")


class ExportManager:
    def __init__(self, renderer):
        self.renderer = renderer
        self.root = Path(tempfile.mkdtemp(prefix="xmb-wave-"))
        self.executable, self.encoder_error = check_encoder()
        self.jobs: dict[str, ExportJob] = {}
        self.lock = threading.Lock()
        self.default_encoder = select_encoder(
            self.executable, 256, 256, renderer.info.get("device") or "",
        ) if self.executable else None

    @property
    def active(self):
        return any(job.status in ACTIVE_STATES for job in list(self.jobs.values()))

    def create(self, request: ExportRequest) -> ExportJob:
        if not self.executable:
            raise RuntimeError(self.encoder_error)
        with self.lock:
            if self.active:
                raise ValueError("다른 영상이 제작 중입니다. 완료하거나 취소한 뒤 다시 시작해 주세요.")
            output = request.output
            self.renderer.submit("allocate", output.width, output.height).result()
            encoder = select_encoder(self.executable, *output.encoded_size,
                                     self.renderer.info["device"], output.encoder)
            job = ExportJob(request, self.root, self.executable, encoder)
            self.jobs[job.id] = job
            return job

    def expire_unconnected(self):
        for job in list(self.jobs.values()):
            if job.status == "ready" and not job.connected and time.monotonic() - job.created > 45:
                job.stop("브라우저 진행 연결이 열리지 않아 작업을 정리했습니다.", "connection_lost")

    def close(self):
        for job in list(self.jobs.values()):
            job.stop()
        for job in list(self.jobs.values()):
            if job.worker:
                job.worker.join()
        shutil.rmtree(self.root, ignore_errors=True)
