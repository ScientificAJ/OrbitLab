/**
 * Visual planet classification for OrbitScene.
 *
 * Maps the science pipeline's physics outputs (equilibrium temperature,
 * radius ratio, inferred planet radius) onto a small set of render classes
 * that drive the GLSL surface shaders. This is presentation-layer taxonomy
 * only — it never feeds back into science results or vetting decisions.
 *
 * Temperature bands (equilibrium temperature, K):
 *   > 1200      LAVA        molten surface, self-luminous cracks
 *   > 500       HOT_ROCKY   scorched silicate, no liquid water possible
 *   200 – 500   OCEAN       plausibly temperate; liquid-water aesthetic
 *   100 – 200   COLD_ROCKY  frost-streaked regolith
 *   < 100       ICE         frozen volatiles, subsurface-ocean hints
 *
 * Gas-giant detection runs first: a transit radius ratio above 0.08 (or an
 * inferred radius above ~6 Earth radii, the sub-Neptune/Jovian divide) means
 * the temperature bands describe cloud decks, not surfaces.
 */
export enum PlanetClass {
  LAVA = 'lava',
  HOT_ROCKY = 'hot_rocky',
  OCEAN = 'ocean',
  COLD_ROCKY = 'cold_rocky',
  ICE = 'ice',
  GAS = 'gas',
  UNKNOWN = 'unknown',
}

export interface PlanetPhysicsInput {
  equilibrium_temperature_k?: number | null;
  is_in_habitable_zone?: boolean | null;
  radius_ratio?: number | null;
  planet_radius_earth?: number | null;
}

export function classifyPlanet(physics: PlanetPhysicsInput): PlanetClass {
  const { equilibrium_temperature_k: t, radius_ratio: rr, planet_radius_earth: re } = physics;

  if ((rr != null && rr > 0.08) || (re != null && re > 6)) return PlanetClass.GAS;

  if (t != null && Number.isFinite(t)) {
    if (t > 1200) return PlanetClass.LAVA;
    if (t > 500) return PlanetClass.HOT_ROCKY;
    if (t >= 200) return PlanetClass.OCEAN;
    if (t >= 100) return PlanetClass.COLD_ROCKY;
    return PlanetClass.ICE;
  }

  return PlanetClass.UNKNOWN;
}
