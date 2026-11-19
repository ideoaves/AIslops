import * as THREE from 'three';

// 観測者（船）の速度。uVelDirは宇宙の静止系での進む向き、uUは固有速度γβ、uGammaはローレンツ因子。全マテリアルで同じオブジェクトを共有する
export const relUniforms = {
  uVelDir: { value: new THREE.Vector3(0, 0, -1) },
  uU: { value: 0 },
  uGamma: { value: 1 },
};

// 光行差とドップラー因子。静止系で観測者から見た位置pを、観測者系の見かけの位置（距離は保つ）に移す
// 光源方向と進行方向のなす角の余弦c、固有速度u=γβについて D = γ(1+βc) = γ+uc、見かけの方向は 平行成分 (γc+u)/D・垂直成分 n⊥/D
// 後方（c<0）は γ+uc の桁落ちを避けて D = (1+u²|n⊥|²)/(γ−uc) で求める
export const ABERRATION_GLSL = `
  uniform vec3 uVelDir;
  uniform float uU;
  uniform float uGamma;
  vec3 aberrate(vec3 p, out float D) {
    float d = length(p);
    D = 1.0;
    if (uU <= 0.0 || d <= 0.0) return p;
    vec3 n = p / d;
    float c = dot(n, uVelDir);
    vec3 perp = n - c * uVelDir;
    D = c >= 0.0 ? uGamma + uU * c : (1.0 + uU * uU * dot(perp, perp)) / (uGamma - uU * c);
    return normalize(((uGamma * c + uU) / D) * uVelDir + perp / D) * d;
  }
`;

// 恒星の見え方。温度(K)から黒体の表示色（Tanner Hellandの近似式、sRGB）と、可視域380〜780nmに入る放射の割合（プランクの式を8点で積分）を求める
export const STELLAR_GLSL = `
  vec3 blackbody(float T) {
    float t = clamp(T, 1000.0, 40000.0) / 100.0;
    float r = t <= 66.0 ? 255.0 : 329.698727446 * pow(t - 60.0, -0.1332047592);
    float g = t <= 66.0 ? 99.4708025861 * log(t) - 161.1195681661 : 288.1221695283 * pow(t - 60.0, -0.0755148492);
    float b = t >= 66.0 ? 255.0 : (t <= 19.0 ? 0.0 : 138.5177312231 * log(t - 10.0) - 305.0447927307);
    return clamp(vec3(r, g, b) / 255.0, 0.0, 1.0);
  }
  float planck(float lambda, float T) {
    float x = 1.4388e7 / (lambda * T);
    return x > 80.0 ? 0.0 : pow(lambda, -5.0) / (x < 1e-3 ? x : exp(x) - 1.0);
  }
  float visibleFraction(float T) {
    float s = 0.0;
    for (int i = 0; i < 8; i++) s += planck(405.0 + 50.0 * float(i), T);
    return s * 50.0 / (pow(T / 1.4388e7, 4.0) * 6.4939394);
  }
`;

export const CMB_TEMPERATURE = 2.7255; // 宇宙背景放射の温度（K）。宇宙の静止系をCMBの静止系とみなす
const CMB_REFERENCE_K = 1000;

// 宇宙背景放射を全画面に描く板（射影行列とカメラの姿勢は参照で渡すので毎フレームの更新は要らない）。画素の見かけの方向と進行方向のなす角の余弦cからドップラー因子 D = 1/(γ−uc) を求め、温度 D·T_CMB の黒体として描く
// （I_ν/ν³は不変なので、黒体は温度がD倍になるだけでよい）。前方 c>0 は桁落ちを避けて D = (γ+uc)/(1+u²|n×v|²)
export function createCmb(camera) {
  const material = new THREE.ShaderMaterial({
    uniforms: {
      ...relUniforms,
      projection: { value: camera.projectionMatrix },
      cameraWorld: { value: camera.matrixWorld },
    },
    vertexShader: `
      varying vec2 vNdc;
      void main() {
        vNdc = position.xy;
        gl_Position = vec4(position.xy, 0.0, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 uVelDir;
      uniform float uU;
      uniform float uGamma;
      uniform mat4 projection;
      uniform mat4 cameraWorld;
      varying vec2 vNdc;
      ${STELLAR_GLSL}
      float visibleRadiance(float T) {
        float s = 0.0;
        for (int i = 0; i < 8; i++) s += planck(405.0 + 50.0 * float(i), T);
        return s;
      }
      void main() {
        // 近遠比が極端なので逆射影は使わず、射影行列の対角成分（1/(aspect·tan), 1/tan）から視線方向を作る
        vec3 view = vec3(vNdc.x / projection[0][0], vNdc.y / projection[1][1], -1.0);
        vec3 dir = normalize((cameraWorld * vec4(view, 0.0)).xyz);
        float c = dot(dir, uVelDir);
        vec3 side = cross(dir, uVelDir);
        float D = c <= 0.0 ? 1.0 / (uGamma - uU * c) : (uGamma + uU * c) / (1.0 + uU * uU * dot(side, side));
        float T = ${CMB_TEMPERATURE.toFixed(4)} * D;
        float v = visibleRadiance(T) / visibleRadiance(${CMB_REFERENCE_K.toFixed(1)});
        vec3 color = blackbody(T) * (1.0 - exp(-v));
        gl_FragColor = vec4(color, 1.0);
      }`,
    depthTest: false,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;
  return mesh;
}

// JS側の光行差。GLSLのaberrateと同じ式で、観測者からの位置pを見かけの位置に書き換えて返す
export function aberrate(p) {
  const u = relUniforms.uU.value;
  const g = relUniforms.uGamma.value;
  const v = relUniforms.uVelDir.value;
  const d = p.length();
  if (u <= 0 || d <= 0) return p;
  const n = p.clone().divideScalar(d);
  const c = n.dot(v);
  const perp = n.addScaledVector(v, -c);
  const D = c >= 0 ? g + u * c : (1 + u * u * perp.lengthSq()) / (g - u * c);
  return p.copy(v).multiplyScalar((g * c + u) / D).addScaledVector(perp, 1 / D).normalize().multiplyScalar(d);
}

// 標準マテリアルの頂点変換に光行差を差し込む。カメラが原点なのでワールド座標がそのまま観測者からの位置になる
export function relativistic(material) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, relUniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${ABERRATION_GLSL}`)
      .replace('#include <project_vertex>', `
        vec4 mvPosition = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          mvPosition = instanceMatrix * mvPosition;
        #endif
        vec4 observed = modelMatrix * mvPosition;
        float doppler;
        observed.xyz = aberrate(observed.xyz, doppler);
        mvPosition = viewMatrix * observed;
        gl_Position = projectionMatrix * mvPosition;
      `);
  };
  return material;
}
