/**
 * Eyepiece vignette for theater mode.
 */
export const VignetteShader = {
  uniforms: {
    tDiffuse: { value: null },
    uStrength: { value: 0.55 },
    uOffset: { value: 0.35 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uStrength;
    uniform float uOffset;
    varying vec2 vUv;
    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      // [CREATIVE: asymmetric vignette — slightly heavier at the bottom, like
      // looking through a real telescope eyepiece]
      vec2 uv2 = vUv - vec2(0.5, 0.48);
      float dist = length(uv2 * vec2(1.0, 1.1));
      float vignette = smoothstep(uOffset + uStrength, uOffset, dist);
      color.rgb *= vignette;
      gl_FragColor = color;
    }
  `,
};
