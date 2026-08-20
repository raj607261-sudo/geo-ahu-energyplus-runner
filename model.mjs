const finite = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const within = (value, minimum, maximum, fallback) => Math.min(maximum, Math.max(minimum, finite(value, fallback)));
const idfText = (value, fallback = "Geo AHU") => String(value || fallback).replace(/[;,!\r\n]/g, " ").trim().slice(0, 96) || fallback;

export function normalizeDesign(input = {}) {
  const hybrid = input.systemMode === "hybridTwoChamber";
  const mushroom = input.systemMode === "mushroomCentralPlant";
  const chamberCount = mushroom ? Math.round(within(input.chamberCount, 1, 8, 4)) : 1;
  const length = within(input.length, 2, 15, hybrid ? 9 : mushroom ? 8 : 6);
  const width = within(input.width, 2, 12, hybrid ? 6 : 4);
  const height = within(input.height, 2, 6, hybrid ? 3.5 : 3);
  const preCoolLength = within(input.preCoolLength, 2, 10, 5);
  const preCoolWidth = within(input.preCoolWidth, 2, 10, 4);
  const preCoolHeight = within(input.preCoolHeight, 2, 6, 3);
  const indoor = within(input.indoor, -25, mushroom ? 32 : 18, mushroom ? 18 : 8);
  const fieldTemp = within(input.fieldTemp, indoor, 55, 38);
  const dailyBatch = within(input.dailyBatch, 0, hybrid ? 15 : 10, mushroom ? 0 : hybrid ? 10 : 2.5);
  const cp = within(input.cp, 1, 5, 3.8);
  const pullHours = within(input.pullHours, 1, 24, 8);
  const operatingDays = within(input.operatingDays ?? input.days, 1, 31, 30);
  const loopLength = within(input.loopLength, 75, 2400, 600);
  const boreholeCount = Math.max(1, Math.min(12, Math.ceil(loopLength / 200)));
  const boreholeLength = Math.max(30, loopLength / (2 * boreholeCount));
  const floorArea = length * width;
  const exposedArea = length * width + 2 * height * (length + width);
  const preCoolFloorArea = preCoolLength * preCoolWidth;
  const preCoolExposedArea = preCoolLength * preCoolWidth + 2 * preCoolHeight * (preCoolLength + preCoolWidth);
  const productLoadW = dailyBatch * 1000 * cp * Math.max(0, fieldTemp - indoor) / (3.6 * pullHours) * (operatingDays / 30.4375);
  const envelopeLoadW = within(input.uValue, 0.08, 0.8, 0.29) * (floorArea + exposedArea) * Math.max(8, within(input.ambient, indoor + 1, 55, 42) - indoor);
  const internalLoadW = within(input.internal, 0, 8, 0.92) * 1000;
  const respirationLoadW = within(input.respiration, 0, 5, 0.33) * 1000;
  const preCoolEnvelopeLoadW = within(input.uValue, 0.08, 0.8, 0.29) * (preCoolFloorArea + preCoolExposedArea) * Math.max(8, within(input.ambient, indoor + 1, 55, 42) - indoor);
  const preCoolAncillaryLoadW = Math.max(800, dailyBatch * 120);
  const preCoolRespirationLoadW = respirationLoadW * Math.min(1, dailyBatch / Math.max(0.1, within(input.capacity, 0.1, 30, hybrid ? 30 : 10)));
  const safety = within(input.safety, 0, 40, 15) / 100;
  const rawChambers = Array.isArray(input.chambers) ? input.chambers.slice(0, chamberCount) : [];
  const mushroomChambers = mushroom ? Array.from({ length: chamberCount }, (_, index) => {
    const source = rawChambers[index] || {};
    const targetTemp = within(source.targetTemp, 10, 32, indoor);
    const targetRh = within(source.targetRh, 50, 100, within(input.targetRh, 50, 100, 88));
    const co2Setpoint = within(source.co2Setpoint, 400, 10000, within(input.co2Setpoint, 400, 10000, 1000));
    const ach = within(source.ach, 0, 12, 4);
    const processHeatW = within(source.processHeatKw, 0, 5, .8) * 1000;
    const fanPowerW = within(source.fanKw, 0, 4, .75) * 1000;
    const lightPowerW = within(source.lightKw, 0, 4, .35) * 1000;
    const deltaT = Math.max(4, within(input.ambient, targetTemp + 1, 55, 42) - targetTemp);
    const ventilationLoadW = 1.2 * 1005 * (ach * length * width * height / 3600) * deltaT;
    const chamberEnvelopeLoadW = within(input.uValue, 0.08, 0.8, 0.29) * (floorArea + exposedArea) * deltaT;
    const simulationLoadW = processHeatW + ventilationLoadW;
    const ratedCapacityW = Math.max(2500, (chamberEnvelopeLoadW + simulationLoadW + fanPowerW + lightPowerW) * (1 + safety) * 1.15);
    return { name: idfText(source.name, `Grow Chamber ${index + 1}`), stage: idfText(source.stage, "Fruiting"), targetTemp, targetRh, co2Setpoint, ach, processHeatW, ventilationLoadW, simulationLoadW, fanPowerW, lightPowerW, ratedCapacityW };
  }) : [];
  const preCoolRatedCapacityW = hybrid ? Math.max(2500, (productLoadW + preCoolEnvelopeLoadW + preCoolAncillaryLoadW + preCoolRespirationLoadW) * (1 + safety) * 1.15) : 0;
  const holdingRatedCapacityW = mushroom ? mushroomChambers.reduce((sum, chamber) => sum + chamber.ratedCapacityW, 0) * within(input.diversity, 50, 100, 85) / 100 : hybrid ? Math.max(2500, (envelopeLoadW + internalLoadW + respirationLoadW) * (1 + safety) * 1.15) : Math.max(2500, (productLoadW + envelopeLoadW + internalLoadW + respirationLoadW) * (1 + safety) * 1.15);
  const ratedCapacityW = preCoolRatedCapacityW + holdingRatedCapacityW;
  const designFlow = Math.max(0.003, Math.min(0.02, (holdingRatedCapacityW * 1.35) / (997 * 4180 * 5)));

  return {
    location: idfText(input.location, "Darbhanga Bihar"),
    crop: idfText(input.crop, "Fresh produce"),
    systemMode: mushroom ? "mushroomCentralPlant" : hybrid ? "hybridTwoChamber" : "singleRoom",
    hybrid,
    mushroom,
    chamberCount,
    mushroomChambers,
    capacity: within(input.capacity, 0.1, mushroom ? 50 : hybrid ? 30 : 10, mushroom ? 12 : hybrid ? 30 : 10),
    length,
    width,
    height,
    preCoolLength,
    preCoolWidth,
    preCoolHeight,
    indoor,
    fieldTemp,
    dailyBatch,
    cp,
    pullHours,
    operatingDays,
    puf: within(input.puf, 50, 200, 80),
    uValue: within(input.uValue, 0.08, 0.8, 0.29),
    soil: within(input.soil, 8, 40, 24),
    soilConductivity: within(input.soilConductivity, 0.5, 4, 1.8),
    soilDensity: within(input.soilDensity, 700, 2400, 1600),
    soilSpecificHeat: within(input.soilSpecificHeat, 600, 3000, 1200),
    loopLength,
    depth: within(input.depth, 0.8, 6, 3.5),
    spacing: within(input.spacing, 0.5, 6, 1.2),
    pipeInnerDiameter: within(input.pipeInnerDiameter, 0.012, 0.05, 0.026),
    pipeOuterDiameter: within(input.pipeOuterDiameter, 0.016, 0.063, 0.032),
    convCop: within(input.convCop, 1.1, 6, 2.25),
    geoCop: within(input.geoCop, 1.1, 7, 3.55),
    geoAux: within(input.geoAux, 0.03, 4, 0.35),
    tariff: within(input.tariff, 0, 100, 8.5),
    carbonFactor: within(input.carbonFactor, 0, 2, 0.716),
    infiltrationAch: within(input.infiltrationAch, 0, 3, 0.15),
    doorOpenings: within(input.doorOpenings, 0, 100, 12),
    lightingHours: within(input.lightingHours, 0, 24, 4),
    defrostHours: within(input.defrostHours, 0, 6, 1),
    floorArea,
    exposedArea,
    preCoolFloorArea,
    preCoolExposedArea,
    totalFloorArea: mushroom ? floorArea * chamberCount : floorArea + (hybrid ? preCoolFloorArea : 0),
    productLoadW,
    holdingProcessLoadW: internalLoadW + respirationLoadW,
    mushroomProcessLoadW: mushroomChambers.reduce((sum, chamber) => sum + chamber.processHeatW, 0),
    preCoolRatedCapacityW,
    holdingRatedCapacityW,
    ratedCapacityW,
    designFlow,
    boreholeCount,
    boreholeLength,
  };
}

