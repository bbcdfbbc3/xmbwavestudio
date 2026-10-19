/** Pure, resolution-independent settings and closed animation phases. */
export const DEFAULT_SCENE = Object.freeze({
  style: 'ps3', color: '#3264c5', background_color: null, wave_color: null,
  speed: 0.5, rotation: 0, height: 0.55, width: 1.15, overlap: 0.82, layer_motion: 1, x: 0, y: 0,
  scale: 1, glow: 0.9, particle_count: 450, particle_speed: 0.4, particle_size: 1, seed: 2026,
});
export const PRESET_REVISION = 2;

/** Upgrade untouched old defaults while retaining the user's actual edits. */
export function migrateScene(stored, defaults, revision = 0) {
  const result = {...defaults, ...stored};
  if (revision >= PRESET_REVISION) return result;
  const legacy = {
    ...DEFAULT_SCENE, color: '#4387de', speed: 1, height: 0.65, width: 1,
    overlap: 0.6, glow: 1, particle_count: 180, particle_speed: 1,
    ...(stored.style === 'psp-classic' ? {height: 0.45, glow: 0.8} : {}),
    ...(stored.style === 'psp-original' ? {height: 0.8, overlap: 0.75} : {}),
  };
  for (const key of Object.keys(defaults)) {
    if (stored[key] === undefined || stored[key] === legacy[key]) result[key] = defaults[key];
  }
  return result;
}
export const DEFAULT_OUTPUT = Object.freeze({kind: 'video', width: 1080, height: 1920, duration: 10, fps: 30});

export function cyclesFor(speed, duration, basePeriod) {
  return speed === 0 ? 0 : Math.max(1, Math.round(speed * duration / basePeriod));
}

export function loopState(scene, time, duration) {
  // Reduce on the CPU before passing to GPU float uniforms, even for very long videos.
  const phase = ((time % duration) + duration) % duration / duration;
  const waveCycles = cyclesFor(scene.speed, duration, 12);
  const particleCycles = cyclesFor(scene.particle_speed, duration, 16);
  const angle = (cycles) => 2 * Math.PI * ((phase * cycles) % 1);
  return {
    wave: angle(waveCycles), particle: angle(particleCycles),
    waveSpeed: waveCycles * 12 / duration,
    particleSpeed: particleCycles * 16 / duration,
    waveCycles, particleCycles,
  };
}

export function encodedSize(output) {
  return [output.width + output.width % 2, output.height + output.height % 2];
}

export function frameCount(output) {
  const count = output.duration * output.fps;
  if (!Number.isSafeInteger(count) || count < 1) throw new Error('영상 길이가 정확히 계산할 수 있는 범위를 넘습니다.');
  return count;
}

export function mulberry32(seed) {
  return () => {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

export function aspectLabel(width, height) {
  const gcd = (a, b) => b ? gcd(b, a % b) : a;
  const divisor = gcd(width, height);
  return `${width / divisor}:${height / divisor}`;
}
