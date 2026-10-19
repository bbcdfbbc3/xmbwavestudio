"""Native GPU regression checks, independent of the browser and encoder."""

import io
import math

import numpy as np
import pytest
from PIL import Image

from xmbwavestudio.models import STYLE_PRESETS, SceneConfig
from xmbwavestudio.rendering import SHADERS, GpuRenderer, loop_angle


@pytest.fixture(scope="module")
def renderer():
    renderer = GpuRenderer()
    yield renderer
    renderer.close()


@pytest.mark.parametrize("style", ["psp-classic", "psp-original", "ps3"])
@pytest.mark.parametrize("rotation", [0, 45, 90])
@pytest.mark.parametrize("size", [(256, 144), (144, 256), (192, 192)])
def test_scene_closure_and_animation(renderer, style, rotation, size):
    defaults = next(p["defaults"] for p in STYLE_PRESETS if p["id"] == style)
    scene = SceneConfig(**{**defaults, "rotation": rotation})
    first = renderer.render(scene, 0, *size, 10)
    assert renderer.render(scene, 10, *size, 10) == first
    assert renderer.render(scene, 2.1, *size, 10) != first
    stopped = scene.model_copy(update={"speed": 0, "particle_speed": 0})
    assert renderer.render(stopped, 0, *size, 10) == renderer.render(stopped, 4, *size, 10)


@pytest.mark.parametrize("strength", [0, 1, 2])
@pytest.mark.parametrize("duration", [1, 10, 12])
@pytest.mark.parametrize("fps", [30, 60])
def test_layer_loop_boundary(renderer, strength, duration, fps):
    scene = SceneConfig(layer_motion=strength)
    first = np.frombuffer(renderer.render(scene, 0, 256, 144, duration), np.uint8).astype(float)
    end = np.frombuffer(renderer.render(scene, duration, 256, 144, duration), np.uint8)
    assert np.array_equal(first, end)
    after = np.frombuffer(renderer.render(scene, 1 / fps, 256, 144, duration), np.uint8)
    before = np.frombuffer(renderer.render(scene, duration - 1 / fps, 256, 144, duration), np.uint8)
    assert np.abs(after.astype(float) + before - 2 * first).mean() < 3


def test_closed_phase_nonzero_speed():
    assert loop_angle(0, 3, 10, 12) == 0
    assert loop_angle(.0001, 2.5, 10, 12) == math.pi / 2
    assert loop_angle(4, 10**10, 12, 12) == loop_angle(4, 10**10 % 12, 12, 12)


def test_preview_resolution_preserves_composition(renderer):
    scene = SceneConfig(rotation=45, particle_count=2000, particle_size=4)
    full = Image.open(io.BytesIO(renderer.image(scene, 2, 720, 1280, 10, format="PNG")))
    small = Image.open(io.BytesIO(renderer.image(
        scene, 2, 180, 320, 10, (720, 1280), "PNG",
    )))
    reduced = np.asarray(full.resize(small.size, Image.Resampling.LANCZOS)).astype(float)
    difference = np.abs(reduced - np.asarray(small))
    # Tiny, bright particles alias at quarter resolution; geometry and placement stay fixed.
    assert difference.mean() < 2 and np.percentile(difference, 90) <= 2


def test_particle_size_and_seed(renderer):
    scene = SceneConfig(particle_count=2000)
    base = renderer.render(scene, 2, 640, 360, 10)
    assert renderer.render(scene, 2, 640, 360, 10) == base
    assert renderer.render(scene.model_copy(update={"particle_size": 4}), 2, 640, 360, 10) != base
    assert renderer.render(scene.model_copy(update={"seed": 100}), 2, 640, 360, 10) != base


def test_real_layer_edges_stay_grouped(renderer):
    """Inspect production GPU edge functions in a frame moving with the common wave."""
    shader = renderer.wave
    screen = renderer.screen
    source = SHADERS
    fragment = (source / "wave.frag").read_text(encoding="utf-8")
    instrument = fragment[:fragment.rfind("void main() {")] + '''
        uniform int testLayer;
        uniform float testShift;
        vec2 packEdge(float edge) {
          float v=floor(clamp(edge*.5+.5,0.0,1.0)*65535.0+.5);
          return vec2(floor(v/256.0),mod(v,256.0))/255.0;
        }
        void main() {
          float x=(vUv.x-.5)*1.65/uWidth+testShift;
          vec3 e=ps3Layer(x,testLayer);
          fragColor=vec4(packEdge(e.x),packEdge(e.y));
        }
    '''
    program = renderer.ctx.program(vertex_shader=(source / "screen.vert").read_text(),
                                   fragment_shader=instrument)
    vao = renderer.ctx.vertex_array(program, [(renderer.screen_buffer, "2f", "position")])
    renderer.wave, renderer.screen = program, vao
    try:
        def edges(time, strength):
            program["testShift"] = (time / 12 * 2 * math.pi) / 3.687
            sheets = []
            for layer in range(4):
                program["testLayer"] = layer
                p = np.frombuffer(renderer.render(SceneConfig(
                    layer_motion=strength, speed=1, particle_count=0,
                ), time, 96, 1, 12), np.uint8).reshape(96, 4).astype(float)
                sheets.append(np.stack((p[:, 0] * 256 + p[:, 1],
                                        p[:, 2] * 256 + p[:, 3]), axis=1) / 65535 * 2 - 1)
            return np.array(sheets)

        for strength in [0, 1, 2]:
            initial = edges(0, strength)
            relative = width_change = 0
            for time in [1.5, 3, 4.5, 6, 7.5, 9, 10.5]:
                sample = edges(time, strength)
                gaps = sample.mean(axis=2) - sample.mean(axis=2)[0]
                start_gaps = initial.mean(axis=2) - initial.mean(axis=2)[0]
                relative = max(relative, np.abs(gaps - start_gaps).max())
                width_change = max(width_change, np.abs(np.diff(sample) - np.diff(initial)).max())
                assert np.ptp(sample, axis=(0, 2)).max() < .32
            if strength == 0:
                assert relative < .00015 and width_change < .00015
            else:
                assert .004 < relative < .2 and width_change > .0005
    finally:
        renderer.wave, renderer.screen = shader, screen
        vao.release()
        program.release()