function schedules(x) {
  const hourStamp = (value) => {
    const hours = Math.floor(value);
    const minutes = Math.round((value - hours) * 60);
    return `${hours}:${String(minutes).padStart(2, "0")}`;
  };
  const lightStart = 8;
  const lightEnd = Math.min(24, lightStart + x.lightingHours);
  const pullEnd = Math.min(24, 8 + x.pullHours);
  const doorFraction = Math.min(0.35, x.doorOpenings * 2 / 600);
  const defrostFraction = x.indoor <= 4 && x.defrostHours > 0 ? 1 : 0;
  const defrostEnd = Math.min(24, 5 + x.defrostHours);
  const mushroomSchedules = x.mushroomChambers.map((chamber, index) => `Schedule:Compact,Mushroom Process Load ${index + 1},Any Number,Through: 12/31,For: AllDays,Until: 24:00,${chamber.simulationLoadW.toFixed(2)};`).join("\n");
  const productSchedule = x.mushroom || x.productLoadW === 0
    ? "Schedule:Compact,Product Restocking,Any Number,Through: 12/31,For: AllDays,Until: 24:00,0;\nSchedule:Compact,Precool Product Restocking,Any Number,Through: 12/31,For: AllDays,Until: 24:00,0;"
    : `Schedule:Compact,Product Restocking,Any Number,Through: 12/31,For: AllDays,Until: 8:00,0,Until: ${hourStamp(pullEnd)},${x.productLoadW.toFixed(2)}${pullEnd < 24 ? ",Until: 24:00,0" : ""};\nSchedule:Compact,Precool Product Restocking,Any Number,Through: 12/31,For: AllDays,Until: 8:00,0,Until: ${hourStamp(pullEnd)},${x.productLoadW.toFixed(2)}${pullEnd < 24 ? ",Until: 24:00,0" : ""};`;
  const defrostSchedules = defrostFraction === 0
    ? "Schedule:Compact,Defrost Schedule,Fraction,Through: 12/31,For: AllDays,Until: 24:00,0;\nSchedule:Compact,Dripdown Schedule,Fraction,Through: 12/31,For: AllDays,Until: 24:00,0;"
    : `Schedule:Compact,Defrost Schedule,Fraction,Through: 12/31,For: AllDays,Interpolate:Average,Until: 5:00,0,Until: ${hourStamp(defrostEnd)},1,Until: 24:00,0;\nSchedule:Compact,Dripdown Schedule,Fraction,Through: 12/31,For: AllDays,Interpolate:Average,Until: 5:00,0,Until: ${hourStamp(Math.min(24, defrostEnd + 0.5))},1,Until: 24:00,0;`;
  return `
ScheduleTypeLimits,Fraction,0,1,Continuous;
ScheduleTypeLimits,Any Number;
ScheduleTypeLimits,Temperature,-60,100,Continuous,Temperature;

Schedule:Compact,Always On,Fraction,Through: 12/31,For: AllDays,Until: 24:00,1;
Schedule:Compact,Always Off,Fraction,Through: 12/31,For: AllDays,Until: 24:00,0;
Schedule:Compact,Lighting Schedule,Fraction,Through: 12/31,For: AllDays,Until: ${lightStart}:00,0,Until: ${lightEnd}:00,1,Until: 24:00,0;
Schedule:Compact,Door Schedule,Fraction,Through: 12/31,For: AllDays,Until: 8:00,0.01,Until: 18:00,${doorFraction.toFixed(4)},Until: 24:00,0.01;
${productSchedule}
Schedule:Compact,Holding Produce Load,Any Number,Through: 12/31,For: AllDays,Until: 24:00,${x.holdingProcessLoadW.toFixed(2)};
${mushroomSchedules}
${defrostSchedules}
Schedule:Compact,Condenser Outlet Setpoint,Temperature,Through: 12/31,For: AllDays,Until: 24:00,45;
Schedule:Compact,Ground Loop Setpoint,Temperature,Through: 12/31,For: AllDays,Until: 24:00,30;
`;
}

