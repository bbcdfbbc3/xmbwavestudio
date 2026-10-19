import {WaveRenderer} from './renderer.js';
import {DEFAULT_SCENE, DEFAULT_OUTPUT, PRESET_REVISION, migrateScene, loopState, encodedSize, frameCount, aspectLabel} from './scene.js';
import {VideoExport, api, makeJpeg, download} from './export-client.js';

const $ = (id) => document.getElementById(id);
const STORAGE_KEY = 'xmb-wave-studio-v1';
const ranges = [
  ['height', '물결 높이', 0, 2, 0.01], ['width', '물결 폭', 0.25, 3, 0.01],
  ['overlap', '겹침', 0, 1, 0.01], ['scale', '전체 크기', 0.25, 3, 0.01],
  ['x', '가로 위치', -1, 1, 0.01], ['y', '세로 위치', -1, 1, 0.01],
  ['glow', '빛 강도', 0, 3, 0.01],
];
let scene = {...DEFAULT_SCENE};
let output = {...DEFAULT_OUTPUT};
let presets;
let renderer;
let playing = !matchMedia('(prefers-reduced-motion: reduce)').matches;
let currentTime = 0;
let clockStart = performance.now();
let clockOffset = 0;
let busy = false;
let activeExport = null;
let dirty = true;
let previewSize = {width: 360, height: 640};
let toastTimer;
let quality = 720;
let animationId;

function notify(message, error = false) {
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 10000 : 4500);
}

function fatal(error) {
  $('fatal-message').textContent = `${error.message} Edge 또는 Chrome의 하드웨어 가속이 켜져 있는지 확인해 주세요.`;
  $('fatal-error').hidden = false;
  $('loading').hidden = true;
  cancelAnimationFrame(animationId);
}

function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({scene, output, quality, revision: PRESET_REVISION})); }
  catch { /* Storage can be unavailable in restricted browser profiles. */ }
}

function restore() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!stored) return;
    const defaults = presets.styles.find((style) => style.id === stored.scene?.style)?.defaults || DEFAULT_SCENE;
    const restoredScene = migrateScene(stored.scene || {}, defaults, stored.revision);
    for (const key of Object.keys(DEFAULT_SCENE)) {
      if (restoredScene[key] !== undefined) scene[key] = restoredScene[key];
    }
    if (!presets.styles.some((style) => style.id === scene.style)) scene.style = 'ps3';
    for (const key of ['color', 'background_color', 'wave_color']) {
      if (scene[key] !== null && !/^#[a-f\d]{6}$/i.test(scene[key])) scene[key] = DEFAULT_SCENE[key];
    }
    for (const key of Object.keys(DEFAULT_SCENE).filter((key) => typeof DEFAULT_SCENE[key] === 'number')) {
      if (!Number.isFinite(scene[key])) scene[key] = DEFAULT_SCENE[key];
    }
    for (const key of ['width', 'height', 'duration', 'fps']) {
      if (Number.isSafeInteger(stored.output?.[key]) && stored.output[key] >= 1) output[key] = stored.output[key];
    }
    if (![30, 60].includes(output.fps)) output.fps = 30;
    if ([320, 480, 720].includes(stored.quality)) quality = stored.quality;
    frameCount(output);
  } catch { scene = {...DEFAULT_SCENE}; output = {...DEFAULT_OUTPUT}; }
}

function timeLabel(seconds, decimal = false) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const rest = (decimal ? (seconds % 60).toFixed(1) : Math.floor(seconds % 60).toString()).padStart(decimal ? 4 : 2, '0');
  return `${minutes}:${rest}`;
}

function rangeFill(input) {
  const value = (+input.value - +input.min) / (+input.max - +input.min) * 100;
  input.style.setProperty('--fill', `${value}%`);
}

function refreshScene() {
  document.querySelectorAll('[data-scene]').forEach((input) => {
    const key = input.dataset.scene;
    scene[key] = Math.max(+input.min, Math.min(+input.max, Number(scene[key])));
    input.value = scene[key];
    rangeFill(input);
    const suffix = key === 'rotation' ? '°' : key === 'particle_count' ? '' : '×';
    $(`${input.id}-value`).value = `${key === 'particle_count' || key === 'rotation' ? scene[key] : scene[key].toFixed(2)}${suffix}`;
  });
  $('color').value = scene.color;
  $('color-hex').value = scene.color.toUpperCase();
  document.querySelectorAll('.swatch').forEach((button) => {
    const active = button.dataset.color.toLowerCase() === scene.color.toLowerCase();
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active);
  });
  document.querySelectorAll('.style-card').forEach((button) => {
    const active = button.dataset.style === scene.style;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active);
  });
  document.querySelectorAll('[data-angle]').forEach((button) => button.classList.toggle('active', +button.dataset.angle === scene.rotation));
  $('particles-section').hidden = scene.style !== 'ps3';
  $('preview-style').textContent = presets.styles.find((style) => style.id === scene.style).name;
  for (const key of ['background', 'wave']) {
    $(`${key}-override`).checked = scene[`${key}_color`] !== null;
    $(`${key}-color`).disabled = scene[`${key}_color`] === null || busy;
    if (scene[`${key}_color`]) $(`${key}-color`).value = scene[`${key}_color`];
  }
  refreshLoop();
  dirty = true;
}

