export async function response(url, options = {}) {
  const result = await fetch(url, options);
  if (!result.ok) {
    let detail;
    try { detail = (await result.json()).detail; } catch { /* Keep the HTTP fallback. */ }
    throw new Error(typeof detail === 'string' ? detail : `요청을 처리하지 못했습니다 (${result.status}). 입력값을 확인해 주세요.`);
  }
  return result;
}

export async function api(url, options = {}) { return (await response(url, options)).json(); }

export class VideoExport {
  constructor(onProgress) {
    this.onProgress = onProgress;
    this.controller = new AbortController();
    this.job = null;
    this.socket = null;
    this.cancelRequest = null;
  }
  async run(scene, output) {
    const signal = this.controller.signal;
    let completed = false;
    try {
      this.job = await api('/api/exports', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scene, output: {...output, kind: 'video'}}),
      });
      signal.throwIfAborted();
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const result = await new Promise((resolve, reject) => {
        const socket = this.socket = new WebSocket(`${scheme}//${location.host}/api/exports/${this.job.id}/progress`);
        signal.addEventListener('abort', () => reject(new DOMException('제작을 취소했어.', 'AbortError')), {once: true});
        socket.addEventListener('message', (event) => {
          const snapshot = JSON.parse(event.data);
          this.onProgress(snapshot);
          if (snapshot.status === 'completed') { completed = true; resolve(snapshot); }
          if (snapshot.status === 'error') reject(new Error(snapshot.error || '영상 제작에 실패했어.'));
          if (snapshot.status === 'cancelled') reject(new DOMException('제작을 취소했어.', 'AbortError'));
        });
        socket.addEventListener('error', () => reject(new Error('Python 영상 제작 서버에 연결할 수 없어.')));
        socket.addEventListener('close', () => { if (!completed) reject(new Error('영상 제작 연결이 끊어졌어. 다시 제작해 줘.')); });
      });
      return result;
    } finally {
      if (!completed && this.job) {
        await (this.cancelRequest || fetch(`/api/exports/${this.job.id}`, {method: 'DELETE'}).catch(() => {}));
      }
      this.socket?.close();
    }
  }
  async cancel() {
    if (this.job) this.cancelRequest = fetch(`/api/exports/${this.job.id}`, {method: 'DELETE'}).catch(() => {});
    this.controller.abort();
    await this.cancelRequest;
  }
}

export async function makeJpeg(scene, output, time) {
  return (await response('/api/images', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scene, output: {...output, kind: 'jpeg'}, time})})).blob();
}

export function download(url, filename) {
  const link = document.createElement('a');
  link.href = url;
  if (filename) link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}