function geometry(x) {
  const l = x.length;
  const w = x.width;
  const h = x.height;
  return `
Material,Ambient Shell,MediumRough,0.10,0.40,800,1000,0.9,0.7,0.7;
Construction,Ambient Construction,Ambient Shell;
Zone,Ambient Zone,0,0,0,0,1,1,${h},${(l * w * h).toFixed(3)},${(l * w).toFixed(3)};
Site:GroundTemperature:BuildingSurface,${Array(12).fill(x.soil.toFixed(2)).join(",")};

BuildingSurface:Detailed,Ambient Floor,Floor,Ambient Construction,Ambient Zone,,Ground,,NoSun,NoWind,1.0,4,0,${w},0,${l},${w},0,${l},0,0,0,0,0;
BuildingSurface:Detailed,Ambient Roof,Roof,Ambient Construction,Ambient Zone,,Outdoors,,SunExposed,WindExposed,0.0,4,0,0,${h},${l},0,${h},${l},${w},${h},0,${w},${h};
BuildingSurface:Detailed,Ambient South Wall,Wall,Ambient Construction,Ambient Zone,,Outdoors,,SunExposed,WindExposed,0.5,4,0,0,${h},0,0,0,${l},0,0,${l},0,${h};
BuildingSurface:Detailed,Ambient East Wall,Wall,Ambient Construction,Ambient Zone,,Outdoors,,SunExposed,WindExposed,0.5,4,${l},0,${h},${l},0,0,${l},${w},0,${l},${w},${h};
BuildingSurface:Detailed,Ambient North Wall,Wall,Ambient Construction,Ambient Zone,,Outdoors,,SunExposed,WindExposed,0.5,4,${l},${w},${h},${l},${w},0,0,${w},0,0,${w},${h};
BuildingSurface:Detailed,Ambient West Wall,Wall,Ambient Construction,Ambient Zone,,Outdoors,,SunExposed,WindExposed,0.5,4,0,${w},${h},0,${w},0,0,0,0,0,0,${h};

ZoneInfiltration:DesignFlowRate,Ambient Outdoor Coupling,Ambient Zone,Always On,AirChanges/Hour,,,,8.0;

ZoneHVAC:EquipmentConnections,Ambient Zone,Ambient Zone Equipment,Ambient Zone Supply Inlet,,Ambient Zone Air Node,Ambient Zone Return Outlet;
ZoneHVAC:EquipmentList,Ambient Zone Equipment,SequentialLoad,ZoneHVAC:IdealLoadsAirSystem,Ambient Zone Ideal Loads,1,1,,;
ZoneHVAC:IdealLoadsAirSystem,Ambient Zone Ideal Loads,,Ambient Zone Supply Inlet,,,50,13,0.015,0.01,NoLimit,,,NoLimit,,,,,ConstantSupplyHumidityRatio,,ConstantSupplyHumidityRatio,,,,,,,,;
`;
}