function refreshLoop() {
  const loop = loopState(scene, 0, output.duration);
  $('loop-info').textContent = `요청 ${scene.speed.toFixed(2)}× → 반복 적용 ${loop.waveSpeed.toFixed(2)}× · ${output.duration}초에 ${loop.waveCycles}회`;
  $('particle-loop-info').textContent = `요청 ${scene.particle_speed.toFixed(2)}× → 반복 적용 ${loop.particleSpeed.toFixed(2)}×`;
}

function resizePreview() {
  if (!renderer) return;
  const bounds = $('stage').getBoundingClientRect();
  const widthRoom = Math.max(30, bounds.width - 94);
  const heightRoom = Math.max(30, bounds.height - 68);
  const factor = Math.min(widthRoom / output.width, heightRoom / output.height);
  const width = Math.max(1, Math.round(output.width * factor));
  const height = Math.max(1, Math.round(output.height * factor));
  $('canvas-surround').style.width = `${width}px`;
  $('canvas-surround').style.height = `${height}px`;
  // Preserve the output aspect in shader coordinates regardless of preview quality.
  const pixelFactor = Math.min(quality / Math.min(output.width, output.height),
    Math.min(renderer.maxSize / output.width, renderer.maxSize / output.height),
    devicePixelRatio * factor);
  previewSize = {width: Math.max(1, Math.round(output.width * pixelFactor)), height: Math.max(1, Math.round(output.height * pixelFactor))};
  dirty = true;
}

function refreshOutput(matchDevice = true) {
  for (const key of ['width', 'height', 'duration', 'fps']) $(key).value = output[key];
  $('quality').value = quality;
  $('timeline').max = output.duration;
  currentTime = currentTime % output.duration;
  clockOffset = currentTime;
  clockStart = performance.now();
  $('duration-display').textContent = timeLabel(output.duration);
  $('ratio-label').textContent = aspectLabel(output.width, output.height);
  $('canvas-dimensions').textContent = `${output.width.toLocaleString()} × ${output.height.toLocaleString()}`;
  const selectedDevice = presets.devices.find((device) => device.id === $('device').value);
  if (matchDevice && (!selectedDevice || selectedDevice.width !== output.width || selectedDevice.height !== output.height)) {
    $('device').value = 'custom';
  }
  const device = presets.devices.find((item) => item.id === $('device').value);
  $('canvas-preset').textContent = device ? device.name.toUpperCase() : 'CUSTOM CANVAS';
  $('device-source').hidden = !device;
  if (device) $('device-source').href = device.source;
  const [width, height] = encodedSize(output);
  const padded = width !== output.width || height !== output.height;
  $('output-summary').textContent = `MP4 · H.264 · ${width} × ${height} · ${frameCount(output).toLocaleString()} 프레임${padded ? ' · 가장자리 1px 확장' : ''}`;
  refreshLoop();
  resizePreview();
  persist();
}

function setBusy(value) {
  busy = value;
  $('scene-controls').disabled = value;
  for (const id of ['device', 'width', 'height', 'duration', 'fps', 'swap', 'save-image', 'save-video', 'play', 'restart', 'timeline', 'quality']) $(id).disabled = value;
  if (!presets.encoder.available) $('save-video').disabled = true;
  if (!value) {
    clockOffset = currentTime;
    clockStart = performance.now();
    refreshScene();
  }
}

function updatePlayButton() {
  $('play').setAttribute('aria-label', playing ? '일시정지' : '재생');
  $('play-icon').innerHTML = playing ? '<path d="M8 5v14M16 5v14"/>' : '<path d="m8 4 12 8-12 8Z"/>';
}

function animate(now) {
  animationId = requestAnimationFrame(animate);
  if (busy) return;
  if (playing) currentTime = (clockOffset + (now - clockStart) / 1000) % output.duration;
  if (!playing && !dirty) return;
  try {
    renderer.renderAt(scene, currentTime, previewSize, output.duration);
    dirty = false;
    $('time-display').textContent = timeLabel(currentTime, true);
    $('timeline').value = currentTime;
    rangeFill($('timeline'));
  } catch (error) { fatal(error); }
}

