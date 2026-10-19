"""Real Edge/Chrome viewer, GPU exports and bounded-memory checks against a local server."""

import argparse
import json
import time
from pathlib import Path

import imageio_ffmpeg
import psutil
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test-results" / "python-gpu"


def set_number(page, key, value):
    page.locator(f"#{key}").fill(str(value))
    page.locator(f"#{key}").dispatch_event("change")


def set_range(page, key, value):
    page.locator(f"#{key}").evaluate(
        "(el,v)=>{el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));}", value,
    )


def inspect_video(path, size, fps, duration):
    frames = imageio_ffmpeg.read_frames(str(path))
    metadata = next(frames)
    assert metadata["size"] == size and metadata["fps"] == fps, metadata
    assert metadata["codec"] == "h264" and abs(metadata["duration"] - duration) < .01
    assert "bt709/bt709/iec61966-2-1" in metadata["pix_fmt"]
    assert sum(1 for _ in frames) == fps * duration
    return metadata


def wait_preview(page):
    page.wait_for_function("window.studio && !studio.renderer.pending && studio.renderer.displayedTime===studio.time")


def make_video(page, path):
    start = time.perf_counter()
    with page.expect_download(timeout=120000) as pending:
        page.locator("#save-video").click()
        page.wait_for_function("studio.busy")
        assert page.locator("#layer_motion").is_disabled()
        assert page.locator("#particle_size").is_disabled()
    pending.value.save_as(path)
    page.wait_for_function("!studio.busy")
    return time.perf_counter() - start


