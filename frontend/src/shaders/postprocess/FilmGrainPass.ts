/**
 * Animated film grain — a faint per-frame noise wash that keeps large dark
 * areas of the scene from banding and gives theater mode a documentary
 * texture. Strength stays under ~3% so science detail is never obscured.
 */
export const FilmGrainShader = {
  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 },
    uStrength: { value: 0.032 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform float uStrength;
    varying vec2 vUv;
    float rand(vec2 co) { return fract(sin(dot(co, vec2(12.9898,78.233))) * 43758.5453); }
    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      float grain = rand(vUv + fract(uTime * 0.07)) - 0.5;
      // [CREATIVE: luminance-aware grain — shadows get more grain than
      // highlights, the way physical film stock behaves]
      float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));
      color.rgb += grain * uStrength * (1.0 - luma * 0.6);
      gl_FragColor = color;
    }
  `,
};
