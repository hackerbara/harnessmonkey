#!/usr/bin/env node
'use strict';

const ESC = String.fromCharCode(27);
const HALF = String.fromCharCode(9600);
const BRAILLE_BASE = 0x2800;
const BRAILLE_DOTS = [1, 8, 2, 16, 4, 32, 64, 128];

function parseArgs(argv) {
  const out = { width: 80, height: 32, fps: 8, scene: 'orbit-lab', frames: 0, renderer: 'webgpu', ansi: 'braille' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === '--width' && next) out.width = Number(next), i++;
    else if (arg === '--height' && next) out.height = Number(next), i++;
    else if (arg === '--fps' && next) out.fps = Number(next), i++;
    else if (arg === '--scene' && next) out.scene = String(next), i++;
    else if (arg === '--frames' && next) out.frames = Number(next), i++;
    else if (arg === '--renderer' && next) out.renderer = String(next), i++;
    else if (arg === '--ansi' && next) out.ansi = String(next), i++;
  }
  out.width = clampInt(out.width, 8, 180, 80);
  out.height = clampInt(out.height, 6, 120, 32);
  out.fps = clampInt(out.fps, 1, 30, 8);
  out.frames = clampInt(out.frames, 0, 1000000, 0);
  if (!['webgpu', 'software', 'wireframe'].includes(out.renderer)) out.renderer = 'webgpu';
  if (!['braille', 'half'].includes(out.ansi)) out.ansi = 'braille';
  return out;
}

function clampInt(value, min, max, fallback) {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, Math.round(value)));
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

function safeRequire(id) {
  try { return require(id); }
  catch (error) { return null; }
}

function withSuppressedConsoleLog(fn) {
  const original = console.log;
  console.log = () => {};
  try { return fn(); }
  finally { console.log = original; }
}

const opts = parseArgs(process.argv.slice(2));
let rendererState = null;
let rendererKind = opts.renderer;
let rendererError = null;
let seq = 0;
let start = Date.now();
let timer = null;
let stopped = false;

async function main() {
  await initializeRenderer();

  emit({
    type: 'hello',
    protocol: 1,
    renderer: rendererKind,
    requestedRenderer: opts.renderer,
    fallbackReason: rendererError,
    scene: opts.scene,
    width: opts.width,
    height: opts.height,
    fps: opts.fps,
    ansi: opts.ansi,
    threeRevision: rendererState.threeRevision,
    softwareThreeRevision: rendererState.softwareThreeRevision || null
  });

  await loop();
}

async function initializeRenderer() {
  if (opts.renderer === 'webgpu') {
    try {
      rendererState = await createWebGpuRenderer(opts.width, opts.height, opts.scene, opts.ansi);
      rendererKind = rendererState.rendererKind || 'webgpu';
    } catch (error) {
      rendererError = error && error.message ? error.message : String(error);
      rendererKind = 'wireframe-fallback';
    }
  }

  if (!rendererState && opts.renderer === 'software') {
    try {
      rendererState = createSoftwareRenderer(opts.width, opts.height, opts.scene);
      rendererKind = 'software';
    } catch (error) {
      rendererError = error && error.message ? error.message : String(error);
      rendererKind = 'wireframe-fallback';
    }
  }

  if (!rendererState) {
    try {
      rendererState = createWireframeRenderer(opts.width, opts.height, opts.scene);
      if (opts.renderer === 'wireframe') rendererKind = 'wireframe';
    } catch (error) {
      emit({ type: 'error', message: error && error.message ? error.message : String(error) });
      process.exit(2);
    }
  }
}

