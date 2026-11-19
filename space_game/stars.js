import * as THREE from 'three';

export const AU_PER_LY = 63241.077;

const SEED = 20261015;
const FIELD_RADIUS_LY = 40;          // 星を生成する範囲の半径
const STAR_DENSITY_PER_LY3 = 0.004;  // 太陽近傍の恒星密度（約0.14個/pc³）

// 星の種類ごとの出現比（太陽近傍の個数比）と表面温度・質量・光度の範囲。V=主系列 III=巨星 I=超巨星 D=白色矮星
const STAR_KINDS = [
  { cls: 'V', weight: 0.0000003, T: [30000, 45000], M: [16, 60] },
  { cls: 'V', weight: 0.0012, T: [10000, 30000], M: [2.1, 16] },
  { cls: 'V', weight: 0.0057, T: [7500, 10000], M: [1.4, 2.1] },
  { cls: 'V', weight: 0.029, T: [6000, 7500], M: [1.04, 1.4] },
  { cls: 'V', weight: 0.072, T: [5200, 6000], M: [0.8, 1.04] },
  { cls: 'V', weight: 0.114, T: [3700, 5200], M: [0.45, 0.8] },
  { cls: 'V', weight: 0.72, T: [2400, 3700], M: [0.08, 0.45] },
  { cls: 'III', weight: 0.002, T: [3600, 5200], M: [1, 3], L: [30, 500] },
  { cls: 'I', weight: 0.00002, T: [3500, 30000], M: [10, 25], L: [1e4, 3e5] },
  { cls: 'D', weight: 0.06, T: [5000, 25000], M: [0.5, 0.8], R: 0.012 },
];

// 惑星系の配置。円盤サイズ∝M^0.9（Tazzari+2018）、雪線2.7AU√L、巨大惑星の出現率∝M（Johnson+2010）、隣接軌道の周期比は1.5〜2.5が典型（Weiss+2018）
const PLANET_OUTER_AU = 30;   // 1太陽質量での最も外側の惑星軌道
const SYSTEM_EDGE_AU = 50;    // 1太陽質量での星系の境界（カイパーベルト外縁相当）
const INNER_EDGE_AU = 0.1;    // 1太陽光度での最も内側の軌道
const SNOW_LINE_AU = 2.7;
const PERIOD_RATIO = [1.5, 2.5];
const INNER_OCCUPANCY = 0.3;  // 雪線の内側の各軌道に岩石惑星がある確率
const GIANT_RATE = 0.1;       // 1太陽質量で雪線の外側の各軌道に巨大惑星がある確率
const PLANET_TYPES = {
  rock: { R: [0.5, 3], colors: [0x9c8a74, 0x7d8a99, 0xb07a5a, 0x5f7fa8] },
  ice: { R: [3.5, 4.5], colors: [0x7fb6d6, 0x5f8fd0] },
  gas: { R: [8, 12], M: [30, 3000], colors: [0xd8b088, 0xc9a27a, 0xe0c9a0] }, // 巨大ガス惑星は半径がほぼ一定なので質量は0.1〜10木星質量から選ぶ
};

const AU_PER_SOLAR_RADIUS = 0.00465047;
const AU_PER_EARTH_RADIUS = 4.2635e-5;
const GM_SUN = 1.32712440018e20 / 1.495978707e11 ** 3; // 太陽の重力定数（AU³/s²）
const EARTH_PER_SUN_MASS = 3.003489e-6;

