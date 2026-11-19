import * as THREE from 'three';
import { AU_PER_LY, generateStars } from './stars.js';
import { createStarMap } from './map.js';
import { makePlanetMesh, placePlanetMesh, makeStarMesh, setStar, bodyPhoto, makeGlare } from './planets.js';
import { relUniforms, ABERRATION_GLSL, STELLAR_GLSL, CMB_TEMPERATURE, aberrate, relativistic, createCmb } from './relativity.js';

const LIGHT_YEAR_SECONDS = 60;      // 光が1光年進むのにかかるゲーム内の秒数（光速の設定）
const START_ALTITUDE_KM = 400;      // 開始時の地球周回軌道の高度
const TURN_SPEED = 1.2;             // 標準視野角での最大角速度（rad/秒）
const SHIP_MASS = 1e5;              // 船の質量（kg）。仮の値
const SHIP_LENGTH = 30;             // 船を立方体とみなしたときの一辺（m）。仮の値
const THRUSTER_TORQUE = 2e7;        // 姿勢制御スラスターのトルク（N·m）
const MAIN_THRUST = 1e8;            // メインエンジンの最大推力（N）。惑星圏での加速度は推力÷質量（約100G）
const THRUST_RAMP_TIME = 2;         // 押し始めの1%から最大推力まで指数的に強まる秒数
const ACCEL_RATE = 1.0;             // 押し続けた1秒あたりの固有速度の増加率
const SYSTEM_SPEED_REF = 1e-9;      // 星系内モードの加減速の基準（光速に対する固有速度。約160 km/s）
const SYSTEM_SPEED_MAX = 0.01;      // 星系内モードの最高固有速度
const INTERSTELLAR_SPEED_REF = 1;   // 恒星間モードの加減速の基準。移行演出はこの速度まで加速する
const CAPTURE_FACTOR = 3;           // 重力圏内で惑星に対する速さがその位置の脱出速度のこの倍を下回ったら重力に捕まる
const SPOOL_TIME = 3;               // 星系内の最高速度から恒星間の基準速度へ移る演出の秒数
const DROP_TIME = 2;                // Interstellar解除時に星系内の最高速度まで落とす演出の秒数
const BRAKE_TIME = 3;               // 境界へ近づくときの減速の時定数（秒）。境界までの距離÷この秒数を上限速度にする
const STEP_FRACTION = 0.005;        // 惑星圏の運動の積分刻み（力学的時間 √(r³/GM) に対する割合）
const MAX_SUBSTEPS = 4000;          // 1フレームの積分刻みの上限。時間加速中はこれを超えないよう刻みを広げる
const PREDICT_STEP = 0.02;          // 予想軌道の積分刻み（同上）
const PREDICT_POINTS = 2000;        // 予想軌道の最大点数
const FOV_DEFAULT = 60;
const FOV_MIN = 1e-5;
const FOV_MAX = 120;
const ZOOM_STEP = 1.15;
const STAR_PX_SCALE = 6;            // 1光年先の太陽が見える大きさ（px）。明るさの4乗根に比例させる
const STAR_PX_MAX = 20;
const PLANET_PX = 3;
const PLANET_SHOW_PX = 8;           // 惑星系の見かけの半径がこのpxを超えたら惑星を表示する
const PICK_PX = 14;                 // クリックで天体を選べる距離
const PHOTO_PX = 56;                // 選択中の天体の横に出す写真の大きさ（CSSの#目標写真と揃える）。天体の見かけの直径がこれを超えたら写真を畳む
const SAS_LOG_LINES = 40;           // SAS記録欄に残す行数
const SNAP_DEG = 3;                 // 見渡した視点が機首からこの角度以内に戻ったら機首へ吸い付かせる
const SNAP_TIME = 0.12;             // 吸い付くときのイーズの時定数（秒）

const C = AU_PER_LY / LIGHT_YEAR_SECONDS; // 光速（AU/秒）
const KM_PER_AU = 1.495978707e8;

const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(FOV_DEFAULT, innerWidth / innerHeight, 1e-8, 1e9);
const button = document.getElementById('恒星間ボタン');
const target = document.getElementById('目標');
const targetBody = document.getElementById('目標本文');
const targetPhoto = document.getElementById('目標写真');
const infoPhoto = Object.assign(document.createElement('img'), { id: '情報写真', alt: '' });
const targetInfo = document.getElementById('目標情報');
let photoBody = null; // 写真に描いている天体

// UIの表示・非表示の統一の動き（0.3秒）。消すときは下辺が上辺へ上がって1pxの線になり、次に右端が左端へ縮んで消える。出すときはその逆再生
// mirroredは右から出るもの用に左右反転し、左端が右端へ縮む。動きの間だけclip-pathを上書きし、終わったら外して元のCSSに戻す
const FOLD_FRAMES = [
  { clipPath: 'inset(0 0 0 0)' },
  { clipPath: 'inset(0 0 calc(100% - 1px) 0)', offset: 0.5 },
  { clipPath: 'inset(0 calc(100% - 1px) calc(100% - 1px) 0)' },
];
const FOLD_FRAMES_MIRRORED = [
  { clipPath: 'inset(0 0 0 0)' },
  { clipPath: 'inset(0 0 calc(100% - 1px) 0)', offset: 0.5 },
  { clipPath: 'inset(0 0 calc(100% - 1px) calc(100% - 1px))' },
];
function setShown(el, shown, mirrored = false) {
  if (el.shown === shown) return;
  el.shown = shown;
  el.getAnimations().forEach((a) => a.cancel());
  if (shown) el.hidden = false;
  const animation = el.animate(mirrored ? FOLD_FRAMES_MIRRORED : FOLD_FRAMES, { duration: 300, direction: shown ? 'reverse' : 'normal', fill: 'forwards' });
  animation.onfinish = () => {
    if (!el.shown) el.hidden = true;
    animation.cancel();
  };
}
const infoTab = document.getElementById('情報タブ');
const infoBody = infoTab.querySelector('.中身');
const conditionBody = document.querySelector('#状態タブ .中身');
const sasLog = document.getElementById('記録');
const noseMark = document.getElementById('機首');
const sasButtons = document.querySelectorAll('[data-姿勢]');
const navMarks = [['.順行', 1, 'vel'], ['.逆行', -1, 'vel'], ['.外向き', 1, 'rel'], ['.内向き', -1, 'rel']]
  .map(([selector, sign, key]) => ({ el: document.querySelector(selector), sign, key }));
const clock = new THREE.Clock();
const keys = new Set();
const rel = new THREE.Vector3();
const scratch = new THREE.Vector3();
const tmp = new THREE.Vector3();
const center = new THREE.Vector3();
const acc = new THREE.Vector3();
const pfs = new THREE.Vector3();
const sv = new THREE.Vector3();
const qv = new THREE.Vector3();
const zero = new THREE.Vector3();
const HOST = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()]; // bodyOffsetの入れ子ごとの作業用

const stars = generateStars();
const planets = stars.flatMap((s) => s.planets);
planets.forEach((p, i) => (p.index = i));
const maxPlanets = Math.max(...stars.map((s) => s.planets.length));
const companions = stars.map((s) => s.companion).filter(Boolean);

// 各惑星の赤道面の基底（衛星の軌道面）。惑星の描画と同じく、公転面の法線を地軸の傾きぶん倒した向きを地軸にする
planets.forEach((p) => {
  const axis = new THREE.Quaternion().setFromAxisAngle(p.star.u, p.tilt)
    .multiply(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3().crossVectors(p.star.u, p.star.v)));
  p.eq1 = new THREE.Vector3(1, 0, 0).applyQuaternion(axis);
  p.eq2 = new THREE.Vector3(0, 0, -1).applyQuaternion(axis);
});