async function tick() {
  const now = Date.now();
  const t = (now - start) / 1000;
  const before = Date.now();
  let frame;
  try {
    frame = await rendererState.render(t);
  } catch (error) {
    emit({ type: 'error', message: (error && error.message ? error.message : String(error)).slice(0, 160) });
    if (rendererKind.startsWith('webgpu') || rendererKind.startsWith('software')) {
      try { rendererState.dispose?.(); } catch {}
      rendererState = createWireframeRenderer(opts.width, opts.height, opts.scene);
      rendererKind = 'wireframe-fallback-after-error';
      frame = await rendererState.render(t);
    } else {
      process.exit(2);
    }
  }
  const renderMs = Date.now() - before;
  emit({
    type: 'frame',
    seq: ++seq,
    width: opts.width,
    height: opts.height,
    renderer: rendererKind,
    encoding: 'base64-ansi',
    data: Buffer.from(frame, 'utf8').toString('base64')
  });
  if (seq % Math.max(1, opts.fps) === 0) emit({ type: 'metric', fps: opts.fps, renderMs, renderer: rendererKind });
}

async function loop() {
  if (stopped) return;
  await tick();
  if (opts.frames && seq >= opts.frames) {
    shutdown(0);
    return;
  }
  timer = setTimeout(() => {
    loop().catch((error) => {
      emit({ type: 'error', message: String(error && error.message || error).slice(0, 160) });
      shutdown(2);
    });
  }, Math.round(1000 / opts.fps));
}

function installNodeWebGpuGlobals(gpu, globals) {
  Object.assign(globalThis, globals);
  globalThis.self = globalThis;
  globalThis.window = globalThis;
  if (!globalThis.navigator) globalThis.navigator = {};
  Object.defineProperty(globalThis.navigator, 'gpu', { value: gpu, configurable: true });
  Object.defineProperty(globalThis.navigator, 'userAgent', { value: 'node-webgpu', configurable: true });
  globalThis.requestAnimationFrame = globalThis.requestAnimationFrame || ((cb) => setTimeout(() => cb(Date.now()), 16));
  globalThis.cancelAnimationFrame = globalThis.cancelAnimationFrame || ((id) => clearTimeout(id));
}

async function createWebGpuRenderer(width, rows, sceneName, ansiMode) {
  const pixelWidth = ansiMode === 'braille' ? width * 2 : width;
  const pixelHeight = ansiMode === 'braille' ? Math.max(4, rows * 4) : Math.max(2, rows * 2);
  const { create, globals } = await import('webgpu');
  const gpu = create([]);
  installNodeWebGpuGlobals(gpu, globals);

  const THREE = await import('three/webgpu');
  const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
  if (!adapter) throw new Error('webgpu: no adapter');
  const device = await adapter.requestDevice();

  const fakeCanvas = {
    width: pixelWidth,
    height: pixelHeight,
    clientWidth: pixelWidth,
    clientHeight: pixelHeight,
    style: {},
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {}
  };

  const renderer = new THREE.WebGPURenderer({
    canvas: fakeCanvas,
    device,
    antialias: false,
    alpha: false
  });
  renderer.setSize(pixelWidth, pixelHeight, false);
  await renderer.init();

  const sceneState = createWebGpuScene(THREE, pixelWidth, pixelHeight, sceneName);
  const target = new THREE.RenderTarget(pixelWidth, pixelHeight, { samples: 0 });

  return {
    threeRevision: THREE.REVISION,
    softwareThreeRevision: null,
    rendererKind: 'webgpu',
    async render(time) {
      sceneState.update(time);
      renderer.setRenderTarget(target);
      await renderer.render(sceneState.scene, sceneState.camera);
      const pixels = await renderer.readRenderTargetPixelsAsync(target, 0, 0, pixelWidth, pixelHeight);
      return imageDataToAnsiFrame(pixels, pixelWidth, pixelHeight, width, rows, ansiMode);
    },
    dispose() {
      try { target.dispose(); } catch {}
      try { renderer.dispose(); } catch {}
      try { device.destroy?.(); } catch {}
      try { delete globalThis.navigator.gpu; } catch {}
    }
  };
}

function createWebGpuScene(THREE, width, pixelHeight, sceneName) {
  if (sceneName === 'orbit-lab') return createOrbitLabScene(THREE, width, pixelHeight);
  if (sceneName === 'webgl-camera-left') return createWebglCameraLeftScene(THREE, width, pixelHeight);
  return createDefaultWebGpuScene(THREE, width, pixelHeight, sceneName);
}