function refrigeration(x, variant) {
  if (x.mushroom) return mushroomRefrigeration(x, variant);
  if (x.hybrid) return hybridRefrigeration(x, variant);
  const fanPower = Math.max(180, x.capacity * 42);
  const lightPower = Math.max(80, x.floorArea * 6);
  const defrostPower = x.indoor <= 4 ? Math.max(800, x.ratedCapacityW * 0.45) : 0;
  const sourceTemp = x.indoor - 5;
  const defrostType = defrostPower > 0 ? "Electric" : "None";
  const floorU = Math.max(0.12, x.uValue * 0.9);
  const rack = variant === "geo" ? `
Refrigeration:CompressorRack,
  Geo AHU Rack,
  Outdoors,
  ${x.geoCop.toFixed(4)},
  Rack COP Modifier,
  0,
  ,
  WaterCooled,
  Ground Loop Demand Inlet,
  Ground Loop Demand Outlet,
  ConstantFlow,
  Condenser Outlet Setpoint,
  ${x.designFlow.toFixed(7)},
  ${x.designFlow.toFixed(7)},
  55,
  10,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  Geo AHU Refrigeration,
  Geo AHU WalkIn;
` : `
Refrigeration:CompressorRack,
  Conventional Rack,
  Outdoors,
  ${x.convCop.toFixed(4)},
  Rack COP Modifier,
  ${Math.max(120, x.ratedCapacityW * 0.035).toFixed(2)},
  ,
  AirCooled,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  Outdoor Condenser Air Node,
  Conventional Refrigeration,
  Geo AHU WalkIn;

OutdoorAir:Node,Outdoor Condenser Air Node;
`;
  return `
Curve:Quadratic,Rack COP Modifier,1,0,0,-20,60,0.5,1.5,Temperature,Dimensionless;

Refrigeration:WalkIn,
  Geo AHU WalkIn,
  Always On,
  ${x.ratedCapacityW.toFixed(2)},
  ${x.indoor.toFixed(2)},
  ${sourceTemp.toFixed(2)},
  0,
  Always Off,
  ${fanPower.toFixed(2)},
  0,
  ${lightPower.toFixed(2)},
  Lighting Schedule,
  ${defrostType},
  TimeSchedule,
  Defrost Schedule,
  Dripdown Schedule,
  ${defrostPower.toFixed(2)},
  ,
  Product Restocking,
  ,
  ${x.floorArea.toFixed(3)},
  ${floorU.toFixed(4)},
  Ambient Zone,
  ${x.exposedArea.toFixed(3)},
  ${x.uValue.toFixed(4)},
  ,,,,
  ${Math.min(4, Math.max(1.5, x.width * 0.5)).toFixed(2)},
  ${Math.min(2.5, Math.max(1.8, x.height * 0.75)).toFixed(2)},
  ,
  Door Schedule,
  StripCurtain;
${rack}`;
}