// 自機は常に原点に置き、天体の倍精度座標から自機座標を引いて描画する（Floating Origin）
const ship = new THREE.Vector3();
let properSpeed = 0; // 固有速度 γβ（後退は負）。惑星圏では宇宙系での速さ
const turnRate = new THREE.Vector2(); // 機体の角速度（x=ピッチ, y=ヨー, rad/秒）
let sasMode = 'off'; // SASが向き続ける方向（off / target / pro / retro / radout / radin）
let sasLocked = false;  // SASが目標方向に合っているか
let sasPlanned = false; // 今の回頭の計画を記録済みか
let sasElapsed = 0;     // 回頭を始めてからの実時間
const shipQuat = new THREE.Quaternion(); // 船の姿勢。カメラは船の姿勢に見渡しの向きを重ねたもの
const look = { yaw: 0, pitch: 0, dragging: false, moved: false, wasFree: false, track: null }; // 船に対する視点の向き（rad）、ドラッグの状態、追尾中の天体
let thrustHeld = 0;  // 推力キーを押し続けている秒数
let thrustRatio = 0; // 今の推力の最大推力に対する割合（負は逆噴射）
let worldTime = 0;
let shipTime = 0;
let warp = 1; // 時間加速の倍率（実時間1秒あたりに進む船内時間の秒数）
let mode = 'planet';  // system → armed（星系内の最高速度待ち）→ spool（移行演出）→ interstellar → drop（解除演出）→ system。planet は惑星の重力圏
let transition = null;
let departure = null; // Interstellarを押したときにいた星系。出るまでは突入判定から外す
let escaping = null;  // 惑星圏脱出ボタンで離れた惑星。重力圏を出るまでは捕まらない
let selected = null;  // 選択中の恒星か惑星（惑星は .star を持つ）
let current = null;
let focus = undefined;
const visited = []; // 訪れた星系（入った順）
const local = { body: null, rel: new THREE.Vector3(), vel: new THREE.Vector3(), landed: false }; // 惑星圏での惑星基準の位置（AU）と速度（AU/s）

// 開始位置：地球の昼側、黄道面内の順行の円軌道に置き、地球を足元にして進行方向を向く
local.body = stars[0].planets.find((p) => p.name === 'Earth');
local.rel.copy(bodyOffset(local.body, 0, 0, tmp)).negate().setLength(local.body.radiusAU + START_ALTITUDE_KM / KM_PER_AU);
local.vel.crossVectors(scratch.crossVectors(local.body.star.u, local.body.star.v), local.rel).setLength(Math.sqrt(local.body.gm / local.rel.length()));
ship.copy(bodyPosition(local.body, 0, center)).add(local.rel);
camera.up.copy(local.rel).normalize();
camera.lookAt(scratch.copy(local.vel));
shipQuat.copy(camera.quaternion);