function progress(snapshot) {
  $('job-progress').hidden = false;
  const done = snapshot.type === 'completed';
  const encoding = snapshot.type === 'encoding';
  const percent = Math.floor(snapshot.progress * 100);
  $('job-label').textContent = done ? '나만의 웨이브, 완성!' : encoding ? 'MP4 파일을 마무리하는 중' : '프레임을 그리는 중';
  $('job-percent').textContent = `${percent}%`;
  $('progress-fill').style.width = `${percent}%`;
  $('job-details').textContent = `${snapshot.frames.toLocaleString()} / ${snapshot.total_frames.toLocaleString()} 프레임 · 경과 ${timeLabel(snapshot.elapsed)}${snapshot.eta && !done && !encoding ? ` · 남은 시간 약 ${timeLabel(snapshot.eta)}` : ''}`;
  $('cancel-export').hidden = done;
  if (done) {
    $('download-video').href = snapshot.download_url;
    $('download-video').hidden = false;
  }
}

async function saveImage() {
  const time = currentTime;
  setBusy(true);
  try {
    const blob = await makeJpeg({...scene}, {...output}, time);
    const url = URL.createObjectURL(blob);
    download(url, `xmb-${scene.style}-${output.width}x${output.height}.jpg`);
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notify('JPEG 이미지를 저장했어.');
  } catch (error) { notify(error.message, true); }
  finally { setBusy(false); }
}

async function saveVideo() {
  setBusy(true);
  $('job-progress').hidden = false;
  $('download-video').hidden = true;
  $('cancel-export').hidden = false;
  $('job-label').textContent = '출력 해상도와 인코더를 준비하는 중';
  $('job-percent').textContent = '0%';
  $('progress-fill').style.width = '0%';
  $('job-details').textContent = '제작하는 동안 이 탭을 열어둬.';
  activeExport = new VideoExport(progress);
  try {
    const result = await activeExport.run({...scene}, {...output});
    download(result.download_url);
    notify('영상이 완성됐어. 다운로드 버튼으로 다시 저장할 수도 있어.');
  } catch (error) {
    const cancelled = error.name === 'AbortError';
    $('job-label').textContent = cancelled ? '제작을 취소했어' : '제작을 완료하지 못했어';
    $('job-details').textContent = cancelled ? '설정을 바꾸고 언제든 다시 만들 수 있어.' : error.message;
    $('cancel-export').hidden = true;
    if (!cancelled) notify(error.message, true);
  } finally { activeExport = null; setBusy(false); }
}