function airCooledRack({ name, load, endUse, node, cop, ratedCapacityW }) {
  return `
Refrigeration:CompressorRack,
  ${name},
  Outdoors,
  ${cop.toFixed(4)},
  Rack COP Modifier,
  ${Math.max(120, ratedCapacityW * 0.035).toFixed(2)},
  ,
  AirCooled,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ${node},
  ${endUse},
  ${load};

OutdoorAir:Node,${node};
`;
}

function holdingGeoRack(x) {
  return `
Refrigeration:CompressorRack,
  Holding Geo Rack,
  Outdoors,
  ${x.geoCop.toFixed(4)},
  Rack COP Modifier,
  0,
  ,
  WaterCooled,
  Ground Loop Demand Inlet,
  Ground Loop Demand Outlet,
  ConstantFlow,
  Condenser Outlet Setpoint,
  ${x.designFlow.toFixed(7)},
  ${x.designFlow.toFixed(7)},
  55,
  10,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  Holding Geo Refrigeration,
  Holding WalkIn;
`;
}

function walkIn({ name, capacityW, targetC, fanW, lightW, restocking, floorArea, exposedArea, width, height, uValue }) {
  const defrostPower = targetC <= 4 ? Math.max(800, capacityW * 0.45) : 0;
  const defrostType = defrostPower > 0 ? "Electric" : "None";
  return `
Refrigeration:WalkIn,
  ${name},
  Always On,
  ${capacityW.toFixed(2)},
  ${targetC.toFixed(2)},
  ${(targetC - 5).toFixed(2)},
  0,
  Always Off,
  ${fanW.toFixed(2)},
  0,
  ${lightW.toFixed(2)},
  Lighting Schedule,
  ${defrostType},
  TimeSchedule,
  Defrost Schedule,
  Dripdown Schedule,
  ${defrostPower.toFixed(2)},
  ,
  ${restocking},
  ,
  ${floorArea.toFixed(3)},
  ${Math.max(0.12, uValue * 0.9).toFixed(4)},
  Ambient Zone,
  ${exposedArea.toFixed(3)},
  ${uValue.toFixed(4)},
  ,,,,
  ${Math.min(4, Math.max(1.5, width * 0.5)).toFixed(2)},
  ${Math.min(2.5, Math.max(1.8, height * 0.75)).toFixed(2)},
  ,
  Door Schedule,
  StripCurtain;
`;
}