// count個の光点をまとめて描くPointsを作る（対数深度・光行差対応）
// 恒星（stellar）は温度と光度を渡し、ドップラー因子Dで温度をD倍した黒体の色と、放射流束D²倍×可視域の割合の変化から明るさを決める
// それ以外は頂点ごとの色と大きさを渡し、明るさだけD²倍（上限1）にする
function makeMarkers(count, stellar) {
  const pos = new Float32Array(count * 3);
  const extra = stellar ? { temp: new Float32Array(count), lum: new Float32Array(count) } : { tint: new Float32Array(count * 3), size: new Float32Array(count) };
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  Object.entries(extra).forEach(([name, array]) => geometry.setAttribute(name, new THREE.BufferAttribute(array, name === 'tint' ? 3 : 1)));
  const points = new THREE.Points(geometry, new THREE.ShaderMaterial({
    uniforms: {
      ...relUniforms,
      pixelRatio: { value: renderer.getPixelRatio() },
      pxScale: { value: STAR_PX_SCALE },
      pxMax: { value: STAR_PX_MAX },
      auPerLy: { value: AU_PER_LY },
    },
    vertexShader: `
      attribute vec3 tint;
      attribute float size;
      attribute float temp;
      attribute float lum;
      uniform float pixelRatio;
      uniform float pxScale;
      uniform float pxMax;
      uniform float auPerLy;
      varying vec3 vTint;
      #include <common>
      #include <logdepthbuf_pars_vertex>
      ${ABERRATION_GLSL}
      ${STELLAR_GLSL}
      void main() {
        float D;
        vec3 seen = aberrate(position, D);
        ${stellar ? `
          float shifted = temp * D;
          float dly = length(position) / auPerLy;
          float px = pxScale * pow(lum * D * D * visibleFraction(shifted) / visibleFraction(temp) / (dly * dly), 0.25);
          vTint = blackbody(shifted) * min(1.0, px / 1.5);
          gl_PointSize = clamp(px, 1.5, pxMax) * pixelRatio;
        ` : `
          vTint = tint * min(1.0, D * D);
          gl_PointSize = size * pixelRatio;
        `}
        gl_Position = projectionMatrix * modelViewMatrix * vec4(seen, 1.0);
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `
      varying vec3 vTint;
      #include <logdepthbuf_pars_fragment>
      void main() {
        #include <logdepthbuf_fragment>
        float a = smoothstep(1.0, 0.3, length(gl_PointCoord - 0.5) * 2.0);
        gl_FragColor = vec4(vTint * a, 1.0);
      }`,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    transparent: true,
  }));
  points.frustumCulled = false;
  scene.add(points);
  return { geometry, pos, ...extra };
}

scene.add(createCmb(camera));

// 生成範囲の外の遠い星々（約1600光年先）。温度3000〜15000K、光度10³〜10⁴·⁵L☉の巨星として、光行差とドップラーを同じように受ける
const background = makeMarkers(4000, true);
Array.from({ length: 4000 }, (_, i) => {
  const z = Math.random() * 2 - 1;
  const a = Math.random() * Math.PI * 2;
  const r = Math.sqrt(1 - z * z);
  background.pos.set([r * Math.cos(a) * 1e8, r * Math.sin(a) * 1e8, z * 1e8], i * 3);
  background.temp[i] = 3000 * 5 ** Math.random();
  background.lum[i] = 10 ** (3 + 1.5 * Math.random());
});

const starMarks = makeMarkers(stars.length, true);
stars.forEach((s, i) => {
  starMarks.temp[i] = s.T;
  starMarks.lum[i] = s.L;
});
const companionMarks = makeMarkers(Math.max(1, companions.length), true);
companions.forEach((c, i) => {
  companionMarks.temp[i] = c.T;
  companionMarks.lum[i] = c.L;
});
const planetMarks = makeMarkers(planets.length, false);
const trueMarks = makeMarkers(maxPlanets, false);
const starMesh = makeStarMesh();
const planetGroup = new THREE.Group(); // 今いる（または選んだ）星系の惑星と衛星だけをシェーダーで描く
const companionMesh = makeStarMesh();
let focusBodies = [];
const orbits = new THREE.LineSegments(new THREE.BufferGeometry(), relativistic(new THREE.LineBasicMaterial({ color: 0x2a3a55 })));
const binaryOrbits = new THREE.LineSegments(new THREE.BufferGeometry(), orbits.material);
const moonOrbits = new THREE.Group(); // 衛星の軌道線。衛星を持つ惑星ごとに1本ずつ、親惑星に付けて動かす
const predictLine = new THREE.Line(new THREE.BufferGeometry(), relativistic(new THREE.LineDashedMaterial({ color: 0xdcd9d0, transparent: true, opacity: 0.8 })));
predictLine.frustumCulled = false;
const glare = makeGlare();
scene.add(starMesh, companionMesh, planetGroup, orbits, binaryOrbits, moonOrbits, predictLine, glare);

// 円軌道の項。中心から半径a・周期period（負なら逆行）・位相phaseで、基底e1→e2の向きに回る天体の、宇宙時刻tでの位置（derivative 0）・速度（1）・加速度（2）
function orbitTerm(e1, e2, a, period, phase, t, derivative, out) {
  const w = (Math.PI * 2) / period;
  const angle = phase + w * t;
  const [c, s] = [Math.cos(angle), Math.sin(angle)];
  const [x, y, k] = [[c, s, a], [-s, c, a * w], [-c, -s, a * w * w]][derivative];
  return out.copy(e1).multiplyScalar(x * k).addScaledVector(e2, y * k);
}

// 連星の公転による、主星（companionなら伴星）の重心からのずれ・速度・加速度。両星は質量の逆比の距離で共通重心を回る
function starMotion(star, t, derivative, companion, out) {
  const c = star.companion;
  if (!c) return out.set(0, 0, 0);
  const share = companion ? star.M / (star.M + c.M) : -c.M / (star.M + c.M);
  return orbitTerm(star.u, star.v, c.a * share, c.period, c.phase, t, derivative, out);
}

// 天体の、星系の重心からの位置（derivative 0）・速度（1）・加速度（2）を宇宙時刻tで求める
// 恒星・伴星は連星の公転、惑星は主星（周連星惑星は重心）を中心に公転面で、衛星は親惑星を中心に赤道面で円軌道を回る
function bodyOffset(b, t, derivative, out, level = 0) {
  if (b.primary) return starMotion(b.primary, t, derivative, true, out);
  if (!b.star) return starMotion(b, t, derivative, false, out);
  const host = b.parent ? bodyOffset(b.parent, t, derivative, HOST[level], level + 1)
    : b.circumbinary ? HOST[level].set(0, 0, 0) : starMotion(b.star, t, derivative, false, HOST[level]);
  const [e1, e2] = b.parent ? [b.parent.eq1, b.parent.eq2] : [b.star.u, b.star.v];
  return orbitTerm(e1, e2, b.a, b.period * (b.direction ?? 1), b.phase, t, derivative, out).add(host);
}

// 天体の属する星系の主星
function systemOf(b) {
  return b.primary ?? b.star ?? b;
}

// 宇宙時刻tにおける天体の実際の位置をoutに書き込む
function bodyPosition(b, t, out) {
  return bodyOffset(b, t, 0, out).add(systemOf(b).pos);
}

// 今自機に届いている光を天体が発した時刻を、t = 現在 − 距離(t)/c の不動点反復で求める
function emissionTime(p, t, depth) {
  const next = worldTime - bodyPosition(p, t, scratch).distanceTo(ship) / C;
  return depth >= 10 || Math.abs(next - t) < 1e-9 ? next : emissionTime(p, next, depth + 1);
}

// 惑星基準の位置rの船が受ける相対加速度。惑星・両恒星・他の惑星・この惑星の衛星の万有引力の和から、惑星自身の軌道上の加速度を引く
function localAccel(body, r, t, out) {
  const star = body.star;
  bodyOffset(body, t, 0, pfs);
  sv.addVectors(pfs, r);
  out.copy(r).multiplyScalar(-body.gm / r.lengthSq() ** 1.5);
  [[star, false], [star.companion, true]].forEach(([source, companion]) => {
    if (!source) return;
    starMotion(star, t, 0, companion, qv).sub(sv);
    out.addScaledVector(qv, source.gm / qv.lengthSq() ** 1.5);
  });
  [...star.planets, ...body.moons].forEach((q) => {
    if (q === body) return;
    bodyOffset(q, t, 0, qv).sub(sv);
    out.addScaledVector(qv, q.gm / qv.lengthSq() ** 1.5);
  });
  return out.sub(bodyOffset(body, t, 2, qv));
}

// 積分の刻みの基準にする力学的時間 √(r³/GM)。惑星と、この惑星の衛星のうち船に近く短いほう
function dynamicalTime(body, r, t) {
  return body.moons.reduce((min, m) => {
    const d = bodyOffset(m, t, 0, qv).sub(bodyOffset(body, t, 0, pfs)).sub(r).length();
    return Math.min(min, Math.sqrt(d ** 3 / m.gm));
  }, Math.sqrt(r.lengthSq() ** 1.5 / body.gm));
}

// 相対位置rと速度vを時刻tからh秒進める（速度ベルレ法）。extraは推力などの一定加速度
function verlet(body, r, v, t, h, extra) {
  v.addScaledVector(localAccel(body, r, t, acc).add(extra), h / 2);
  r.addScaledVector(v, h);
  v.addScaledVector(localAccel(body, r, t + h, acc).add(extra), h / 2);
}

// 力学的時間に比例した刻み（1フレームの刻み数には上限）でremaining秒ぶん進める。地表を割り込んだら地表に置いて惑星に対して静止させる
function advance(body, r, v, t, remaining, extra) {
  const minStep = remaining / MAX_SUBSTEPS;
  while (remaining > 0) {
    const h = Math.min(remaining, Math.max(minStep, STEP_FRACTION * dynamicalTime(body, r, t)));
    verlet(body, r, v, t, h, extra);
    local.landed = r.length() < body.radiusAU;
    if (local.landed) {
      r.setLength(body.radiusAU);
      v.set(0, 0, 0);
    }
    t += h;
    remaining -= h;
  }
}

// 推力なしで進めた軌道を点列に記録し、終わり方（impact 地表に当たる / escape 重力圏を出る / orbit 1周回り切る / limit 点数の上限）と一緒に返す
function predict(body, r, v, t, remaining, points) {
  points.push(r.x, r.y, r.z);
  const dist = r.length();
  const end = dist < body.radiusAU ? 'impact' : dist > body.soi ? 'escape' : remaining <= 0 ? 'orbit' : points.length >= PREDICT_POINTS * 3 ? 'limit' : null;
  if (end) return { points, end };
  const h = Math.min(remaining, PREDICT_STEP * dynamicalTime(body, r, t));
  verlet(body, r, v, t, h, zero);
  return predict(body, r, v, t + h, remaining - h, points);
}

// 恒星（伴星）・惑星・衛星・軌道線の詳細表示を、指定した星系に切り替える
// 軌道線は、主星を回る惑星は主星に、周連星惑星と連星自身の軌道は重心に付ける
function setFocus(star) {
  focus = star;
  focusBodies = star ? [...star.planets, ...star.planets.flatMap((p) => p.moons)] : [];
  [starMesh, orbits, binaryOrbits, moonOrbits].forEach((o) => (o.visible = !!star));
  companionMesh.visible = !!star?.companion;
  planetGroup.children.forEach((m) => {
    m.material.dispose();
    m.userData.ring?.material.dispose();
  });
  planetGroup.clear();
  if (!star) return;
  focusBodies.forEach((b) => planetGroup.add(makePlanetMesh(b)));
  const circle = (radius) => Array.from({ length: 256 }, (_, i) => [i, i + 1].map((j) => {
    const a = (j / 256) * Math.PI * 2;
    return new THREE.Vector3().addScaledVector(star.u, Math.cos(a) * radius).addScaledVector(star.v, Math.sin(a) * radius);
  })).flat();
  const c = star.companion;
  orbits.geometry.dispose();
  orbits.geometry = new THREE.BufferGeometry().setFromPoints(star.planets.filter((p) => !p.circumbinary).flatMap((p) => circle(p.a)));
  moonOrbits.children.forEach((line) => line.geometry.dispose());
  moonOrbits.clear();
  star.planets.filter((p) => p.moons.length).forEach((p) => {
    const ring = (m) => Array.from({ length: 128 }, (_, i) => [i, i + 1].map((j) => {
      const a = (j / 128) * Math.PI * 2;
      return new THREE.Vector3().addScaledVector(p.eq1, Math.cos(a) * m.a).addScaledVector(p.eq2, Math.sin(a) * m.a);
    })).flat();
    const line = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(p.moons.flatMap(ring)), orbits.material);
    line.frustumCulled = false;
    line.userData.planet = p;
    moonOrbits.add(line);
  });
  binaryOrbits.geometry.dispose();
  binaryOrbits.geometry = new THREE.BufferGeometry().setFromPoints([
    ...star.planets.filter((p) => p.circumbinary).flatMap((p) => circle(p.a)),
    ...(c ? [...circle((c.a * c.M) / (star.M + c.M)), ...circle((c.a * star.M) / (star.M + c.M))] : []),
  ]);
}

// 秒数を桁に応じた単位の文字列にする
function formatTime(s) {
  if (!Number.isFinite(s)) return '∞';
  if (s < 600) return `${s.toFixed(2)} s`;
  if (s < 36000) return `${(s / 60).toFixed(2)} min`;
  if (s < 864000) return `${(s / 3600).toFixed(2)} h`;
  if (s < 63115200) return `${(s / 86400).toFixed(2)} d`;
  const years = s / 31557600;
  return years < 1e6 ? `${years.toFixed(1)} yr` : `${years.toExponential(2)} yr`;
}

// 時間加速の倍率を「実時間1秒あたりに進む時間」の表記にする
function formatWarp(w) {
  const [unit, seconds] = [['y', 31557600], ['d', 86400], ['h', 3600], ['min', 60], ['s', 1]].find(([, s]) => w >= s * 0.9999);
  return `${(w / seconds).toPrecision(3)} ${unit}/s`;
}

// 宇宙の静止系での速さ（AU/s）を、1時間あたりの距離で km/h → Ls/h → Lh/h → Ly/h と桁に応じて表す（Ls・Lh・Lyは実際の光秒・光時・光年の距離）
function formatSpeed(auPerSecond) {
  const kmPerHour = auPerSecond * KM_PER_AU * 3600;
  const units = [['Ly/h', 299792.458 * 31557600], ['Lh/h', 299792.458 * 3600], ['Ls/h', 299792.458], ['km/h', 1]];
  const [unit, km] = units.find(([, k]) => kmPerHour >= k) ?? units[3];
  const value = kmPerHour / km;
  return `${value >= 1e4 ? Math.round(value).toLocaleString() : value.toPrecision(4)} ${unit}`;
}

// AU単位の距離を桁に応じて光年・AU・kmの文字列にする
function formatDistance(au) {
  if (!Number.isFinite(au)) return '∞';
  if (au > AU_PER_LY * 0.01) return `${(au / AU_PER_LY).toFixed(3)} LY`;
  return au > 0.01 ? `${au.toFixed(3)} AU` : `${Math.round(au * KM_PER_AU).toLocaleString()} km`;
}

// 自機から向きdirへまっすぐ進んだとき最初に入る球（中心center(b)・半径radius(b)）と、その境界までの距離を求める。出発星系は除く
function rayEntry(dir, bodies, centerOf, radiusOf) {
  return bodies.reduce((hit, b) => {
    if (b === departure) return hit;
    const f = scratch.subVectors(ship, centerOf(b));
    const bDot = f.dot(dir);
    const radius = radiusOf(b);
    const disc = bDot * bDot - (f.lengthSq() - radius * radius);
    const dist = -bDot - Math.sqrt(disc);
    return disc > 0 && dist >= 0 && dist < hit.dist ? { body: b, dist } : hit;
  }, { body: null, dist: Infinity });
}

// 現在の固有速度から速さtoへ、対数スケールのイーズでduration秒かけて移る演出を始める
function startTransition(next, to, duration) {
  mode = next;
  transition = { from: properSpeed, to, t: 0, duration };
}

// 航行状態ごとの計器表示とボタン表記
const MODE_LABELS = {
  system: ['System', 'Interstellar'],
  armed: ['Standby (reach max speed)', 'Standby — Accelerate'],
  spool: ['Engaging', 'Engaging'],
  interstellar: ['Interstellar', 'Disengage'],
  drop: ['Decelerating', 'Decelerating'],
  planet: ['Planetary', 'Leave planet zone'],
};
const CLASS_NAMES = { V: 'Main sequence', III: 'Giant', I: 'Supergiant', D: 'White dwarf' };

// 項目と値（と行に付けるクラス）の組を、引き出し線でつないだ計器の行のHTMLにする
function rows(pairs) {
  return pairs.map(([label, value, cls = '']) => `<div class="行 ${cls}"><span>${label}</span><i></i><b>${value}</b></div>`).join('');
}

// 惑星・衛星の種類名
function planetType(p) {
  if (p.parent) return 'Moon';
  return p.radiusEarth < 3.2 ? 'Rocky' : p.radiusEarth < 6 ? 'Ice giant' : 'Gas giant';
}

// 天体一覧の表。行は [天体, 名前, 種類, 軌道長半径, 公転周期]。衛星は名前の頭を字下げする
function bodyTable(entries) {
  const row = ([b, name, type, a, period]) => `<tr>
    <td><i class="惑星色" style="background:#${b.color.getHexString()}"></i>${b.parent ? '└ ' : ''}${name}</td>
    <td>${type}</td><td>${formatDistance(a)}</td><td>${formatTime(period)}</td></tr>`;
  return `<table class="惑星表"><tr><th>Name</th><th>Type</th><th>Orbit</th><th>Period</th></tr>${entries.map(row).join('')}</table>`;
}

// 選択中の天体の情報タブの中身を作る。恒星の表には伴星と惑星を、惑星の表には衛星を載せる
function infoHtml(body, d) {
  if (!body) return '<h2 class="見出し">Object<br>Data</h2><p class="空">Nothing selected</p>';
  if (body.star) {
    const surfaceGravity = (body.gm / body.radiusAU ** 2) * KM_PER_AU * 1000;
    const host = body.parent ?? (body.circumbinary ? { name: `${body.star.name} AB` } : body.star);
    return `<h2 class="見出し">${body.parent ? 'Lunar' : 'Planetary'}<br>Data</h2>
      <div class="通し番号">#${body.name} / ${planetType(body)}</div>
      <div class="星名"><ul class="一覧"><li>Orbiting ${host.name}</li><li>${formatDistance(d)}</li></ul></div>
      ${rows([
        ['Orbit', formatDistance(body.a)],
        ['Period', `${formatTime(body.period)}${body.direction < 0 ? ' (retrograde)' : ''}`],
        ['Radius', `${body.radiusEarth.toFixed(3)} R⊕ / ${Math.round(body.radiusAU * KM_PER_AU).toLocaleString()} km`],
        ['Mass', `${body.massEarth.toPrecision(3)} M⊕`],
        ['Surface gravity', `${surfaceGravity.toFixed(2)} m/s²`],
        ...(body.teq ? [['Equilibrium temp.', `${Math.round(body.teq)} K`]] : []),
        ['Escape velocity', `${(Math.sqrt((2 * body.gm) / body.radiusAU) * KM_PER_AU).toFixed(2)} km/s`],
        ...(body.parent ? [] : [['Sphere of influence', formatDistance(body.soi)]]),
        ['Distance', formatDistance(d)],
        ['Light delay', formatTime(d / C)],
      ])}
      ${body.moons.length ? `<h3 class="小見出し">Moons</h3>${bodyTable(body.moons.map((m) => [m, m.name.replace(body.name, '').trim() || m.name, 'Moon', m.a, m.period]))}` : ''}`;
  }
  const c = body.companion;
  const entries = [
    ...(c ? [[c, c.name.replace(body.name, '').trim() || c.name, c.label, c.a, c.period]] : []),
    ...body.planets.flatMap((p) => [
      [p, p.name.replace(body.name, '').trim() || p.name, `${planetType(p)}${p.circumbinary ? ' (P)' : ''}`, p.a, p.period],
      ...p.moons.map((m) => [m, m.name.replace(p.name, '').trim() || m.name, 'Moon', m.a, m.period]),
    ]),
  ];
  return `<h2 class="見出し">Stellar<br>Data</h2>
    <div class="通し番号">#${body.name} / ${body.label}</div>
    <div class="星名"><ul class="一覧"><li>${CLASS_NAMES[body.cls]}${body.primary ? ` / companion of ${body.primary.name}` : ''}</li><li>${formatDistance(d)}</li>${body.primary ? '' : `<li>Planets ${body.planets.length}</li>`}</ul></div>
    ${rows([
      ['Temperature', `${Math.round(body.T).toLocaleString()} K`],
      ['Luminosity', `${body.L.toPrecision(3)} L☉`],
      ['Radius', `${body.R.toPrecision(3)} R☉`],
      ['Mass', `${body.M.toPrecision(3)} M☉`],
      ...(body.primary ? [['Binary separation', formatDistance(body.a)], ['Binary period', formatTime(body.period)]] : []),
      ['Distance', formatDistance(d)],
      ['Light delay', formatTime(d / C)],
      ...(body.primary ? [] : [['System edge', `${body.edge.toFixed(1)} AU`]]),
    ])}
    ${body.primary ? '' : `<h3 class="小見出し">System</h3>${entries.length ? bodyTable(entries) : '<p class="空">No companions or planets detected</p>'}`}`;
}

// SASの記録欄に船内時刻つきの1行を足し、古い行を捨てて最下部を見せる
function logSas(text) {
  const s = Math.floor(shipTime);
  const stamp = `T+${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  sasLog.textContent = [...sasLog.textContent.split('\n').filter(Boolean), `${stamp} ${text}`].slice(-SAS_LOG_LINES).join('\n') + '\n';
  sasLog.scrollTop = sasLog.scrollHeight;
}

// SASの方向を切り替え、ボタンの点灯を合わせて記録する
function setSas(next, reason) {
  sasMode = next;
  sasLocked = false;
  sasPlanned = false;
  sasButtons.forEach((b) => b.classList.toggle('作動中', b.dataset['姿勢'] === next));
  logSas(next === 'off' ? `SAS OFF${reason ? ` (${reason})` : ''}` : `SAS ENGAGE ${next.toUpperCase()}`);
}

// SASが向くべきワールド座標の方向。今の状態で定まらなければnull
function sasDirection() {
  if (sasMode === 'target' && selected) {
    return bodyPosition(selected, selected.tEmit ?? worldTime, new THREE.Vector3()).sub(ship);
  }
  if (mode !== 'planet') return null;
  return { pro: local.vel.clone(), retro: local.vel.clone().negate(), radout: local.rel.clone(), radin: local.rel.clone().negate() }[sasMode] ?? null;
}

// 1フレーム分の操舵・推進・時間経過を進め、天体を自機基準に置き直して描画と計器を更新する
function tick() {
  // dtauは実時間（操作の反応と演出に使う）、dtは時間加速をかけた船内時間（運動と時刻に使う）
  const dtau = Math.min(clock.getDelta(), 0.1);
  const dt = dtau * warp;
  // 姿勢制御：目標角速度へ、トルク÷慣性モーメント（立方体 mL²/6）の角加速度αで近づける。入力がなければ0へ減速する
  // SASは目標方向とのピッチ・ヨーのずれθから、αで止まりきれる角速度 √(2αθ) を目標にする。WASDを押すと解除
  const zoom = camera.fov / FOV_DEFAULT;
  const alpha = THRUSTER_TORQUE / ((SHIP_MASS * SHIP_LENGTH ** 2) / 6);
  const manual = new THREE.Vector2(keys.has('KeyW') - keys.has('KeyS'), keys.has('KeyA') - keys.has('KeyD'));
  if (manual.lengthSq() && sasMode !== 'off') setSas('off', 'manual input');
  const sasTarget = sasDirection();
  const sasDir = sasTarget?.lengthSq() > 0 ? sasTarget.applyQuaternion(shipQuat.clone().invert()).normalize() : null;
  // 機首(0,0,-1)から目標への最短回転（回転軸 = 機首×目標 = (y, −x, 0)、角度θ）をピッチとヨーの成分に分ける。真後ろならピッチで回る
  const theta = sasDir ? Math.acos(THREE.MathUtils.clamp(-sasDir.z, -1, 1)) : 0;
  const axisLength = sasDir ? Math.hypot(sasDir.x, sasDir.y) : 0;
  const sasError = sasDir && (axisLength > 1e-9 ? new THREE.Vector2(sasDir.y, -sasDir.x).multiplyScalar(theta / axisLength) : new THREE.Vector2(theta, 0));
  const sasRate = (error) => Math.sign(error) * Math.min(TURN_SPEED, 0.9 * Math.sqrt(2 * alpha * Math.abs(error)), Math.abs(error) / Math.max(dtau, 1e-3));
  const want = sasError ? new THREE.Vector2(sasRate(sasError.x), sasRate(sasError.y)) : manual.multiplyScalar(TURN_SPEED * zoom);
  const maxStep = alpha * (sasDir ? 1 : zoom) * dtau;
  turnRate.x += THREE.MathUtils.clamp(want.x - turnRate.x, -maxStep, maxStep);
  turnRate.y += THREE.MathUtils.clamp(want.y - turnRate.y, -maxStep, maxStep);
  if (sasError) {
    // 回頭の始めに、目標とのずれと、αとωmaxで回り切る最短時間（加速→巡航→減速）を記録し、0.05°以内に合ったら所要時間を記録する。1°以上ずれたら計画し直す
    const deg =(rad) => `${rad < 0 ? '-' : '+'}${Math.abs(THREE.MathUtils.radToDeg(rad)).toFixed(2)}°`;
    if (!sasPlanned) {
      const eta = theta < TURN_SPEED ** 2 / alpha ? 2 * Math.sqrt(theta / alpha) : theta / TURN_SPEED + TURN_SPEED / alpha;
      logSas(`AIM ${sasMode.toUpperCase()} Δp${deg(sasError.x)} Δy${deg(sasError.y)} θ ${THREE.MathUtils.radToDeg(theta).toFixed(2)}° ETA ${eta.toFixed(2)} s`);
      sasPlanned = true;
      sasElapsed = 0;
    }
    sasElapsed += dtau;
    if (!sasLocked && theta < THREE.MathUtils.degToRad(0.05)) logSas(`LOCKED ${sasMode.toUpperCase()} in ${sasElapsed.toFixed(2)} s`);
    if (sasLocked && theta > THREE.MathUtils.degToRad(1)) {
      logSas(`DRIFT ${THREE.MathUtils.radToDeg(theta).toFixed(2)}°`);
      sasPlanned = false;
    }
    sasLocked = theta < THREE.MathUtils.degToRad(sasLocked ? 1 : 0.05);
  }
  shipQuat.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), turnRate.x * dtau));
  shipQuat.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), turnRate.y * dtau));
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(shipQuat);

  // 見渡し：追尾中は選んだ天体の方へ視点をイーズで向け続ける（船の向きとは無関係）。そうでなく視点が機首からSNAP_DEG以内なら機首へ戻す
  // カメラは船の姿勢に見渡しの向きを重ねる
  if (look.track && !look.dragging) {
    const t = look.track;
    const d = bodyPosition(t, t.tEmit ?? worldTime, new THREE.Vector3()).sub(ship).applyQuaternion(shipQuat.clone().invert()).normalize();
    const ease = 1 - Math.exp(-dtau / SNAP_TIME);
    look.yaw += (THREE.MathUtils.euclideanModulo(Math.atan2(-d.x, -d.z) - look.yaw + Math.PI, Math.PI * 2) - Math.PI) * ease;
    look.pitch += (Math.atan2(d.y, Math.hypot(d.x, d.z)) - look.pitch) * ease;
  } else if (!look.dragging && Math.hypot(look.yaw, look.pitch) < THREE.MathUtils.degToRad(SNAP_DEG)) {
    const keep = Math.exp(-dtau / SNAP_TIME);
    look.yaw = Math.abs(look.yaw * keep) < 1e-5 ? 0 : look.yaw * keep;
    look.pitch = Math.abs(look.pitch * keep) < 1e-5 ? 0 : look.pitch * keep;
  }
  camera.quaternion.copy(shipQuat).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(look.pitch, look.yaw, 0, 'YXZ')));
  const viewForward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  const throttle = keys.has('Space') - (keys.has('ShiftLeft') || keys.has('ShiftRight'));

  if (mode === 'planet') {
    // 惑星圏：惑星基準の相対運動を推力と万有引力で積分する。速さは光速より桁違いに小さいので宇宙時間＝船内時間とみなす
    // 推力は押し始めの1%から押し続けるほど指数的に強まり、THRUST_RAMP_TIME秒で最大になる。短く押せば微調整になる
    const body = local.body;
    thrustHeld = throttle ? thrustHeld + dtau : 0;
    thrustRatio = throttle * Math.min(1, 0.01 * 100 ** (thrustHeld / THRUST_RAMP_TIME));
    advance(body, local.rel, local.vel, worldTime, dt, tmp.copy(forward).multiplyScalar((thrustRatio * MAIN_THRUST) / SHIP_MASS / (KM_PER_AU * 1000)));
    worldTime += dt;
    shipTime += dt;
    ship.copy(bodyPosition(body, worldTime, center)).add(local.rel);
    properSpeed = bodyOffset(body, worldTime, 1, tmp).add(local.vel).length() / C;
    if (local.rel.length() > body.soi * 1.02) {
      // 重力圏を出たら星系内の巡航に戻り、惑星に対する速度の機首方向成分を引き継ぐ
      mode = 'system';
      properSpeed = THREE.MathUtils.clamp(local.vel.dot(forward) / C, -SYSTEM_SPEED_MAX, SYSTEM_SPEED_MAX);
      local.body = null;
    }
  } else {
    if (mode === 'system' || mode === 'armed' || mode === 'interstellar') {
      properSpeed += throttle * ACCEL_RATE * Math.max(Math.abs(properSpeed), mode === 'interstellar' ? INTERSTELLAR_SPEED_REF : SYSTEM_SPEED_REF) * dtau;
    }
    if (mode === 'system' || mode === 'armed') properSpeed = THREE.MathUtils.clamp(properSpeed, -SYSTEM_SPEED_MAX, SYSTEM_SPEED_MAX);
    if (mode === 'armed' && properSpeed >= SYSTEM_SPEED_MAX) startTransition('spool', INTERSTELLAR_SPEED_REF, SPOOL_TIME);
    if (transition) {
      transition.t = Math.min(1, transition.t + dtau / transition.duration);
      const ease = transition.t * transition.t * (3 - 2 * transition.t);
      properSpeed = Math.sign(transition.from) * Math.exp(THREE.MathUtils.lerp(Math.log(Math.abs(transition.from)), Math.log(transition.to), ease));
      if (transition.t === 1) {
        mode = mode === 'spool' ? 'interstellar' : 'system';
        transition = null;
      }
    }

    // 高速時は先の星系の境界までの距離に比例した上限速度を設け、近づくほど指数的に減速させる
    const dir = forward.clone().multiplyScalar(Math.sign(properSpeed) || 1);
    const fast = Math.abs(properSpeed) > SYSTEM_SPEED_MAX;
    const localPlanets = (mode === 'system' || mode === 'armed') && current ? current.planets : [];
    const hit = fast ? rayEntry(dir, stars, (s) => s.pos, (s) => s.edge) : { body: null, dist: Infinity };
    const allowed = SYSTEM_SPEED_MAX + hit.dist / (C * BRAKE_TIME * warp);
    if (hit.body && Math.abs(properSpeed) > allowed) {
      if (mode === 'spool') {
        mode = 'interstellar';
        transition = null;
      }
      properSpeed = Math.sign(properSpeed) * (allowed + (Math.abs(properSpeed) - allowed) * Math.exp(-dtau / 0.3));
    }

    // 実時間は船内時間として進み、宇宙時間はγ倍進む。移動量は宇宙系の速度×宇宙時間 = γβc×船内時間
    const gamma = Math.sqrt(1 + properSpeed * properSpeed);
    shipTime += dt;
    worldTime += gamma * dt;
    const moveLength = Math.abs(properSpeed) * C * dt;
    if (hit.body && hit.dist <= moveLength) {
      // 星系の境界を飛び越えないよう、境界の少し内側で星系内モードに戻す
      ship.addScaledVector(dir, hit.dist + hit.body.edge * 0.001);
      mode = 'system';
      transition = null;
      properSpeed = THREE.MathUtils.clamp(properSpeed, -SYSTEM_SPEED_MAX, SYSTEM_SPEED_MAX);
    } else {
      ship.addScaledVector(dir, moveLength);
    }

    // 星系内の巡航は、最寄りの惑星の重力圏に近づくほどその惑星の公転に乗った座標系で行う（重力圏の半径の10倍→1倍で0→1）
    const near = localPlanets.reduce((best, p) => {
      const ratio = bodyPosition(p, worldTime, center).distanceTo(ship) / p.soi;
      return ratio < best.ratio ? { p, ratio } : best;
    }, { p: null, ratio: Infinity });
    const frameWeight = THREE.MathUtils.clamp((10 - near.ratio) / 9, 0, 1);
    if (near.p) ship.addScaledVector(bodyOffset(near.p, worldTime, 1, tmp), frameWeight * gamma * dt);
    if (escaping && (near.p !== escaping || near.ratio > 1)) escaping = null;
    if (near.p && near.ratio < 1 && near.p !== escaping) {
      // 重力圏内で惑星に対する速さが脱出速度の数倍まで落ちたら重力に捕まり、その速度のまま惑星基準の相対運動に切り替える
      const vRel = dir.clone().multiplyScalar(Math.abs(properSpeed) * C).addScaledVector(bodyOffset(near.p, worldTime, 1, tmp), frameWeight - 1);
      const r = bodyPosition(near.p, worldTime, center).distanceTo(ship);
      if (vRel.length() < CAPTURE_FACTOR * Math.sqrt((2 * near.p.gm) / r)) {
        mode = 'planet';
        transition = null;
        local.body = near.p;
        local.rel.subVectors(ship, center);
        local.vel.copy(vRel);
      }
    }
  }
  current = stars.find((s) => s.pos.distanceToSquared(ship) < s.edge * s.edge) ?? null;
  if (current && visited.at(-1) !== current) visited.push(current);
  if (departure !== current) departure = null;
  const wantFocus = current ?? (selected && systemOf(selected));
  if (wantFocus !== focus) setFocus(wantFocus);

  // 宇宙の静止系での船の速度を、光行差とドップラーのシェーダーへ渡す。惑星圏では惑星の公転速度と相対速度の和（光速比、γβ≒β）
  const velocity = mode === 'planet'
    ? bodyOffset(local.body, worldTime, 1, new THREE.Vector3()).add(local.vel).divideScalar(C)
    : forward.clone().multiplyScalar(properSpeed);
  relUniforms.uU.value = velocity.length();
  relUniforms.uGamma.value = Math.sqrt(1 + velocity.lengthSq());
  if (velocity.lengthSq() > 0) relUniforms.uVelDir.value.copy(velocity).normalize();

  // 恒星の光点は位置だけ渡し、大きさと色はシェーダーが温度・光度・距離・ドップラーから決める。連星は主星・伴星をそれぞれの位置に置く
  const focalPx = innerHeight / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  stars.forEach((s, i) => {
    bodyPosition(s, worldTime, rel).sub(ship).toArray(starMarks.pos, i * 3);
    const d = rel.length();
    const visible = (s.planetSpan / d) * focalPx > PLANET_SHOW_PX;
    s.planets.forEach((p) => {
      planetMarks.size[p.index] = visible ? PLANET_PX : 0;
      if (!visible && s !== focus && (selected && systemOf(selected)) !== s) return;
      p.tEmit = emissionTime(p, worldTime - d / C, 0);
      bodyPosition(p, p.tEmit, rel).sub(ship).toArray(planetMarks.pos, p.index * 3);
      p.color.toArray(planetMarks.tint, p.index * 3);
      p.moons.forEach((m) => (m.tEmit = p.tEmit));
    });
    if (s !== focus) return;
    s.planets.forEach((p, j) => {
      trueMarks.size[j] = visible ? PLANET_PX : 0;
      bodyPosition(p, worldTime, rel).sub(ship).toArray(trueMarks.pos, j * 3);
      trueMarks.tint.set([1, 0.25, 0.25], j * 3);
    });
    trueMarks.size.fill(0, s.planets.length);
  });
  if (!focus) trueMarks.size.fill(0);
  companions.forEach((c, i) => bodyPosition(c, worldTime, rel).sub(ship).toArray(companionMarks.pos, i * 3));
  companionMarks.geometry.attributes.position.needsUpdate = true;
  [starMarks, planetMarks, trueMarks].forEach((m) => Object.values(m.geometry.attributes).forEach((a) => (a.needsUpdate = true)));

  if (focus) {
    bodyPosition(focus, worldTime, starMesh.position).sub(ship);
    const flux = focus.L / starMesh.position.lengthSq();
    setStar(starMesh, focus, worldTime, flux);
    orbits.position.copy(starMesh.position);
    binaryOrbits.position.subVectors(focus.pos, ship);
    moonOrbits.children.forEach((line) => bodyPosition(line.userData.planet, line.userData.planet.tEmit ?? worldTime, line.position).sub(ship));
    const c = focus.companion;
    if (c) {
      bodyPosition(c, worldTime, companionMesh.position).sub(ship);
      setStar(companionMesh, c, worldTime, c.L / companionMesh.position.lengthSq());
    }
    // 惑星と衛星は主星の光を基準に、伴星の光も明るさの比（光度÷距離²）で重ねて照らす
    focusBodies.forEach((b, i) => {
      const position = bodyPosition(b, b.tEmit ?? worldTime, new THREE.Vector3()).sub(ship);
      const second = c && {
        position: companionMesh.position,
        color: c.color,
        weight: (c.L / position.distanceToSquared(companionMesh.position)) / (focus.L / position.distanceToSquared(starMesh.position)),
      };
      placePlanetMesh(planetGroup.children[i], b, position, starMesh.position, focus.color, worldTime, null, second);
    });

    // 恒星のまぶしさ：受ける光の強さ（光度÷距離²）の4乗根に比例したにじみを、見かけの円盤の大きさに足して画面上の恒星の位置に重ねる
    // 恒星が視野の後ろにあるか、手前の惑星に隠れていれば消す
    const distance = starMesh.position.length();
    const toStar = starMesh.position.clone().divideScalar(distance);
    const hidden = planetGroup.children.some((m) => {
      const along = m.position.dot(toStar);
      return along > 0 && along < distance && m.position.lengthSq() - along * along < m.scale.x * m.scale.x;
    });
    camera.updateMatrixWorld();
    aberrate(rel.copy(starMesh.position));
    const glareOn = !hidden && rel.dot(viewForward) > 0;
    rel.project(camera);
    const pixelRatio = renderer.getPixelRatio();
    glare.material.uniforms.uCenter.value.set(((rel.x + 1) / 2) * innerWidth * pixelRatio, ((rel.y + 1) / 2) * innerHeight * pixelRatio);
    glare.material.uniforms.uHalo.value = (120 * flux ** 0.25 + (focus.radiusAU / distance) * focalPx) * pixelRatio;
    glare.material.uniforms.uStrength.value = glareOn ? Math.min(1.5, flux ** 0.25) : 0;
    glare.material.uniforms.uColor.value.copy(focus.color).convertLinearToSRGB();
  }
  glare.visible = !!focus;

  // 惑星圏では接触軌道要素を求め、推力なしの予想軌道を惑星の現在位置基準の点線で描く。衝突予想の点滅は実時間0.4秒ごと
  const blinkOn = Math.floor(performance.now() / 400) % 2 === 0;
  const orbit = mode === 'planet' ? (() => {
    const body = local.body;
    const r = local.rel.length();
    const energy = local.vel.lengthSq() / 2 - body.gm / r;
    const angular = new THREE.Vector3().crossVectors(local.rel, local.vel);
    const ecc = new THREE.Vector3().crossVectors(local.vel, angular).divideScalar(body.gm).addScaledVector(local.rel, -1 / r).length();
    const sma = -body.gm / (2 * energy);
    const period = energy < 0 ? 2 * Math.PI * Math.sqrt(sma ** 3 / body.gm) : Infinity;
    const { points, end } = predict(body, local.rel.clone(), local.vel.clone(), worldTime, period, []);
    // 地表に当たる予想なら赤の点滅、1周回り切れば緑、それ以外は白
    const state = local.landed ? 'none' : end === 'impact' ? 'impact' : end === 'orbit' ? 'orbit' : 'none';
    predictLine.material.color.set({ impact: 0xff4b3a, orbit: 0x6be38f, none: 0xdcd9d0 }[state]);
    predictLine.material.opacity = state === 'impact' && !blinkOn ? 0.15 : 0.8;
    const positions = new Float32Array(points.map((v, i) => v - local.rel.getComponent(i % 3)));
    predictLine.geometry.dispose();
    predictLine.geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(positions, 3));
    predictLine.computeLineDistances();
    const distances = predictLine.geometry.attributes.lineDistance;
    predictLine.material.dashSize = predictLine.material.gapSize = distances.getX(distances.count - 1) / 300 || 1e-9;
    return {
      body, r, ecc, period, end, state,
      speed: local.vel.length(),
      vertical: local.vel.dot(local.rel) / r,
      horizontal: Math.sqrt(Math.max(0, local.vel.lengthSq() - (local.vel.dot(local.rel) / r) ** 2)),
      periapsis: energy < 0 ? sma * (1 - ecc) : angular.lengthSq() / (body.gm * (1 + ecc)),
      apoapsis: energy < 0 ? sma * (1 + ecc) : Infinity,
    };
  })() : null;
  predictLine.visible = !!orbit;
  renderer.render(scene, camera);
  if (mapPanel.shown) updateStarMap(ship, visited, selected);

  const gamma = Math.sqrt(1 + properSpeed * properSpeed);
  const beta = properSpeed / gamma;
  const selectedPos = selected && bodyPosition(selected, selected.tEmit ?? worldTime, new THREE.Vector3());
  const d = selectedPos?.distanceTo(ship);
  // 情報タブの写真は作り直さず、見出しのすぐ後ろへ差し込み直す（毎フレームの書き換えで画像がちらつかないように）
  if (infoTab.classList.contains('開いている')) {
    infoBody.innerHTML = infoHtml(selected, d);
    if (selected && infoPhoto.dataset['天体'] !== selected.name) {
      infoPhoto.src = bodyPhoto(renderer, selected);
      infoPhoto.dataset['天体'] = selected.name;
    }
    infoPhoto.hidden = !selected;
    infoBody.querySelector('.見出し').after(infoPhoto);
  }
  {
    // 速度ゲージは固有速度の対数で、星系内の基準速度から恒星間の速度までを表す
    const gauge = THREE.MathUtils.clamp((Math.log10(Math.max(Math.abs(properSpeed), 1e-8)) + 8) / 10, 0, 1);
    // 衝突予想のときだけ、危険な値（状態と近点高度）の行を赤く点滅させる
    const danger = orbit?.state === 'impact' ? `危険${blinkOn ? '' : ' 消灯'}` : '';
    const altitude = (au) => (Number.isFinite(au) ? `${Math.round((au - orbit.body.radiusAU) * KM_PER_AU).toLocaleString()} km` : '∞');
    conditionBody.innerHTML = `<h2 class="見出し">Ship<br>Condition</h2>
      ${rows([['Mode', MODE_LABELS[mode][0]], ['Current system', current ? `${current.name} ${current.label}` : '—']])}
      ${orbit ? `<h3 class="小見出し">Orbit</h3>${rows([
        ['Orbiting', orbit.body.name],
        ['Status', local.landed ? 'Landed' : { impact: 'Impact course', orbit: 'Stable orbit', escape: 'Escape trajectory', limit: orbit.ecc < 1 ? 'Bound orbit' : 'Escape trajectory' }[orbit.end], danger],
        ['Altitude', altitude(orbit.r)],
        ['Periapsis', altitude(orbit.periapsis), danger],
        ['Apoapsis', altitude(orbit.apoapsis)],
        ['Eccentricity', orbit.ecc.toFixed(4)],
        ['Period', formatTime(orbit.period)],
        ['Circular speed', `${(Math.sqrt(orbit.body.gm / orbit.r) * KM_PER_AU).toFixed(3)} km/s`],
      ])}` : ''}
      <h3 class="小見出し">Velocity</h3>
      <div class="ゲージ"><i style="width:${gauge * 100}%"></i></div>
      <div class="ゲージ目盛"><span>10⁻⁸</span><span>10⁻⁴</span><span>c</span><span>10² γβ</span></div>
      ${rows([
        ['Speed', formatSpeed(Math.abs(beta) * C)],
        ...(orbit ? [
          ['Relative speed', `${(orbit.speed * KM_PER_AU).toFixed(3)} km/s`],
          ['Horizontal speed', `${(orbit.horizontal * KM_PER_AU).toFixed(3)} km/s`],
          ['Vertical speed', `${(orbit.vertical * KM_PER_AU).toFixed(3)} km/s`],
        ] : []),
      ])}
      <h3 class="小見出し">Relativity</h3>
      ${rows([
        ['Lorentz factor γ', gamma.toPrecision(6)],
        ['Doppler fore / aft', `×${(gamma + Math.abs(properSpeed)).toPrecision(4)} / ×${(1 / (gamma + Math.abs(properSpeed))).toPrecision(4)}`],
        ['CMB fore', `${(CMB_TEMPERATURE * (gamma + Math.abs(properSpeed))).toPrecision(4)} K`],
      ])}
      <h3 class="小見出し">Propulsion</h3>
      ${rows([
        ...(orbit ? [['Thrust', `${Math.round(thrustRatio * 100)}% / ${((thrustRatio * MAIN_THRUST) / SHIP_MASS / 9.80665).toFixed(1)} G`]] : []),
        ['Turn rate', `${THREE.MathUtils.radToDeg(turnRate.length()).toFixed(1)} °/s`],
      ])}
      <h3 class="小見出し">Time</h3>
      ${rows([['Universe time', formatTime(worldTime)], ['Ship time', formatTime(shipTime)]])}`;
  }

  // 機首方向の十字。見渡しているときは機首のある位置へずれ、視野の外なら消える
  rel.copy(forward);
  noseMark.hidden = rel.dot(viewForward) <= 0;
  if (!noseMark.hidden) {
    rel.project(camera);
    noseMark.style.left = `${Math.round(((rel.x + 1) / 2) * innerWidth)}px`;
    noseMark.style.top = `${Math.round(((1 - rel.y) / 2) * innerHeight)}px`;
  }

  // 惑星圏では順行・逆行・外向き・内向きの方向を画面上に標識で示す
  navMarks.forEach((m) => {
    m.el.hidden = mode !== 'planet' || local[m.key].lengthSq() === 0;
    if (m.el.hidden) return;
    rel.copy(local[m.key]).normalize().multiplyScalar(m.sign);
    m.el.hidden = rel.dot(viewForward) <= 0;
    rel.project(camera);
    m.el.style.left = `${Math.round(((rel.x + 1) / 2) * innerWidth)}px`;
    m.el.style.top = `${Math.round(((1 - rel.y) / 2) * innerHeight)}px`;
  });

  // SASの軌道方向は惑星圏だけ、Targetは天体を選んでいるときだけ使える。使えなくなったらOffに戻す
  sasButtons.forEach((b) => {
    const key = b.dataset['姿勢'];
    const unavailable = key === 'target' ? !selected : key !== 'off' && mode !== 'planet';
    setShown(b, !unavailable);
    if (unavailable && sasMode === key) setSas('off', 'unavailable');
  });

  // 画面中央下のボタンは惑星圏では脱出、それ以外はInterstellar。選択中の天体の横に写真・名前・距離・今の速度のままの到達予想（船内時間）とInfoボタンを出す
  setShown(button, true);
  button.textContent = MODE_LABELS[mode][1];
  button.classList.toggle('待機中', mode === 'armed');
  button.classList.toggle('作動中', mode !== 'system' && mode !== 'armed' && mode !== 'planet');
  aberrate(rel.subVectors(selectedPos ?? ship, ship));
  const targetVisible = !!selected && rel.dot(viewForward) > 0;
  setShown(targetInfo, targetVisible);
  if (!targetVisible) return;
  rel.project(camera);
  target.style.left = `${Math.round(((rel.x + 1) / 2) * innerWidth)}px`;
  target.style.top = `${Math.round(((1 - rel.y) / 2) * innerHeight)}px`;
  // 写真は選んだ天体が変わったときだけ塗り直し、天体の見かけの直径が写真より大きくなったら消す（離れたら出す）
  if (photoBody !== selected) {
    photoBody = selected;
    targetPhoto.innerHTML = `<img src="${bodyPhoto(renderer, selected)}" alt="">`;
  }
  setShown(targetPhoto, ((selected.radiusAU * 2) / d) * focalPx < PHOTO_PX);
  targetBody.innerHTML = `<div class="目標名">${selected.name}</div><div class="目標副">
    <span>> ${formatDistance(d)}</span><span>> ETA ${properSpeed ? formatTime(d / (Math.abs(properSpeed) * C)) : '∞'}</span></div>`;
}