def check_browser(playwright, channel, url):
    browser = playwright.chromium.launch(channel=channel, headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    external, errors, raw_frame_uploads = [], [], []

    def route_request(route):
        if route.request.url.startswith(url):
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    context.route("**/*", route_request)
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda message: print(f"[{channel}] {message.text}", flush=True)
            if message.type == "error" else None)

    def socket_created(socket):
        sent = []
        if socket.url.endswith('/api/preview'):
            socket.on('framesent', lambda payload: sent.__setitem__(slice(None), [payload]))
            socket.on('framereceived', lambda payload: print(f'Preview error: {payload}; request={sent}', flush=True)
                      if isinstance(payload, str) else None)
        socket.on("framesent", lambda payload: raw_frame_uploads.append(len(payload))
                  if isinstance(payload, bytes) else None)
    page.on("websocket", socket_created)
    # Prove the dashboard does not need browser WebGL, even for final exports.
    page.add_init_script("""(() => {
        const original=HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext=function(type,...args){
            if(type.startsWith('webgl')) throw new Error('Browser WebGL must not be used');
            return original.call(this,type,...args);
        };
    })();""")
    page.goto(url)
    page.wait_for_function("!!window.studio")
    page.locator("#play").click()
    wait_preview(page)
    assert "PYTHON GPU" in page.locator("#gpu-status").inner_text()
    assert page.locator("#device option").count() == 33
    assert not page.locator("#fatal-error").is_visible()
    page.screenshot(path=str(RESULTS / f"dashboard-{channel}.png"))

    page.locator("#layer_motion").evaluate("el=>el.closest('details').open=true")
    set_range(page, "layer_motion", 1.65)
    set_range(page, "particle_size", 2.5)
    set_number(page, "width", 127)
    set_number(page, "height", 129)
    page.reload()
    page.wait_for_function("!!window.studio")
    if page.locator("#play").get_attribute("aria-label") == "일시정지":
        page.locator("#play").click()
    wait_preview(page)
    assert page.evaluate("studio.scene.layer_motion") == 1.65
    assert page.evaluate("studio.scene.particle_size") == 2.5
    page.locator("#timeline").evaluate("el=>{el.value=2.5;el.dispatchEvent(new Event('input'));}")
    wait_preview(page)
    with page.expect_download() as pending:
        page.locator("#save-image").click()
    pending.value.save_as(RESULTS / f"image-{channel}.jpg")
    assert Image.open(RESULTS / f"image-{channel}.jpg").size == (127, 129)
    page.wait_for_function("!studio.busy")
    # JPEG endpoint and the displayed preview use the same frozen scene/time.
    body = page.evaluate("({scene:studio.scene,output:studio.output,time:studio.time})")
    expected = context.request.post(url + "/api/images", data=body)
    assert expected.status == 200
    assert (RESULTS / f"image-{channel}.jpg").read_bytes() == expected.body()

    set_number(page, "duration", 1)
    page.locator("#advanced").evaluate("el=>el.open=true")
    timings = {}
    for style in ["psp-classic", "psp-original", "ps3"]:
        page.locator(f'[data-style="{style}"]').click()
        assert page.locator("#layer-motion-control").is_visible() == (style == "ps3")
        path = RESULTS / f"{style}-{channel}.mp4"
        timings[style] = make_video(page, path)
        inspect_video(path, (128, 130), 30, 1)

    # Actual-size performance, including POST, status subscription, encoding and download.
    set_number(page, "width", 1080)
    set_number(page, "height", 1920)
    set_number(page, "duration", 10)
    page.locator("#reset").click()
    path = RESULTS / f"1080x1920-{channel}.mp4"
    timings["1080x1920_10s"] = make_video(page, path)
    inspect_video(path, (1080, 1920), 30, 10)

    set_number(page, "duration", 3600)
    page.locator("#save-video").click()
    page.wait_for_function("studio.busy")
    page.locator("#cancel-export").click()
    page.wait_for_function("!studio.busy", timeout=15000)
    assert "취소" in page.locator("#job-label").inner_text()
    # A tab closing/reloading cancels the native worker, even though it renders independently.
    page.locator("#save-video").click()
    page.wait_for_function("studio.busy")
    page.wait_for_function("document.querySelector('#job-details').textContent.includes('프레임')")
    page.close(run_before_unload=False)
    for _ in range(100):
        probe = context.request.post(url + "/api/exports", data={"scene": body["scene"], "output": {
            **body["output"], "width": 32, "height": 32, "duration": 1,
        }})
        if probe.status == 201:
            context.request.delete(url + "/api/exports/" + probe.json()["id"])
            break
        time.sleep(.05)
    assert probe.status == 201, probe.text()
    assert not external and not errors and not raw_frame_uploads, (external, errors, raw_frame_uploads)
    result = {"browser": channel, "seconds": timings, "browser_binary_uploads": 0,
              "gpu": context.request.get(url + "/api/presets").json()["gpu"]}
    (RESULTS / f"browser-{channel}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    context.close()
    browser.close()


def long_export(playwright, channel, url):
    browser = playwright.chromium.launch(channel=channel, headless=True)
    page = browser.new_page(accept_downloads=True)
    page.goto(url)
    page.wait_for_function("!!window.studio")
    set_number(page, "width", 32)
    set_number(page, "height", 32)
    set_number(page, "duration", 600)
    rows = []
    start = time.monotonic()
    with page.expect_download(timeout=180000) as pending:
        page.locator("#save-video").click()
        page.wait_for_function("studio.busy")
        while page.evaluate("studio.busy"):
            server_memory = 0
            for process in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
                try:
                    cmd = " ".join(process.info["cmdline"] or [])
                    name = (process.info["name"] or "").lower()
                    if "ffmpeg" in name or ("python" in name and "-m xmbwavestudio" in cmd):
                        server_memory += process.info["memory_info"].rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            rows.append({"time": time.monotonic() - start, "rss": server_memory})
            page.wait_for_timeout(100)
    path = RESULTS / "600s-18000frames.mp4"
    pending.value.save_as(path)
    inspect_video(path, (32, 32), 30, 600)
    settled = [row["rss"] for row in rows if row["time"] > 1]
    assert not settled or max(settled) - min(settled) < 128 * 1024**2
    result = {"seconds": time.monotonic() - start, "samples": rows}
    (RESULTS / "long-memory.json").write_text(json.dumps(result), encoding="utf-8")
    print(f"600s/18000 frames passed, {result['seconds']:.2f}s", flush=True)
    browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--browser", choices=["chrome", "msedge", "all"], default="all")
    parser.add_argument("--long", action="store_true")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        for channel in ["chrome", "msedge"] if args.browser == "all" else [args.browser]:
            check_browser(playwright, channel, args.url)
        if args.long:
            long_export(playwright, "chrome" if args.browser == "all" else args.browser, args.url)


if __name__ == "__main__":
    main()