function createDefaultWebGpuScene(THREE, width, pixelHeight, sceneName) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x040714);

  const camera = new THREE.PerspectiveCamera(50, Math.max(0.2, width / Math.max(1, pixelHeight)), 0.1, 100);
  camera.position.set(0, 0.25, 4.2);
  camera.lookAt(0, 0, 0);

  const mesh = new THREE.Mesh(
    buildWebGpuGeometry(THREE, sceneName),
    new THREE.MeshNormalMaterial()
  );
  scene.add(mesh);

  return {
    scene,
    camera,
    update(time) {
      mesh.rotation.x = time * 0.67;
      mesh.rotation.y = time * 0.93;
      mesh.rotation.z = Math.sin(time * 0.37) * 0.26;
    }
  };
}


function createOrbitLabScene(THREE, width, pixelHeight) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020614);

  const camera = new THREE.PerspectiveCamera(42, Math.max(0.35, width / Math.max(1, pixelHeight)), 0.1, 100);
  camera.position.set(0, 0.55, 6.2);
  camera.lookAt(0, 0, 0);

  const root = new THREE.Group();
  scene.add(root);

  const halo = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(1.55, 36, 18)),
    new THREE.LineBasicMaterial({ color: 0x9df7ff })
  );
  root.add(halo);

  const core = new THREE.Mesh(
    new THREE.TorusKnotGeometry(0.74, 0.18, 128, 14),
    new THREE.MeshNormalMaterial()
  );
  root.add(core);

  const ringA = new THREE.Mesh(
    new THREE.TorusGeometry(2.05, 0.012, 8, 160),
    new THREE.MeshBasicMaterial({ color: 0xff84d8 })
  );
  ringA.rotation.x = Math.PI / 2.7;
  root.add(ringA);

  const ringB = new THREE.Mesh(
    new THREE.TorusGeometry(1.9, 0.01, 8, 160),
    new THREE.MeshBasicMaterial({ color: 0x75f6a0 })
  );
  ringB.rotation.x = Math.PI / 2.15;
  ringB.rotation.y = Math.PI / 7;
  root.add(ringB);

  const satellites = [];
  const satMaterials = [0xffee88, 0x66ccff, 0xff7fbf, 0xaaff77].map((color) => new THREE.MeshBasicMaterial({ color }));
  for (let i = 0; i < 8; i++) {
    const pivot = new THREE.Group();
    const sat = new THREE.Mesh(
      i % 2 === 0 ? new THREE.IcosahedronGeometry(0.075, 1) : new THREE.BoxGeometry(0.12, 0.12, 0.12),
      satMaterials[i % satMaterials.length]
    );
    sat.position.x = 1.75 + (i % 3) * 0.18;
    pivot.rotation.z = i * Math.PI / 4;
    pivot.rotation.x = (i % 2 ? 0.65 : -0.48);
    pivot.add(sat);
    root.add(pivot);
    satellites.push({ pivot, sat, speed: 0.45 + i * 0.09 });
  }

  const starGeometry = new THREE.BufferGeometry();
  const starVertices = [];
  const rand = createSeededRandFloatSpread(0x50da7a);
  for (let i = 0; i < 900; i++) {
    starVertices.push(rand(8.5));
    starVertices.push(rand(5.4));
    starVertices.push(-2.5 - (rand(1) + 0.5) * 5.5);
  }
  starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starVertices, 3));
  const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({ color: 0x7f8fa8, size: 0.012 }));
  scene.add(stars);

  const trailGeometry = new THREE.BufferGeometry();
  const trailPoints = [];
  for (let i = 0; i < 160; i++) {
    const a = i / 159 * Math.PI * 2;
    const radius = 2.45 + Math.sin(a * 3) * 0.15;
    trailPoints.push(Math.cos(a) * radius, Math.sin(a * 2) * 0.22, Math.sin(a) * radius * 0.38);
  }
  trailGeometry.setAttribute('position', new THREE.Float32BufferAttribute(trailPoints, 3));
  const trail = new THREE.Line(trailGeometry, new THREE.LineBasicMaterial({ color: 0x8899ff }));
  root.add(trail);

  return {
    scene,
    camera,
    update(time) {
      root.rotation.y = time * 0.34;
      root.rotation.x = Math.sin(time * 0.31) * 0.18;
      core.rotation.x = time * 0.72;
      core.rotation.y = time * 0.53;
      halo.rotation.y = -time * 0.18;
      ringA.rotation.z = time * 0.29;
      ringB.rotation.z = -time * 0.22;
      trail.rotation.z = time * 0.13;
      stars.rotation.y = time * 0.018;
      for (const { pivot, sat, speed } of satellites) {
        pivot.rotation.y = time * speed;
        sat.rotation.x = time * 1.4;
        sat.rotation.y = time * 1.1;
      }
    }
  };
}

