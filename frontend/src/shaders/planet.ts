import { PlanetClass } from '../lib/planetClassifier';

/**
 * Shared GLSL surface shader for all rendered planet classes.
 *
 * One material, seven looks: the fragment shader branches on uClass and
 * builds each surface procedurally from seeded FBM noise, then applies a
 * single physically-motivated lighting pass — per-pixel diffuse from the
 * star at the origin, a soft terminator, Fresnel atmosphere rim that
 * brightens toward the star, and class-specific extras (lava self-glow,
 * ocean specular glint, night-side city lights).
 */

export const planetVertexShader = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vWorldPos;
  varying vec2 vUv;
  varying float vFresnel;

  void main() {
    vec4 worldPos = modelMatrix * vec4(position, 1.0);
    vWorldPos = worldPos.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    vUv = uv;

    vec3 viewDir = normalize(cameraPosition - worldPos.xyz);
    vFresnel = pow(1.0 - max(0.0, dot(vNormal, viewDir)), 3.0);

    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

export const planetFragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec3  uStarPos;
  uniform int   uClass;       // 0=unknown 1=lava 2=hot_rocky 3=ocean 4=cold_rocky 5=ice 6=gas
  uniform float uSeed;        // per-planet random seed
  uniform vec3  uAtmColor;    // atmosphere rim color
  uniform float uAtmStrength; // 0–1
  uniform bool  uGhosted;
  uniform bool  uHabitable;

  varying vec3  vNormal;
  varying vec3  vWorldPos;
  varying vec2  vUv;
  varying float vFresnel;

  // ── Noise ──────────────────────────────────────────────────
  float hash(vec2 p) {
    p = fract(p * vec2(127.1 + uSeed * 0.01, 311.7 + uSeed * 0.007));
    p += dot(p, p + 17.5);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),u.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x),u.y);
  }
  float fbm(vec2 p, int oct) {
    float v=0.0,a=0.5,fr=1.0;
    for(int i=0;i<7;i++){if(i>=oct)break; v+=a*noise(p*fr); a*=0.5; fr*=2.1;}
    return v;
  }

  float diffuse(vec3 normal, vec3 starPos, vec3 worldPos) {
    vec3 L = normalize(starPos - worldPos);
    return max(0.0, dot(normal, L));
  }

  // ── Planet class surfaces ──────────────────────────────────

  vec3 surfaceLava(vec2 uv, float t) {
    vec2 warp = vec2(fbm(uv*1.8+vec2(uSeed,0.0),4), fbm(uv*1.8+vec2(0.0,uSeed),4));
    // [CREATIVE: tectonic drift — the crack network migrates over ~5 minutes]
    float crack = fbm(uv*3.2 + warp*1.4 + vec2(t*0.004, 0.0), 5);
    float ember  = fbm(uv*7.0 + vec2(t*0.012, t*0.008), 3);
    vec3 crust = vec3(0.12, 0.06, 0.03);
    vec3 lava  = vec3(1.0, 0.38 + ember*0.2, 0.02);
    float lavaMask = smoothstep(0.48, 0.38, crack);
    vec3 col = mix(crust, lava, lavaMask);
    col += vec3(0.6, 0.2, 0.0) * smoothstep(0.55, 0.72, ember) * (1.0 - lavaMask) * 0.6;
    return col;
  }

  vec3 surfaceHotRocky(vec2 uv) {
    float n = fbm(uv*2.5 + vec2(uSeed*0.1), 5);
    float crater = smoothstep(0.58, 0.54, fbm(uv*4.0+vec2(uSeed*0.3), 3));
    vec3 base = mix(vec3(0.42,0.22,0.12), vec3(0.68,0.38,0.18), n);
    base = mix(base, vec3(0.18,0.10,0.08), crater * 0.6);
    return base;
  }

  vec3 surfaceOcean(vec2 uv, float t) {
    float n = fbm(uv*2.2 + vec2(uSeed*0.08), 5);
    float lat = abs(vUv.y - 0.5) * 2.0; // 0=equator 1=pole
    float landMask = smoothstep(0.42, 0.52, n);
    // [CREATIVE: living ocean — slow specular shimmer bands drift across open
    // water like sun-glint on real ocean swell]
    vec3 ocean = vec3(0.08, 0.28, 0.65)
      + vec3(0.0, 0.1, 0.2) * fbm(uv*5.0 + vec2(t*0.01, 0.0), 3);
    vec3 land  = mix(vec3(0.22,0.48,0.18), vec3(0.52,0.38,0.22), fbm(uv*3.0+vec2(uSeed),3));
    vec3 col = mix(ocean, land, landMask);
    float iceMask = smoothstep(0.72, 0.88, lat);
    col = mix(col, vec3(0.88,0.92,0.98), iceMask);
    return col;
  }

  vec3 surfaceColdRocky(vec2 uv) {
    float n = fbm(uv*3.0 + vec2(uSeed*0.12), 5);
    float crater = smoothstep(0.6, 0.55, fbm(uv*5.0+vec2(uSeed*0.4), 3));
    float frost = smoothstep(0.55, 0.65, n);
    vec3 base = mix(vec3(0.28,0.26,0.24), vec3(0.48,0.44,0.40), n);
    base = mix(base, vec3(0.15,0.14,0.13), crater*0.5);
    base = mix(base, vec3(0.82,0.86,0.90), frost*0.35);
    return base;
  }

  vec3 surfaceIce(vec2 uv) {
    float n = fbm(uv*2.8 + vec2(uSeed*0.09), 5);
    float crack = smoothstep(0.5, 0.42, fbm(uv*4.5+vec2(uSeed*0.6,1.0), 4));
    vec3 base = mix(vec3(0.72,0.84,0.94), vec3(0.88,0.94,0.99), n);
    // [CREATIVE: Europa treatment — darker patches hint at a subsurface ocean
    // beneath the crust, brightest fractures stay pure white]
    vec3 sub = vec3(0.18,0.32,0.55);
    float subMask = smoothstep(0.48, 0.38, n);
    base = mix(base, sub, subMask*0.4);
    base = mix(base, vec3(0.95,0.97,1.0), crack*0.6);
    return base;
  }

  vec3 surfaceGas(vec2 uv, float t) {
    float band1 = sin((uv.y + fbm(uv*1.5+vec2(t*0.006),3)*0.1) * 3.14159*9.0)*0.5+0.5;
    float band2 = sin((uv.y + fbm(uv*2.0+vec2(t*0.009),3)*0.08) * 3.14159*17.0)*0.5+0.5;
    float wisp  = fbm(uv*4.0 + vec2(t*0.015,0.0), 3);
    vec3 col = mix(vec3(0.62,0.38,0.16), vec3(0.90,0.68,0.32), band1);
    col = mix(col, vec3(0.78,0.52,0.22), band2*0.4);
    col += (wisp-0.5)*0.08;
    // [CREATIVE: a Great Spot storm that slowly migrates around the planet]
    vec2 spotUv = uv - vec2(0.62 + t*0.0001, 0.54);
    float spot = 1.0 - smoothstep(0.0, 0.07, length(spotUv * vec2(2.0, 3.5)));
    col = mix(col, vec3(0.78,0.32,0.18), spot*0.7);
    return col;
  }

  vec3 surfaceUnknown(vec2 uv) {
    float n = fbm(uv*2.0 + vec2(uSeed*0.05), 3);
    return mix(vec3(0.18,0.22,0.30), vec3(0.28,0.34,0.44), n);
  }

  void main() {
    vec3 surface;
    if      (uClass == 1) surface = surfaceLava(vUv, uTime);
    else if (uClass == 2) surface = surfaceHotRocky(vUv);
    else if (uClass == 3) surface = surfaceOcean(vUv, uTime);
    else if (uClass == 4) surface = surfaceColdRocky(vUv);
    else if (uClass == 5) surface = surfaceIce(vUv);
    else if (uClass == 6) surface = surfaceGas(vUv, uTime);
    else                  surface = surfaceUnknown(vUv);

    // ── Lighting ────────────────────────────────────────────
    float diff = diffuse(vNormal, uStarPos, vWorldPos);
    float night = 1.0 - smoothstep(0.0, 0.22, diff);

    // City lights on habitable ocean worlds, night side only
    vec3 cityLights = vec3(0.0);
    if (uClass == 3) {
      float cityNoise = fbm(vUv * 6.0 + vec2(uSeed*0.2, 1.5), 3);
      float landMask  = smoothstep(0.42, 0.52, fbm(vUv*2.2+vec2(uSeed*0.08),5));
      cityLights = vec3(0.9,0.7,0.3) * smoothstep(0.55,0.72,cityNoise) * landMask * night * 0.7;
      // [CREATIVE: bio-fluorescence — HZ ocean night sides shimmer faintly
      // teal, like plankton blooms lighting a dark sea]
      if (uHabitable) {
        float glow = fbm(vUv*4.0 + vec2(uTime*0.006, uSeed), 3);
        cityLights += vec3(0.05, 0.35, 0.30) * smoothstep(0.55, 0.75, glow) * (1.0 - landMask) * night * 0.35;
      }
    }

    // Lava self-illumination — cracks glow even on the night side
    float selfEmit = 0.0;
    if (uClass == 1) {
      vec2 warp = vec2(fbm(vUv*1.8+vec2(uSeed,0.0),4), fbm(vUv*1.8+vec2(0.0,uSeed),4));
      float crack = fbm(vUv*3.2 + warp*1.4 + vec2(uTime*0.004,0.0), 5);
      selfEmit = smoothstep(0.48, 0.38, crack) * 0.65;
    }

    float ambientMin = (uClass == 1) ? 0.15 : 0.04;
    float lit = max(ambientMin, diff) + selfEmit;
    vec3 color = surface * lit + cityLights;

    // [CREATIVE: terminator sunset band — a warm rust tint right along the
    // day/night line, the way Earth's terminator photographs from orbit]
    float terminator = smoothstep(0.0, 0.18, diff) * (1.0 - smoothstep(0.18, 0.42, diff));
    color += vec3(0.45, 0.18, 0.04) * terminator * 0.35 * uAtmStrength;

    // Atmosphere scattering rim (Fresnel), brighter toward the star
    if (uAtmStrength > 0.0) {
      vec3 L = normalize(uStarPos - vWorldPos);
      float rimTowardStar = max(0.0, dot(L, vNormal));
      float rim = vFresnel * uAtmStrength * (0.6 + rimTowardStar * 0.4);
      color += uAtmColor * rim;
    }

    // Specular glint on water and ice
    if (uClass == 3 || uClass == 5) {
      vec3 L = normalize(uStarPos - vWorldPos);
      vec3 V = normalize(cameraPosition - vWorldPos);
      vec3 H = normalize(L + V);
      float spec = pow(max(0.0, dot(vNormal, H)), 48.0) * diff;
      color += vec3(1.0, 0.98, 0.92) * spec * 0.55;
    }

    // Ghosted (rejected/blocked) candidates render desaturated and translucent
    float alpha = uGhosted ? 0.52 : 1.0;
    if (uGhosted) color = mix(color, vec3(0.3,0.35,0.40), 0.55);

    gl_FragColor = vec4(color, alpha);
  }