function bind() {
  document.querySelectorAll('[data-scene]').forEach((input) => input.addEventListener('input', () => {
    scene[input.dataset.scene] = Number(input.value);
    refreshScene(); persist();
  }));
  $('color').addEventListener('input', () => { scene.color = $('color').value; refreshScene(); persist(); });
  $('color-hex').addEventListener('change', () => {
    const hex = $('color-hex').value.startsWith('#') ? $('color-hex').value : `#${$('color-hex').value}`;
    if (/^#[\da-f]{6}$/i.test(hex)) scene.color = hex;
    else notify('색상은 #4387DE처럼 6자리 HEX 코드로 입력해 줘.', true);
    refreshScene(); persist();
  });
  $('palette').addEventListener('click', (event) => {
    const button = event.target.closest('[data-color]');
    if (!button) return;
    scene.color = button.dataset.color; refreshScene(); persist();
  });
  $('style-options').addEventListener('click', (event) => {
    const button = event.target.closest('[data-style]');
    if (!button) return;
    const {color, rotation, x, y, scale, seed} = scene;
    scene = {...presets.styles.find((style) => style.id === button.dataset.style).defaults, color, rotation, x, y, scale, seed};
    refreshScene(); persist();
  });
  $('rotation-presets').addEventListener('click', (event) => {
    const button = event.target.closest('[data-angle]');
    if (button) { scene.rotation = +button.dataset.angle; refreshScene(); persist(); }
  });
  $('reset').addEventListener('click', () => {
    scene = {...presets.styles.find((style) => style.id === scene.style).defaults}; refreshScene(); persist();
  });
  for (const name of ['background', 'wave']) {
    $(`${name}-override`).addEventListener('change', () => {
      scene[`${name}_color`] = $(`${name}-override`).checked ? $(`${name}-color`).value : null;
      refreshScene(); persist();
    });
    $(`${name}-color`).addEventListener('input', () => {
      scene[`${name}_color`] = $(`${name}-color`).value; dirty = true; persist();
    });
  }
  $('play').addEventListener('click', () => {
    playing = !playing; clockOffset = currentTime; clockStart = performance.now(); updatePlayButton(); dirty = true;
  });
  $('restart').addEventListener('click', () => { currentTime = 0; clockOffset = 0; clockStart = performance.now(); dirty = true; });
  $('timeline').addEventListener('input', () => {
    currentTime = +$('timeline').value; playing = false; updatePlayButton(); dirty = true;
  });
  $('device').addEventListener('change', () => {
    const id = $('device').value;
    const generic = {portrait: [1080, 1920], landscape: [1920, 1080], '4k': [3840, 2160], square: [1080, 1080]};
    const device = presets.devices.find((item) => item.id === id);
    if (device) { output.width = device.width; output.height = device.height; }
    else if (generic[id]) [output.width, output.height] = generic[id];
    refreshOutput(false);
  });
  for (const key of ['width', 'height', 'duration', 'fps']) $(key).addEventListener('change', () => {
    const value = Number($(key).value);
    const previous = output[key];
    try {
      if (!Number.isSafeInteger(value) || value < 1) throw new Error('1 이상의 정수를 입력해 줘.');
      if ((key === 'width' || key === 'height') && value > renderer.maxSize) throw new Error(`이 GPU에서는 한 변 ${renderer.maxSize}px까지 지원해.`);
      output[key] = value; frameCount(output);
    } catch (error) { output[key] = previous; notify(error.message, true); }
    refreshOutput();
  });
  $('swap').addEventListener('click', () => { [output.width, output.height] = [output.height, output.width]; refreshOutput(); });
  $('quality').addEventListener('change', () => { quality = +$('quality').value; resizePreview(); persist(); });
  $('save-image').addEventListener('click', saveImage);
  $('save-video').addEventListener('click', saveVideo);
  $('cancel-export').addEventListener('click', () => {
    $('job-label').textContent = '제작을 정리하는 중'; activeExport?.cancel();
  });
  window.addEventListener('beforeunload', (event) => { if (busy) { event.preventDefault(); event.returnValue = ''; } });
  $('preview').addEventListener('renderer-error', (event) => { activeExport?.cancel(); fatal(new Error(event.detail)); });
  new ResizeObserver(resizePreview).observe($('stage'));
}

async function init() {
  presets = await api('/api/presets');
  $('version').textContent = `v${presets.version}`;
  $('advanced-ranges').innerHTML = ranges.map(([id, label, min, max, step]) => `
    <div class="control-label"><label for="scene-${id}">${label}</label><output id="scene-${id}-value"></output></div>
    <input id="scene-${id}" data-scene="${id}" type="range" min="${min}" max="${max}" step="${step}">`).join('');
  $('style-options').innerHTML = presets.styles.map((style) => `<button type="button" class="style-card" data-style="${style.id}" title="${style.description}" aria-pressed="false"><img id="thumb-${style.id}" alt=""><span class="style-name">${style.name}</span><span class="style-era">${style.era}</span></button>`).join('');
  $('palette').innerHTML = presets.palette.map((color) => `<button class="swatch" type="button" data-color="${color}" style="background:${color}" aria-label="색상 ${color}" aria-pressed="false"></button>`).join('');
  for (const brand of ['Galaxy', 'iPhone']) {
    const group = document.createElement('optgroup'); group.label = brand;
    for (const device of presets.devices.filter((item) => item.brand === brand)) {
      const option = document.createElement('option'); option.value = device.id;
      option.textContent = `${device.name} · ${device.width} × ${device.height}`; group.append(option);
    }
    $('device').append(group);
  }
  restore();
  const thumbs = new WaveRenderer();
  try {
    for (const style of presets.styles) {
      thumbs.renderAt(style.defaults, 2, {width: 240, height: 140}, 10);
      $(`thumb-${style.id}`).src = thumbs.canvas.toDataURL('image/jpeg', .9);
    }
  } finally { thumbs.dispose(); }
  renderer = new WaveRenderer($('preview'));
  $('gpu-status').textContent = `WEBGL 2 · MAX ${renderer.maxSize.toLocaleString()} PX`;
  bind();
  refreshScene(); refreshOutput(); updatePlayButton();
  if (!presets.encoder.available) { $('save-video').disabled = true; notify(presets.encoder.error, true); }
  $('loading').hidden = true;
  animationId = requestAnimationFrame(animate);
  // Small inspection API for browser integration tests; contains no separate render logic.
  window.studio = {
    get scene() { return {...scene}; }, get output() { return {...output}; },
    get renderer() { return renderer; }, get busy() { return busy; },
    get time() { return currentTime; },
  };
}

init().catch(fatal);