function createWebglCameraLeftScene(THREE, width, pixelHeight) {
  // Port of the left/main view from:
  // https://github.com/mrdoob/three.js/blob/dev/examples/webgl_camera.html
  //
  // The original example renders two browser WebGL viewports. In this sidecar we
  // keep the scene graph and active-camera animation, then render only the left
  // active-camera view into the existing offscreen WebGPU render target.
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const aspect = (width * 2) / Math.max(1, pixelHeight);
  const cameraPerspective = new THREE.PerspectiveCamera(50, 0.5 * aspect, 150, 1000);
  cameraPerspective.rotation.y = Math.PI;

  const cameraRig = new THREE.Group();
  cameraRig.add(cameraPerspective);
  scene.add(cameraRig);

  const mesh = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(100, 16, 8)),
    new THREE.LineBasicMaterial({ color: 0xffffff })
  );
  scene.add(mesh);

  const childSphere = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(50, 16, 8)),
    new THREE.LineBasicMaterial({ color: 0x00ff00 })
  );
  childSphere.position.y = 150;
  mesh.add(childSphere);

  const cameraMarker = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(5, 16, 8)),
    new THREE.LineBasicMaterial({ color: 0x0000ff })
  );
  cameraMarker.position.z = 150;
  cameraRig.add(cameraMarker);

  const geometry = new THREE.BufferGeometry();
  const vertices = [];
  const randFloatSpread = createSeededRandFloatSpread(0x31c0de);
  const particleCount = Math.max(600, Math.min(5000, Math.round(width * pixelHeight * 0.18)));
  for (let i = 0; i < particleCount; i++) {
    vertices.push(randFloatSpread(2000));
    vertices.push(randFloatSpread(2000));
    vertices.push(randFloatSpread(2000));
  }
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));

  const particles = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({ color: 0x888888 })
  );
  scene.add(particles);

  return {
    scene,
    camera: cameraPerspective,
    update(time) {
      const r = time * 0.5;

      mesh.position.x = 700 * Math.cos(r);
      mesh.position.z = 700 * Math.sin(r);
      mesh.position.y = 700 * Math.sin(r);

      mesh.children[0].position.x = 70 * Math.cos(2 * r);
      mesh.children[0].position.z = 70 * Math.sin(r);

      cameraPerspective.fov = 35 + 30 * Math.sin(0.5 * r);
      // The browser example sets far exactly to the sphere-center distance.
      // In this low-resolution WebGPU readback target that clips the wire
      // sphere into bands, so keep the example motion but give the object room.
      cameraPerspective.far = mesh.position.length() + 300;
      cameraPerspective.updateProjectionMatrix();

      cameraRig.lookAt(mesh.position);
    }
  };
}

function createSeededRandFloatSpread(seed) {
  let state = seed >>> 0;
  return function randFloatSpread(range) {
    state = (state * 1664525 + 1013904223) >>> 0;
    return range * (state / 0x100000000 - 0.5);
  };
}

function buildWebGpuGeometry(THREE, sceneName) {
  if (sceneName === 'knot' && THREE.TorusKnotGeometry) return new THREE.TorusKnotGeometry(1.05, 0.28, 96, 12);
  if (sceneName === 'sphere') return new THREE.SphereGeometry(1.35, 32, 16);
  return new THREE.BoxGeometry(1.65, 1.65, 1.65);
}

