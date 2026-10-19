"""One native GPU renderer for previews, JPEGs and video frames.

The OpenGL context and all of its objects stay on one dedicated thread.
Only small preview images leave Python; full-size frames go to FFmpeg directly.
"""

import colorsys
import io
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

from .models import SceneConfig

SHADERS = Path(__file__).with_name("gpu")


def loop_angle(speed: float, time: float, duration: int, period: int) -> float:
    cycles = 0 if speed == 0 else max(1, math.floor(speed * duration / period + .5))
    phase = (time % duration) / duration
    return 2 * math.pi * ((phase * cycles) % 1)


def linear(rgb):
    return tuple(c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb)


def rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def scene_colors(scene):
    base_srgb = rgb(scene.color)
    h, lightness, saturation = colorsys.rgb_to_hls(*base_srgb)
    base = linear(base_srgb)
    background = linear(rgb(scene.background_color)) if scene.background_color else base
    accent = linear(colorsys.hls_to_rgb(
        (h - .085) % 1, min(.68, max(.44, lightness * 1.2)), min(.98, saturation * 1.5),
    ))
    if scene.style == "psp-classic":
        if not scene.background_color:
            background = linear(colorsys.hls_to_rgb(h, lightness, min(.98, saturation * 1.65)))
        accent = linear(colorsys.hls_to_rgb((h - .09) % 1, .48, min(.98, saturation * 1.8)))
    if scene.wave_color:
        wave = linear(rgb(scene.wave_color))
    elif scene.style == "psp-original":
        wave = tuple(c * 2 for c in base)
    elif scene.style == "ps3":
        wave = linear(colorsys.hls_to_rgb(h, .72, min(.8, saturation * 1.4)))
    else:
        wave = tuple(c * .7 + .3 for c in base)
    return background, wave, accent


