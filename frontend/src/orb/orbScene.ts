// The Orb's three.js scene: a gold holographic machine of circuit shells, ring discs, a six-blade iris core,
// ray fans and a network (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md, ported from the approved
// mock docs/superpowers/specs/assets/expressive-ui-orb/arp-landing-source.html). Loaded on demand by
// components/Orb.tsx, so three.js never reaches the main bundle. Phases and colours come from lib/orbMotion.ts;
// this file only draws them.
import {
  AdditiveBlending,
  BufferGeometry,
  CanvasTexture,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  HalfFloatType,
  LineSegments,
  MathUtils,
  Mesh,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  PointsMaterial,
  Quaternion,
  Ray,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  UnsignedByteType,
  Vector2,
  Vector3,
  WebGLRenderTarget,
  WebGLRenderer,
  type IUniform,
  type Material,
  type Object3D,
} from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { pixelRatio, type OrbPhase, type OrbQuality } from "../lib/orbMotion";

export interface OrbSceneOptions {
  quality: OrbQuality;
  /** Run the assembling intro. */
  intro: boolean;
}

export interface OrbScene {
  /** The box is square; `size` is its side in CSS pixels. */
  resize(size: number, dpr: number): void;
  setQuality(q: OrbQuality, dpr: number): void;
  /** Pointer in CSS pixels inside the box, or null when it left. Returns whether it is over the sphere. */
  pointer(x: number | null, y: number | null, hover: boolean): boolean;
  /** Start a transformation; the next colour spreads from the pointer when it is over the sphere. */
  transform(): void;
  /** The transformation ended: the next colour is now the Orb's colour. */
  commit(): void;
  /** Draw one frame. `dt` in seconds; `voice` makes the ring around the core pulse. */
  frame(dt: number, phase: OrbPhase, voice: boolean): void;
  dispose(): void;
}

