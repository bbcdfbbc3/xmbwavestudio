/** The browser displays Python-rendered images. It owns no scene or GPU shader. */
export class RemotePreview {
  constructor(canvas, maxSize) {
    this.canvas = canvas;
    this.context = canvas.getContext('2d', {alpha: false});
    this.maxSize = maxSize;
    this.pending = null;
    this.displayedTime = 0;
    this.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/preview`);
    this.socket.binaryType = 'blob';
    this.opened = new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, {once: true});
      this.socket.addEventListener('error', () => reject(new Error('Python 미리보기 서버에 연결할 수 없어.')), {once: true});
    });
    this.socket.addEventListener('message', async (event) => {
      const waiter = this.waiter;
      if (!waiter) return;
      this.waiter = null;
      clearTimeout(waiter.timer);
      try {
        if (typeof event.data === 'string') {
          const message = JSON.parse(event.data);
          throw new Error(message.error || '미리보기를 만들지 못했어.');
        }
        const bitmap = await createImageBitmap(event.data);
        try {
          if (this.canvas.width !== bitmap.width) this.canvas.width = bitmap.width;
          if (this.canvas.height !== bitmap.height) this.canvas.height = bitmap.height;
          this.context.drawImage(bitmap, 0, 0);
          this.displayedTime = waiter.time;
        } finally { bitmap.close(); }
        waiter.resolve();
      } catch (error) { waiter.reject(error); }
    });
    this.socket.addEventListener('close', () => {
      if (this.waiter) {
        clearTimeout(this.waiter.timer);
        this.waiter.reject(new Error('Python 미리보기 연결이 끊어졌어. 서버를 확인하고 새로고침해 줘.'));
        this.waiter = null;
      }
    });
  }
  renderAt(scene, time, size, duration, output) {
    if (this.pending) return this.pending;
    this.pending = (async () => {
      await this.opened;
      if (this.socket.readyState !== WebSocket.OPEN) throw new Error('Python 서버 연결이 종료됐어. 새로고침해 줘.');
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.waiter = null;
          this.socket.close();
          reject(new Error('미리보기 응답이 없어. Python 서버를 확인해 줘.'));
        }, 20000);
        this.waiter = {resolve, reject, timer, time};
        this.socket.send(JSON.stringify({scene, output: {...output, duration}, time,
          width: size.width, height: size.height}));
      });
    })().finally(() => { this.pending = null; });
    return this.pending;
  }
}