def particle_random(count, seed):
    # Match the existing Mulberry32 sequence, including JS unsigned overflow.
    values = []
    for _ in range(count * 6):
        seed = (seed + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((seed ^ (seed >> 15)) * (seed | 1)) & 0xFFFFFFFF
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & 0xFFFFFFFF)) & 0xFFFFFFFF
        values.append(((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296)
    random = np.asarray(values[:count * 4], dtype="f4").reshape(count, 4)
    depth = np.asarray(values[count * 4:], dtype="f4").reshape(count, 2)
    return np.concatenate((random, depth), axis=1).tobytes()


class GpuRenderer:
    def __init__(self):
        self.ctx = moderngl.create_standalone_context(require=330)
        self.device = self.ctx.info["GL_RENDERER"]
        if any(name in self.device.lower() for name in (
            "llvmpipe", "swiftshader", "gdi generic", "software rasterizer", "basic render",
        )):
            self.ctx.release()
            raise RuntimeError("GPU 하드웨어 가속을 사용할 수 없습니다. 그래픽 드라이버를 확인해 주세요.")
        self.max_size = min(self.ctx.info["GL_MAX_TEXTURE_SIZE"],
                            self.ctx.info["GL_MAX_RENDERBUFFER_SIZE"],
                            *self.ctx.info["GL_MAX_VIEWPORT_DIMS"])
        self.wave = self.ctx.program(
            vertex_shader=(SHADERS / "screen.vert").read_text(encoding="utf-8"),
            fragment_shader=(SHADERS / "wave.frag").read_text(encoding="utf-8"),
        )
        self.particle = self.ctx.program(
            vertex_shader=(SHADERS / "particle.vert").read_text(encoding="utf-8"),
            fragment_shader=(SHADERS / "particle.frag").read_text(encoding="utf-8"),
        )
        self.screen_buffer = self.ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype="f4"))
        self.screen = self.ctx.vertex_array(self.wave, [(self.screen_buffer, "2f", "position")])
        # Same two-triangle quad, UVs and instance attributes as the WebGL version.
        quad = np.array([
            [-.5, .5, 0, 0, 1], [-.5, -.5, 0, 0, 0], [.5, .5, 0, 1, 1],
            [-.5, -.5, 0, 0, 0], [.5, -.5, 0, 1, 0], [.5, .5, 0, 1, 1],
        ], dtype="f4")
        self.quad_buffer = self.ctx.buffer(quad)
        self.particle_buffer = self.ctx.buffer(reserve=2000 * 6 * 4)
        self.particles = self.ctx.vertex_array(self.particle, [
            (self.quad_buffer, "3f 2f", "position", "uv"),
            (self.particle_buffer, "4f 2f /i", "aRandom", "aDepth"),
        ])
        self.particle_key = None
        self.fbo = self.texture = self.readback = None
        self.size = None

    def validate_size(self, width, height):
        if min(width, height) < 1 or max(width, height) > self.max_size:
            raise ValueError(f"이 GPU의 한 변 최대 크기는 {self.max_size:,}px입니다.")

    def allocate(self, width, height):
        self.validate_size(width, height)
        if self.size == (width, height):
            return
        # Drop old targets before allocating new ones, avoiding a transient 2x peak.
        for item in (self.fbo, self.texture, self.readback):
            if item:
                item.release()
        self.fbo = self.texture = self.readback = None
        self.size = None
        try:
            self.texture = self.ctx.texture((width, height), 4, dtype="f1")
            self.fbo = self.ctx.framebuffer([self.texture])
            self.readback = self.ctx.buffer(reserve=width * height * 4)
            self.size = (width, height)
        except Exception as exc:
            raise RuntimeError("GPU가 지정한 크기의 화면을 만들지 못했습니다. 해상도를 줄여 주세요.") from exc

    @staticmethod
    def uniforms(program, values):
        for name, value in values.items():
            if name in program:
                program[name].value = value

    def render(self, scene: SceneConfig, time, width, height, duration, logical_size=None):
        self.allocate(width, height)
        self.fbo.use()
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        background, wave, accent = scene_colors(scene)
        logical = logical_size or (width, height)
        common = {
            "uResolution": logical, "uRotation": math.radians(scene.rotation),
            "uScale": scene.scale, "uOffset": (scene.x, scene.y), "uWave": wave,
        }
        self.uniforms(self.wave, {
            **common, "uRasterSize": (width, height), "uBackground": background,
            "uAccent": accent, "uPhase": loop_angle(scene.speed, time, duration, 12),
            "uStyle": {"psp-classic": 0, "psp-original": 1, "ps3": 2}[scene.style],
            "uHeight": scene.height, "uWidth": scene.width, "uOverlap": scene.overlap,
            "uLayerMotion": scene.layer_motion, "uGlow": scene.glow,
        })
        self.screen.render(moderngl.TRIANGLES)
        if scene.style == "ps3" and scene.particle_count:
            key = (scene.particle_count, scene.seed)
            if key != self.particle_key:
                self.particle_buffer.write(particle_random(*key))
                self.particle_key = key
            self.uniforms(self.particle, {
                **common, "uPhase": loop_angle(scene.particle_speed, time, duration, 16),
                "uPixelScale": min(logical) / 720, "uSize": scene.particle_size,
            })
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)
            self.particles.render(moderngl.TRIANGLES, instances=scene.particle_count)
            self.ctx.disable(moderngl.BLEND)
        self.fbo.read_into(self.readback, components=4, alignment=1)
        pixels = self.readback.read()
        error = self.ctx.error
        if error != "GL_NO_ERROR":
            raise RuntimeError(f"GPU 렌더링 실패: {error}")
        return pixels

    def image(self, scene, time, width, height, duration, logical_size=None, format="JPEG"):
        pixels = self.render(scene, time, width, height, duration, logical_size)
        image = Image.frombytes("RGBA", (width, height), pixels, "raw", "RGBA", 0, -1).convert("RGB")
        stream = io.BytesIO()
        image.save(stream, format=format, **({"quality": 95, "subsampling": 0} if format == "JPEG" else {}))
        return stream.getvalue()

    def close(self):
        for item in (self.fbo, self.texture, self.readback, self.screen, self.particles,
                     self.screen_buffer, self.quad_buffer, self.particle_buffer,
                     self.wave, self.particle):
            if item:
                item.release()
        self.ctx.release()


class RenderService:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xmb-gpu")
        self.renderer = None
        self.error = None
        try:
            self.renderer = self.pool.submit(GpuRenderer).result()
            self.info = {"available": True, "device": self.renderer.device,
                         "max_size": self.renderer.max_size, "backend": "OpenGL / ModernGL"}
        except Exception as exc:  # noqa: BLE001 - Driver initialization failures must reach the UI.
            self.error = f"Python GPU 렌더러를 시작하지 못했습니다: {exc}"
            self.info = {"available": False, "device": None, "max_size": 0, "error": self.error}

    def submit(self, method, *args, **kwargs):
        if not self.renderer:
            raise RuntimeError(self.error)
        return self.pool.submit(getattr(self.renderer, method), *args, **kwargs)

    def close(self):
        if self.renderer:
            self.pool.submit(self.renderer.close).result()
        self.pool.shutdown(wait=True, cancel_futures=True)