`;

const CLASS_INT: Record<PlanetClass, number> = {
  [PlanetClass.UNKNOWN]: 0,
  [PlanetClass.LAVA]: 1,
  [PlanetClass.HOT_ROCKY]: 2,
  [PlanetClass.OCEAN]: 3,
  [PlanetClass.COLD_ROCKY]: 4,
  [PlanetClass.ICE]: 5,
  [PlanetClass.GAS]: 6,
};

const ATM_COLORS: Record<PlanetClass, [number, number, number]> = {
  [PlanetClass.LAVA]: [1.0, 0.32, 0.08],
  [PlanetClass.HOT_ROCKY]: [0.72, 0.38, 0.18],
  [PlanetClass.OCEAN]: [0.22, 0.62, 1.0],
  [PlanetClass.COLD_ROCKY]: [0.55, 0.58, 0.62],
  [PlanetClass.ICE]: [0.65, 0.82, 1.0],
  [PlanetClass.GAS]: [0.88, 0.65, 0.32],
  [PlanetClass.UNKNOWN]: [0.38, 0.44, 0.52],
};

const ATM_STRENGTH: Record<PlanetClass, number> = {
  [PlanetClass.LAVA]: 0.7,
  [PlanetClass.HOT_ROCKY]: 0.3,
  [PlanetClass.OCEAN]: 0.9,
  [PlanetClass.COLD_ROCKY]: 0.15,
  [PlanetClass.ICE]: 0.35,
  [PlanetClass.GAS]: 0.8,
  [PlanetClass.UNKNOWN]: 0.1,
};

export function makePlanetUniforms(
  planetClass: PlanetClass,
  seed: number,
  ghosted: boolean,
  habitable: boolean,
  starPos: [number, number, number] = [0, 0, 0],
) {
  return {
    uTime: { value: 0 },
    uStarPos: { value: starPos },
    uClass: { value: CLASS_INT[planetClass] },
    uSeed: { value: seed },
    uAtmColor: { value: ATM_COLORS[planetClass] },
    uAtmStrength: { value: ATM_STRENGTH[planetClass] },
    uGhosted: { value: ghosted },
    uHabitable: { value: habitable },
  };
}
