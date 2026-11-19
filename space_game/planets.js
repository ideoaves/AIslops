import * as THREE from 'three';
import { relUniforms, ABERRATION_GLSL, STELLAR_GLSL } from './relativity.js';

// 3次元シンプレックスノイズ（Ian McEwan / Ashima Arts、MITライセンス）と、その重ね合わせ（fbm）・クレーター用のセルノイズ
const NOISE_GLSL = `
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x * 34.0) + 10.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.5 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 105.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }
  float fbm(vec3 p, int octaves) {
    float sum = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 8; i++) {
      if (i >= octaves) break;
      sum += amp * snoise(p);
      p = p * 2.03 + 17.0;
      amp *= 0.5;
    }
    return sum;
  }
  vec3 hash3(vec3 p) {
    p = fract(p * vec3(443.897, 441.423, 437.195));
    p += dot(p, p.yzx + 19.19);
    return fract((p.xxy + p.yzz) * p.zyx);
  }
  // 格子ごとに半分の確率でクレーターを置き、お椀状のくぼみと縁の盛り上がりの高さを返す
  float craters(vec3 p) {
    vec3 cell = floor(p);
    vec3 f = fract(p);
    float h = 0.0;
    for (int x = -1; x <= 1; x++) for (int y = -1; y <= 1; y++) for (int z = -1; z <= 1; z++) {
      vec3 o = vec3(x, y, z);
      vec3 rnd = hash3(cell + o);
      if (rnd.z > 0.5) continue;
      float d = length(f - o - rnd) / (0.2 + 0.3 * rnd.x);
      h += (d < 1.0 ? d * d - 1.0 : 0.0) + 0.35 * exp(-pow((d - 1.0) * 5.0, 2.0));
    }
    return h;
  }
`;