function hybridRefrigeration(x, variant) {
  const preCool = walkIn({
    name: "Precool WalkIn",
    capacityW: x.preCoolRatedCapacityW,
    targetC: x.indoor,
    fanW: Math.max(420, x.dailyBatch * 75),
    lightW: Math.max(120, x.preCoolFloorArea * 6),
    restocking: "Precool Product Restocking",
    floorArea: x.preCoolFloorArea,
    exposedArea: x.preCoolExposedArea,
    width: x.preCoolWidth,
    height: x.preCoolHeight,
    uValue: x.uValue,
  });
  const holding = walkIn({
    name: "Holding WalkIn",
    capacityW: x.holdingRatedCapacityW,
    targetC: x.indoor,
    fanW: Math.max(300, x.capacity * 28),
    lightW: Math.max(180, x.floorArea * 5),
    restocking: "Holding Produce Load",
    floorArea: x.floorArea,
    exposedArea: x.exposedArea,
    width: x.width,
    height: x.height,
    uValue: x.uValue,
  });
  const preCoolRack = airCooledRack({ name: "Precool Booster Rack", load: "Precool WalkIn", endUse: "Precool Booster Refrigeration", node: "Precool Condenser Air Node", cop: x.convCop, ratedCapacityW: x.preCoolRatedCapacityW });
  const holdingRack = variant === "geo"
    ? holdingGeoRack(x)
    : airCooledRack({ name: "Holding Conventional Rack", load: "Holding WalkIn", endUse: "Holding Conventional Refrigeration", node: "Holding Condenser Air Node", cop: x.convCop, ratedCapacityW: x.holdingRatedCapacityW });
  return `
Curve:Quadratic,Rack COP Modifier,1,0,0,-20,60,0.5,1.5,Temperature,Dimensionless;
${preCool}
${holding}
${preCoolRack}
${holdingRack}`;
}

function mushroomGeoRack(x) {
  return `
Refrigeration:CompressorRack,
  Mushroom Central Geo Rack,
  Outdoors,
  ${x.geoCop.toFixed(4)},
  Rack COP Modifier,
  0,
  ,
  WaterCooled,
  Ground Loop Demand Inlet,
  Ground Loop Demand Outlet,
  ConstantFlow,
  Condenser Outlet Setpoint,
  ${x.designFlow.toFixed(7)},
  ${x.designFlow.toFixed(7)},
  55,
  10,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  ,
  Mushroom Central Geo Refrigeration,
  Central Mushroom Chamber List;
`;
}

function mushroomRefrigeration(x, variant) {
  const rooms = x.mushroomChambers.map((chamber, index) => walkIn({
    name: chamber.name,
    capacityW: chamber.ratedCapacityW,
    targetC: chamber.targetTemp,
    fanW: chamber.fanPowerW,
    lightW: chamber.lightPowerW,
    restocking: `Mushroom Process Load ${index + 1}`,
    floorArea: x.floorArea,
    exposedArea: x.exposedArea,
    width: x.width,
    height: x.height,
    uValue: x.uValue,
  })).join("\n");
  const roomList = `
Refrigeration:CaseAndWalkInList,
  Central Mushroom Chamber List,
${x.mushroomChambers.map((chamber, index) => `  ${chamber.name}${index === x.mushroomChambers.length - 1 ? ";" : ","}`).join("\n")}
`;
  const rack = variant === "geo"
    ? mushroomGeoRack(x)
    : airCooledRack({ name: "Mushroom Central Conventional Rack", load: "Central Mushroom Chamber List", endUse: "Mushroom Central Conventional Refrigeration", node: "Mushroom Central Condenser Air Node", cop: x.convCop, ratedCapacityW: x.holdingRatedCapacityW });
  return `
Curve:Quadratic,Rack COP Modifier,1,0,0,-20,60,0.5,1.5,Temperature,Dimensionless;
${rooms}
${roomList}
${rack}`;
}