function createSoftwareRenderer(width, rows, sceneName) {
  const SoftwareRenderer = safeRequire('three-software-renderer');
  const THREE = safeRequire('three-software-renderer/node_modules/three');
  if (!SoftwareRenderer || !THREE) throw new Error('three-software-renderer is not installed; run npm install');

  const pixelHeight = Math.max(2, rows * 2);
  const renderer = withSuppressedConsoleLog(() => new SoftwareRenderer({ alpha: false }));
  renderer.setSize(width, pixelHeight);

  const camera = new THREE.PerspectiveCamera(50, Math.max(0.2, width / Math.max(1, pixelHeight)), 0.1, 100);
  camera.position.set(0, 0.25, 4.2);
  camera.lookAt(new THREE.Vector3(0, 0, 0));

  const scene = new THREE.Scene();
  const geometry = buildSoftwareGeometry(THREE, sceneName);
  const material = new THREE.MeshBasicMaterial({ vertexColors: THREE.FaceColors, overdraw: 0.25 });
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  const lightDir = new THREE.Vector3(-0.35, 0.45, 0.82).normalize();
  const normalMatrix = new THREE.Matrix3();
  const faceNormal = new THREE.Vector3();
  const baseA = { r: 70, g: 205, b: 255 };
  const baseB = { r: 255, g: 170, b: 92 };

  function shadeFaces(time) {
    mesh.rotation.x = time * 0.67;
    mesh.rotation.y = time * 0.93;
    mesh.rotation.z = Math.sin(time * 0.37) * 0.26;
    mesh.updateMatrixWorld(true);
    normalMatrix.getNormalMatrix(mesh.matrixWorld);
    for (let i = 0; i < geometry.faces.length; i++) {
      const face = geometry.faces[i];
      faceNormal.copy(face.normal).applyMatrix3(normalMatrix).normalize();
      const ndotl = Math.max(0, faceNormal.dot(lightDir));
      const rim = Math.pow(Math.max(0, 1 - Math.abs(faceNormal.z)), 2) * 0.38;
      const mix = Math.max(0, Math.min(1, 0.5 + faceNormal.x * 0.25 + faceNormal.y * 0.18));
      const intensity = 0.22 + 0.72 * ndotl + rim;
      const r = clampColor((baseA.r * (1 - mix) + baseB.r * mix) * intensity + 10);
      const g = clampColor((baseA.g * (1 - mix) + baseB.g * mix) * intensity + 8);
      const b = clampColor((baseA.b * (1 - mix) + baseB.b * mix) * intensity + 18);
      face.color.setRGB(r / 255, g / 255, b / 255);
    }
    geometry.colorsNeedUpdate = true;
  }

  return {
    threeRevision: THREE.REVISION,
    softwareThreeRevision: THREE.REVISION,
    render(time) {
      shadeFaces(time);
      const image = renderer.render(scene, camera);
      return imageDataToHalfBlockAnsi(image.data, width, pixelHeight);
    }
  };
}

function buildSoftwareGeometry(THREE, sceneName) {
  if (sceneName === 'knot' && THREE.TorusKnotGeometry) return new THREE.TorusKnotGeometry(1.15, 0.34, 72, 10);
  if (sceneName === 'sphere') return new THREE.SphereGeometry(1.35, 24, 16);
  return new THREE.BoxGeometry(1.65, 1.65, 1.65, 1, 1, 1);
}

function imageDataToAnsiFrame(data, pixelWidth, pixelHeight, columns, rows, ansiMode) {
  if (ansiMode === 'braille') return imageDataToBrailleAnsi(data, pixelWidth, pixelHeight, columns, rows);
  return imageDataToHalfBlockAnsi(data, pixelWidth, pixelHeight);
}