// 惑星の表面。岩石（海・陸・極冠・雲・クレーター）、氷惑星（淡い縞と霞）、ガス惑星（乱流で歪んだ縞と嵐の渦）を、球面上の3次元ノイズで描く
// 光は恒星の方向からのランバート反射、海は鏡面反射、縁は大気の散乱光、ガス・氷惑星は周辺減光をつける
const PLANET_FRAGMENT = `
  uniform int uKind;
  uniform float uSeed;
  uniform vec3 uColor;
  uniform float uOcean;
  uniform float uClouds;
  uniform float uCaps;
  uniform float uCraters;
  uniform float uAtmosphere;
  uniform vec3 uCloudTint;
  uniform float uLava;
  uniform float uBands;
  uniform float uContrast;
  uniform vec3 uZone;
  uniform vec3 uBelt;
  uniform vec3 uPolar;
  uniform vec4 uStorm;
  uniform vec3 uStarPos;
  uniform vec3 uStarColor;
  uniform vec3 uStar2Pos;
  uniform vec3 uStar2Color;
  uniform float uStar2Weight;
  varying vec3 vLocal;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;
  #include <logdepthbuf_pars_fragment>
  ${NOISE_GLSL}
  void main() {
    #include <logdepthbuf_fragment>
    vec3 p = normalize(vLocal);
    vec3 seed = vec3(uSeed, uSeed * 1.7, uSeed * 2.3);
    vec3 surface;
    float water = 0.0;
    float lava = 0.0;
    if (uKind == 0) {
      float h = fbm(p * 1.8 + seed, 6);
      if (uOcean > 0.5) {
        water = step(h, 0.0);
        vec3 sea = mix(vec3(0.01, 0.05, 0.18), vec3(0.04, 0.18, 0.36), smoothstep(-0.35, 0.0, h));
        vec3 land = mix(vec3(0.16, 0.30, 0.10), vec3(0.55, 0.47, 0.30), smoothstep(0.05, 0.3, h + 0.15 * fbm(p * 6.0 + seed, 3)));
        land = mix(land, vec3(0.45, 0.42, 0.40), smoothstep(0.35, 0.55, h));
        surface = mix(land, sea, water);
      } else {
        h += uCraters * 0.35 * craters(p * 5.0 + seed);
        surface = mix(uColor * 0.45, uColor * 1.2, smoothstep(-0.7, 0.7, h));
        lava = uLava * smoothstep(-0.05, -0.35, h) * (0.6 + 0.4 * snoise(p * 12.0 + seed));
      }
      float cap = smoothstep(uCaps, uCaps + 0.04, abs(p.y) + 0.06 * fbm(p * 5.0 + seed, 3));
      surface = mix(surface, vec3(0.92, 0.94, 0.96), uCaps > 0.0 ? cap : 0.0);
      water *= 1.0 - cap;
      float cloud = smoothstep(1.0 - uClouds, 1.15 - uClouds * 0.8, 0.5 + 0.6 * fbm(p * vec3(2.5, 4.0, 2.5) + seed * 3.0, 5));
      vec3 cloudColor = uClouds > 0.9 ? mix(uColor, vec3(1.0), 0.3) : uCloudTint;
      surface = mix(surface, cloudColor, uClouds > 0.0 ? cloud : 0.0);
      water *= 1.0 - cloud;
    } else if (uKind == 2) {
      // ガス惑星：明るいゾーンと暗いベルト。緯度に沿った低い周波数のノイズで帯の位置をずらして幅を不揃いにし、
      // 境界は正弦波のままなだらかにつなぐ。境界のわずかな乱流と経度方向の淡い筋を重ね、高緯度は極域の色へ寄せる
      float lat = p.y;
      float edge = fbm(p * vec3(2.5, 10.0, 2.5) + seed, 4) * 0.02;
      float shift = 0.9 * snoise(vec3(lat * 1.3, seed.x, 0.0)) + 0.4 * snoise(vec3(lat * 3.1, seed.y, 5.0));
      float zone = 0.5 + 0.5 * sin((lat + edge) * uBands * 3.14159 + shift);
      float streak = fbm(vec3(p.x * 1.5, lat * 30.0, p.z * 1.5) + seed, 3);
      surface = mix(uBelt, uZone, mix(0.65, zone, uContrast)) * (0.985 + 0.025 * streak);
      surface = mix(surface, uPolar, smoothstep(0.5, 0.95, abs(lat)) * 0.6);
    } else {
      // 氷惑星：ほとんど模様のない淡い色に、かすかな縞と極域の暗さ
      float warp = fbm(p * vec3(2.0, 9.0, 2.0) + seed, 5) * 0.25;
      float band = 0.5 + 0.35 * sin((p.y * uBands + warp) * 3.14159) + 0.15 * sin((p.y * uBands * 2.7 + warp * 1.5) * 3.14159);
      surface = mix(uColor * vec3(0.8, 0.85, 0.9), mix(uColor, vec3(0.96, 0.92, 0.84), 0.15), 0.5 + 0.25 * (band - 0.5));
      surface *= (0.97 + 0.05 * fbm(vec3(p.x * 2.0, p.y * 30.0, p.z * 2.0) + seed, 3)) * (1.0 - 0.25 * smoothstep(0.6, 1.0, abs(p.y)));
      if (uStorm.w > 0.0) {
        vec3 centre = vec3(cos(uStorm.y) * cos(uStorm.x), sin(uStorm.x), sin(uStorm.y) * cos(uStorm.x));
        surface = mix(surface, vec3(0.15, 0.2, 0.45), smoothstep(0.13, 0.05, length((p - centre) * vec3(0.7, 1.7, 0.7))) * 0.85);
      }
    }
    vec3 N = normalize(vWorldNormal);
    vec3 L = normalize(uStarPos - vWorldPos);
    vec3 V = normalize(-vWorldPos);
    float ndl = dot(N, L);
    float ndv = max(dot(N, V), 0.0);
    float lit = clamp(ndl * 1.1 + 0.02, 0.0, 1.0);
    if (uKind != 0) surface *= 0.7 + 0.3 * ndv;
    float lit2 = clamp(dot(N, normalize(uStar2Pos - vWorldPos)) * 1.1 + 0.02, 0.0, 1.0);
    vec3 color = surface * (uStarColor * lit + uStar2Color * lit2 * uStar2Weight) + surface * 0.008;
    color += water * uStarColor * pow(max(dot(reflect(-L, N), V), 0.0), 80.0) * 0.6;
    color += lava * vec3(1.0, 0.32, 0.06);
    vec3 sky = uKind == 0 && uOcean > 0.5 ? vec3(0.35, 0.55, 1.0) : mix(uColor, vec3(1.0), 0.3);
    color += sky * uStarColor * uAtmosphere * pow(1.0 - ndv, 3.0) * smoothstep(-0.25, 0.4, ndl);
    gl_FragColor = vec4(color, 1.0);
  }
`;