function groundLoop(x) {
  const pumpPower = Math.max(30, x.geoAux * 1000);
  return `
Site:GroundTemperature:Undisturbed:KusudaAchenbach,
  Geo Soil,
  ${x.soilConductivity.toFixed(3)},
  ${x.soilDensity.toFixed(1)},
  ${x.soilSpecificHeat.toFixed(1)},
  ${x.soil.toFixed(2)},
  6.0,
  25;

GroundHeatExchanger:System,
  Geo Borefield,
  Ground Loop Pump Outlet,
  Ground Loop HX Outlet,
  ${x.designFlow.toFixed(7)},
  Site:GroundTemperature:Undisturbed:KusudaAchenbach,
  Geo Soil,
  ${x.soilConductivity.toFixed(3)},
  ${(x.soilDensity * x.soilSpecificHeat).toFixed(1)},
  ,
  UHFcalc,
  ,
  ,
  Geo Borefield Array;

GroundHeatExchanger:Vertical:Properties,
  Geo Borehole Properties,
  ${x.depth.toFixed(3)},
  ${x.boreholeLength.toFixed(3)},
  0.114,
  0.7443,
  3900000,
  0.40,
  1770000,
  ${x.pipeOuterDiameter.toFixed(4)},
  ${Math.max(0.002, (x.pipeOuterDiameter - x.pipeInnerDiameter) / 2).toFixed(4)},
  0.049;

GroundHeatExchanger:Vertical:Array,
  Geo Borefield Array,
  Geo Borehole Properties,
  ${x.boreholeCount},
  1,
  ${Math.max(5, x.spacing).toFixed(3)};

PlantLoop,
  Geo Condenser Loop,
  Water,
  ,
  Geo Loop Operation,
  Ground Loop Supply Outlet,
  60,
  5,
  ${x.designFlow.toFixed(7)},
  0,
  autocalculate,
  Ground Loop Supply Inlet,
  Ground Loop Supply Outlet,
  Ground Loop Supply Branches,
  ,
  Ground Loop Demand Inlet,
  Ground Loop Demand Outlet,
  Ground Loop Demand Branches,
  ,
  SequentialLoad;

SetpointManager:Scheduled,Geo Loop Setpoint Manager,Temperature,Ground Loop Setpoint,Ground Loop Supply Outlet;

BranchList,Ground Loop Supply Branches,Ground Loop Supply Branch;
Branch,
  Ground Loop Supply Branch,
  ,
  Pump:VariableSpeed,Geo Loop Pump,Ground Loop Supply Inlet,Ground Loop Pump Outlet,
  GroundHeatExchanger:System,Geo Borefield,Ground Loop Pump Outlet,Ground Loop HX Outlet,
  Pipe:Adiabatic,Ground Loop Supply Pipe,Ground Loop HX Outlet,Ground Loop Supply Outlet;

BranchList,Ground Loop Demand Branches,Ground Loop Demand Branch;
Branch,
  Ground Loop Demand Branch,
  ,
  Refrigeration:CompressorRack,${x.mushroom ? "Mushroom Central Geo Rack" : x.hybrid ? "Holding Geo Rack" : "Geo AHU Rack"},Ground Loop Demand Inlet,Ground Loop Demand Outlet;

Pipe:Adiabatic,Ground Loop Supply Pipe,Ground Loop HX Outlet,Ground Loop Supply Outlet;

PlantEquipmentOperationSchemes,Geo Loop Operation,PlantEquipmentOperation:CoolingLoad,Geo Cooling Operation,Always On;
PlantEquipmentOperation:CoolingLoad,Geo Cooling Operation,0,1000000000,Geo HX Equipment;
PlantEquipmentList,Geo HX Equipment,GroundHeatExchanger:System,Geo Borefield;

Pump:VariableSpeed,
  Geo Loop Pump,
  Ground Loop Supply Inlet,
  Ground Loop Pump Outlet,
  ${x.designFlow.toFixed(7)},
  90000,
  ${pumpPower.toFixed(2)},
  0.87,
  0,
  0,
  1,
  0,
  0,
  0,
  Intermittent;
`;
}