// ドラッグで景色を見渡す。動かした量は視野角に合わせ、カーソルの下の景色がそのまま付いてくるようにする
const DRAG_THRESHOLD_PX = 5;
renderer.domElement.addEventListener('pointerdown', (e) => {
  look.dragging = true;
  look.moved = false;
  look.wasFree = !!look.track || Math.hypot(look.yaw, look.pitch) >= THREE.MathUtils.degToRad(SNAP_DEG);
  look.track = null;
  look.startX = e.clientX;
  look.startY = e.clientY;
  renderer.domElement.setPointerCapture(e.pointerId);
  renderer.domElement.classList.add('見渡し中');
});
renderer.domElement.addEventListener('pointermove', (e) => {
  if (!look.dragging) return;
  look.moved ||= Math.hypot(e.clientX - look.startX, e.clientY - look.startY) > DRAG_THRESHOLD_PX;
  const radPerPx = THREE.MathUtils.degToRad(camera.fov) / innerHeight;
  look.yaw = THREE.MathUtils.euclideanModulo(look.yaw + e.movementX * radPerPx + Math.PI, Math.PI * 2) - Math.PI;
  look.pitch = THREE.MathUtils.clamp(look.pitch + e.movementY * radPerPx, -Math.PI / 2 + 0.01, Math.PI / 2 - 0.01);
});
renderer.domElement.addEventListener('pointerup', () => {
  look.dragging = false;
  renderer.domElement.classList.remove('見渡し中');
});