// シード値から再現可能な0〜1の乱数列を作る（mulberry32）
function mulberry32(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 名前から決まる乱数列（星系の生成の乱数列を変えずに、天体ごとの性質を決めるのに使う）
function seededRand(name) {
  return mulberry32([...name].reduce((h, ch) => Math.imul(h ^ ch.charCodeAt(0), 16777619), 2166136261));
}

// 標準正規分布の乱数（ボックス＝ミュラー法）
function gaussian(rand) {
  return Math.sqrt(-2 * Math.log(1 - rand())) * Math.cos(2 * Math.PI * rand());
}

// 主系列星の質量(M☉)から光度・半径・温度を求める（質量光度関係と、半径 M^0.8（1M☉未満）・M^0.57（以上）、シュテファン＝ボルツマンの法則）
function mainSequence(M) {
  const L = M < 0.43 ? 0.23 * M ** 2.3 : M < 2 ? M ** 4 : 1.4 * M ** 3.5;
  const R = M < 1 ? M ** 0.8 : M ** 0.57;
  return { L, R, T: 5772 * (L / R ** 2) ** 0.25 };
}

// 軌道長半径a(AU)の平衡温度（K）。反射率0・全球で熱を均す近似で T = 278K × L^(1/4) / √a（地球で約278K）。周連星惑星も主星の光で近似する
function equilibriumTemperature(star, a) {
  return (278 * star.L ** 0.25) / Math.sqrt(a);
}

// 範囲[min,max]をsで対数補間する
function logLerp([min, max], s) {
  return min * (max / min) ** s;
}

// 黒体の温度(K)からおおよその表示色を求める（Tanner Hellandの近似式）
export function blackbodyColor(T) {
  const t = T / 100;
  const r = t <= 66 ? 255 : 329.698727446 * (t - 60) ** -0.1332047592;
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * (t - 60) ** -0.0755148492;
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  const clamp = (v) => THREE.MathUtils.clamp(v / 255, 0, 1);
  return new THREE.Color().setRGB(clamp(r), clamp(g), clamp(b), THREE.SRGBColorSpace);
}

// 温度と光度階級からスペクトル分類の表記（例: G2 V）を作る
function spectralLabel(T, cls) {
  if (cls === 'D') return `DA${Math.min(9, Math.round(50400 / T))}`;
  const types = [['O', 30000, 60000], ['B', 10000, 30000], ['A', 7500, 10000], ['F', 6000, 7500], ['G', 5200, 6000], ['K', 3700, 5200], ['M', 2000, 3700]];
  const [letter, lo, hi] = types.find(([, lo]) => T >= lo) ?? types[6];
  return `${letter}${THREE.MathUtils.clamp(Math.floor(((hi - T) / (hi - lo)) * 10), 0, 9)} ${cls}`;
}

// 内縁から周期比ぶん外側へ軌道を進めながら、雪線の内外の確率で惑星を置いていく
function addPlanets(star, a, aOut, rand, list) {
  if (a > aOut) return list;
  const outside = a > SNOW_LINE_AU * Math.sqrt(star.L);
  if (rand() < (outside ? Math.min(GIANT_RATE * star.M, 0.5) : INNER_OCCUPANCY)) {
    const type = PLANET_TYPES[!outside ? 'rock' : rand() < 0.5 ? 'gas' : 'ice'];
    const R = logLerp(type.R, rand());
    // 岩石惑星の地表の色は平衡温度で選ぶ（1000K超は黒い玄武岩、500K超は焼けた暗い岩、200K未満は氷、その間は茶・赤茶）
    const teq = equilibriumTemperature(star, a);
    const colors = !outside ? (teq > 1000 ? [0x3e3a37, 0x4a4440] : teq > 500 ? [0x5a524a, 0x6e5f50, 0x584a40] : teq < 200 ? [0xc9cfd6, 0xaeb7c2, 0x9aa4b0] : [0x9c8a74, 0xb07a5a, 0x8a7f72]) : type.colors;
    // 質量半径関係（Chen & Kipping 2017）：岩石 R∝M^0.279、海王星型 R∝M^0.589
    const mass = type.M ? logLerp(type.M, rand()) : R < 1.23 ? R ** 3.58 : (R / 0.808) ** 1.698;
    const name = `${star.name} ${'bcdefghijklmnopqrstuvwxyz'[list.length]}`;
    list.push(makePlanet(star, a, R, mass, colors[Math.floor(rand() * colors.length)], rand, name));
  }
  return addPlanets(star, a * logLerp(PERIOD_RATIO, rand()) ** (2 / 3), aOut, rand, list);
}

// 軌道長半径a(AU)・半径と質量(地球比)の円軌道の惑星を作る。公転周期はケプラーの第3法則 P = 2π√(a³/GM★)、重力圏はラプラスの影響圏 a(m/M★)^0.4
// 見た目の性質は名前から決まる別の乱数で決めるので、星系の生成の乱数列は変わらない。lookは実在の惑星の値で上書きするときに渡す
function makePlanet(star, a, radiusEarth, massEarth, color, rand, name, look = {}) {
  return {
    star, a, name, radiusEarth, massEarth,
    period: 2 * Math.PI * Math.sqrt(a ** 3 / (GM_SUN * star.M)),
    phase: rand() * Math.PI * 2,
    radiusAU: radiusEarth * AU_PER_EARTH_RADIUS,
    gm: GM_SUN * EARTH_PER_SUN_MASS * massEarth,
    soi: a * ((massEarth * EARTH_PER_SUN_MASS) / star.M) ** 0.4,
    color: new THREE.Color(color),
    ...planetLook(star, a, radiusEarth, seededRand(name)),
    ...look,
  };
}

// 惑星の見た目の性質。種類は半径で分け、海はハビタブルゾーン（0.95〜1.67 AU×√L）の地球に近い大きさの岩石惑星にだけ置く
// rotationは自転周期（秒、負は逆行）、tiltは地軸の傾き（rad）、capsは極冠が始まる緯度の正弦、ringの半径は惑星半径単位
function planetLook(star, a, R, rand) {
  const kind = R < 3.2 ? 'rock' : R < 6 ? 'ice' : 'gas';
  const habitable = a > 0.95 * Math.sqrt(star.L) && a < 1.67 * Math.sqrt(star.L);
  const ocean = kind === 'rock' && habitable && R > 0.7 && R < 1.8 && rand() < 0.6;
  const clouds = ocean ? 0.5 : kind === 'rock' && R > 1.3 ? rand() * 0.9 : 0;
  const hours = kind === 'gas' ? 8 + rand() * 8 : kind === 'ice' ? 13 + rand() * 7 : 15 + rand() * 45;
  const ringed = (kind === 'gas' && rand() < 0.35) || (kind === 'ice' && rand() < 0.25);
  const teq = equilibriumTemperature(star, a);
  return {
    kind, ocean, clouds, teq,
    // 雲は330K未満なら水の白い雲、それより熱ければ硫酸の黄色い雲。
    // 岩石惑星は昼側の中心が平衡温度の約√2倍になるので、平衡温度750K（中心約1060K）を超えると低地の溶岩が光り始める
    cloudTint: teq > 330 ? new THREE.Color(0.93, 0.86, 0.66) : new THREE.Color(0.95, 0.95, 0.95),
    lava: kind === 'rock' && teq > 750 ? Math.min(1, (teq - 750) / 500) : 0,
    seed: rand() * 100,
    tilt: rand() ** 2 * (Math.PI / 4),
    rotation: hours * 3600 * (rand() < 0.1 ? -1 : 1),
    caps: ocean ? 0.82 : kind === 'rock' && teq < 260 && rand() < 0.6 ? 0.88 - Math.max(0, 200 - teq) / 300 : 0,
    craters: kind === 'rock' && clouds < 0.1 ? 1 : 0,
    atmosphere: ocean ? 0.6 : kind === 'rock' ? clouds * 0.5 + (R > 0.5 ? 0.1 : 0) : kind === 'ice' ? 0.5 : 0.35,
    bands: kind === 'gas' ? 4 + rand() * 4 : 3 + rand() * 4,
    contrast: 0.15 + rand() * 0.45,
    storm: kind === 'ice' && rand() < 0.4 ? { lat: (rand() - 0.5) * 1.2, lon: rand() * Math.PI * 2 } : null,
    ring: ringed ? { inner: 1.3 + rand() * 0.3, outer: 1.9 + rand() * 0.6, opacity: kind === 'gas' ? 0.5 + rand() * 0.4 : 0.1 + rand() * 0.15 } : null,
  };
}

// 伴星。多重度は主星の質量で変わる（M型約27%：Winters+2019、FGK型約44%：Raghavan+2010、A型約50%・O/B型約70%：Duchêne & Kraus 2013、白色矮星約25%：Holberg+2016）
// 質量比 q=M₂/M₁ は0.1〜0.9で一様（太陽型の質量比分布はほぼ平坦。同じ大きさの恒星にはしない）、公転周期は対数正規 log10 P[日]〜N(5.0, 2.3)（Raghavan+2010）
// 伴星は主系列星として質量から決める。主星が軽すぎて恒星の伴星を持てない（0.08/M₁ ≥ 0.9）なら伴星なし。連星は円軌道で、惑星と同じ面で共通重心のまわりを回る
function makeCompanion(star, rand) {
  const multiplicity = star.cls === 'D' ? 0.25 : star.M < 0.45 ? 0.27 : star.M < 1.4 ? 0.44 : star.M < 2.1 ? 0.5 : 0.7;
  if (rand() > multiplicity) return null;
  // 多重度は恒星の伴星（0.08M☉以上）の割合なので、質量比は伴星が恒星になる範囲 [max(0.1, 0.08/M₁), 0.9] から一様に選ぶ
  const qMin = Math.max(0.1, 0.08 / star.M);
  if (qMin >= 0.9) return null;
  const M = star.M * THREE.MathUtils.lerp(qMin, 0.9, rand());
  const { L, R, T } = mainSequence(M);
  const contact = (star.R + R) * AU_PER_SOLAR_RADIUS * 3;
  const period = 10 ** THREE.MathUtils.clamp(5.0 + 2.3 * gaussian(rand), 0, 7) * 86400;
  const a = Math.max(contact, Math.cbrt((GM_SUN * (star.M + M) * period ** 2) / (4 * Math.PI ** 2)));
  return {
    name: `${star.name} B`, primary: star, cls: 'V', T, M, L, R, a,
    period: 2 * Math.PI * Math.sqrt(a ** 3 / (GM_SUN * (star.M + M))),
    phase: rand() * Math.PI * 2,
    label: spectralLabel(T, 'V'),
    color: blackbodyColor(T),
    radiusAU: R * AU_PER_SOLAR_RADIUS,
    gm: GM_SUN * M,
    planets: [],
  };
}

// 衛星（軌道長半径a(AU)の円軌道）。自転は公転と同期（潮汐固定）し、地軸は親惑星に合わせる。lookで雲・クレーター・大気・逆行を上書きする
function makeMoon(planet, a, radiusEarth, massEarth, color, name, rand, look = {}) {
  const period = 2 * Math.PI * Math.sqrt(a ** 3 / planet.gm);
  return {
    parent: planet, star: planet.star, name, a, radiusEarth, massEarth, period,
    phase: rand() * Math.PI * 2,
    direction: look.retro ? -1 : 1,
    radiusAU: radiusEarth * AU_PER_EARTH_RADIUS,
    gm: GM_SUN * EARTH_PER_SUN_MASS * massEarth,
    color: new THREE.Color(color),
    kind: 'rock', ocean: false, caps: 0, bands: 3, contrast: 0.3, storm: null, ring: null,
    clouds: look.clouds ?? 0,
    craters: look.craters ?? 1,
    atmosphere: look.atmosphere ?? 0,
    seed: rand() * 100,
    tilt: planet.tilt,
    rotation: period,
    moons: [],
  };
}

// 生成する衛星。ガス惑星は1〜4個、氷惑星は0〜3個、地球の0.7倍より大きい岩石惑星は30%で1個
// 軌道はロッシュ限界より外（ガス5・氷8・岩石20惑星半径から）、ヒル球の0.4倍より内に、1.5〜2.5倍ずつ間を空けて置く。密度は岩石と氷の中間（M≈0.55R³）
function generateMoons(planet, rand) {
  const count = planet.kind === 'gas' ? 1 + Math.floor(rand() * 4) : planet.kind === 'ice' ? Math.floor(rand() * 4) : planet.radiusEarth > 0.7 && rand() < 0.3 ? 1 : 0;
  const hill = planet.a * Math.cbrt((planet.massEarth * EARTH_PER_SUN_MASS) / (3 * planet.star.M));
  const sizes = { gas: [0.1, 0.45], ice: [0.05, 0.25], rock: [0.1 * planet.radiusEarth, 0.3 * planet.radiusEarth] }[planet.kind];
  const colors = [0x9a9a96, 0xcfcac2, 0x8a7f72, 0xd9c37a, 0x6e665c, 0xb8b2aa];
  const place = (a, list) => {
    if (list.length >= count || a > 0.4 * hill) return list;
    const R = logLerp(sizes, rand());
    list.push(makeMoon(planet, a, R, 0.55 * R ** 3, colors[Math.floor(rand() * colors.length)], `${planet.name} ${['I', 'II', 'III', 'IV'][list.length]}`, rand));
    return place(a * logLerp([1.5, 2.5], rand()), list);
  };
  return place(planet.radiusAU * { gas: 5, ice: 8, rock: 20 }[planet.kind] * logLerp([1, 2], rand()), []);
}

// 物理量の揃った恒星に、名前・色・大きさ・軌道面・星系の境界・惑星を付け足す
function finishStar(star, rand) {
  const n = new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).normalize();
  star.u = new THREE.Vector3(0, 1, 0).cross(n).normalize();
  star.v = new THREE.Vector3().crossVectors(n, star.u);
  star.label = spectralLabel(star.T, star.cls);
  star.color = blackbodyColor(star.T);
  star.radiusAU = star.R * AU_PER_SOLAR_RADIUS;
  star.gm = GM_SUN * star.M;
  star.edge = Math.max(SYSTEM_EDGE_AU * star.M ** 0.9, star.radiusAU * 20);
  if (star.companion === undefined) star.companion = makeCompanion(star, seededRand(`${star.name} companion`));
  // 巨星は内側の惑星を飲み込み、白色矮星は巨星期を経ているので内側が空く
  const inner = Math.max(INNER_EDGE_AU * Math.sqrt(star.L), star.radiusAU * 3, star.cls === 'D' ? 3 : 0.01);
  star.planets ??= addPlanets(star, inner, PLANET_OUTER_AU * star.M ** 0.9, rand, []);
  const c = star.companion;
  if (c) {
    // 連星系の惑星の安定条件（Holman & Wiegert 1999、円軌道）。主星を回るS型は a < a連(0.464−0.380μ)、両星を回るP型は a > a連(1.60+4.12μ−5.09μ²)
    // その間の不安定な軌道の惑星は作らない。P型は重心を中心に両星の質量の和で公転する
    const mu = c.M / (star.M + c.M);
    const sType = c.a * (0.464 - 0.38 * mu);
    const pType = c.a * (1.6 + 4.12 * mu - 5.09 * mu * mu);
    star.planets = star.planets.filter((p) => p.a < sType || p.a > pType);
    star.planets.filter((p) => p.a > pType).forEach((p) => {
      p.circumbinary = true;
      p.period = 2 * Math.PI * Math.sqrt(p.a ** 3 / (GM_SUN * (star.M + c.M)));
      p.soi = p.a * ((p.massEarth * EARTH_PER_SUN_MASS) / (star.M + c.M)) ** 0.4;
    });
    star.edge = Math.max(star.edge, c.a * 1.5);
  }
  star.planets.forEach((p) => (p.moons ??= generateMoons(p, seededRand(`${p.name} moons`))));
  star.planetSpan = star.planets.reduce((max, p) => Math.max(max, p.a), 0);
  star.edge = Math.max(star.edge, star.planetSpan * 1.2);
  return star;
}

