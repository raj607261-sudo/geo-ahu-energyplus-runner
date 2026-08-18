import { runEnergyPlusPair } from "./runner.mjs";

const [energyplusExe, epwPath, runRoot] = process.argv.slice(2);
if (!energyplusExe || !epwPath || !runRoot) {
  console.error("Usage: node smoke.mjs <energyplus-exe> <weather.epw> <run-root>");
  process.exit(2);
}

const design = {
  location: "Darbhanga, Bihar",
  crop: "Fresh Mangoes",
  capacity: 10,
  length: 6,
  width: 4,
  height: 3,
  puf: 80,
  uValue: 0.29,
  ambient: 42,
  indoor: 8,
  dailyBatch: 2.5,
  fieldTemp: 38,
  pullHours: 8,
  cp: 3.8,
  internal: 0.92,
  respiration: 0.33,
  safety: 15,
  convCop: 2.25,
  geoCop: 3.55,
  geoAux: 0.35,
  tariff: 8.5,
  loopLength: 600,
  depth: 3.5,
  spacing: 1.2,
  soil: 24,
  operatingDays: 30,
  lightingHours: 4,
  defrostHours: 1,
  carbonFactor: 0.716,
};

try {
  const { result, runDirectory } = await runEnergyPlusPair(design, { energyplusExe, epwPath, runRoot });
  console.log(JSON.stringify({
    runDirectory,
    runId: result.runId,
    baselineKwh: result.baseline.electricityKwh,
    geoKwh: result.geo.electricityKwh,
    savingPercent: result.comparison.savingPercent,
    baselineDiagnostics: result.baseline.diagnostics,
    geoDiagnostics: result.geo.diagnostics,
    rows: { baseline: result.baseline.rows, geo: result.geo.rows },
  }, null, 2));
} catch (error) {
  console.error(error.stack || error.message);
  if (error.details) console.error(JSON.stringify(error.details, null, 2));
  process.exit(1);
}