renderer.domElement.addEventListener('click', (e) => {
  if (look.moved) return;
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  // カメラ基準の位置vの光行差を受けた見かけの位置が、画面上でクリック位置から何px離れているか（背後なら無限大）
  const screenDistance = (v) => {
    if (aberrate(v).dot(forward) <= 0) return Infinity;
    v.project(camera);
    return Math.hypot(((v.x + 1) / 2) * innerWidth - e.clientX, ((1 - v.y) / 2) * innerHeight - e.clientY);
  };
  const best = [
    ...stars.map((s) => [s, screenDistance(bodyPosition(s, worldTime, rel).sub(ship))]),
    ...companions.map((c) => [c, screenDistance(bodyPosition(c, worldTime, rel).sub(ship))]),
    ...focusBodies.filter((b) => b.parent).map((m) => [m, screenDistance(bodyPosition(m, m.tEmit ?? worldTime, rel).sub(ship))]),
    ...planets.filter((p) => planetMarks.size[p.index] > 0 || p.star === focus)
      .map((p) => [p, screenDistance(rel.fromArray(planetMarks.pos, p.index * 3))]),
  ].reduce((acc, c) => (c[1] < acc[1] ? c : acc), [null, PICK_PX]);
  if (!best[0]) return;
  selected = best[0];
  // 見渡し中（または追尾中）に選んだ天体は、視点の中心にとらえ続ける
  if (look.wasFree) look.track = selected;
});
// 星図：右下のMAPボタンで開閉し、星図で星をクリックすると宇宙で星をクリックしたのと同じように選ぶ
const mapPanel = document.getElementById('地図');
const mapButton = document.getElementById('地図ボタン');
const mapList = mapPanel.querySelector('.地図一覧');
let mapListBodies = [];
// 星図でダブルクリックした星系の、恒星・伴星・惑星・衛星の一覧を出す。項目を押すとその天体を選び、横のInfoで選んだうえ情報タブを開く
const openSystemList = (star) => {
  mapListBodies = [star, ...(star.companion ? [star.companion] : []), ...star.planets.flatMap((p) => [p, ...p.moons])];
  mapList.innerHTML = `<h3>${star.name} system</h3>${mapListBodies.map((b, i) => `<div class="一覧行">
    <button tabindex="-1" data-番号="${i}" class="${b.parent ? '衛星' : ''}">${b.name}<span>${b.star ? planetType(b) : b.label}</span></button>
    <button tabindex="-1" data-番号="${i}" data-情報="1" class="一覧情報">Info</button></div>`).join('')}`;
  setShown(mapList, true);
};
mapList.addEventListener('click', (e) => {
  const item = e.target.closest('[data-番号]');
  if (!item) return;
  item.blur();
  selected = mapListBodies[Number(item.dataset['番号'])];
  if (!item.dataset['情報']) return;
  infoTab.classList.add('開いている');
  infoButton.classList.add('作動中');
  setShown(infoTab, true, true);
});
const updateStarMap = createStarMap(mapPanel, stars, (star) => (selected = star), openSystemList);
const toggleMap = (open) => {
  mapButton.classList.toggle('作動中', open);
  setShown(mapPanel, open);
};
mapButton.addEventListener('click', () => {
  mapButton.blur();
  toggleMap(!mapPanel.shown);
});
mapPanel.querySelector('.閉じる').addEventListener('click', () => toggleMap(false));

