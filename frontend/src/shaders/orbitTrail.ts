/**
 * Comet-tail orbit trail shader.
 *
 * Each orbit torus vertex carries an `angle` attribute (its position around
 * the ring, 0–2π in the torus's local XY plane — the mesh is rotated into
 * the world XZ orbital plane afterward). The vertex shader measures how far
 * "behind" the planet each vertex sits and fades alpha over ~315° so the
 * trail is bright at the planet's heel and dissolves into space behind it.
 *
 * uPlanetAngle must be supplied already wrapped to [0, 2π).
 */

export const orbitTrailVertexShader = /* glsl */ `
  attribute float angle;      // per-vertex angle around the orbit, [0, 2PI)
  uniform float uPlanetAngle; // current planet angle, wrapped to [0, 2PI)
  varying float vAlpha;

  void main() {
    float delta = uPlanetAngle - angle;
    if (delta < 0.0) delta += 6.2831853;
    // Bright right behind the planet, fading over ~315 degrees
    vAlpha = 1.0 - smoothstep(0.0, 5.50, delta);
    // [CREATIVE: tiny hot head — the 15 degrees right behind the planet get an
    // extra brightness kick so the trail reads like a comet coma]
    vAlpha += (1.0 - smoothstep(0.0, 0.26, delta)) * 0.6;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const orbitTrailFragmentShader = /* glsl */ `
  uniform vec3  uColor;
  uniform vec3  uFadeColor;
  uniform float uOpacity;
  varying float vAlpha;

  void main() {
    // [CREATIVE: trail color cools as it fades — bright head in the planet's
    // own hue, tail dissolving toward deep-space blue]
    vec3 color = mix(uFadeColor, uColor, clamp(vAlpha, 0.0, 1.0));
    gl_FragColor = vec4(color, uOpacity * clamp(vAlpha, 0.0, 1.4));
  }
`;

export const TWO_PI = Math.PI * 2;

/** Wrap an unbounded accumulating angle into [0, 2π) for the shader. */
export function wrapAngle(angle: number): number {
  const wrapped = angle % TWO_PI;
  return wrapped < 0 ? wrapped + TWO_PI : wrapped;
}
