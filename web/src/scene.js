// The forge: a molten core (the agent) with the seven factory stages orbiting it.
// The scene carries information: node colour = stage state, core colour = exam score, pulse = running stage.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const COLORS = { idle: 0x5b6472, done: 0x37d39a, warn: 0xffb020, active: 0xff7a1a };

export function createForge(container, labelsEl, stages, onPick) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch {
    container.classList.add('no-webgl');
    return { select() {}, setStates() {}, setScore() {}, setBusy() {} };
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0b0d12, 16, 34);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 6.2, 15);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableZoom = false;
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.minPolarAngle = 0.7;
  controls.maxPolarAngle = 1.45;
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  scene.add(new THREE.AmbientLight(0x8090b0, 0.7));
  const heat = new THREE.PointLight(0xff7a1a, 60, 30);
  scene.add(heat);
  const rim = new THREE.DirectionalLight(0x9ec5ff, 1.2);
  rim.position.set(-6, 8, 4);
  scene.add(rim);

  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.35, 1),
    new THREE.MeshStandardMaterial({ color: 0x241206, emissive: 0xff6a00, emissiveIntensity: 0.9, flatShading: true, roughness: 0.4, metalness: 0.6 }),
  );
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.9, 1), new THREE.MeshBasicMaterial({ color: 0xffa04d, wireframe: true, transparent: true, opacity: 0.28 }));
  scene.add(core, shell);

  const RADIUS = 6;
  const ring = new THREE.Mesh(new THREE.TorusGeometry(RADIUS, 0.025, 8, 180), new THREE.MeshBasicMaterial({ color: 0x3a4252 }));
  ring.rotation.x = Math.PI / 2;
  scene.add(ring);

  const nodeGeo = new THREE.OctahedronGeometry(0.52, 0);
  const nodes = stages.map((s, i) => {
    const a = (i / stages.length) * Math.PI * 2 - Math.PI / 2;
    const mesh = new THREE.Mesh(nodeGeo, new THREE.MeshStandardMaterial({ color: COLORS.idle, emissive: COLORS.idle, emissiveIntensity: 0.35, metalness: 0.7, roughness: 0.3 }));
    mesh.position.set(Math.cos(a) * RADIUS, 0, -Math.sin(a) * RADIUS * -1);
    mesh.userData = { index: i, state: 'idle' };
    const spoke = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), mesh.position]), new THREE.LineBasicMaterial({ color: 0x2b3140, transparent: true, opacity: 0.8 }));
    const halo = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.02, 8, 60), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0 }));
    halo.position.copy(mesh.position);
    mesh.userData.halo = halo;
    scene.add(spoke, mesh, halo);

    const label = document.createElement('button');
    label.className = 'node-label';
    label.innerHTML = `<b>${i + 1}</b>${s.title}`;
    label.addEventListener('click', () => onPick(i));
    labelsEl.appendChild(label);
    mesh.userData.label = label;
    return mesh;
  });

  // Sparks travelling stage to stage show the direction of the pipeline.
  const sparkCount = 60;
  const sparks = new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(sparkCount * 3), 3)),
    new THREE.PointsMaterial({ color: 0xffc07a, size: 0.12, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  const embers = new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(Float32Array.from({ length: 600 }, (_, i) => (i % 3 === 1 ? Math.random() * 8 - 3 : (Math.random() - 0.5) * 5)), 3)),
    new THREE.PointsMaterial({ color: 0xff7a1a, size: 0.05, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  scene.add(sparks, embers);

  let selected = 0;
  let busy = false;
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let downAt = null;
  const pick = (e) => {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    return ray.intersectObjects(nodes)[0]?.object;
  };
  renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 6) return;
    const hit = pick(e);
    if (hit) onPick(hit.userData.index);
  });
  renderer.domElement.addEventListener('pointermove', (e) => { renderer.domElement.style.cursor = pick(e) ? 'pointer' : 'grab'; });

  new ResizeObserver(() => {
    const { clientWidth: w, clientHeight: h } = container;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.position.setLength(w < 700 ? 24 : 16.2);
    camera.updateProjectionMatrix();
  }).observe(container);

  const clock = new THREE.Clock();
  const v = new THREE.Vector3();
  renderer.setAnimationLoop(() => {
    const t = still ? 0 : clock.getElapsedTime();
    core.rotation.set(t * 0.25, t * (busy ? 1.2 : 0.35), 0);
    shell.rotation.set(-t * 0.12, -t * 0.18, 0);
    const pulse = 1 + Math.sin(t * (busy ? 6 : 1.6)) * (busy ? 0.09 : 0.035);
    core.scale.setScalar(pulse);

    nodes.forEach((n, i) => {
      const on = i === selected;
      n.rotation.y = t * (on ? 1.4 : 0.4) + i;
      const active = n.userData.state === 'active';
      n.scale.setScalar((on ? 1.35 : 1) * (active ? 1 + Math.sin(t * 7) * 0.18 : 1));
      n.userData.halo.material.opacity = on ? 0.75 : 0;
      n.userData.halo.lookAt(camera.position);
      v.copy(n.position).add({ x: 0, y: 1.15, z: 0 }).project(camera);
      const l = n.userData.label;
      l.style.transform = `translate(-50%,-50%) translate(${(v.x * 0.5 + 0.5) * container.clientWidth}px, ${(-v.y * 0.5 + 0.5) * container.clientHeight}px)`;
      l.classList.toggle('on', on);
    });

    const sp = sparks.geometry.attributes.position;
    for (let i = 0; i < sparkCount; i++) {
      const f = ((i / sparkCount) + t * (busy ? 0.12 : 0.035)) % 1;
      const a = f * Math.PI * 2 - Math.PI / 2;
      sp.setXYZ(i, Math.cos(a) * RADIUS, Math.sin(f * 40 + t * 2) * 0.12, Math.sin(a) * RADIUS);
    }
    sp.needsUpdate = true;
    const ep = embers.geometry.attributes.position;
    if (!still) {
      for (let i = 0; i < ep.count; i++) {
        const y = ep.getY(i) + (busy ? 0.05 : 0.012);
        ep.setY(i, y > 5 ? -3 : y);
      }
      ep.needsUpdate = true;
    }
    controls.update();
    renderer.render(scene, camera);
  });

  return {
    select(i) { selected = i; },
    setStates(states) {
      nodes.forEach((n, i) => {
        const s = states[i] || 'idle';
        n.userData.state = s;
        n.material.color.setHex(COLORS[s]);
        n.material.emissive.setHex(COLORS[s]);
        n.userData.label.dataset.state = s;
      });
    },
    setScore(ratio) {
      // red-hot when failing, bright forge-gold when passing
      const c = new THREE.Color().setHSL(0.01 + ratio * 0.1, 1, 0.5);
      core.material.emissive.copy(c);
      heat.color.copy(c);
    },
    setBusy(v_) { busy = v_; },
  };
}
