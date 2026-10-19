import {WaveRenderer} from './renderer.js';
import {frameCount} from './scene.js';

export async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Preserve a readable HTTP fallback. */ }
    throw new Error(typeof detail === 'string' ? detail : `요청을 처리하지 못했습니다 (${response.status}). 입력값을 확인해 주세요.`);
  }
  return response.json();
}

class FrameConnection {
  constructor(url, signal) {
    this.socket = new WebSocket(url);
    this.queue = [];
    this.waiter = null;
    this.error = null;
    this.opened = new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, {once: true});
      this.socket.addEventListener('error', () => reject(new Error('로컬 인코더에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요.')), {once: true});
    });
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (this.waiter) { this.waiter.resolve(message); this.waiter = null; }
      else this.queue.push(message);
    });
    this.socket.addEventListener('close', () => this.fail(new Error('영상 제작 연결이 끊어졌습니다. 다시 제작해 주세요.')));
    this.socket.addEventListener('error', () => this.fail(new Error('영상 제작 연결에 문제가 생겼습니다.')));
    signal.addEventListener('abort', () => {
      this.fail(new DOMException('제작을 취소했습니다.', 'AbortError'));
    }, {once: true});
  }
  fail(error) {
    this.error = error;
    if (this.waiter) { this.waiter.reject(error); this.waiter = null; }
  }
  next() {
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    if (this.error) return Promise.reject(this.error);
    return new Promise((resolve, reject) => { this.waiter = {resolve, reject}; });
  }
  async sendFrame(index, pixels, chunkSize, signal) {
    this.socket.send(JSON.stringify({type: 'frame', index}));
    for (let offset = 0; offset < pixels.length; offset += chunkSize) {
      signal.throwIfAborted();
      while (this.socket.bufferedAmount > chunkSize * 2) {
        if (this.error) throw this.error;
        signal.throwIfAborted();
        await new Promise((resolve) => setTimeout(resolve, 2));
      }
      this.socket.send(pixels.subarray(offset, Math.min(offset + chunkSize, pixels.length)));
    }
    const response = await this.next();
    if (response.type === 'error') throw new Error(response.error || '인코더가 작업을 중단했습니다.');
    if (response.type !== 'ack' || response.index !== index) throw new Error('프레임 처리 순서가 일치하지 않습니다.');
    return response;
  }
}

export class VideoExport {
  constructor(onProgress) {
    this.onProgress = onProgress;
    this.controller = new AbortController();
    this.job = null;
    this.connection = null;
    this.cancelRequest = null;
  }
  async run(scene, output) {
    const signal = this.controller.signal;
    const count = frameCount(output);
    let renderer;
    let completed = false;
    try {
      renderer = new WaveRenderer();
      // Test actual allocation and readback before reserving a server export job.
      renderer.renderAt(scene, 0, output, output.duration);
      renderer.readPixels();
      signal.throwIfAborted();
      this.job = await api('/api/exports', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scene, output: {...output, kind: 'video'}}),
      });
      signal.throwIfAborted();
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
      this.connection = new FrameConnection(`${scheme}//${location.host}/api/exports/${this.job.id}/frames`, signal);
      await this.connection.opened;
      const ready = await this.connection.next();
      if (ready.type !== 'ready') throw new Error(ready.error || '인코더가 준비되지 않았습니다.');
      for (let index = 0; index < count; index++) {
        signal.throwIfAborted();
        renderer.renderAt(scene, index / output.fps, output, output.duration);
        const response = await this.connection.sendFrame(index, renderer.readPixels(), ready.chunk_size, signal);
        this.onProgress(response);
        // Yield independently of requestAnimationFrame: background tabs may pause RAF.
        if (index % 3 === 0) await new Promise((resolve) => setTimeout(resolve, 0));
      }
      while (true) {
        const response = await this.connection.next();
        this.onProgress(response);
        if (response.type === 'completed') { completed = true; return response; }
        if (response.type === 'error') throw new Error(response.error || '영상 파일을 완성하지 못했습니다.');
      }
    } finally {
      if (!completed && this.job) {
        // Record an explicit cancel before closing WS, otherwise it looks like a lost tab.
        await (this.cancelRequest || fetch(`/api/exports/${this.job.id}`, {method: 'DELETE'}).catch(() => {}));
      }
      this.connection?.socket.close();
      renderer?.dispose();
    }
  }
  async cancel() {
    if (this.job) this.cancelRequest = fetch(`/api/exports/${this.job.id}`, {method: 'DELETE'}).catch(() => {});
    this.controller.abort();
    await this.cancelRequest;
  }
}

export async function makeJpeg(scene, output, time) {
  const renderer = new WaveRenderer();
  try {
    renderer.renderAt(scene, time, output, output.duration);
    return await renderer.jpeg();
  } finally { renderer.dispose(); }
}

export function download(url, filename) {
  const link = document.createElement('a');
  link.href = url;
  if (filename) link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}