// 惑星の環。半径ごとの濃淡の縞と隙間を数本の正弦波で作り、環の点から恒星へ向かう光が惑星本体に遮られるところを影にする
const RING_FRAGMENT = `
  uniform float uInner;
  uniform float uOuter;
  uniform float uOpacity;
  uniform float uSeed;
  uniform vec3 uColor;
  uniform vec3 uStarColor;
  uniform vec3 uStarLocal;
  varying vec3 vLocal;
  #include <logdepthbuf_pars_fragment>
  void main() {
    #include <logdepthbuf_fragment>
    float r = length(vLocal.xy);
    float t = (r - uInner) / (uOuter - uInner);
    if (t < 0.0 || t > 1.0) discard;
    float density = 0.55 + 0.25 * sin(r * 37.0 + uSeed) + 0.15 * sin(r * 91.0 + uSeed * 3.0) + 0.1 * sin(r * 211.0 + uSeed * 7.0);
    density *= smoothstep(0.0, 0.04, t) * smoothstep(1.0, 0.96, t) * smoothstep(0.0, 0.025, abs(t - 0.62));
    float b = dot(vLocal, uStarLocal);
    float shadow = b < 0.0 && b * b - dot(vLocal, vLocal) + 1.0 > 0.0 ? 0.08 : 1.0;
    gl_FragColor = vec4(uColor * uStarColor * shadow, clamp(density, 0.0, 1.0) * uOpacity);
  }
`;

// 惑星・環で共通の頂点処理。球の局所座標と、カメラ基準のワールド座標・法線を渡し、表示位置には光行差をかける
const BODY_VERTEX = `
  varying vec3 vLocal;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;
  #include <common>
  #include <logdepthbuf_pars_vertex>
  ${ABERRATION_GLSL}
  void main() {
    vLocal = position;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorldPos = world.xyz;
    vWorldNormal = normalize(mat3(modelMatrix) * normal);
    float doppler;
    gl_Position = projectionMatrix * viewMatrix * vec4(aberrate(world.xyz, doppler), 1.0);
    #include <logdepthbuf_vertex>
  }
`;

// ガス惑星の配色（sRGB）。ゾーン（明るい帯）・ベルト（暗い縞）・極域。木星と土星の実際の色を基準にする
const GAS_PALETTES = {
  Jupiter: { zone: 0xe8dfcc, belt: 0xc7aa8a, polar: 0xb0ab9f },
  Saturn: { zone: 0xe6d9b5, belt: 0xdccaa0, polar: 0xc9bf9f },
};

// 惑星のガス配色のuniform。系外惑星は木星型か土星型を元に、種から決まる量だけ色相と彩度をずらす
function gasPalette(p) {
  const known = GAS_PALETTES[p.name];
  const base = known ?? GAS_PALETTES[Math.floor(p.seed) % 2 ? 'Saturn' : 'Jupiter'];
  const shift = known ? 0 : ((p.seed * 7.13) % 1) - 0.5;
  const color = (hex) => new THREE.Color().setHex(hex, THREE.LinearSRGBColorSpace).offsetHSL(shift * 0.08, shift * 0.15, 0);
  return {
    uZone: { value: color(base.zone) },
    uBelt: { value: color(base.belt) },
    uPolar: { value: color(base.polar) },
  };
}

const sphere = new THREE.SphereGeometry(1, 192, 96);
const ringGeometry = new THREE.RingGeometry(1, 3, 256, 1);

