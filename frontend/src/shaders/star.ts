/**
 * GLSL photosphere shader for the host star.
 *
 * Physics notes:
 * - Limb darkening uses the Eddington linear approximation I(μ)/I(1) = a + b·μ
 *   with a=0.4, b=0.6 — a good match for the Sun in visible light.
 * - Granulation is domain-warped FBM; real solar granules are convection cells
 *   that drift and churn, which the time-driven warp approximates.
 * - Differential rotation: the Sun's equator rotates ~30% faster than its
 *   poles; granulation drift speed scales with cos(latitude) here.
 * - Sunspot coverage waxes and wanes on a slow cycle, a nod to the 11-year
 *   solar activity cycle (compressed enormously for watchability).
 */

export const starVertexShader = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  varying vec2 vUv;

  void main() {
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vWorldPos = worldPos.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    vUv = uv;
    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

export const starFragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec3  uColor1;   // core color (hot white)
  uniform vec3  uColor2;   // mid color (yellow)
  uniform vec3  uColor3;   // limb color (deep orange)

  varying vec3 vNormal;
  varying vec3 vWorldPos;
  varying vec2 vUv;

  // ── Hash / noise ─────────────────────────────────────────
  float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 17.5);
    return fract(p.x * p.y);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1,0)), u.x),
      mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x),
      u.y
    );
  }

  float fbm(vec2 p, int octaves) {
    float v = 0.0; float amp = 0.5; float freq = 1.0;
    for (int i = 0; i < 6; i++) {
      if (i >= octaves) break;
      v += amp * noise(p * freq);
      amp *= 0.5; freq *= 2.1;
    }
    return v;
  }

  // ── Granulation (domain-warped fbm) ──────────────────────
  float granulation(vec2 uv, float t, float latFactor) {
    // [CREATIVE: differential rotation — equatorial granulation drifts faster
    // than polar granulation, like the real Sun]
    vec2 drift = vec2(t * 0.018 * latFactor, t * 0.011);
    vec2 q = vec2(fbm(uv + drift, 4), fbm(uv + vec2(5.2, 1.3) + drift * 0.8, 4));
    return fbm(uv + 0.9 * q + drift, 5);
  }

  // ── Sunspots with a slow activity cycle ───────────────────
  float sunspot(vec2 uv, float t) {
    float s = fbm(uv * 0.55 + vec2(t * 0.004, t * 0.003), 3);
    // [CREATIVE: solar activity cycle — spot coverage waxes and wanes slowly]
    float cycle = 0.5 + 0.5 * sin(t * 0.012);
    float threshold = mix(0.50, 0.62, cycle);
    return smoothstep(threshold, threshold - 0.07, s);
  }

  void main() {
    // Limb darkening — Eddington approximation with the true view angle
    vec3 viewDir = normalize(cameraPosition - vWorldPos);
    float mu = max(0.0, dot(normalize(vNormal), viewDir));
    float limb = 0.4 + 0.6 * mu;

    float latFactor = 0.7 + 0.3 * (1.0 - abs(vUv.y - 0.5) * 2.0);
    float gran = granulation(vUv * 4.0, uTime, latFactor);
    float spot = sunspot(vUv * 3.0, uTime);

    // Base color — blend from hot core tone toward the limb tone
    vec3 color = mix(uColor1, mix(uColor2, uColor3, 1.0 - mu), 1.0 - mu * 0.7);

    // Granulation brightens/darkens slightly
    color += (gran - 0.5) * 0.18 * uColor1;

    // [CREATIVE: faculae — bright magnetic lacework hugging sunspot edges,
    // visible mostly near the limb like the real thing]
    float faculae = smoothstep(0.05, 0.30, spot) * (1.0 - spot) * (1.0 - mu);
    color += uColor1 * faculae * 0.35;

    // Sunspot umbra darkens
    color *= (1.0 - spot * 0.52);

    color *= limb;

    // [CREATIVE: rare coronal-mass-ejection brightening — every ~3 minutes the
    // whole photosphere surges for a couple of seconds, feeding the bloom pass]
    float cmePhase = fract(uTime / 180.0);
    float cme = smoothstep(0.0, 0.011, cmePhase) * (1.0 - smoothstep(0.011, 0.025, cmePhase));
    color *= 1.0 + cme * 0.85;

    gl_FragColor = vec4(color, 1.0);
  }
`;

export type SpectralType = 'F' | 'G' | 'K' | 'M';

const palettes: Record<SpectralType, { c1: number[]; c2: number[]; c3: number[] }> = {
  F: { c1: [1.0, 1.0, 0.96], c2: [1.0, 0.94, 0.72], c3: [0.92, 0.65, 0.22] },
  G: { c1: [1.0, 0.98, 0.88], c2: [1.0, 0.82, 0.38], c3: [0.88, 0.42, 0.08] },
  K: { c1: [1.0, 0.88, 0.7], c2: [0.98, 0.62, 0.22], c3: [0.8, 0.3, 0.05] },
  M: { c1: [1.0, 0.72, 0.48], c2: [0.9, 0.42, 0.18], c3: [0.72, 0.2, 0.06] },
};

/**
 * [CREATIVE: infer the host star's spectral type from its habitable-zone
 * inner radius. The HZ distance scales with sqrt(L*): cool M dwarfs hold
 * their HZ within ~0.3 AU, K dwarfs within ~0.8, Sun-likes near 1 AU, and
 * hotter F stars push it past ~1.3 AU. So when the pipeline reports HZ
 * boundaries we can color the star plausibly without extra catalog calls.]
 */
export function inferSpectralType(hzInnerAu: number | null | undefined): SpectralType {
  if (hzInnerAu == null || !Number.isFinite(hzInnerAu) || hzInnerAu <= 0) return 'G';
  if (hzInnerAu < 0.3) return 'M';
  if (hzInnerAu < 0.8) return 'K';
  if (hzInnerAu < 1.3) return 'G';
  return 'F';
}

export function makeStarUniforms(spectralType: SpectralType = 'G') {
  const p = palettes[spectralType];
  return {
    uTime: { value: 0 },
    uColor1: { value: p.c1 },
    uColor2: { value: p.c2 },
    uColor3: { value: p.c3 },
  };
}