const TAU = Math.PI * 2;
/** The sphere's radius as a share of half the box: discs reach 1.52 radii, so this leaves room for their glow. */
const EXTENT = 1.62;
const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const easeIO = (x: number) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const back = (x: number) => { x = clamp(x); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const easeOut = (x: number) => 1 - Math.pow(1 - clamp(x), 3);
const rnd = (a = 1, b?: number) => (b === undefined ? Math.random() * a : a + Math.random() * (b - a));
const pick = <T,>(arr: readonly T[]): T => arr[(Math.random() * arr.length) | 0];
const randQ = () => {
  const u = Math.random(), v = Math.random(), w = Math.random();
  return new Quaternion(Math.sqrt(1 - u) * Math.sin(TAU * v), Math.sqrt(1 - u) * Math.cos(TAU * v), Math.sqrt(u) * Math.sin(TAU * w), Math.sqrt(u) * Math.cos(TAU * w));
};

/* ---------- shaders (from the approved mock) ---------- */
const COMMON = `
#define PI 3.14159265
#define TAU 6.2831853
float h11(float n){ return fract(sin(n * 127.1 + 3.7) * 43758.5453); }
float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
// hold, then snap to the next position with a small overshoot: every moving part uses this
float stepEase(float x){ float i = floor(x), f = fract(x); float m = smoothstep(0.62, 1.0, f); float b = m - 1.0; return i + 1.0 + 2.2 * b * b * b + 1.2 * b * b; }
float ln(float dpx, float w, float s){ return 1.0 - smoothstep(max(w - s, 0.0), w + s, dpx); }
float bx(float dpx, float s){ return 1.0 - smoothstep(-s, s, dpx); }
vec2 pattern(float a, float vb, float da, float dvb, float seed, float t, float s){
  float bi = floor(vb), bf = fract(vb);
  float h1 = h11(bi * 1.7 + seed), h2 = h11(bi * 3.1 + seed + 7.0), h3 = h11(bi * 5.3 + seed + 13.0);
  float nc = floor(mix(3.0, 20.0, h1 * h1)) + 2.0;
  float dir = h2 > 0.5 ? 1.0 : -1.0;
  float rot = stepEase(t * (0.06 + 0.14 * h3) + h1 * 20.0) * dir * (1.0 + floor(h2 * 3.0)) / nc;
  float uc = fract(a + rot) * nc;
  float ci = floor(uc), cf = fract(uc);
  float duc = da * nc;
  float ch = h21(vec2(ci, bi) + seed), ch2 = h21(vec2(ci + 31.0, bi + 17.0) + seed * 1.3);
  float I = 0.0, hot = 0.0;
  if (ch < 0.28) {
    float L = mix(0.22, 0.90, clamp(abs(fract(stepEase(t * 0.11 + ch2 * 9.0) * 0.5) * 2.0 - 1.0), 0.0, 1.0));
    float y0 = (ch2 - 0.5) * 0.5;
    float dy = abs(bf - 0.5 - y0) / dvb;
    float e1 = 0.05 + L * 0.9;
    float arc = ln(dy, 0.5, s) * bx(max(0.05 - cf, cf - e1) / duc, s);
    float cap = ln(abs(cf - e1) / duc, 0.5, s) * bx(dy - 0.17 / dvb, s);
    float e = pow(0.5 + 0.5 * sin((cf - t * 0.9 * dir) * TAU + ch * 40.0), 10.0);
    I += arc + cap * 0.9; hot += arc * e * 1.6;
  } else if (ch < 0.40) {
    float d1 = abs(abs(bf - 0.5) - 0.14) / dvb;
    float inx = bx(max(0.04 - cf, cf - 0.96) / duc, s);
    float tf = abs(fract(cf * 6.0) - 0.5) / (duc * 6.0);
    I += ln(d1, 0.45, s) * inx * 0.8;
    I += ln(tf, 0.45, s) * bx((abs(bf - 0.5) - 0.14) / dvb, s) * inx * 0.55 * (1.0 - smoothstep(0.25, 0.6, duc * 6.0));
  } else if (ch < 0.50) {
    float d = max(max(0.10 - cf, cf - 0.90) / duc, (abs(bf - 0.5) - 0.30) / dvb);
    float blink = step(0.72, h11(floor(t * 1.5 + ch * 10.0) + ch * 77.0));
    I += ln(abs(d), 0.5, s) + bx(d, s) * (0.06 + 0.30 * blink);
    hot += bx(d, s) * blink * 0.35;
  } else if (ch < 0.60) {
    float n = 16.0;
    float tf = abs(fract(cf * n) - 0.5) / (duc * n);
    float idx = floor(cf * n);
    float len = mod(idx, 4.0) < 0.5 ? 0.30 : 0.16;
    float tk = ln(tf, 0.4, s) * bx((abs(bf - 0.5) - len) / dvb, s) * (1.0 - smoothstep(0.25, 0.55, duc * n));
    float mk = floor(fract(stepEase(t * 0.5 + ch * 5.0) / n) * n);
    I += tk * 0.8; hot += tk * step(abs(idx - mk), 0.5) * 2.2;
  } else if (ch < 0.68) {
    float hl = ln(abs(bf - 0.3) / dvb, 0.5, s) * bx(max(0.0 - cf, cf - 0.5) / duc, s);
    float vl = ln(abs(cf - 0.5) / duc, 0.5, s) * bx(max(0.3 - bf, bf - 1.0) / dvb, s);
    float nd = bx(max(abs(cf - 0.5) / duc, abs(bf - 0.3) / dvb) - 1.8, s);
    I += max(hl, vl) + nd; hot += nd * 0.6;
  }
  if (h3 > 0.5) I += ln(min(bf, 1.0 - bf) / dvb, 0.4, s) * 0.32;
  float fade = (1.0 - smoothstep(0.30, 0.70, dvb)) * (1.0 - smoothstep(0.30, 0.70, duc));
  return vec2(I, hot) * fade;
}`;
const VERT = `
varying vec3 vP; varying vec3 vW; varying float vDepth;
uniform vec3 uCenter; uniform float uR;
void main(){ vP = position; vec4 wp = modelMatrix * vec4(position, 1.0); vW = wp.xyz - uCenter; vDepth = vW.z / uR; gl_Position = projectionMatrix * viewMatrix * wp; }`;
const TAIL = `
  vec3 wd = normalize(vW);
  float hv = smoothstep(0.8, 0.0, distance(wd, uHover)) * uHoverAmp;
  float ang = acos(clamp(dot(wd, uRipDir), -1.0, 1.0));
  float rp = exp(-pow((ang - uFront) * 4.0, 2.0)) * uRipAmp;
  float mm = clamp(smoothstep(-0.22, 0.22, uFront - ang) + hv * 0.9, 0.0, 1.0);
  vec3 colA = mix(uCol, uAlt, mm), hotA = mix(uHot, uAltHot, mm);
  float k = (gl_FrontFacing ? 1.0 : 0.42) / (1.0 + blur * 1.5) * uAlpha * msk * uGainAll;
  vec3 c = colA * (I * (1.0 + hv * 1.4 + rp * 2.2)) + hotA * (hot + I * (hv * 0.9 + rp * 1.2)) + vec3(0.9) * I * rp * 1.2;
  gl_FragColor = vec4(c * k, 1.0);
}`;
const HEAD = `
uniform float uTime, uSeed, uBands, uGain, uAlpha, uLonHalf, uPx, uFocus, uDof, uHoverAmp, uFront, uRipAmp, uGainAll;
uniform vec3 uCol, uHot, uAlt, uAltHot, uHover, uRipDir;
varying vec3 vP; varying vec3 vW; varying float vDepth;`;
const SHELL_FRAG = COMMON + HEAD + `
uniform vec2 uLat; uniform float uSym;
void main(){
  vec3 p = normalize(vP);
  float lat = asin(clamp(p.y, -1.0, 1.0)), lon = atan(p.z, p.x), lonB = atan(-p.z, -p.x);
  float v = lat / PI + 0.5, a = lon / TAU + 0.5;
  float da = max(min(fwidth(lon), fwidth(lonB)) / TAU, 1e-5) * uPx, dv = max(fwidth(lat) / PI, 1e-5) * uPx;
  float blur = min(abs(vDepth - uFocus) * uDof, 4.0);
  float s = 0.5 / uPx + blur;
  float dLat = max(uLat.x - v, v - uLat.y);
  float dLon = uLonHalf >= 0.499 ? -1000.0 * da : (abs(fract(a * uSym) - 0.5) - uLonHalf) / uSym;
  float msk = bx(max(dLat / dv, dLon / da), s);
  if (msk < 0.003) discard;
  float border = max(ln(abs(dLat) / dv, 0.6, s), ln(abs(dLon) / da, 0.6, s));
  vec2 pt = pattern(a, v * uBands, da, dv * uBands, uSeed, uTime, s);
  float I = pt.x * uGain + border * 1.25 + 0.018;
  float hot = pt.y * uGain + border * 0.15;` + TAIL;
const DISC_FRAG = COMMON + HEAD + `
uniform float uInner, uSweep;
void main(){
  vec2 q = vP.xy; float r = length(q);
  float an = atan(q.y, q.x), anB = atan(-q.y, -q.x);
  float a = an / TAU + 0.5;
  float da = max(min(fwidth(an), fwidth(anB)) / TAU, 1e-5) * uPx, dr = max(fwidth(r), 1e-5) * uPx;
  float blur = min(abs(vDepth - uFocus) * uDof, 4.0);
  float s = 0.5 / uPx + blur;
  float dR = max(uInner - r, r - 1.0);
  float dLon = uLonHalf >= 0.499 ? -1000.0 * da : abs(a - 0.5) - uLonHalf;
  float msk = bx(max(dR / dr, dLon / da), s);
  if (msk < 0.003) discard;
  float border = max(ln(abs(r - 1.0) / dr, 0.7, s), ln(abs(r - uInner) / dr, 0.5, s) * 0.8);
  border = max(border, ln(abs(dLon) / da, 0.6, s));
  float nb = uBands / (1.0 - uInner);
  vec2 pt = pattern(a, (r - uInner) * nb, da, dr * nb, uSeed, uTime, s);
  float sw = pow(1.0 - fract(a - uTime * 0.06), 10.0) * uSweep;
  float I = pt.x * uGain + border * 0.9 + sw + 0.003;
  float hot = pt.y * uGain + sw * 0.4;` + TAIL;
const IRIS_FRAG = COMMON + `
uniform float uTime, uPx, uAperture, uVoice, uBeat, uGainAll; uniform vec3 uCol, uHot;
varying vec3 vP;
void main(){
  vec2 q = vP.xy; float r = length(q);
  float an = atan(q.y, q.x), anB = atan(-q.y, -q.x);
  float a = an / TAU + 0.5;
  float da = max(min(fwidth(an), fwidth(anB)) / TAU, 1e-5) * uPx, dr = max(fwidth(r), 1e-5) * uPx;
  float s = 0.5 / uPx;
  float I = 0.0, hot = 0.0;
  float R0 = 0.15 + 0.08 * uAperture;
  hot += exp(-r * r * 150.0) * (1.4 + uBeat * 1.4) + exp(-r * r * 26.0) * 0.22;
  I += ln(abs(r - R0) / dr, 1.3, s) * 1.6; hot += ln(abs(r - R0) / dr, 0.5, s) * 1.0;
  float n = 6.0;
  float aa = mod(an + uTime * 0.15 + uAperture * 1.6, TAU / n) - PI / n;
  float rh = R0 * 0.78 * cos(PI / n) / cos(aa);
  I += ln(abs(r - rh) / dr, 0.45, s) * 0.9;
  float rh2 = (R0 + 0.07) * cos(PI / n) / cos(mod(an - uTime * 0.11 - uAperture * 1.1, TAU / n) - PI / n);
  I += ln(abs(r - rh2) / dr, 0.4, s) * 0.45;
  float nz = sin(an * 7.0 + uTime * 4.0) * 0.45 + sin(an * 13.0 - uTime * 6.3) * 0.30 + sin(an * 29.0 + uTime * 9.1) * 0.25;
  float rw = 0.36 + uVoice * 0.05 * nz;
  I += ln(abs(r - rw) / dr, 0.55, s) * (0.7 + uVoice * 0.9); hot += ln(abs(r - rw) / dr, 0.4, s) * uVoice * 0.8;
  float a1 = fract(a + stepEase(uTime * 0.35) / 8.0);
  I += ln(abs(r - 0.50) / dr, 1.1, s) * step(fract(a1 * 3.0), 0.74) * 1.1;
  float a2 = fract(a - stepEase(uTime * 0.22 + 3.0) / 12.0);
  I += ln(abs(r - 0.58) / dr, 0.4, s) * step(fract(a2 * 24.0), 0.5) * 0.7;
  float nt = 72.0;
  float tf = abs(fract(a * nt) - 0.5) / (da * nt);
  I += ln(tf, 0.4, s) * bx((abs(r - 0.69) - (mod(floor(a * nt), 6.0) < 0.5 ? 0.04 : 0.022)) / dr, s) * 0.75;
  I += ln(abs(r - 0.80) / dr, 0.4, s) * 0.45;
  float a3 = fract(a + stepEase(uTime * 0.18 + 7.0) / 6.0);
  I += ln(abs(r - 0.93) / dr, 1.5, s) * step(fract(a3 * 3.0), 0.16) * 1.3;
  I *= bx((r - 0.985) / dr, s);
  gl_FragColor = vec4((uCol * I + uHot * hot) * uGainAll, 1.0);
}`;
const LINE_VERT = `
attribute float aT; attribute float aSeed; varying float vT; varying float vSeed; varying float vDepth;
uniform vec3 uCenter; uniform float uR;
void main(){ vT = aT; vSeed = aSeed; vec4 wp = modelMatrix * vec4(position, 1.0); vDepth = (wp.z - uCenter.z) / uR; gl_Position = projectionMatrix * viewMatrix * wp; }`;
// Rays and links draw out from their start, hold, then retract from the tail: nothing travels in or out.
const LINE_FRAG = `
uniform float uTime, uSpeed, uGain, uFocus, uDof; uniform vec3 uCol, uHot;
varying float vT; varying float vSeed; varying float vDepth;
void main(){
  float ph = fract(uTime * uSpeed * (0.6 + 0.8 * fract(vSeed * 7.31)) + vSeed);
  float head = smoothstep(0.0, 0.16, ph), tail = smoothstep(0.58, 0.84, ph);
  float on = step(vT, head) * step(tail, vT);
  float tip = exp(-abs(vT - head) * 9.0) * (1.0 - smoothstep(0.14, 0.34, ph));
  float k = (vDepth < 0.0 ? 0.55 : 1.0) / (1.0 + abs(vDepth - uFocus) * uDof * 0.5);
  gl_FragColor = vec4((uCol * 0.5 + uHot * tip * 1.8) * on * uGain * k, 1.0);
}`;
const FINAL_FRAG = `
uniform sampler2D tDiffuse; uniform vec2 uC, uRes; uniform float uTime, uCA, uExp, uGrain; varying vec2 vUv;
float hh(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233)) + uTime * 3.1) * 43758.5453); }
void main(){
  vec2 d = vUv - uC; float r2 = dot(d, d);
  vec2 off = d * uCA * (1.0 + 8.0 * r2);
  vec3 c = vec3(0.0), wsum = vec3(0.0);
  for (int i = 0; i < 7; i++) {
    float t = float(i) / 6.0;
    vec3 w = max(vec3(1.0 - smoothstep(0.0, 0.6, t), 1.0 - abs(t - 0.5) * 2.6, smoothstep(0.4, 1.0, t)), 0.0);
    c += texture2D(tDiffuse, vUv + off * (t - 0.5) * 2.0).rgb * w; wsum += w;
  }
  c /= wsum;
  c = 1.0 - exp(-c * uExp);
  c *= 1.0 + (hh(floor(vUv * uRes)) - 0.5) * uGrain;
  c *= 1.0 - smoothstep(0.47, 0.5, length(vUv - 0.5)); // the glow fades out before the box's edge
  gl_FragColor = vec4(c, 1.0);
}`;

// Raw component values (not sRGB-decoded), as in the mock; DESIGN.md lists them as orb-gold, -ice, -ember, -mint.
const PAL = [
  { col: new Color(1.0, 0.56, 0.12), hot: new Color(1.0, 0.86, 0.48) },
  { col: new Color(0.14, 0.62, 1.0), hot: new Color(0.62, 0.95, 1.0) },
  { col: new Color(1.0, 0.27, 0.1), hot: new Color(1.0, 0.7, 0.34) },
  { col: new Color(0.1, 0.92, 0.62), hot: new Color(0.74, 1.0, 0.86) },
];
const LON = [0.14, 0.2, 0.26, 0.32, 0.38];

interface Part {
  mesh: Mesh; mat: ShaderMaterial; r: number; q: Quaternion; qFrom: Quaternion | null; qTo: Quaternion | null; qT: number; qDur: number;
  spin: number; lonHalf: number; latC: number; latH: number; rs: number; w: number; next: number;
}
interface Disc { g: Group; mesh: Mesh; mat: ShaderMaterial; tx: number; ty: number; spin: number; lonHalf: number; home: number; fixed: boolean; w: number; next: number }
interface Tween { o: Record<string, number>; k: string; from: number | null; to: number; dur: number; t: number; e: (x: number) => number }

export function createOrbScene(canvas: HTMLCanvasElement, context: WebGL2RenderingContext, opts: OrbSceneOptions): OrbScene {
  const renderer = new WebGLRenderer({ canvas, context, antialias: false, alpha: false, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 1);
  const scene = new Scene();
  const camera = new PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0, 12);
  camera.updateMatrixWorld();
  const FT = renderer.extensions.has("EXT_color_buffer_float") ? HalfFloatType : UnsignedByteType;
  // No MSAA: 4x multisampling more than doubled the frame time of high and medium in a software renderer, which
  // kept slow machines from stepping down in time (AC-26); bloom and grain already soften the line edges.
  // The composer, bloom and final pass cost memory and a shader compile, so they are built on the first layout
  // whose quality is not "low" and kept from then on.
  type Post = { composer: EffectComposer; bloom: UnrealBloomPass; finalPass: ShaderPass };
  let post: Post | null = null;
  function buildPost(): Post {
    const rt = new WebGLRenderTarget(8, 8, { type: FT, samples: 0, depthBuffer: false });
    const composer = new EffectComposer(renderer, rt);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new Vector2(256, 256), 0.62, 0.62, 0.5);
    [bloom.renderTargetBright, ...bloom.renderTargetsHorizontal, ...bloom.renderTargetsVertical].forEach((t) => { t.texture.type = FT; });
    composer.addPass(bloom);
    const finalPass = new ShaderPass({
      uniforms: { tDiffuse: { value: null }, uC: { value: new Vector2(0.5, 0.5) }, uTime: { value: 0 }, uCA: { value: 0.0032 }, uExp: { value: 1.4 }, uGrain: { value: 0.06 }, uRes: { value: new Vector2(1, 1) } },
      vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: FINAL_FRAG,
    });
    composer.addPass(finalPass);
    return { composer, bloom, finalPass };
  }

  const U: Record<string, IUniform> = {
    uTime: { value: 0 }, uCol: { value: PAL[0].col.clone() }, uHot: { value: PAL[0].hot.clone() },
    uCenter: { value: new Vector3() }, uR: { value: 1 }, uPx: { value: 1 },
    uHover: { value: new Vector3(0, 0, 1) }, uHoverAmp: { value: 0 },
    uRipDir: { value: new Vector3(0, 0, 1) }, uFront: { value: -1 }, uRipAmp: { value: 0 },
    uAlt: { value: PAL[1].col.clone() }, uAltHot: { value: PAL[1].hot.clone() },
    uFocus: { value: 0.55 }, uDof: { value: 1.15 }, uGainAll: { value: 1 },
  };
  const S = { aperture: 1, front: -1, ripAmp: 0, colT: 0, punch: 0, voice: 0, grow: 1 };
  const cur = { uCol: { value: PAL[0].col.clone() }, uHot: { value: PAL[0].hot.clone() } };
  const matOpts = { transparent: true, depthWrite: false, depthTest: false, side: DoubleSide, blending: AdditiveBlending } as const;

  const orb = new Group();
  scene.add(orb);
  const body = new Group();
  orb.add(body);

  const sphereGeo = new SphereGeometry(1, 96, 64);
  const parts: Part[] = [];
  ([[0.46, 8, 0.8, 0.9, 3], [0.62, 12, 0.7, 0.85, 2], [0.8, 16, 0.65, 0.8, 4], [0.94, 20, 0.6, 0.75, 3], [1.06, 24, 0.6, 0.7, 2], [1.2, 16, 0.5, 0.6, 5], [1.32, 12, 0.45, 0.5, 2]] as const).forEach(([r, bands, gain, alpha, sym], i) => {
    const mat = new ShaderMaterial({ ...matOpts, uniforms: { ...U, uSeed: { value: 11.3 * (i + 1) }, uBands: { value: bands }, uGain: { value: gain }, uAlpha: { value: alpha }, uLat: { value: new Vector2(0.2, 0.8) }, uLonHalf: { value: 0.3 }, uSym: { value: sym } }, vertexShader: VERT, fragmentShader: SHELL_FRAG });
    const mesh = new Mesh(sphereGeo, mat);
    mesh.frustumCulled = false;
    body.add(mesh);
    parts.push({ mesh, mat, r, q: randQ(), qFrom: null, qTo: null, qT: 0, qDur: 1, spin: rnd(TAU), lonHalf: pick(LON), latC: rnd(0.34, 0.66), latH: rnd(0.05, 0.15), rs: 1, w: (i % 2 ? -1 : 1) * rnd(0.03, 0.09), next: rnd(0.5, 3.5) });
  });

  const planeGeo = new PlaneGeometry(2, 2);
  const discs: Disc[] = [];
  ([[1.42, 0.3, 12, 0.9, 0.9, 0.22, -1.15, 0.25, 0.5], [1.14, 0.83, 3, 1.0, 0.9, 0, 0.55, 1.0, 0.36], [0.86, 0.8, 3, 1.0, 0.9, 0, -0.45, -0.9, 0.3], [1.52, 0.895, 3, 0.9, 0.8, 0.1, 0.1, -0.08, 0.5]] as const).forEach(([outer, inner, bands, gain, alpha, sweep, tx, ty, lonHalf], i) => {
    const mat = new ShaderMaterial({ ...matOpts, uniforms: { ...U, uSeed: { value: 40.7 + i * 9.1 }, uBands: { value: bands }, uGain: { value: gain }, uAlpha: { value: alpha }, uInner: { value: inner }, uSweep: { value: sweep }, uLonHalf: { value: lonHalf } }, vertexShader: VERT, fragmentShader: DISC_FRAG });
    const g = new Group();
    orb.add(g);
    const mesh = new Mesh(planeGeo, mat);
    mesh.frustumCulled = false;
    mesh.scale.setScalar(outer);
    g.add(mesh);
    discs.push({ g, mesh, mat, tx, ty, spin: rnd(TAU), lonHalf, home: lonHalf, fixed: i === 3, w: [0.03, -0.05, 0.07, -0.02][i], next: rnd(1, 4) });
  });

  function lineSet(pos: number[], ts: number[], seeds: number[], speed: number, gain: number, parent: Object3D) {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(pos, 3));
    g.setAttribute("aT", new Float32BufferAttribute(ts, 1));
    g.setAttribute("aSeed", new Float32BufferAttribute(seeds, 1));
    const mat = new ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: AdditiveBlending, uniforms: { ...U, ...cur, uSpeed: { value: speed }, uGain: { value: gain } }, vertexShader: LINE_VERT, fragmentShader: LINE_FRAG });
    const l = new LineSegments(g, mat);
    l.frustumCulled = false;
    parent.add(l);
  }
  const rays = new Group();
  body.add(rays);
  {
    const pos: number[] = [], ts: number[] = [], seeds: number[] = [];
    for (let f = 0; f < 8; f++) {
      const q = randQ(), n = 4 + ((Math.random() * 5) | 0), a0 = rnd(TAU), spread = rnd(0.045, 0.11), base = Math.random();
      for (let i = 0; i < n; i++) {
        const a = a0 + i * spread, d = new Vector3(Math.cos(a), Math.sin(a), 0).applyQuaternion(q);
        const r0 = rnd(0.12, 0.2), r1 = rnd(0.8, 1.38), sd = base + i * 0.018;
        pos.push(d.x * r0, d.y * r0, d.z * r0, d.x * r1, d.y * r1, d.z * r1);
        ts.push(0, 1);
        seeds.push(sd, sd);
      }
    }
    for (let i = 0; i < 5; i++) {
      const a = new Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(1.3), b = new Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(1.3), sd = Math.random();
      pos.push(a.x, a.y, a.z, b.x, b.y, b.z);
      ts.push(0, 1);
      seeds.push(sd, sd);
    }
    lineSet(pos, ts, seeds, 0.16, 1.0, rays);
  }
  const net = new Group();
  body.add(net);
  const nodeMat = new PointsMaterial({ size: 3, sizeAttenuation: false, transparent: true, opacity: 0.9, blending: AdditiveBlending, depthWrite: false, depthTest: false });
  {
    const N = 30, nodes: Vector3[] = [];
    for (let i = 0; i < N; i++) nodes.push(new Vector3(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(rnd(0.58, 0.8)));
    const pos: number[] = [], ts: number[] = [], seeds: number[] = [], seen = new Set<string>();
    nodes.forEach((v, i) => {
      nodes.map((w, j) => [v.distanceToSquared(w), j] as const).filter((x) => x[1] !== i).sort((a, b) => a[0] - b[0]).slice(0, 2).forEach(([, j]) => {
        const key = Math.min(i, j) + "-" + Math.max(i, j);
        if (seen.has(key)) return;
        seen.add(key);
        const w = nodes[j], sd = Math.random();
        pos.push(v.x, v.y, v.z, w.x, w.y, w.z);
        ts.push(0, 1);
        seeds.push(sd, sd);
      });
    });
    lineSet(pos, ts, seeds, 0.11, 1.1, net);
    net.add(new Points(new BufferGeometry().setFromPoints(nodes), nodeMat));
  }

  // core, glow and lens streak face the camera
  const flat = new Group();
  scene.add(flat);
  const irisMat = new ShaderMaterial({ ...matOpts, uniforms: { uTime: U.uTime, uPx: U.uPx, uGainAll: U.uGainAll, uCol: cur.uCol, uHot: cur.uHot, uAperture: { value: 1 }, uVoice: { value: 0 }, uBeat: { value: 0 } }, vertexShader: "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }", fragmentShader: IRIS_FRAG });
  const iris = new Mesh(planeGeo, irisMat);
  iris.scale.setScalar(0.56);
  flat.add(iris);
  const tex = (w: number, h: number, draw: (x: CanvasRenderingContext2D, w: number, h: number) => void) => {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    draw(c.getContext("2d")!, w, h);
    return new CanvasTexture(c);
  };
  const glowMat = new SpriteMaterial({
    map: tex(256, 256, (x) => { const g = x.createRadialGradient(128, 128, 0, 128, 128, 128); g.addColorStop(0, "rgba(255,255,255,.5)"); g.addColorStop(0.3, "rgba(255,255,255,.12)"); g.addColorStop(1, "rgba(255,255,255,0)"); x.fillStyle = g; x.fillRect(0, 0, 256, 256); }),
    transparent: true, opacity: 0.2, blending: AdditiveBlending, depthWrite: false, depthTest: false,
  });
  const glow = new Sprite(glowMat);
  glow.scale.set(3.2, 3.2, 1);
  flat.add(glow);
  const streakMat = new SpriteMaterial({
    map: tex(512, 32, (x, w, h) => { const g = x.createLinearGradient(0, 0, w, 0); g.addColorStop(0, "rgba(255,255,255,0)"); g.addColorStop(0.5, "rgba(255,255,255,1)"); g.addColorStop(1, "rgba(255,255,255,0)"); x.fillStyle = g; x.fillRect(0, 0, w, h); const v = x.createLinearGradient(0, 0, 0, h); v.addColorStop(0, "rgba(0,0,0,1)"); v.addColorStop(0.5, "rgba(0,0,0,0)"); v.addColorStop(1, "rgba(0,0,0,1)"); x.globalCompositeOperation = "destination-out"; x.fillStyle = v; x.fillRect(0, 0, w, h); }),
    transparent: true, opacity: 0.3, blending: AdditiveBlending, depthWrite: false, depthTest: false,
  });
  const streak = new Sprite(streakMat);
  streak.scale.set(3.2, 0.05, 1);
  flat.add(streak);

  /* ---------- tweens ---------- */
  let tweens: Tween[] = [];
  const tw = (o: object, k: string, to: number, dur: number, delay = 0, e = easeIO) => { tweens.push({ o: o as Record<string, number>, k, from: null, to, dur, t: -delay, e }); };
  const runTweens = (dt: number) => {
    tweens = tweens.filter((w) => {
      w.t += dt;
      if (w.t < 0) return true;
      if (w.from === null) w.from = w.o[w.k];
      const x = clamp(w.t / w.dur);
      w.o[w.k] = w.from + (w.to - w.from) * w.e(x);
      return x < 1;
    });
  };

  /* ---------- choreography ---------- */
  let palIdx = 0;
  function reconfigure(dir: Vector3 | null) {
    tweens = [];
    parts.forEach((p, i) => {
      const d = i * 0.07;
      tw(p, "lonHalf", 0.05, 0.6, d); // fold to a sliver
      tw(p, "rs", 0.62 + 0.03 * i, 0.55, 0.15 + d); // slide in toward the core
      p.qFrom = null; p.qTo = randQ(); p.qT = -(0.5 + d); p.qDur = 1.15; // swing to a new axis
      tw(p, "spin", p.spin + pick([-1, 1]) * Math.PI * rnd(0.5, 1.25), 1.5, 0.45 + d);
      tw(p, "latC", rnd(0.34, 0.66), 0.9, 1.5 + d);
      tw(p, "latH", rnd(0.05, 0.15), 0.9, 1.5 + d);
      tw(p, "rs", 1, 0.7, 1.45 + d * 1.8, back); // telescope back out, inner parts first
      tw(p, "lonHalf", pick(LON), 0.95, 1.7 + d * 1.8, back); // unfold and lock
      p.next = rnd(3.4, 6.5);
    });
    discs.forEach((d, i) => {
      tw(d, "lonHalf", 0.06, 0.5, i * 0.08);
      if (!d.fixed) { tw(d, "tx", rnd(-1.25, 1.25), 1.25, 0.4 + i * 0.12, back); tw(d, "ty", rnd(-1.1, 1.1), 1.25, 0.4 + i * 0.12, back); }
      tw(d, "spin", d.spin + pick([-1, 1]) * rnd(1, 2.4), 1.6, 0.3 + i * 0.1);
      tw(d, "lonHalf", d.home, 0.9, 1.7 + i * 0.12, back);
      d.next = rnd(3.4, 6);
    });
    tw(S, "aperture", 0, 0.5, 0);
    tw(S, "aperture", 1, 0.75, 1.55, back);
    (U.uRipDir.value as Vector3).copy(dir ?? new Vector3(0, 0, 1));
    S.front = -0.3; S.ripAmp = 1; S.colT = 0;
    tw(S, "front", Math.PI + 0.4, 1.7, 1.3, easeOut); // the next colour spreads from that point
    tw(S, "ripAmp", 0, 0.7, 2.4);
    tw(S, "colT", 1, 1.0, 1.3);
  }
  function assemble() {
    S.aperture = 0; S.grow = 0;
    tw(S, "aperture", 1, 0.8, 0.35, back);
    tw(S, "grow", 1, 1.5, 0.5, easeOut);
    parts.forEach((p, i) => {
      const lon = p.lonHalf, d = 0.55 + i * 0.17;
      p.lonHalf = 0.02; p.rs = 0.5 + 0.03 * i;
      tw(p, "rs", 1, 0.8, d, back); // each shell slides out to its radius
      tw(p, "spin", p.spin + (i % 2 ? -1 : 1) * Math.PI * 0.75, 1.4, d);
      tw(p, "lonHalf", lon, 1.0, d + 0.3, back); // then opens and locks
      p.next = rnd(4.2, 7);
    });
    discs.forEach((d, i) => {
      d.lonHalf = 0.02;
      tw(d, "spin", d.spin + (i % 2 ? -1.6 : 1.6), 1.6, 1.0 + i * 0.25);
      tw(d, "lonHalf", d.home, 1.0, 1.2 + i * 0.25, back);
      d.next = rnd(4.2, 7);
    });
  }
  function commitColour() {
    palIdx = (palIdx + 1) % PAL.length;
    const nx = PAL[(palIdx + 1) % PAL.length];
    (U.uCol.value as Color).copy(PAL[palIdx].col);
    (U.uHot.value as Color).copy(PAL[palIdx].hot);
    (U.uAlt.value as Color).copy(nx.col);
    (U.uAltHot.value as Color).copy(nx.hot);
    S.front = -1; S.colT = 0;
  }
  function idle(dt: number) {
    parts.forEach((p) => {
      p.next -= dt;
      if (p.next > 0) return;
      const r = Math.random();
      if (r < 0.6) tw(p, "spin", p.spin + pick([-1, 1]) * pick([Math.PI / 4, Math.PI / 3, Math.PI / 2, (2 * Math.PI) / 3]), rnd(0.9, 1.5), 0, back);
      else if (r < 0.78) tw(p, "lonHalf", pick(LON), 1.1, 0, back);
      else if (r < 0.9) { tw(p, "rs", pick([0.92, 1.08]), 0.7, 0, back); tw(p, "rs", 1, 0.7, 1.6, back); }
      else { tw(p, "latC", rnd(0.34, 0.66), 1.1); tw(p, "latH", rnd(0.05, 0.15), 1.1); }
      p.next = rnd(1.6, 4.5);
    });
    discs.forEach((d) => {
      d.next -= dt;
      if (d.next > 0) return;
      tw(d, "spin", d.spin + pick([-1, 1]) * pick([Math.PI / 6, Math.PI / 4, Math.PI / 2]), rnd(0.9, 1.4), 0, back);
      if (!d.fixed && Math.random() < 0.4) tw(d, "tx", d.tx + rnd(-0.35, 0.35), 1.3, 0, back);
      d.next = rnd(2, 5);
    });
  }

  /* ---------- layout, quality and input ---------- */
  let quality = opts.quality;
  let size = 1, dpr = 1, rPx = 1;
  const ppu = () => size / (2 * camera.position.z * Math.tan(MathUtils.degToRad(camera.fov / 2)));
  function layout() {
    const pr = pixelRatio(quality, dpr, size, size);
    renderer.setPixelRatio(pr);
    renderer.setSize(size, size, false);
    if (quality !== "low") post ??= buildPost();
    if (post) {
      post.composer.setPixelRatio(pr);
      post.composer.setSize(size, size);
      if (quality === "medium") post.bloom.setSize(Math.round(size / 2), Math.round(size / 2));
      (post.finalPass.uniforms.uRes.value as Vector2).set(size, size);
    }
    U.uPx.value = pr;
    rPx = size / 2 / EXTENT;
    U.uDof.value = quality === "high" ? 1.15 : 0;
    // Without post-processing nothing blooms: lift the lines so the low Orb still reads as lit gold.
    U.uGainAll.value = quality === "low" ? 1.35 : 1;
    net.visible = quality !== "low";
  }
  const ptr = { x: 0, y: 0, in: false };
  const hitV = new Vector3();
  const ray = new Ray();
  function hitDir(): Vector3 | null {
    if (!ptr.in) return null;
    const nx = (ptr.x / size) * 2 - 1, ny = -(ptr.y / size) * 2 + 1;
    ray.origin.copy(camera.position);
    ray.direction.set(nx, ny, 0.5).unproject(camera).sub(camera.position).normalize();
    const R = U.uR.value as number;
    const toC = new Vector3().sub(ray.origin);
    const tca = toC.dot(ray.direction), d2 = toC.lengthSq() - tca * tca, rr = (R * 1.1) ** 2;
    if (d2 > rr) return null;
    ray.at(tca - Math.sqrt(rr - d2), hitV);
    return hitV.clone().normalize();
  }
  let hover = false;

  if (opts.intro) assemble();

  let T = 0, prevPhase: OrbPhase | null = null;
  const qy = new Quaternion(), yAxis = new Vector3(0, 1, 0), WHITE = new Color(0.9, 0.9, 0.9);

  return {
    resize(s, d) {
      size = Math.max(1, s);
      dpr = d;
      layout();
    },
    setQuality(q, d) {
      quality = q;
      dpr = d;
      layout();
    },
    pointer(x, y, hv) {
      hover = hv;
      if (x === null || y === null) ptr.in = false;
      else { ptr.x = x; ptr.y = y; ptr.in = true; }
      return hitDir() !== null;
    },
    transform() {
      reconfigure(hover ? hitDir() : null);
    },
    commit() {
      commitColour();
    },
    frame(dt, phase, voiceOn) {
      T += dt;
      U.uTime.value = T;
      if (post) post.finalPass.uniforms.uTime.value = T % 100;
      runTweens(dt);
      if (phase === "locked" && prevPhase !== "locked") S.punch = 1;
      prevPhase = phase;
      if (phase === "idle" || phase === "speaking") idle(dt);
      S.punch *= Math.exp(-dt * 5);
      const env = voiceOn ? 0.25 + 0.75 * Math.abs(Math.sin(T * 9.1) * Math.sin(T * 5.3 + 1.0) + 0.3 * Math.sin(T * 23.0)) : 0;
      S.voice += (env - S.voice) * Math.min(1, dt * 14);
      const bt = (T % 2.4) / 2.4, beat = Math.exp(-Math.pow((bt - 0.05) * 20, 2)) + 0.6 * Math.exp(-Math.pow((bt - 0.17) * 20, 2));

      const wh = Math.sin(Math.PI * S.colT) * 0.6;
      cur.uCol.value.copy(U.uCol.value as Color).lerp(U.uAlt.value as Color, S.colT).lerp(WHITE, wh);
      cur.uHot.value.copy(U.uHot.value as Color).lerp(U.uAltHot.value as Color, S.colT).lerp(WHITE, wh);

      // body: slow turn and a lean toward the pointer; a punch when everything locks
      body.rotation.y += dt * 0.07;
      body.rotation.x = Math.sin(T * 0.19) * 0.14;
      const c = size / 2;
      const lx = ptr.in && hover ? clamp((ptr.x - c) / (rPx * 4), -0.4, 0.4) : 0;
      const ly = ptr.in && hover ? clamp((ptr.y - c) / (rPx * 4), -0.4, 0.4) : 0;
      orb.rotation.y += (lx * 0.7 - orb.rotation.y) * Math.min(1, dt * 3);
      orb.rotation.x += (ly * 0.7 - orb.rotation.x) * Math.min(1, dt * 3);
      const R = (rPx / ppu()) * (1 + S.punch * 0.03 + 0.006 * Math.sin(T * 1.1));
      orb.scale.setScalar(R);
      flat.scale.setScalar(R);
      U.uR.value = R;

      const hd = hover ? hitDir() : null;
      if (hd) (U.uHover.value as Vector3).lerp(hd, Math.min(1, dt * 14)).normalize();
      U.uHoverAmp.value += ((hd ? 1 : 0) - (U.uHoverAmp.value as number)) * Math.min(1, dt * 8);
      U.uFront.value = S.front;
      U.uRipAmp.value = S.ripAmp;

      parts.forEach((p) => {
        if (p.qTo) {
          p.qT += dt;
          if (p.qT >= 0) {
            if (!p.qFrom) p.qFrom = p.q.clone();
            const x = clamp(p.qT / p.qDur);
            p.q.copy(p.qFrom).slerp(p.qTo, back(x)).normalize();
            if (x >= 1) { p.q.copy(p.qTo); p.qTo = null; p.qFrom = null; }
          }
        }
        p.spin += dt * p.w;
        p.mesh.quaternion.copy(p.q).multiply(qy.setFromAxisAngle(yAxis, p.spin));
        p.mesh.scale.setScalar(p.r * p.rs * (1 + S.punch * 0.02));
        (p.mat.uniforms.uLat.value as Vector2).set(p.latC - p.latH, p.latC + p.latH);
        p.mat.uniforms.uLonHalf.value = p.lonHalf;
      });
      discs.forEach((d) => { d.spin += dt * d.w; d.g.rotation.set(d.tx, d.ty, 0); d.mesh.rotation.z = d.spin; d.mat.uniforms.uLonHalf.value = d.lonHalf; });
      rays.scale.setScalar(Math.max(0.001, S.grow));
      net.scale.setScalar(Math.max(0.001, S.grow));
      rays.rotation.z += dt * 0.03;
      net.rotation.y -= dt * 0.12;
      net.rotation.x += dt * 0.05;
      nodeMat.color.copy(cur.uHot.value);

      irisMat.uniforms.uAperture.value = S.aperture;
      irisMat.uniforms.uVoice.value = S.voice;
      irisMat.uniforms.uBeat.value = beat + S.punch * 2;
      glowMat.color.copy(cur.uCol.value);
      glowMat.opacity = 0.06 + beat * 0.015 + S.punch * 0.14 + S.voice * 0.04;
      streakMat.color.copy(cur.uHot.value);
      streakMat.opacity = 0.14 + beat * 0.08 + S.punch * 0.6 + S.voice * 0.2;
      streak.scale.set(2.9 + S.punch * 1.2 + S.voice * 0.3, 0.045, 1);

      if (quality === "low") renderer.render(scene, camera);
      else {
        post ??= buildPost();
        post.bloom.strength = 0.62 + S.punch * 0.55 + S.voice * 0.1;
        post.composer.render();
      }
    },
    dispose() {
      scene.traverse((o) => {
        const m = o as Mesh;
        m.geometry?.dispose();
        const mats: Material[] = m.material ? ([] as Material[]).concat(m.material) : [];
        mats.forEach((mt) => { (mt as SpriteMaterial).map?.dispose(); mt.dispose(); });
      });
      post?.bloom.dispose();
      post?.finalPass.dispose();
      post?.composer.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
