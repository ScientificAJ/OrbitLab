import { describe, expect, it } from 'vitest';
import { classifyPlanet, PlanetClass } from './planetClassifier';

describe('classifyPlanet', () => {
  it('returns LAVA for temperature > 1200', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 1800 })).toBe(PlanetClass.LAVA);
  });
  it('returns HOT_ROCKY for 600–1200 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 900 })).toBe(PlanetClass.HOT_ROCKY);
  });
  it('returns HOT_ROCKY for the 500–600 K band (no classification gap)', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 550 })).toBe(PlanetClass.HOT_ROCKY);
  });
  it('returns OCEAN for 200–400 K with habitable zone', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 288, is_in_habitable_zone: true })).toBe(PlanetClass.OCEAN);
  });
  it('returns COLD_ROCKY for 100–200 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 150 })).toBe(PlanetClass.COLD_ROCKY);
  });
  it('returns ICE for < 100 K', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 60 })).toBe(PlanetClass.ICE);
  });
  it('returns GAS for high radius ratio', () => {
    expect(classifyPlanet({ radius_ratio: 0.12 })).toBe(PlanetClass.GAS);
  });
  it('returns GAS for large inferred planet radius', () => {
    expect(classifyPlanet({ planet_radius_earth: 9, equilibrium_temperature_k: 288 })).toBe(PlanetClass.GAS);
  });
  it('returns UNKNOWN when no data', () => {
    expect(classifyPlanet({})).toBe(PlanetClass.UNKNOWN);
  });
  it('returns OCEAN for 200–400 K even without explicit HZ flag', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: 310 })).toBe(PlanetClass.OCEAN);
  });
  it('ignores null fields gracefully', () => {
    expect(classifyPlanet({ equilibrium_temperature_k: null, radius_ratio: null, planet_radius_earth: null })).toBe(
      PlanetClass.UNKNOWN,
    );
  });
});
