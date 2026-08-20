import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { createRunId, generateIdf, normalizeDesign } from "./model.mjs";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const JOULES_PER_KWH = 3_600_000;

function csvLine(line) {
  const fields = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else quoted = !quoted;
    } else if (character === "," && !quoted) {
      fields.push(value.trim());
      value = "";
    } else value += character;
  }
  fields.push(value.trim());
  return fields;
}

function findColumn(headers, terms, excluded = []) {
  return headers.findIndex((header) => {
    const lowered = header.toLowerCase();
    return terms.every((term) => lowered.includes(term)) && excluded.every((term) => !lowered.includes(term));
  });
}

function findColumns(headers, terms, excluded = []) {
  return headers.reduce((indexes, header, index) => {
    const lowered = header.toLowerCase();
    if (terms.every((term) => lowered.includes(term)) && excluded.every((term) => !lowered.includes(term))) indexes.push(index);
    return indexes;
  }, []);
}

function valueAt(row, index) {
  return index >= 0 ? Number(row[index]) || 0 : 0;
}

function sumAt(row, indexes) {
  return indexes.reduce((sum, index) => sum + valueAt(row, index), 0);
}

function parseMonth(dateTime) {
  const match = String(dateTime).match(/(\d{1,2})\/(\d{1,2})/);
  return match ? Math.min(11, Math.max(0, Number(match[1]) - 1)) : 0;
}

