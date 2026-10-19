import * as THREE from '../vendor/three.module.min.js';
import {loopState, mulberry32} from './scene.js';
import {screenVertex, waveFragment, particleVertex, particleFragment} from './shaders.js';

export class WaveRenderer {
  constructor(canvas = document.createElement('canvas')) {
    this.canvas = canvas;
    this.lost = false;
    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      this.lost = true;
      canvas.dispatchEvent(new CustomEvent('renderer-error', {detail: 'GPU 연결이 끊어졌습니다. 새로고침한 뒤 다시 제작해 주세요.'}));
    });
    this.renderer = new THREE.WebGLRenderer({canvas, antialias: false, alpha: false, preserveDrawingBuffer: true});
    this.renderer.setPixelRatio(1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.debug.onShaderError = (gl, program, vertex, fragment) => {
      this.shaderError = `${gl.getShaderInfoLog(vertex) || ''}\n${gl.getShaderInfoLog(fragment) || ''}`;
      console.error('웨이브 셰이더 오류', this.shaderError);
    };
    this.gl = this.renderer.getContext();
    this.maxSize = Math.min(
      this.gl.getParameter(this.gl.MAX_TEXTURE_SIZE),
      this.gl.getParameter(this.gl.MAX_RENDERBUFFER_SIZE),
      ...this.gl.getParameter(this.gl.MAX_VIEWPORT_DIMS),
    );
    this.scene = new THREE.Scene();
    this.camera = new THREE.Camera();
    this.uniforms = {
      uResolution: {value: new THREE.Vector2(1, 1)},
      uBase: {value: new THREE.Color()}, uBackground: {value: new THREE.Color()},
      uWave: {value: new THREE.Color()}, uAccent: {value: new THREE.Color()},
      uPhase: {value: 0}, uStyle: {value: 2},
      uRotation: {value: 0}, uHeight: {value: 0.65}, uWidth: {value: 1},
      uOverlap: {value: 0.6}, uScale: {value: 1}, uGlow: {value: 1},
      uOffset: {value: new THREE.Vector2()},
    };
    this.material = new THREE.ShaderMaterial({
      uniforms: this.uniforms, vertexShader: screenVertex, fragmentShader: waveFragment,
      depthTest: false, depthWrite: false,
    });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material);
    this.quad.frustumCulled = false;
    this.scene.add(this.quad);
    this.particleUniforms = {
      uResolution: {value: new THREE.Vector2(1, 1)}, uPhase: {value: 0},
      uRotation: {value: 0}, uScale: {value: 1}, uOffset: {value: new THREE.Vector2()},
      uWave: {value: new THREE.Color()}, uPixelScale: {value: 1},
      uSize: {value: 1},
    };
    this.particleMaterial = new THREE.ShaderMaterial({
      uniforms: this.particleUniforms, vertexShader: particleVertex, fragmentShader: particleFragment,
      transparent: true, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
    });
    this.particleGeometry = new THREE.InstancedBufferGeometry();
    this.particles = new THREE.Mesh(this.particleGeometry, this.particleMaterial);
    this.particles.frustumCulled = false;
    this.particles.renderOrder = 1;
    this.scene.add(this.particles);
    this.particleKey = '';
    this.pixelBuffer = null;
  }

  validateSize(width, height) {
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 1 || height < 1) {
      throw new Error('해상도는 1 이상의 정수로 입력해 주세요.');
    }
    if (width > this.maxSize || height > this.maxSize) {
      throw new Error(`이 GPU의 한 변 최대 크기는 ${this.maxSize.toLocaleString()}px입니다. 해상도를 줄여 주세요.`);
    }
  }

  updateParticles(count, seed) {
    const key = `${count}:${seed}`;
    if (this.particleKey === key) return;
    const random = mulberry32(seed);
    const values = new Float32Array(count * 4);
    for (let i = 0; i < values.length; i++) values[i] = random();
    const depths = new Float32Array(count * 2);
    for (let i = 0; i < depths.length; i++) depths[i] = random();
    this.particleGeometry.dispose();
    // Instanced quads keep large soft particles consistent at 4K, beyond GL point-size caps.
    this.particleGeometry = new THREE.InstancedBufferGeometry();
    const quad = new THREE.PlaneGeometry(1, 1);
    this.particleGeometry.index = quad.index;
    this.particleGeometry.setAttribute('position', quad.attributes.position);
    this.particleGeometry.setAttribute('uv', quad.attributes.uv);
    this.particleGeometry.setAttribute('aRandom', new THREE.InstancedBufferAttribute(values, 4));
    this.particleGeometry.setAttribute('aDepth', new THREE.InstancedBufferAttribute(depths, 2));
    this.particleGeometry.instanceCount = count;
    this.particles.geometry = this.particleGeometry;
    this.particleKey = key;
  }

  renderAt(config, time, size, duration = 10) {
    if (this.lost || this.gl.isContextLost()) throw new Error('GPU 연결이 끊어졌습니다. 페이지를 새로고침해 주세요.');
    const {width, height} = size;
    this.validateSize(width, height);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.renderer.setSize(width, height, false);
      if (this.gl.drawingBufferWidth !== width || this.gl.drawingBufferHeight !== height) {
        throw new Error('GPU가 지정한 해상도의 화면을 만들지 못했습니다. 더 작은 해상도로 다시 시도해 주세요.');
      }
    }
    const state = loopState(config, time, duration);
    const u = this.uniforms;
    u.uResolution.value.set(width, height);
    u.uBase.value.set(config.color);
    u.uBackground.value.set(config.background_color || config.color);
    const hsl = u.uBase.value.getHSL({}, THREE.SRGBColorSpace);
    u.uAccent.value.setHSL(
      (hsl.h - 0.085 + 1) % 1, Math.min(0.98, hsl.s * 1.5),
      Math.min(0.68, Math.max(0.44, hsl.l * 1.2)), THREE.SRGBColorSpace,
    );
    if (config.style === 'psp-classic') {
      if (!config.background_color) {
        u.uBackground.value.setHSL(hsl.h, Math.min(.98, hsl.s * 1.65), hsl.l, THREE.SRGBColorSpace);
      }
      u.uAccent.value.setHSL((hsl.h - .09 + 1) % 1, Math.min(.98, hsl.s * 1.8), .48, THREE.SRGBColorSpace);
    }
    if (config.wave_color) u.uWave.value.set(config.wave_color);
    else if (config.style === 'psp-original') u.uWave.value.copy(u.uBase.value).multiplyScalar(2);
    else if (config.style === 'ps3') u.uWave.value.setHSL(hsl.h, Math.min(.8, hsl.s * 1.4), .72, THREE.SRGBColorSpace);
    else u.uWave.value.copy(u.uBase.value).lerp(new THREE.Color('#ffffff'), config.style === 'psp-classic' ? 0.3 : 0.72);
    u.uPhase.value = state.wave;
    u.uStyle.value = {'psp-classic': 0, 'psp-original': 1, ps3: 2}[config.style];
    u.uRotation.value = config.rotation * Math.PI / 180;
    u.uHeight.value = config.height;
    u.uWidth.value = config.width;
    u.uOverlap.value = config.overlap;
    u.uScale.value = config.scale;
    u.uGlow.value = config.glow;
    u.uOffset.value.set(config.x, config.y);
    this.particles.visible = config.style === 'ps3' && config.particle_count > 0;
    if (this.particles.visible) {
      this.updateParticles(config.particle_count, config.seed);
      const p = this.particleUniforms;
      p.uResolution.value.set(width, height);
      p.uPhase.value = state.particle;
      p.uRotation.value = u.uRotation.value;
      p.uScale.value = config.scale;
      p.uOffset.value.set(config.x, config.y);
      p.uWave.value.copy(u.uWave.value);
      p.uPixelScale.value = Math.min(width, height) / 720;
      p.uSize.value = config.particle_size ?? 1;
    }
    this.renderer.render(this.scene, this.camera);
    if (this.shaderError) throw new Error('그래픽 효과를 실행하지 못했습니다. GPU와 브라우저를 확인해 주세요.');
    const error = this.gl.getError();
    if (error !== this.gl.NO_ERROR) throw new Error(`GPU 렌더링에 실패했습니다 (${error}). 해상도를 낮춰 다시 시도해 주세요.`);
    return state;
  }

  readPixels() {
    const length = this.canvas.width * this.canvas.height * 4;
    if (!this.pixelBuffer || this.pixelBuffer.length !== length) this.pixelBuffer = new Uint8Array(length);
    this.gl.readPixels(0, 0, this.canvas.width, this.canvas.height, this.gl.RGBA, this.gl.UNSIGNED_BYTE, this.pixelBuffer);
    if (this.gl.isContextLost() || this.gl.getError() !== this.gl.NO_ERROR) throw new Error('GPU에서 프레임을 읽지 못했습니다.');
    return this.pixelBuffer;
  }

  jpeg() {
    return new Promise((resolve, reject) => {
      this.canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('JPEG 파일을 만들지 못했습니다.')), 'image/jpeg', 0.95);
    });
  }

  dispose() {
    this.quad.geometry.dispose();
    this.material.dispose();
    this.particleGeometry.dispose();
    this.particleMaterial.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.pixelBuffer = null;
  }
}