function imageDataToBrailleAnsi(data, pixelWidth, pixelHeight, columns, rows) {
  const rowStrideBytes = inferRgbaRowStrideBytes(data, pixelWidth, pixelHeight);
  const lines = [];
  const bg = [4, 7, 20];
  const bgKey = bg.join(';');
  for (let row = 0; row < rows; row++) {
    let out = '';
    let last = null;
    for (let col = 0; col < columns; col++) {
      let bits = 0;
      let rSum = 0;
      let gSum = 0;
      let bSum = 0;
      let lit = 0;
      for (let yy = 0; yy < 4; yy++) {
        for (let xx = 0; xx < 2; xx++) {
          const px = Math.min(pixelWidth - 1, col * 2 + xx);
          const py = Math.min(pixelHeight - 1, row * 4 + yy);
          const rgb = samplePixel(data, rowStrideBytes, py, px);
          const luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
          const chroma = Math.max(rgb[0], rgb[1], rgb[2]) - Math.min(rgb[0], rgb[1], rgb[2]);
          if (luminance > 28 || chroma > 22) {
            bits |= BRAILLE_DOTS[yy * 2 + xx];
            rSum += rgb[0];
            gSum += rgb[1];
            bSum += rgb[2];
            lit++;
          }
        }
      }
      let ch = ' ';
      let fg = bg;
      if (bits !== 0) {
        ch = String.fromCharCode(BRAILLE_BASE + bits);
        fg = [clampColor(rSum / lit), clampColor(gSum / lit), clampColor(bSum / lit)];
      }
      const key = `${fg.join(';')};${bgKey}`;
      if (key !== last) {
        out += `${ESC}[38;2;${fg.join(';')};48;2;${bgKey}m`;
        last = key;
      }
      out += ch;
    }
    if (last !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join('\n');
}

function imageDataToHalfBlockAnsi(data, width, pixelHeight) {
  const rows = Math.floor(pixelHeight / 2);
  const rowStrideBytes = inferRgbaRowStrideBytes(data, width, pixelHeight);
  const lines = [];
  for (let y = 0; y < rows; y++) {
    let out = '';
    let lastFg = null;
    let lastBg = null;
    for (let x = 0; x < width; x++) {
      const top = samplePixel(data, rowStrideBytes, y * 2, x);
      const bot = samplePixel(data, rowStrideBytes, y * 2 + 1, x);
      const fg = top.join(';');
      const bg = bot.join(';');
      if (fg !== lastFg || bg !== lastBg) {
        out += `${ESC}[38;2;${fg};48;2;${bg}m`;
        lastFg = fg;
        lastBg = bg;
      }
      out += HALF;
    }
    if (lastFg !== null) out += `${ESC}[0m`;
    lines.push(out);
  }
  return lines.join('\n');
}

function inferRgbaRowStrideBytes(data, width, pixelHeight) {
  const compact = width * pixelHeight * 4;
  if (data.length <= compact) return width * 4;

  const webGpuAligned = Math.ceil((width * 4) / 256) * 256;
  const webGpuWithFinalPadding = webGpuAligned * pixelHeight;
  const webGpuWithoutFinalPadding = webGpuAligned * Math.max(0, pixelHeight - 1) + width * 4;
  if (data.length === webGpuWithFinalPadding || data.length === webGpuWithoutFinalPadding) return webGpuAligned;

  const inferred = Math.floor((data.length - width * 4) / Math.max(1, pixelHeight - 1));
  return Math.max(width * 4, inferred);
}

function samplePixel(data, rowStrideBytes, y, x) {
  const i = y * rowStrideBytes + x * 4;
  let r = data[i] || 0;
  let g = data[i + 1] || 0;
  let b = data[i + 2] || 0;
  // Keep empty background dark blue instead of pure black so the pane has depth.
  if (r === 0 && g === 0 && b === 0) return [4, 7, 20];
  return [r, g, b];
}

function clampColor(value) {
  return Math.max(0, Math.min(255, Math.round(value)));
}

function createWireframeRenderer(width, height, sceneName) {
  const THREE = safeRequire('three');
  if (!THREE) throw new Error('three dependency is not installed; run npm install');
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, Math.max(0.2, width / Math.max(1, height * 2)), 0.1, 100);
  camera.position.set(0, 0.25, 4.2);
  camera.lookAt(0, 0, 0);

  const cube = new THREE.Mesh(
    new THREE.BoxGeometry(1.65, 1.65, 1.65),
    new THREE.MeshBasicMaterial({ color: 0x66ccff, wireframe: true })
  );
  scene.add(cube);

  const vertices = [
    [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
    [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]
  ].map(([x, y, z]) => new THREE.Vector3(x * 0.82, y * 0.82, z * 0.82));
  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7]
  ];
  const palette = [[110, 220, 255], [138, 180, 255], [196, 140, 255], [255, 206, 122]];

  return {
    threeRevision: THREE.REVISION,
    render(time) {
      cube.rotation.x = time * 0.67;
      cube.rotation.y = time * 0.93;
      cube.rotation.z = Math.sin(time * 0.37) * 0.26;
      cube.updateMatrixWorld(true);
      camera.updateMatrixWorld(true);
      camera.updateProjectionMatrix();
      const grid = Array.from({ length: height }, () => Array.from({ length: width }, () => ({ ch: ' ', color: null })));
      drawBackdrop(grid, width, height, time);
      const projected = vertices.map((vertex) => {
        const world = vertex.clone().applyMatrix4(cube.matrixWorld);
        const ndc = world.clone().project(camera);
        return { x: Math.round((ndc.x * 0.5 + 0.5) * (width - 1)), y: Math.round((-ndc.y * 0.5 + 0.5) * (height - 1)), z: world.z };
      });
      edges.forEach(([a, b], index) => {
        const pa = projected[a];
        const pb = projected[b];
        const depth = (pa.z + pb.z) * 0.5;
        const color = palette[index % palette.length].map((v, channel) => clampColor(v * Math.max(0, Math.min(1, 0.62 + (1.6 - depth) * 0.13)) + (channel === 0 ? 20 * Math.sin(time + index) : 0)));
        drawLine(grid, pa.x, pa.y, pb.x, pb.y, color, index % 3 === 0 ? '◆' : '█');
      });
      return gridToAnsi(grid);
    }
  };
}