export function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("EnergyPlus did not produce hourly CSV rows");
  const headers = csvLine(lines[0]);
  const indexes = {
    facility: findColumn(headers, ["electricity:facility", "[j]"]),
    refrigeration: findColumn(headers, ["refrigeration:electricity", "[j]"]),
    pumpsMeter: findColumn(headers, ["pumps:electricity", "[j]"]),
    cooling: findColumns(headers, ["walk in evaporator total cooling energy", "[j]"]),
    rack: findColumns(headers, ["compressor rack electricity energy", "[j]"]),
    compressor: findColumns(headers, ["compressor rack electricity energy", "[j]"]),
    condenserFan: findColumns(headers, ["compressor rack condenser fan electricity energy", "[j]"]),
    walkinFan: findColumns(headers, ["walk in fan electricity energy", "[j]"]),
    lights: findColumns(headers, ["walk in lighting electricity energy", "[j]"]),
    defrost: findColumns(headers, ["walk in defrost electricity energy", "[j]"]),
    ancillary: findColumns(headers, ["walk in ancillary electricity energy", "[j]"]),
    pump: findColumns(headers, ["pump electricity energy", "[j]"]),
    outdoor: findColumn(headers, ["site outdoor air drybulb temperature", "[c]"]),
    zone: findColumn(headers, ["zone mean air temperature", "[c]"]),
    groundIn: findColumn(headers, ["ground heat exchanger inlet temperature", "[c]"]),
    groundOut: findColumn(headers, ["ground heat exchanger outlet temperature", "[c]"]),
    groundRate: findColumn(headers, ["ground heat exchanger heat transfer rate", "[w]"]),
  };
  if (indexes.facility < 0 && indexes.refrigeration < 0 && indexes.rack.length === 0) {
    throw new Error(`Required electricity output was not found. CSV columns: ${headers.join(" | ")}`);
  }

  const monthly = MONTHS.map((month) => ({ month, electricityKwh: 0, coolingKwh: 0, peakKw: 0 }));
  const endUsesJ = { compressor: 0, condenserFan: 0, walkinFan: 0, lights: 0, defrost: 0, ancillary: 0, pumps: 0 };
  const groundTemperatures = [];
  let electricityJ = 0;
  let coolingJ = 0;
  let groundEnergyJ = 0;
  let peakKw = 0;
  let outdoorMaximum = -100;
  let zoneSum = 0;
  let zoneCount = 0;
  let zoneMaximum = -100;

  for (let index = 1; index < lines.length; index += 1) {
    const row = csvLine(lines[index]);
    const month = parseMonth(row[0]);
    const facilityJ = indexes.facility >= 0 ? valueAt(row, indexes.facility) : (indexes.refrigeration >= 0 ? valueAt(row, indexes.refrigeration) + valueAt(row, indexes.pumpsMeter) : sumAt(row, indexes.rack) + sumAt(row, indexes.pump));
    const rowCoolingJ = sumAt(row, indexes.cooling);
    const rowKw = facilityJ / JOULES_PER_KWH;
    electricityJ += facilityJ;
    coolingJ += rowCoolingJ;
    groundEnergyJ += valueAt(row, indexes.groundRate) * 3600;
    peakKw = Math.max(peakKw, rowKw);
    monthly[month].electricityKwh += facilityJ / JOULES_PER_KWH;
    monthly[month].coolingKwh += rowCoolingJ / JOULES_PER_KWH;
    monthly[month].peakKw = Math.max(monthly[month].peakKw, rowKw);
    endUsesJ.compressor += sumAt(row, indexes.compressor) || sumAt(row, indexes.rack);
    endUsesJ.condenserFan += sumAt(row, indexes.condenserFan);
    endUsesJ.walkinFan += sumAt(row, indexes.walkinFan);
    endUsesJ.lights += sumAt(row, indexes.lights);
    endUsesJ.defrost += sumAt(row, indexes.defrost);
    endUsesJ.ancillary += sumAt(row, indexes.ancillary);
    endUsesJ.pumps += sumAt(row, indexes.pump) || valueAt(row, indexes.pumpsMeter);
    outdoorMaximum = Math.max(outdoorMaximum, valueAt(row, indexes.outdoor));
    if (indexes.zone >= 0) {
      const zone = valueAt(row, indexes.zone);
      zoneSum += zone;
      zoneCount += 1;
      zoneMaximum = Math.max(zoneMaximum, zone);
    }
    if (indexes.groundIn >= 0 && indexes.groundOut >= 0) {
      groundTemperatures.push({ inletC: valueAt(row, indexes.groundIn), outletC: valueAt(row, indexes.groundOut) });
    }
  }

  const groundInAverage = groundTemperatures.length ? groundTemperatures.reduce((sum, row) => sum + row.inletC, 0) / groundTemperatures.length : null;
  const groundOutAverage = groundTemperatures.length ? groundTemperatures.reduce((sum, row) => sum + row.outletC, 0) / groundTemperatures.length : null;
  return {
    rows: lines.length - 1,
    electricityKwh: electricityJ / JOULES_PER_KWH,
    coolingKwh: coolingJ / JOULES_PER_KWH,
    peakKw,
    systemCop: electricityJ > 0 ? coolingJ / electricityJ : 0,
    outdoorMaximumC: outdoorMaximum,
    ambientZoneAverageC: zoneCount ? zoneSum / zoneCount : null,
    ambientZoneMaximumC: zoneCount ? zoneMaximum : null,
    groundHeatTransferKwh: Math.abs(groundEnergyJ / JOULES_PER_KWH),
    groundInAverageC: groundInAverage,
    groundOutAverageC: groundOutAverage,
    monthly,
    endUses: Object.fromEntries(Object.entries(endUsesJ).map(([key, joules]) => [key, joules / JOULES_PER_KWH])),
    outputColumns: headers,
  };
}

export function parseErr(text) {
  const warningMatches = [...text.matchAll(/(\d+) Warning/g)].map((match) => Number(match[1]));
  const severeMatches = [...text.matchAll(/(\d+) Severe Errors?/g)].map((match) => Number(match[1]));
  const fatal = /\*\* Fatal \*\*/i.test(text) || /Terminated--Fatal Error Detected/i.test(text);
  return {
    warnings: warningMatches.length ? Math.max(...warningMatches) : (text.match(/\*\* Warning \*\*/g) || []).length,
    severe: severeMatches.length ? Math.max(...severeMatches) : (text.match(/\*\* Severe \*\*/g) || []).length,
    fatal,
    completed: /EnergyPlus Completed Successfully/i.test(text),
  };
}