const infoButton = document.getElementById('情報ボタン');
infoButton.addEventListener('click', () => {
  infoButton.blur();
  const open = infoTab.classList.toggle('開いている');
  infoButton.classList.toggle('作動中', open);
  setShown(infoTab, open, true);
});
infoTab.querySelector('.閉じる').addEventListener('click', () => {
  infoTab.classList.remove('開いている');
  infoButton.classList.remove('作動中');
  setShown(infoTab, false, true);
});
sasButtons.forEach((b) => b.addEventListener('click', () => {
  b.blur();
  setSas(b.dataset['姿勢']);
}));
// スライダーの値は倍率の常用対数（0 = 1 s/s 〜 7.499 = 1 y/s）
const warpSlider = document.getElementById('加速つまみ');
warpSlider.addEventListener('input', () => {
  warp = 10 ** Number(warpSlider.value);
  document.getElementById('加速表示').textContent = formatWarp(warp);
});
warpSlider.addEventListener('change', () => warpSlider.blur());
button.addEventListener('click', () => {
  button.blur();
  if (mode === 'planet') {
    // 惑星圏脱出：重力を切って星系内の巡航に戻る。惑星に対する速度の機首方向成分を引き継ぎ、重力圏を出るまで再び捕まらない
    mode = 'system';
    escaping = local.body;
    properSpeed = THREE.MathUtils.clamp(local.vel.dot(new THREE.Vector3(0, 0, -1).applyQuaternion(shipQuat)) / C, -SYSTEM_SPEED_MAX, SYSTEM_SPEED_MAX);
    local.body = null;
  } else if (mode === 'system') {
    mode = 'armed';
    departure = current;
  } else if (mode === 'armed' || Math.abs(properSpeed) <= SYSTEM_SPEED_MAX) {
    mode = 'system';
    transition = null;
  } else if (mode !== 'drop') {
    startTransition('drop', SYSTEM_SPEED_MAX, DROP_TIME);
  }
});
addEventListener('keydown', (e) => {
  keys.add(e.code);
  if (e.code === 'Space') e.preventDefault();
});
addEventListener('keyup', (e) => keys.delete(e.code));
addEventListener('blur', () => keys.clear());
renderer.domElement.addEventListener('wheel', (e) => {
  camera.fov = THREE.MathUtils.clamp(camera.fov * (e.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP), FOV_MIN, FOV_MAX);
  camera.updateProjectionMatrix();
}, { passive: true });
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

logSas('SYSTEM READY  SAS OFF');
renderer.setAnimationLoop(tick);