function outputs(variant) {
  const groundOutputs = variant === "geo" ? `
Output:Variable,*,Pump Electricity Energy,Hourly;
Output:Variable,*,Ground Heat Exchanger Inlet Temperature,Hourly;
Output:Variable,*,Ground Heat Exchanger Outlet Temperature,Hourly;
Output:Variable,*,Ground Heat Exchanger Heat Transfer Rate,Hourly;
Output:Meter,Pumps:Electricity,Hourly;` : "";
  return `
Output:VariableDictionary,IDF;
Output:Variable,*,Site Outdoor Air Drybulb Temperature,Hourly;
Output:Variable,*,Zone Mean Air Temperature,Hourly;
Output:Variable,*,Refrigeration Walk In Evaporator Total Cooling Energy,Hourly;
Output:Variable,*,Refrigeration Walk In Ancillary Electricity Energy,Hourly;
Output:Variable,*,Refrigeration Walk In Fan Electricity Energy,Hourly;
Output:Variable,*,Refrigeration Walk In Lighting Electricity Energy,Hourly;
Output:Variable,*,Refrigeration Compressor Rack Electricity Energy,Hourly;
Output:Variable,*,Refrigeration Compressor Rack Condenser Fan Electricity Energy,Hourly;
${groundOutputs}
Output:Meter,Electricity:Facility,Hourly;
Output:Meter,Refrigeration:Electricity,Hourly;
Output:Table:SummaryReports,AllSummary;
Output:SQLite,SimpleAndTabular;
`;
}

export function generateIdf(input, variant = "geo") {
  if (!new Set(["geo", "baseline"]).has(variant)) throw new Error(`Unsupported model variant: ${variant}`);
  const x = normalizeDesign(input);
  const systemLabel = x.mushroom
    ? `${x.chamberCount}-chamber mushroom farm with one central refrigeration rack`
    : x.hybrid
      ? "30 MT hybrid two-chamber (air-cooled precool booster + Geo-AHU holding)"
      : "single cold room";
  const variantLabel = x.mushroom
    ? variant === "geo"
      ? "central water-cooled rack + vertical ground heat exchanger"
      : "central air-cooled rack baseline"
    : variant === "geo"
      ? "air-cooled precool booster + water-cooled holding rack + vertical ground heat exchanger"
      : "air-cooled precool and holding racks baseline";
  return `! Geo-AHU cold-room model generated for DOE EnergyPlus 26.1
! System: ${systemLabel}
! Variant: ${variantLabel}
! Project: ${x.location} | Commodity: ${x.crop} | Capacity: ${x.capacity} MT

Version,26.1;
SimulationControl,No,No,No,No,Yes;
Building,Geo AHU ${variant},0,Suburbs,0.04,0.4,FullExterior,25,6;
Timestep,4;
HeatBalanceAlgorithm,ConductionTransferFunction;
ShadowCalculation,PolygonClipping,Timestep;
SurfaceConvectionAlgorithm:Inside,TARP;
SurfaceConvectionAlgorithm:Outside,DOE-2;
GlobalGeometryRules,UpperLeftCorner,CounterClockWise,World;
RunPeriod,Annual,1,1,,12,31,,Tuesday,Yes,Yes,No,Yes,Yes;
${schedules(x)}
${geometry(x)}
${refrigeration(x, variant)}
${variant === "geo" ? groundLoop(x) : ""}
${outputs(variant)}
`;
}

export function createRunId(input) {
  const stable = JSON.stringify(normalizeDesign(input));
  let hash = 2166136261;
  for (let index = 0; index < stable.length; index += 1) {
    hash ^= stable.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `EP26-${(hash >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;
}