// 太陽系を中心に、太陽近傍の密度と種類の比で恒星と惑星系をばらまく
export function generateStars() {
  const rand = mulberry32(SEED);
  const sun = { name: 'Sol', cls: 'V', T: 5772, M: 1, L: 1, R: 1, pos: new THREE.Vector3(), companion: null };
  // 太陽系の惑星は実際の自転周期（時間）・地軸の傾き（度）と、見た目の特徴を与える
  const deg = Math.PI / 180;
  const h = 3600;
  sun.planets = [
    ['Mercury', 0.387, 0.383, 0.0553, 0x9c8a74, { tilt: 0.03 * deg, rotation: 1407.6 * h, craters: 1, clouds: 0, caps: 0, atmosphere: 0 }],
    ['Venus', 0.723, 0.949, 0.815, 0xe0c9a0, { tilt: 177.4 * deg, rotation: -5832.5 * h, clouds: 1, craters: 0, caps: 0, atmosphere: 0.5 }],
    ['Earth', 1, 1, 1, 0x4a7bd0, { tilt: 23.44 * deg, rotation: 23.934 * h, ocean: true, clouds: 0.5, caps: 0.82, craters: 0, atmosphere: 0.6 }],
    ['Mars', 1.524, 0.532, 0.107, 0xb07a5a, { tilt: 25.19 * deg, rotation: 24.62 * h, ocean: false, clouds: 0, caps: 0.9, craters: 0.6, atmosphere: 0.12 }],
    ['Jupiter', 5.2, 11.2, 317.8, 0xd8b088, { tilt: 3.13 * deg, rotation: 9.925 * h, bands: 7, contrast: 0.55, storm: null, ring: null }],
    ['Saturn', 9.58, 9.45, 95.2, 0xe0c9a0, { tilt: 26.73 * deg, rotation: 10.66 * h, bands: 6, contrast: 0.15, storm: null, ring: { inner: 1.24, outer: 2.27, opacity: 0.85 } }],
    ['Uranus', 19.2, 4.0, 14.5, 0x7fb6d6, { tilt: 97.77 * deg, rotation: -17.24 * h, bands: 3, storm: null, ring: { inner: 1.64, outer: 2.0, opacity: 0.12 } }],
    ['Neptune', 30.1, 3.88, 17.1, 0x5f8fd0, { tilt: 28.32 * deg, rotation: 16.11 * h, bands: 5, storm: { lat: -0.35, lon: 2 }, ring: { inner: 1.7, outer: 2.54, opacity: 0.08 } }],
  ].map(([name, a, r, m, color, look]) => makePlanet(sun, a, r, m, color, rand, name, look));
  // 太陽系の主な衛星：[名前, 軌道長半径(km), 半径(地球比), 質量(地球比), 色, 見た目]
  const SOL_MOONS = {
    Earth: [['Moon', 384400, 0.2727, 0.0123, 0x9a9a96]],
    Mars: [['Phobos', 9376, 0.0018, 1.8e-9, 0x7d6e60], ['Deimos', 23463, 0.00098, 2.5e-10, 0x8a7c6c]],
    Jupiter: [['Io', 421700, 0.286, 0.015, 0xd9c37a, { craters: 0.2 }], ['Europa', 671034, 0.245, 0.008, 0xd8d2c4, { craters: 0.1 }],
      ['Ganymede', 1070412, 0.413, 0.025, 0x9e958a], ['Callisto', 1882709, 0.378, 0.018, 0x6e665c]],
    Saturn: [['Rhea', 527108, 0.12, 0.00039, 0xcfcac2], ['Titan', 1221870, 0.404, 0.0225, 0xd9a85b, { clouds: 1, craters: 0, atmosphere: 0.6 }]],
    Uranus: [['Titania', 435910, 0.124, 0.00059, 0xb8b2aa], ['Oberon', 583520, 0.119, 0.00051, 0xa59e94]],
    Neptune: [['Triton', 354759, 0.212, 0.00359, 0xd8cfc6, { retro: true }]],
  };
  sun.planets.forEach((p) => (p.moons = (SOL_MOONS[p.name] ?? []).map(([name, km, r, m, color, look]) =>
    makeMoon(p, km / 1.495978707e8, r, m, color, name, seededRand(name), look))));

  const totalWeight = STAR_KINDS.reduce((sum, k) => sum + k.weight, 0);
  const pickKind = (r, i) => (r < STAR_KINDS[i].weight || i === STAR_KINDS.length - 1 ? STAR_KINDS[i] : pickKind(r - STAR_KINDS[i].weight, i + 1));
  const count = Math.round((STAR_DENSITY_PER_LY3 * 4 / 3) * Math.PI * FIELD_RADIUS_LY ** 3);
  const others = Array.from({ length: count }, (_, i) => {
    const kind = pickKind(rand() * totalWeight, 0);
    const s = rand();
    const giant = kind.cls === 'III' || kind.cls === 'I';
    const T = THREE.MathUtils.lerp(kind.T[0], kind.T[1], giant ? rand() : s);
    const M = logLerp(kind.M, s);
    // 主系列は質量光度関係、巨星は光度の範囲、白色矮星は半径一定から光度を決める
    const L = kind.cls === 'V' ? (M < 0.43 ? 0.23 * M ** 2.3 : M < 2 ? M ** 4 : 1.4 * M ** 3.5)
      : giant ? logLerp(kind.L, rand()) : kind.R ** 2 * (T / 5772) ** 4;
    const r = FIELD_RADIUS_LY * Math.cbrt(THREE.MathUtils.lerp(0.0001, 1, rand())) * AU_PER_LY;
    const z = rand() * 2 - 1;
    const a = rand() * Math.PI * 2;
    const pos = new THREE.Vector3(Math.sqrt(1 - z * z) * Math.cos(a), Math.sqrt(1 - z * z) * Math.sin(a), z).multiplyScalar(r);
    return finishStar({ name: `SG-${String(i + 1).padStart(4, '0')}`, cls: kind.cls, T, M, L, R: kind.R ?? Math.sqrt(L) * (5772 / T) ** 2, pos }, rand);
  });
  return [finishStar(sun, rand), ...others];
}