function drawBackdrop(grid, width, height, time) {
  const stars = Math.max(6, Math.floor(width * height / 70));
  for (let i = 0; i < stars; i++) {
    const x = (i * 17 + 3) % width;
    const y = (i * 11 + 5) % Math.max(1, height - 3);
    const pulse = 0.45 + 0.45 * Math.sin(time * 1.7 + i * 1.91);
    const c = Math.round(68 + pulse * 90);
    put(grid, x, y, i % 3 === 0 ? '·' : '.', [c, c + 10, c + 28]);
  }
}

function drawLine(grid, x0, y0, x1, y1, color, ch) {
  let dx = Math.abs(x1 - x0);
  let sx = x0 < x1 ? 1 : -1;
  let dy = -Math.abs(y1 - y0);
  let sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  let x = x0;
  let y = y0;
  for (;;) {
    put(grid, x, y, ch, color);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) err += dy, x += sx;
    if (e2 <= dx) err += dx, y += sy;
  }
}

function put(grid, x, y, ch, color) {
  if (y < 0 || y >= grid.length || x < 0 || x >= grid[y].length) return;
  grid[y][x] = { ch, color };
}

function gridToAnsi(grid) {
  return grid.map((row) => {
    let out = '';
    let last = null;
    for (const cell of row) {
      if (cell.color) {
        const key = cell.color.join(';');
        if (key !== last) out += `${ESC}[38;2;${key}m`, last = key;
        out += cell.ch;
      } else {
        if (last !== null) out += `${ESC}[0m`, last = null;
        out += ' ';
      }
    }
    if (last !== null) out += `${ESC}[0m`;
    return out;
  }).join('\n');
}

function shutdown(code) {
  if (stopped) return;
  stopped = true;
  if (timer) clearTimeout(timer);
  try { rendererState?.dispose?.(); } catch {}
  process.exit(code);
}

process.on('SIGTERM', () => shutdown(0));
process.on('SIGINT', () => shutdown(0));
process.on('beforeExit', () => {
  try { rendererState?.dispose?.(); } catch {}
});

main().catch((error) => {
  emit({ type: 'error', message: String(error && error.message || error).slice(0, 160) });
  shutdown(2);
});