// 惑星1つ分のメッシュ（環があれば子として赤道面に置く）を作る。描くのは今いる星系（または選んだ星系）の惑星だけ
export function makePlanetMesh(p) {
  const srgb = p.color.clone().convertLinearToSRGB();
  const mesh = new THREE.Mesh(sphere, new THREE.ShaderMaterial({
    uniforms: {
      ...relUniforms,
      uKind: { value: { rock: 0, ice: 1, gas: 2 }[p.kind] },
      uSeed: { value: p.seed },
      uColor: { value: srgb },
      uOcean: { value: p.ocean ? 1 : 0 },
      uClouds: { value: p.clouds },
      uCaps: { value: p.caps },
      uCraters: { value: p.craters },
      uAtmosphere: { value: p.atmosphere },
      uCloudTint: { value: (p.cloudTint ?? new THREE.Color(0.95, 0.95, 0.95)).clone() },
      uLava: { value: p.lava ?? 0 },
      uBands: { value: p.bands },
      uContrast: { value: p.contrast },
      ...gasPalette(p),
      uStorm: { value: p.storm ? new THREE.Vector4(p.storm.lat, p.storm.lon, 0, 1) : new THREE.Vector4() },
      uStarPos: { value: new THREE.Vector3() },
      uStarColor: { value: new THREE.Color(1, 1, 1) },
      uStar2Pos: { value: new THREE.Vector3() },
      uStar2Color: { value: new THREE.Color(0, 0, 0) },
      uStar2Weight: { value: 0 },
    },
    vertexShader: BODY_VERTEX,
    fragmentShader: PLANET_FRAGMENT,
  }));
  mesh.frustumCulled = false;
  if (p.ring) {
    const ring = new THREE.Mesh(ringGeometry, new THREE.ShaderMaterial({
      uniforms: {
        ...relUniforms,
        uInner: { value: p.ring.inner },
        uOuter: { value: p.ring.outer },
        uOpacity: { value: p.ring.opacity },
        uSeed: { value: p.seed },
        uColor: { value: srgb.clone().lerp(new THREE.Color(0.9, 0.85, 0.75), 0.4) },
        uStarColor: mesh.material.uniforms.uStarColor,
        uStarLocal: { value: new THREE.Vector3() },
      },
      vertexShader: BODY_VERTEX,
      fragmentShader: RING_FRAGMENT,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    ring.rotation.x = -Math.PI / 2;
    ring.frustumCulled = false;
    mesh.add(ring);
    mesh.userData.ring = ring;
  }
  return mesh;
}

// 恒星の表面。ベナール対流の粒状斑を、ゆっくり動く特徴点のボロノイ（Worley）距離で描く
// F2−F1 が小さいセルの境目は冷たい下降流で暗く、セルの中ほどは熱い上昇流で明るい。大小2段の粒状斑にゆるやかな超粒状斑を重ね、
// セルが画面で1px未満になる距離では平均の明るさに溶かしてちらつきを防ぐ。温度の揺らぎを黒体色に反映し、縁は周辺減光で暗く赤くする
const STAR_FRAGMENT = `
  uniform float uTemp;
  uniform float uTime;
  uniform float uSeed;
  uniform float uExposure;
  varying vec3 vLocal;
  varying vec3 vWorldPos;
  varying vec3 vWorldNormal;
  #include <logdepthbuf_pars_fragment>
  ${NOISE_GLSL}
  ${STELLAR_GLSL}
  // 最も近い特徴点・2番目に近い特徴点までの距離と、最も近いセルの乱数を返す
  vec3 worley(vec3 p, float t) {
    vec3 cell = floor(p);
    vec3 f = fract(p);
    float f1 = 8.0;
    float f2 = 8.0;
    float id = 0.0;
    for (int x = -1; x <= 1; x++) for (int y = -1; y <= 1; y++) for (int z = -1; z <= 1; z++) {
      vec3 o = vec3(x, y, z);
      vec3 h = hash3(cell + o);
      float d = length(f - o - 0.5 - 0.4 * sin(t * (0.6 + h) + 6.2831 * h));
      f2 = d < f1 ? f1 : min(f2, d);
      id = d < f1 ? h.x : id;
      f1 = min(f1, d);
    }
    return vec3(f1, f2, id);
  }
  // 粒状斑1枚分の明るさ。座標をノイズで歪めてセルを丸く不揃いにし、境目の暗い筋は柔らかく、セルごとに明るさを変える
  float granules(vec3 p, float t) {
    p += 0.35 * vec3(snoise(p * 0.7), snoise(p * 0.7 + 31.0), snoise(p * 0.7 + 67.0));
    vec3 w = worley(p, t);
    float lane = smoothstep(0.0, 0.3 + 0.15 * w.z, w.y - w.x);
    return lane * (0.8 + 0.3 * w.z) * (1.1 - 0.35 * w.x * w.x);
  }
  void main() {
    #include <logdepthbuf_fragment>
    vec3 p = normalize(vLocal) + uSeed;
    float coarse = 9.4;
    float fine = 30.0;
    float fadeCoarse = smoothstep(0.7, 0.25, length(fwidth(p * coarse)));
    float fadeFine = smoothstep(0.7, 0.25, length(fwidth(p * fine)));
    float g = mix(0.75, granules(p * coarse, uTime), fadeCoarse);
    g = mix(g, g * (0.8 + 0.3 * granules(p * fine, uTime * 1.7)), fadeFine);
    float large = fbm(p * 2.0, 3);
    float mu = max(dot(normalize(vWorldNormal), normalize(-vWorldPos)), 0.0);
    float limb = 1.0 - 0.6 * (1.0 - mu);
    float T = uTemp * (0.97 + 0.04 * g + 0.015 * large) * (0.85 + 0.15 * mu);
    // 受ける光の強さに応じた露出で 1−e^(−x) の階調にする。近いほど白く飛んで粒状斑も縁の暗さも見えなくなる
    vec3 color = 1.0 - exp(-blackbody(T) * limb * (0.9 + 0.12 * g) * uExposure);
    gl_FragColor = vec4(color, 1.0);
  }
`;

// 恒星の球のメッシュ。温度・粒状斑の時間・模様の種はsetStarで渡す
export function makeStarMesh() {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 64), new THREE.ShaderMaterial({
    uniforms: {
      ...relUniforms,
      uTemp: { value: 5772 },
      uTime: { value: 0 },
      uSeed: { value: 0 },
      uExposure: { value: 1.5 },
    },
    vertexShader: BODY_VERTEX,
    fragmentShader: STAR_FRAGMENT,
  }));
  mesh.frustumCulled = false;
  return mesh;
}

// 恒星の球を、星の温度と大きさに合わせ、粒状斑の時刻を宇宙時刻から決める（粒状斑の寿命は太陽で約10分）
// fluxは受ける光の強さ（光度÷距離²、地球で1）。写真では省いて露出を控えめにする
export function setStar(mesh, star, worldTime, flux = 0) {
  mesh.material.uniforms.uExposure.value = 1.5 + 3 * Math.log2(1 + flux);
  mesh.scale.setScalar(star.radiusAU);
  mesh.material.uniforms.uTemp.value = star.T;
  mesh.material.uniforms.uSeed.value = ((star.pos ?? star.primary.pos).x * 0.37 + (star.primary ? 13 : 0)) % 50;
  mesh.material.uniforms.uTime.value = (worldTime / 600) % 10000;
}

// 恒星のまぶしさを画面に重ねる板。画面上の恒星の中心から、白い芯・広いにじみ・真横に1本の光条を足し合わせる
const GLARE_FRAGMENT = `
  uniform vec2 uCenter;
  uniform float uHalo;
  uniform float uStrength;
  uniform vec3 uColor;
  void main() {
    vec2 d = gl_FragCoord.xy - uCenter;
    float r = length(d);
    float a = atan(d.y, d.x);
    float core = exp(-pow(r / (uHalo * 0.3), 2.0));
    float halo = 1.0 / (1.0 + pow(r / uHalo, 2.0));
    float rays = pow(abs(cos(a)), 400.0) * exp(-r / (uHalo * 4.0));
    gl_FragColor = vec4(mix(uColor, vec3(1.0), core) * (core + 0.45 * halo + 0.35 * rays) * uStrength, 1.0);
  }
`;

// まぶしさの板（画面全体を覆い、加算で重ねる）
export function makeGlare() {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    uniforms: {
      uCenter: { value: new THREE.Vector2() },
      uHalo: { value: 1 },
      uStrength: { value: 0 },
      uColor: { value: new THREE.Color() },
    },
    vertexShader: 'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: GLARE_FRAGMENT,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  }));
  mesh.frustumCulled = false;
  mesh.renderOrder = 10;
  return mesh;
}

const UP = new THREE.Vector3(0, 1, 0);

// 惑星メッシュを、カメラ基準の位置・半径・地軸の傾き・自転の角度に合わせ、恒星の位置と色をシェーダーへ渡す
// 地軸は公転面の法線から傾け、自転は宇宙時刻を自転周期で割った角度で地軸のまわりに回す。orientationを渡すとその向きにする（写真用）
// secondは連星の伴星の光 { position, color, weight }（weightは主星に対する明るさの比）
export function placePlanetMesh(mesh, p, position, starPosition, starColor, worldTime, orientation = null, second = null) {
  const normal = new THREE.Vector3().crossVectors(p.star.u, p.star.v);
  const spin = (2 * Math.PI * (worldTime % Math.abs(p.rotation))) / p.rotation;
  mesh.position.copy(position);
  mesh.scale.setScalar(p.radiusAU);
  if (orientation) mesh.quaternion.copy(orientation);
  else mesh.quaternion.setFromAxisAngle(p.star.u, p.tilt)
    .multiply(new THREE.Quaternion().setFromUnitVectors(UP, normal))
    .multiply(new THREE.Quaternion().setFromAxisAngle(UP, spin));
  mesh.material.uniforms.uStarPos.value.copy(starPosition);
  mesh.material.uniforms.uStarColor.value.copy(starColor).convertLinearToSRGB();
  mesh.material.uniforms.uStar2Weight.value = second ? Math.min(second.weight, 4) : 0;
  if (second) {
    mesh.material.uniforms.uStar2Pos.value.copy(second.position);
    mesh.material.uniforms.uStar2Color.value.copy(second.color).convertLinearToSRGB();
  }
  if (!mesh.userData.ring) return;
  mesh.updateMatrixWorld(true);
  mesh.userData.ring.material.uniforms.uStarLocal.value.copy(mesh.userData.ring.worldToLocal(starPosition.clone())).normalize();
}

const photos = new Map();

// 天体の写真。その天体のシェーダーで、画面外の512px四方に左上手前から照らして描き、データURLにして天体ごとに覚えておく
// 惑星は地軸を地軸の傾きぶん横へ倒し、少し上から見下ろして環が開いて見える向きにする。光行差は写真では切る
export function bodyPhoto(renderer, body) {
  if (photos.has(body)) return photos.get(body);
  const size = 512;
  const extent = body.radiusAU * (body.ring ? body.ring.outer : 1) * 1.2;
  const distance = extent / Math.tan(THREE.MathUtils.degToRad(15));
  const camera = new THREE.PerspectiveCamera(30, 1, distance * 0.01, distance * 10);
  const position = new THREE.Vector3(0, 0, -distance);
  const light = new THREE.Vector3(-1, 0.6, 0.9).normalize().multiplyScalar(body.radiusAU * 1e4).add(position);
  const mesh = body.star ? makePlanetMesh(body) : makeStarMesh();
  if (body.star) {
    const tilt = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.35, 0, -Math.min(body.tilt, Math.PI / 2)));
    placePlanetMesh(mesh, body, position, light, body.star.color, 0, tilt);
  } else {
    mesh.position.copy(position);
    setStar(mesh, body, 0);
  }
  const scene = new THREE.Scene().add(mesh);
  const target = new THREE.WebGLRenderTarget(size, size);
  const velocity = relUniforms.uU.value;
  relUniforms.uU.value = 0;
  renderer.setRenderTarget(target);
  renderer.clear();
  renderer.render(scene, camera);
  const pixels = new Uint8Array(size * size * 4);
  renderer.readRenderTargetPixels(target, 0, 0, size, size, pixels);
  renderer.setRenderTarget(null);
  relUniforms.uU.value = velocity;

  // 描画先は下から上の行順なので、上下を入れ替えて不透明の画像にする
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d', { alpha: false });
  const image = context.createImageData(size, size);
  for (let y = 0; y < size; y++) image.data.set(pixels.subarray((size - 1 - y) * size * 4, (size - y) * size * 4), y * size * 4);
  context.putImageData(image, 0, 0);
  const url = canvas.toDataURL('image/png');
  target.dispose();
  mesh.material.dispose();
  mesh.userData.ring?.material.dispose();
  if (!body.star) mesh.geometry.dispose();
  photos.set(body, url);
  return url;
}