function execute(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

async function runVariant({ input, variant, runDirectory, energyplusExe, epwPath }) {
  const modelPath = path.join(runDirectory, `${variant}.idf`);
  const outputDirectory = path.join(runDirectory, variant);
  await mkdir(outputDirectory, { recursive: true });
  await writeFile(modelPath, generateIdf(input, variant), "utf8");
  const started = Date.now();
  const execution = await execute(energyplusExe, ["--weather", epwPath, "--output-directory", outputDirectory, "--output-prefix", "eplus", "--readvars", modelPath], { cwd: runDirectory });
  const errPath = path.join(outputDirectory, "eplusout.err");
  const csvPath = path.join(outputDirectory, "eplusout.csv");
  const errText = await readFile(errPath, "utf8").catch(() => execution.stderr || execution.stdout);
  const diagnostics = parseErr(errText);
  if (execution.code !== 0 || !diagnostics.completed || diagnostics.severe > 0 || diagnostics.fatal) {
    const error = new Error(`EnergyPlus ${variant} run failed (${diagnostics.severe} severe, fatal=${diagnostics.fatal})`);
    error.details = { execution, diagnostics, errTail: errText.slice(-8000), modelPath, outputDirectory };
    throw error;
  }
  const csvText = await readFile(csvPath, "utf8");
  return {
    variant,
    durationMs: Date.now() - started,
    diagnostics,
    artifacts: {
      idf: `${variant}.idf`,
      err: `${variant}/eplusout.err`,
      csv: `${variant}/eplusout.csv`,
      sql: `${variant}/eplusout.sql`,
      html: `${variant}/eplustbl.htm`,
    },
    ...parseCsv(csvText),
  };
}

export async function runEnergyPlusPair(input, options = {}) {
  const energyplusExe = options.energyplusExe || process.env.ENERGYPLUS_EXE || "energyplus";
  const epwPath = options.epwPath || process.env.EPW_PATH;
  if (!epwPath) throw new Error("EPW_PATH is required");
  const runRoot = options.runRoot || process.env.RUN_ROOT || path.resolve("runs");
  const normalized = normalizeDesign(input);
  const runId = createRunId(normalized);
  const runDirectory = path.join(runRoot, `${runId}-${Date.now()}`);
  await mkdir(runDirectory, { recursive: true });
  const manifest = {
    runId,
    createdAt: new Date().toISOString(),
    engine: "DOE EnergyPlus 26.1.0",
    weatherFile: path.basename(epwPath),
    design: normalized,
  };
  await writeFile(path.join(runDirectory, "manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
  const baseline = await runVariant({ input: normalized, variant: "baseline", runDirectory, energyplusExe, epwPath });
  const geo = await runVariant({ input: normalized, variant: "geo", runDirectory, energyplusExe, epwPath });
  const savingKwh = baseline.electricityKwh - geo.electricityKwh;
  const result = {
    ...manifest,
    status: "completed",
    validation: {
      officialEnergyPlusRun: true,
      baseline: baseline.diagnostics,
      geo: geo.diagnostics,
    },
    baseline,
    geo,
    comparison: {
      savingKwh,
      savingPercent: baseline.electricityKwh > 0 ? savingKwh / baseline.electricityKwh * 100 : 0,
      annualCostInr: geo.electricityKwh * normalized.tariff,
      annualCostSavingInr: savingKwh * normalized.tariff,
      annualCarbonKg: geo.electricityKwh * normalized.carbonFactor,
      euiKwhM2: geo.electricityKwh / normalized.totalFloorArea,
    },
    artifacts: {
      manifest: "manifest.json",
      summary: "summary.json",
    },
  };
  await writeFile(path.join(runDirectory, "summary.json"), JSON.stringify(result, null, 2), "utf8");
  return { result, runDirectory };
}

export function artifactStream(runDirectory, relativePath) {
  const resolved = path.resolve(runDirectory, relativePath);
  if (!resolved.startsWith(path.resolve(runDirectory) + path.sep)) throw new Error("Invalid artifact path");
  return createReadStream(resolved);
}
