/**
 * Radial chromatic aberration — the red/blue channel split grows with
 * distance from screen center, like the edge dispersion of real telescope
 * optics. Theater mode only; kept very subtle (uStrength ≈ 0.006).
 */
export const ChromaticAberrationShader = {
  uniforms: {
    tDiffuse: { value: null },
    uStrength: { value: 0.004 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uStrength;
    varying vec2 vUv;
    void main() {
      vec2 center = vUv - 0.5;
      float dist = length(center);
      float offset = dist * uStrength;
      vec2 dir = normalize(center + vec2(0.0001));
      float r = texture2D(tDiffuse, vUv - dir * offset).r;
      float g = texture2D(tDiffuse, vUv).g;
      float b = texture2D(tDiffuse, vUv + dir * offset).b;
      gl_FragColor = vec4(r, g, b, 1.0);
    }
  `,
};
