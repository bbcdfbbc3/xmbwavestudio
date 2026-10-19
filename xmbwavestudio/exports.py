"""Bounded frame streaming into one local FFmpeg process per export."""

import errno
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import imageio_ffmpeg

from .models import ExportRequest

ACTIVE_STATES = {"ready", "rendering", "encoding"}
CHUNK_SIZE = 1024 * 1024


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


class ExportJob:
    def __init__(self, request: ExportRequest, root: Path, executable: str):
        self.id = uuid.uuid4().hex
        self.request = request
        self.executable = executable
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
            "download_url": f"/api/exports/{self.id}/download"
            if self.status == "completed" else None,
        }

    def start(self):
        with self.lock:
            if self.status != "ready":
                raise RuntimeError("이미 시작되었거나 취소한 작업입니다.")
            output = self.request.output
            w, h = output.encoded_size
            filters = ["vflip"]  # readPixels is bottom-up; canvas JPEG is already top-down.
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
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
                "-color_primaries", "bt709", "-color_trc", "iec61966-2-1",
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
        process = self.process
        if process:
            if process.poll() is None:
                process.kill()  # Break a blocked stdin write as well as normal rendering.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
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
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="xmb-wave-"))
        self.executable, self.encoder_error = check_encoder()
        self.jobs: dict[str, ExportJob] = {}
        self.lock = threading.Lock()

    def create(self, request: ExportRequest) -> ExportJob:
        if not self.executable:
            raise RuntimeError(self.encoder_error)
        with self.lock:
            if any(job.status in ACTIVE_STATES for job in self.jobs.values()):
                raise ValueError("다른 영상이 제작 중입니다. 완료하거나 취소한 뒤 다시 시작해 주세요.")
            job = ExportJob(request, self.root, self.executable)
            self.jobs[job.id] = job
            return job

    def expire_unconnected(self):
        for job in list(self.jobs.values()):
            if job.status == "ready" and not job.connected and time.monotonic() - job.created > 45:
                job.stop("브라우저 렌더러가 연결되지 않아 작업을 정리했습니다.", "connection_lost")

    def close(self):
        for job in list(self.jobs.values()):
            job.stop()
        shutil.rmtree(self.root, ignore_errors=True)
