import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { AU_PER_LY } from './stars.js';

const MAP_RADIUS_LY = 20;  // 星図に出す範囲（船からの半径）
const STAR_PX = 6;         // 星図の星の点の大きさ
const REBUILD_LY = 0.5;    // 船がこれだけ動いたら星図に出す星を選び直す

// 選択の印に使う、正方形の枠の形に切り抜く小さな画像を作る（拡大縮小でにじまないよう最近傍で引く）
function squareFrame() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 18;
  const context = canvas.getContext('2d');
  context.strokeStyle = '#fff';
  context.lineWidth = 2;
  context.strokeRect(1, 1, 16, 16);
  const texture = new THREE.CanvasTexture(canvas);
  texture.magFilter = texture.minFilter = THREE.NearestFilter;
  return texture;
}

// 星図。アンチエイリアスなしで点はすべて正方形。船を中心に半径MAP_RADIUS_LYの星（恒星の色の点）と、訪れた星系を順に結ぶ線、船の位置、選択中の星の輪を3Dで描く
// ドラッグで回転・ホイールで拡大縮小し、星をクリックするとonSelectでその星を選び、ダブルクリックするとonOpenでその星系の天体一覧を開く。位置は船からの光年で表す
export function createStarMap(panel, stars, onSelect, onOpen) {
  const host = panel.querySelector('.地図描画');
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setPixelRatio(devicePixelRatio);
  host.appendChild(renderer.domElement);
  const labels = document.createElement('div');
  host.appendChild(labels);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1000);
  camera.position.set(0, 14, 26);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  scene.add(new THREE.PolarGridHelper(MAP_RADIUS_LY, 12, 4, 96, 0x4a4740, 0x2a2824));

  const starPoints = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({
    size: STAR_PX, sizeAttenuation: false, vertexColors: true,
  }));
  const pathLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xdcd9d0 }));
  const shipPoint = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ size: 10, sizeAttenuation: false, color: 0xffffff }));
  const selectedRing = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ size: 18, sizeAttenuation: false, color: 0xffffff, map: squareFrame(), alphaTest: 0.5 }));
  scene.add(starPoints, pathLine, shipPoint, selectedRing);

  let nearby = [];
  const builtAt = new THREE.Vector3(Infinity, 0, 0);

  // 船からの光年の位置
  const toMap = (pos, ship) => pos.clone().sub(ship).divideScalar(AU_PER_LY);

  // カーソルの位置に最も近い星
  const pick = (e) => {
    const rect = renderer.domElement.getBoundingClientRect();
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points.threshold = camera.position.distanceTo(controls.target) * 0.02;
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1), camera);
    const hit = raycaster.intersectObject(starPoints).sort((a, b) => a.distanceToRay - b.distanceToRay)[0];
    return hit && nearby[hit.index];
  };

  // クリック（ドラッグでないとき）で星を選び、ダブルクリックでその星系の一覧を開く
  const DRAG_THRESHOLD_PX = 5;
  const down = new THREE.Vector2();
  renderer.domElement.addEventListener('pointerdown', (e) => down.set(e.clientX, e.clientY));
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > DRAG_THRESHOLD_PX) return;
    const star = pick(e);
    if (star) onSelect(star);
  });
  renderer.domElement.addEventListener('dblclick', (e) => {
    const star = pick(e);
    if (star) onOpen(star);
  });

  // 開いている間、毎フレーム呼ぶ。船が動いたら近くの星を選び直し、訪れた星系の線・選択の輪・名前を更新して描く
  return function update(ship, visited, selected) {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (renderer.domElement.width !== Math.round(width * renderer.getPixelRatio())) {
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    if (builtAt.distanceTo(ship) > REBUILD_LY * AU_PER_LY) {
      builtAt.copy(ship);
      nearby = stars.filter((s) => s.pos.distanceTo(ship) < MAP_RADIUS_LY * AU_PER_LY);
      starPoints.geometry.dispose();
      starPoints.geometry = new THREE.BufferGeometry()
        .setAttribute('position', new THREE.Float32BufferAttribute(nearby.flatMap((s) => toMap(s.pos, ship).toArray()), 3))
        .setAttribute('color', new THREE.Float32BufferAttribute(nearby.flatMap((s) => s.color.toArray()), 3));
    }
    starPoints.position.copy(toMap(builtAt, ship));
    pathLine.geometry.dispose();
    pathLine.geometry = new THREE.BufferGeometry().setFromPoints([...visited.map((s) => toMap(s.pos, ship)), new THREE.Vector3()]);
    const target = selected?.star ?? selected;
    selectedRing.visible = !!target;
    if (target) selectedRing.position.copy(toMap(target.pos, ship));
    controls.update();
    renderer.render(scene, camera);

    // 訪れた星系と選択中の星に名前を添える（カメラの後ろは出さない）
    const named = [...new Set([...visited, target].filter(Boolean))];
    labels.innerHTML = named.map((s) => {
      const p = toMap(s.pos, ship).project(camera);
      if (p.z > 1) return '';
      return `<span class="地図名${s === target ? ' 選択' : ''}" style="left:${Math.round(((p.x + 1) / 2) * width)}px;top:${Math.round(((1 - p.y) / 2) * height)}px">${s.name}</span>`;
    }).join('');
  };
}
