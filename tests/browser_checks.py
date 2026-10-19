"""Real WebGL/download checks. Run against a running local server (see docu/guide/cli_usage.md)."""

import argparse
import base64
import io
import json
import time
from pathlib import Path

import imageio_ffmpeg
import psutil
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test-results"


def set_number(page, key, value):
    page.locator(f"#{key}").fill(str(value))
    page.locator(f"#{key}").dispatch_event("change")


def set_range(page, key, value):
    page.locator(f"#{key}").evaluate("(el, value) => {el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}", value)


def inspect_video(path, expected_size, fps, duration):
    frames = imageio_ffmpeg.read_frames(str(path))
    metadata = next(frames)
    assert metadata["size"] == expected_size, metadata
    assert metadata["fps"] == fps, metadata
    assert metadata["codec"] == "h264", metadata
    count = 0
    first = None
    for frame in frames:
        if first is None:
            first = Image.frombytes("RGB", metadata["size"], frame)
        count += 1
    assert count == duration * fps, (count, duration * fps)
    assert abs(metadata["duration"] - duration) < .01
    return first, metadata


def check_browser(playwright, channel, url):
    print(f"[{channel}] starting", flush=True)
    browser = playwright.chromium.launch(channel=channel, headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    external = []
    errors = []

    def route_request(route):
        if route.request.url.startswith(url) or route.request.url.startswith("data:"):
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    context.route("**/*", route_request)
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(url)
    page.wait_for_function("!!window.studio")
    assert not page.locator("#fatal-error").is_visible()
    assert page.locator("#device option").count() == 33
    assert page.evaluate("() => {const ids=[...document.querySelectorAll('[id]')].map(el=>el.id);return new Set(ids).size===ids.length;}")
    page.locator("#play").click()
    page.screenshot(path=str(RESULTS / f"dashboard-{channel}.png"))

    # Full-resolution render math: closure, animation, zero speeds and rotation.
    checks = page.evaluate("""async () => {
      const {WaveRenderer}=await import('/static/js/renderer.js');
      const {DEFAULT_SCENE,loopState}=await import('/static/js/scene.js');
      const r=new WaveRenderer();const results=[];
      for(const style of ['psp-classic','psp-original','ps3']) {
        for(const rotation of [0,45,90]) {
          for(const size of [{width:256,height:144},{width:144,height:256},{width:192,height:192}]) {
            const c={...DEFAULT_SCENE,style,rotation};
            r.renderAt(c,0,size,7);const a=r.readPixels().slice();
            r.renderAt(c,7,size,7);const b=r.readPixels().slice();
            let endpoint=0;for(let i=0;i<a.length;i++)endpoint=Math.max(endpoint,Math.abs(a[i]-b[i]));
            r.renderAt(c,2.1,size,7);const mid=r.readPixels().slice();
            let movement=0;for(let i=0;i<a.length;i++)movement+=Math.abs(a[i]-mid[i]);
            // Symmetric one-frame steps around t=0 test velocity continuity as well as position.
            r.renderAt(c,1/60,size,7);const after=r.readPixels().slice();
            r.renderAt(c,7-1/60,size,7);const before=r.readPixels().slice();
            let jerk=0;for(let i=0;i<a.length;i++)jerk+=Math.abs(after[i]+before[i]-2*a[i]);
            results.push({style,rotation,...size,endpoint,movement:movement/a.length,jerk:jerk/a.length});
          }
        }
      }
      const c={...DEFAULT_SCENE,speed:0,particle_speed:0};
      r.renderAt(c,0,{width:128,height:128},10);const a=r.readPixels().slice();
      r.renderAt(c,4,{width:128,height:128},10);const b=r.readPixels().slice();
      const stopped=a.every((value,index)=>value===b[index]);
      const positive=loopState({...c,speed:.01,particle_speed:.01},0,1);
      r.dispose();return {results,stopped,positive};
    }""")
    assert all(item["endpoint"] == 0 for item in checks["results"]), checks
    assert all(item["movement"] > .05 for item in checks["results"]), checks
    assert all(item["jerk"] < 3 for item in checks["results"]), checks
    assert checks["stopped"]
    assert checks["positive"]["waveSpeed"] > 0 and checks["positive"]["particleSpeed"] > 0
    (RESULTS / f"render-checks-{channel}.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(f"[{channel}] 27 render/rotation/aspect loop checks passed", flush=True)

    # Reference video motion is predominantly rightward transport, not fixed
    # control points bobbing up and down. Compare translated GPU light profiles.
    motion = page.evaluate("""async()=>{
      const {WaveRenderer}=await import('/static/js/renderer.js');
      const data=await (await fetch('/api/presets')).json();
      const c={...data.styles.find(s=>s.id==='ps3').defaults,color:'#672286',
        background_color:'#000000',particle_count:0};
      const r=new WaveRenderer();
      function profile(time,speed=1){
        r.renderAt({...c,speed},time,{width:800,height:450},12);
        const p=r.readPixels(),a=new Float64Array(800);let mass=0,ys=0;
        for(let y=0;y<450;y++)for(let x=0;x<800;x++){
          const i=(y*800+x)*4,v=p[i]+p[i+1]+p[i+2];
          a[x]+=v;mass+=v;ys+=y*v;
        }
        return {a,cy:ys/mass/450};
      }
      function match(a,b){
        let best={shift:0,error:Infinity};
        for(let shift=-90;shift<=90;shift++){
          let error=0;
          for(let x=100;x<700;x++){const d=b[x]-a[x-shift];error+=d*d;}
          error/=600;if(error<best.error)best={shift,error};
        }
        const energy=a.reduce((s,v)=>s+v*v,0)/800;
        return {...best,relativeError:best.error/energy};
      }
      const phases=[];
      for(const time of [0,2,4,6]){
        const a=profile(time),b=profile(time+.5);
        phases.push({time,...match(a.a,b.a),cy:a.cy});
      }
      const doubled=match(profile(0,2).a,profile(.5,2).a);
      r.dispose();return {phases,doubled};
    }""")
    assert all(30 <= p["shift"] <= 50 and p["relativeError"] < .001 for p in motion["phases"]), motion
    assert all(.38 < p["cy"] < .64 for p in motion["phases"]), motion
    assert abs(motion["doubled"]["shift"] - 2 * motion["phases"][0]["shift"]) <= 4, motion
    (RESULTS / f"wave-motion-{channel}.json").write_text(json.dumps(motion, indent=2), encoding="utf-8")
    print(f"[{channel}] rightward transport, reference-scale speed and speed control passed", flush=True)

    # A neutral palette must remain neutral in each style, including the new hue mapping.
    neutral = page.evaluate("""async()=>{
      const {WaveRenderer}=await import('/static/js/renderer.js');
      const {DEFAULT_SCENE}=await import('/static/js/scene.js');
      const r=new WaveRenderer();const differences={};
      for(const style of ['psp-classic','psp-original','ps3']) {
        r.renderAt({...DEFAULT_SCENE,style,color:'#808080',particle_count:0},0,{width:320,height:180},10);
        const p=r.readPixels();let largest=0;
        for(let i=0;i<p.length;i+=4)largest=Math.max(largest,Math.abs(p[i]-p[i+1]),Math.abs(p[i+1]-p[i+2]));
        differences[style]=largest;
      }
      r.dispose();return differences;
    }""")
    assert all(value <= 1 for value in neutral.values()), neutral

    # Observe neutral light at crossings and the narrow rounded roll on Classic.
    # Decode sRGB first: brightness alone must not masquerade as desaturation.
    lighting = page.evaluate("""async()=>{
      const {WaveRenderer}=await import('/static/js/renderer.js');
      const data=await (await fetch('/api/presets')).json();
      const r=new WaveRenderer();const phases=[];
      const linear=c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4;
      const sample=(p,i)=>{
        const hi=Math.max(p[i],p[i+1],p[i+2]),lo=Math.min(p[i],p[i+1],p[i+2]);
        return {brightness:hi,saturation:1-linear(lo/255)/linear(hi/255)};
      };
      const topMean=values=>{
        values.sort((a,b)=>a.brightness-b.brightness);
        const top=values.slice(Math.floor(values.length*.9));
        return {brightness:top.reduce((s,p)=>s+p.brightness,0)/top.length,
                saturation:top.reduce((s,p)=>s+p.saturation,0)/top.length};
      };
      const config={...data.styles.find(s=>s.id==='ps3').defaults,
        color:'#672286',background_color:'#000000',particle_count:0};
      let patches;
      for(const time of [0,2.5,5,7.5]) {
        r.renderAt(config,time,{width:876,height:345},10);
        const p=r.readPixels(),values=[];
        for(let i=0;i<p.length;i+=4){const v=sample(p,i);if(v.brightness>40)values.push(v);}
        values.sort((a,b)=>a.brightness-b.brightness);
        const mean=(lo,hi)=>{
          const a=values.slice(Math.floor(values.length*lo),Math.floor(values.length*hi));
          return a.reduce((s,p)=>s+p.saturation,0)/a.length;
        };
        phases.push({time,body:mean(.15,.35),highlight:mean(.95,.995)});
        if(time===0){
          const patch=(x0,y0,x1,y1)=>{
            const a=[];
            for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
              const v=sample(p,((344-y)*876+x)*4);if(v.brightness>40)a.push(v);
            }
            return topMean(a);
          };
          patches={single:patch(30,208,90,214),crossing:patch(420,145,465,162)};
        }
      }
      const classic={...data.styles.find(s=>s.id==='psp-classic').defaults,
        color:'#084acc',wave_color:'#0949d0',background_color:'#000000',particle_count:0};
      r.renderAt(classic,0,{width:869,height:482},10);
      const pixels=r.readPixels().slice();const red=y=>pixels[((481-y)*869+100)*4];
      let peak=305;for(let y=306;y<366;y++)if(red(y)>red(peak))peak=y;
      const value=red(peak);
      const halfWidth=Array.from({length:61},(_,i)=>red(peak-30+i)).filter(v=>v>=value*.5).length;
      const crease={peak,value,halfWidth,above:red(peak-4),below:red(peak+4),far:red(peak+15)};
      r.renderAt({...classic,glow:0},0,{width:869,height:482},10);
      crease.unlit=r.readPixels()[((481-peak)*869+100)*4];
      r.dispose();return {phases,patches,crease};
    }""")
    assert all(p["highlight"] < p["body"] - .15 for p in lighting["phases"]), lighting
    assert lighting["patches"]["crossing"]["brightness"] > lighting["patches"]["single"]["brightness"] * 1.3, lighting
    assert lighting["patches"]["crossing"]["saturation"] < lighting["patches"]["single"]["saturation"] - .15, lighting
    crease = lighting["crease"]
    assert crease["value"] > 40 and 1 < crease["halfWidth"] < 12, lighting
    assert crease["below"] > crease["above"] + 5 and crease["far"] < crease["value"] * .4, lighting
    assert crease["unlit"] < 10, lighting
    (RESULTS / f"wave-lighting-{channel}.json").write_text(json.dumps(lighting, indent=2), encoding="utf-8")
    print(f"[{channel}] white crossings and thin rounded Classic highlights passed", flush=True)

    # Observe the rendered light footprint, rather than only inspecting size uniforms.
    particles = page.evaluate("""async()=>{
      const {WaveRenderer}=await import('/static/js/renderer.js');
      const {DEFAULT_SCENE}=await import('/static/js/scene.js');
      const r=new WaveRenderer();
      // Centre the probe independently of the PS3 particle path's mean height.
      const config={...DEFAULT_SCENE,y:.025,particle_count:1,particle_speed:0,glow:0,background_color:'#000000'};
      function measure(size,depth){
        const c={...config,particle_size:size};
        r.renderAt(c,0,{width:720,height:720},10);
        const random=r.particleGeometry.attributes.aRandom;
        random.array.set([.5,.75,.5,.6]);random.needsUpdate=true;
        const d=r.particleGeometry.attributes.aDepth;
        d.array.set([depth,.5]);d.needsUpdate=true;
        r.renderAt(c,0,{width:720,height:720},10);
        const pixels=r.readPixels();let area=0,peak=0,sum=0,xSum=0,ySum=0;
        for(let i=0;i<pixels.length;i+=4){
          const value=Math.max(pixels[i],pixels[i+1],pixels[i+2]);
          peak=Math.max(peak,value);
          if(value>5){area++;sum+=value;xSum+=(i/4%720)*value;ySum+=Math.floor(i/4/720)*value;}
        }
        return {area,peak,cx:xSum/sum,cy:ySum/sum,count:r.particleGeometry.instanceCount};
      }
      const sharp=measure(2,.1),large=measure(4,.1),soft=measure(2,1);
      r.dispose();return {sharp,large,soft};
    }""")
    assert particles["large"]["area"] > particles["sharp"]["area"] * 2, particles
    assert particles["soft"]["area"] > particles["sharp"]["area"] * 2, particles
    assert particles["sharp"]["peak"] > particles["soft"]["peak"], particles
    assert all(item["count"] == 1 for item in particles.values()), particles
    assert abs(particles["sharp"]["cx"] - particles["large"]["cx"]) < 1, particles
    (RESULTS / f"particle-focus-{channel}.json").write_text(json.dumps(particles, indent=2), encoding="utf-8")

    set_range(page, "particle_size", 2.25)
    page.reload()
    page.wait_for_function("!!window.studio")
    assert page.evaluate("window.studio.scene.particle_size") == 2.25
    assert page.locator("#particle_size").input_value() == "2.25"

    # Old stored settings get the revised untouched defaults, while actual edits survive.
    page.evaluate("""()=>{
      localStorage.setItem('xmb-wave-studio-v1',JSON.stringify({scene:{
        style:'psp-classic',color:'#7958b6',background_color:null,wave_color:null,
        speed:1,rotation:90,height:.45,width:1.5,overlap:.6,x:0,y:0,scale:1,
        glow:.8,particle_count:180,particle_speed:1,seed:2026
      },output:window.studio.output}));
    }""")
    page.reload()
    page.wait_for_function("!!window.studio")
    migrated = page.evaluate("window.studio.scene")
    assert migrated["height"] == .6 and migrated["overlap"] == .8, migrated
    assert migrated["particle_count"] == 0 and migrated["particle_size"] == 1, migrated
    assert migrated["rotation"] == 90 and migrated["width"] == 1.5, migrated
    assert migrated["color"] == "#7958b6", migrated
    print(f"[{channel}] sharp/soft particle footprints, size and settings migration passed", flush=True)

    # Form behavior, persistence, model sizes and independent shape/output controls.
    page.locator("#device").select_option("iphone16")
    assert page.locator("#width").input_value() == "1179"
    assert "1180" in page.locator("#output-summary").text_content()
    assert page.locator("#device-source").is_visible()
    set_range(page, "rotation", 90)
    page.locator('[data-style="psp-classic"]').click()
    assert page.evaluate("window.studio.scene.rotation") == 90
    assert not page.locator("#particles-section").is_visible()
    page.locator("#advanced summary").click()
    set_range(page, "scene-width", 1.5)
    assert page.locator("#width").input_value() == "1179"
    assert page.evaluate("window.studio.scene.width") == 1.5
    page.reload()
    page.wait_for_function("!!window.studio")
    assert page.evaluate("window.studio.scene.rotation") == 90
    assert page.evaluate("window.studio.scene.width") == 1.5
    page.locator('[data-style="ps3"]').click()
    page.locator("#advanced summary").click()
    page.locator("#reset").click()
    # Pause after a reload regardless of the initial prefers-reduced-motion setting.
    if page.locator("#play").get_attribute("aria-label") == "일시정지":
        page.locator("#play").click()
    set_number(page, "width", 127)
    set_number(page, "height", 129)
    set_number(page, "duration", 1)
    set_range(page, "timeline", 0)
    page.wait_for_timeout(100)

    with page.expect_download() as info:
        page.locator("#save-image").click()
    jpeg = RESULTS / f"sample-{channel}.jpg"
    info.value.save_as(str(jpeg))
    assert Image.open(jpeg).size == (127, 129)
    page.wait_for_function("!window.studio.busy")
    # Matching full-resolution reference from the same common renderer.
    reference_url = page.evaluate("""async()=>{
      const {WaveRenderer}=await import('/static/js/renderer.js');const r=new WaveRenderer();
      r.renderAt(window.studio.scene,0,window.studio.output,1);
      const data=r.canvas.toDataURL('image/png');r.dispose();return data;
    }""")
    reference = Image.open(io.BytesIO(base64.b64decode(reference_url.split(",")[1]))).convert("RGB")
    jpeg_difference = ImageStat.Stat(ImageChops.difference(reference, Image.open(jpeg).convert("RGB"))).mean
    assert max(jpeg_difference) < 3, jpeg_difference

    for style, fps in [("psp-classic", 30), ("psp-original", 60), ("ps3", 30)]:
        page.locator(f'[data-style="{style}"]').click()
        page.locator("#fps").select_option(str(fps))
        with page.expect_download(timeout=90000) as info:
            page.locator("#save-video").click()
        destination = RESULTS / f"{style}-{channel}-{fps}.mp4"
        info.value.save_as(str(destination))
        first, _ = inspect_video(destination, (128, 130), fps, 1)
        page.wait_for_function("!window.studio.busy")
        assert page.locator("#download-video").is_visible()
        if style == "ps3":
            difference = ImageStat.Stat(ImageChops.difference(reference, first.crop((0, 0, 127, 129)))).mean
            assert max(difference) < 8, difference
    print(f"[{channel}] JPEG and all 3 MP4 styles decoded correctly", flush=True)

    # Cancel a long job through the UI and verify the next job isn't blocked.
    set_number(page, "duration", 600)
    with page.expect_response(lambda response: response.url.endswith('/api/exports') and response.request.method == 'POST') as info:
        page.locator("#save-video").click()
    job_id = info.value.json()["id"]
    page.wait_for_function("window.studio.busy")
    page.locator("#cancel-export").click()
    page.wait_for_function("!window.studio.busy")
    assert context.request.get(f"{url}/api/exports/{job_id}").json()["status"] == "cancelled"
    assert page.locator("#save-video").is_enabled()

    # Abrupt tab close mid-frame must also reclaim the server job.
    with page.expect_response(lambda response: response.url.endswith('/api/exports') and response.request.method == 'POST') as info:
        page.locator("#save-video").click()
    job_id = info.value.json()["id"]
    page.wait_for_timeout(200)
    page.close()
    for _ in range(100):
        state = context.request.get(f"{url}/api/exports/{job_id}").json()
        if state["status"] not in {"ready", "rendering", "encoding"}:
            break
        time.sleep(.03)
    assert state["error_code"] == "connection_lost", state
    assert not external, external
    assert not errors, errors
    context.close()
    browser.close()
    print(f"[{channel}] cancellation, tab close and offline checks passed", flush=True)


def long_export(playwright, url):
    print("[long] real browser 600s x 30fps, 32x32 export", flush=True)
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(accept_downloads=True)
    page.goto(url)
    page.wait_for_function("!!window.studio")
    for key, value in [("width", 32), ("height", 32), ("duration", 600)]:
        set_number(page, key, value)
    server_memory = []
    cdp = page.context.new_cdp_session(page)
    browser_cdp = browser.new_browser_cdp_session()
    started = time.monotonic()
    with page.expect_response(lambda r: r.url.endswith('/api/exports') and r.request.method == 'POST') as info:
        page.locator("#save-video").click()
    job_id = info.value.json()["id"]
    with page.expect_download(timeout=900000) as download_info:
        while page.evaluate("window.studio.busy"):
            page.wait_for_timeout(1000)
            state = page.request.get(f"{url}/api/exports/{job_id}").json()
            memory = 0
            for process in psutil.process_iter(["name", "cmdline", "memory_info"]):
                try:
                    arguments = process.info["cmdline"] or []
                    # Match Python argv, not a PowerShell script containing the command text.
                    is_server = any(arg == "-m" and arguments[index+1:index+2] == ["xmbwavestudio"]
                                    for index, arg in enumerate(arguments))
                    if (is_server or 'ffmpeg' in process.info["name"].lower()):
                        memory += process.info["memory_info"].rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            heap = cdp.send("Runtime.getHeapUsage")
            browser_rss = 0
            for process in browser_cdp.send("SystemInfo.getProcessInfo")["processInfo"]:
                try:
                    browser_rss += psutil.Process(process["id"]).memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            server_memory.append({"frames": state["frames"], "rss": memory,
                                  "browser_rss": browser_rss, "js_heap": heap["usedSize"]})
            if len(server_memory) % 10 == 0:
                print(f"[long] {state['frames']}/18000 frames, {memory/1024**2:.1f} MiB server+encoder", flush=True)
            if state["status"] == "error":
                raise AssertionError(state)
    destination = RESULTS / "long-600s.mp4"
    download_info.value.save_as(str(destination))
    inspect_video(destination, (32, 32), 30, 600)
    samples = [sample["rss"] for sample in server_memory[3:]]
    if samples:
        assert max(samples) - min(samples) < 100 * 1024**2, server_memory
    browser_samples = [sample["browser_rss"] for sample in server_memory[3:]]
    heap_samples = [sample["js_heap"] for sample in server_memory[3:]]
    if browser_samples:
        assert max(browser_samples) - min(browser_samples) < 150 * 1024**2, server_memory
        assert max(heap_samples) - min(heap_samples) < 64 * 1024**2, server_memory
    (RESULTS / "long-export-memory.json").write_text(json.dumps({
        "seconds": time.monotonic()-started, "samples": server_memory,
        "frames": 18000, "video_duration": 600,
    }, indent=2), encoding="utf-8")
    browser.close()
    print("[long] 18,000 frames decoded, 600 seconds, bounded memory passed", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--browser", choices=["both", "chrome", "msedge"], default="both")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        for channel in (["msedge", "chrome"] if args.browser == "both" else [args.browser]):
            check_browser(playwright, channel, args.url)
        if args.long:
            long_export(playwright, args.url)


if __name__ == "__main__":
    main()
