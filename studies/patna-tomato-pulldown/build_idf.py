#!/usr/bin/env python3
"""Build EnergyPlus 26.1 IDF files for the Patna tomato pull-down study.

Problem statement (from the client):
  * Weather: Patna (ISHRAE EPW, WMO 424920), month of May.
  * Product: 3 tonnes of tomato arriving at 28 C, pulled down to 12 C.
  * Room: 200 sq ft floor, 80 mm PUF panels.
  * Plant: "4 ton" condensing unit, with and without an M-cycle
    (Maisotsenko dew-point indirect evaporative) pre-cooler on the condenser air.

Everything that is physics is solved by EnergyPlus:
  * envelope conduction / solar / ground contact  -> CTF heat balance
  * room air heat + moisture balance             -> zone air model
  * condensing unit + unit cooler                -> Coil:Cooling:DX:SingleSpeed (ASHRAE 140
    tested DX model: sensible/latent split, cycling loss, coil re-evaporation) inside an
    AirLoopHVAC:UnitarySystem. Its capacity / EIR tables are built by cycle_curves.py from
    the Copeland ZS45K4E-TF5 (R-404A, 50 Hz) AHRI-540 map shipped in EnergyPlus DataSets,
    balanced against the condenser and the evaporator.
    (Refrigeration:AirChiller was tried first and rejected: in this application it put
    ~4 kW of latent load on the compressor while removing no water, RH stuck at 100 %.)
The only things written by us (in EnergyPlus EMS/Erl, inside the same simulation) are:
  * the tomato itself: 1-D transient conduction in a sphere (5 shells), ASHRAE
    Becker-Fricke respiration heat and ASHRAE transpiration (moisture) per shell,
  * door-opening infiltration (Gosney-Olama, ASHRAE Refrigeration Handbook ch. 24),
  * the M-cycle outlet temperature (dew-point effectiveness) that feeds the
    condenser air inlet node, plus its fan/pump power and water use.
All inputs are listed in CONFIG below so the dashboard can print them verbatim.
"""
import json
import math
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from pathlib import Path

HERE = Path(__file__).resolve().parent

FT = 0.3048

CONFIG = {
    "location": "Patna, Bihar (ISHRAE EPW, WMO 424920, 25.27N 85.17E, 53 m)",
    "run_period": {"begin_month": 5, "begin_day": 1, "end_month": 5, "end_day": 31},
    "timesteps_per_hour": 30,
    # ---------------- room ----------------
    "room_length_m": 20 * FT,     # 20 ft
    "room_width_m": 10 * FT,      # 10 ft  -> 200 sq ft floor
    "room_height_m": 10 * FT,     # 10 ft clear height (assumed, typical Indian cold room)
    "puf_thickness_m": 0.080,
    "puf_conductivity": 0.023,    # W/m-K, aged PUF (IS 12436 limit ~0.023)
    "puf_density": 40.0,
    "puf_cp": 1400.0,
    "ppgi_thickness_m": 0.0005,   # 0.5 mm pre-painted steel skins both sides
    "outer_solar_absorptance": 0.45,  # off-white PPGI after some weathering
    "floor_screed_m": 0.100,      # 100 mm RCC wearing screed on top of floor PUF
    "base_infiltration_ach": 0.10,  # cam-lock panel joints, sealed
    "door_width_m": 0.9,
    "door_height_m": 2.0,
    "strip_curtain_effectiveness": 0.80,
    # ---------------- product ----------------
    "product_mass_kg": 3000.0,
    "product_entry_c": 28.0,
    "product_target_c": 12.0,
    "tomato_cp": 3980.0,          # J/kg-K  ASHRAE Refrigeration Handbook ch.19 (tomato, mature/ripe)
    "tomato_k": 0.53,             # W/m-K   ASHRAE ch.19
    "tomato_density": 1000.0,     # kg/m3 (fruit, not bulk)
    "tomato_diameter_m": 0.055,   # ~87 g fruit
    "h_eff": 3.0,                 # W/m2-K effective fruit-to-room-air coefficient for
                                  # ROOM cooling of stacked vented crates (not forced-air).
                                  # Most uncertain input -> swept 1.5 / 3 / 6 in sensitivity runs
    "resp_f": 2.0099e-4,          # ASHRAE Becker-Fricke respiration coefficients, tomato
    "resp_g": 2.8045,
    "transpiration_k": 140e-12,   # kg/(kg s Pa)  ASHRAE transpiration coefficient, tomato
    "crate_mass_kg": 225.0,       # 150 HDPE crates x 1.5 kg (20 kg tomato per crate)
    "crate_cp": 1900.0,
    "crate_area_m2": 120.0,
    "crate_h": 5.0,
    "batch_days": [1, 7, 13, 19, 25],  # a fresh 3 t batch every 6 days (old batch leaves)
    "batch_hour": 10,             # loading 10:00-11:00 (unloading of old batch 09:00-10:00)
    # ---------------- refrigeration ----------------
    "room_setpoint_c": 12.0,
    "compressor": "Copeland-SCROLL-50HZ_R-404A_MED_ZS45K4E-TF5",
    "unit_cooler_fan_w": 570.0,   # 3 x 190 W fans
    "unit_cooler_airflow_m3s": 2.2,
    "evap_enthalpy_effectiveness": 0.33,  # wet-coil enthalpy effectiveness; gives Te ~3 C at 12 C / 85 % room
    "condenser_ua_w_per_k": 1450.0,  # heat rejection per K of (Tcond - Tair_in)
    "condenser_fan_w": 360.0,     # 2 x 180 W
    "condenser_airflow_m3s": 2.1,     # used for M-cycle water use
    # ---------------- M-cycle ----------------
    "mcycle_dewpoint_effectiveness": 0.60,  # field-realistic; lab claims are 0.7-0.9
    "mcycle_parasitic_w": 500.0,  # extra fan (HMX pressure drop + working air) + pump
    "mcycle_water_bleed_factor": 1.25,
    "mcycle_min_outdoor_c": 24.0,
    # ---------------- money ----------------
    "tariff_inr_per_kwh": 8.5,
    "fan_cycling": False,         # False = unit-cooler fans run 24x7 (typical); True = fans cycle with compressor
}


def fmt(v, nd=6):
    return f"{v:.{nd}g}" if isinstance(v, float) else str(v)


def obj(name, *fields):
    body = ",\n  ".join(str(f) for f in fields)
    return f"{name},\n  {body};\n"


def dx_tables(c):
    from cycle_curves import Unit, make_curves
    u = Unit(c)
    base = make_curves(c)
    twb_grid = [4, 6, 8, 10, 12, 14, 16, 18, 19.44, 20, 22, 24, 26]
    tc_grid = [10, 15, 20, 25, 30, 35, 38, 41, 44, 47, 50]
    q_table, eir_table, rows = [], [], []
    for twb in twb_grid:          # first variable varies slowest
        for tc in tc_grid:
            r = u.solve(twb, tc)
            q_table.append(r["q"])
            eir_table.append(r["pt"] / r["q"])
            rows.append(r)
    base.update(twb_grid=twb_grid, tc_grid=tc_grid, q_table=q_table, eir_table=eir_table, table_rows=rows)
    return base


def sphere_model(c):
    """Finite-volume constants for one fruit, 5 concentric shells."""
    n = 5
    R = c["tomato_diameter_m"] / 2
    dr = R / n
    k, rho, cp = c["tomato_k"], c["tomato_density"], c["tomato_cp"]
    vol = [4 / 3 * math.pi * ((i * dr) ** 3 - ((i - 1) * dr) ** 3) for i in range(1, n + 1)]
    rc = [(i - 0.5) * dr for i in range(1, n + 1)]
    G = [4 * math.pi * k / (1 / rc[i] - 1 / rc[i + 1]) for i in range(n - 1)]
    Rk = (1 / rc[-1] - 1 / R) / (4 * math.pi * k)
    A = 4 * math.pi * R ** 2
    Rc = 1 / (c["h_eff"] * A)
    m_fruit = rho * sum(vol)
    nfruit = c["product_mass_kg"] / m_fruit
    return dict(n=n, vol=vol, mass=[rho * v for v in vol], C=[rho * cp * v for v in vol], G=G,
                Rk=Rk, Rc=Rc, A=A, m_fruit=m_fruit, nfruit=nfruit)


def ems_product(c, sm):
    a_resp = 10.7 * c["resp_f"] / 3600.0
    g = c["resp_g"]
    kt = c["transpiration_k"]
    n = sm["n"]
    nsub = 4
    days = c["batch_days"]
    daycond = " || ".join(f"(DayOfMonth == {d})" for d in days)
    Gs = sm["G"]
    C = sm["C"]
    m = sm["mass"]
    Rs = sm["Rk"] + sm["Rc"]
    Ccr = c["crate_mass_kg"] * c["crate_cp"]
    Gcr = c["crate_h"] * c["crate_area_m2"]
    lines = [
        "ProductModel",
        "IF WarmupFlag == 1",
        "  SET Present = 0",
        "  SET BatchNo = 0",
        "  SET LoadedDay = 0",
        "  SET WtLoss = 0",
        "ENDIF",
        f"IF (WarmupFlag == 0) && ({daycond}) && (Hour == {c['batch_hour']}) && (LoadedDay <> DayOfMonth)",
        "  SET LoadedDay = DayOfMonth",
        "  SET Present = 1",
        "  SET BatchNo = BatchNo + 1",
        "  SET WtLoss = 0",
    ]
    lines += [f"  SET T{i} = {c['product_entry_c']}" for i in range(1, n + 1)]
    lines += ["  SET Age = 0", "ENDIF"]
    lines += [
        "IF Present == 0",
        "  SET ProdSensAct = 0",
        "  SET ProdLatAct = 0",
        "  SET RespTot = 0",
        "  SET CoreT = Tair",
        "  SET SurfT = Tair",
        "  SET MeanT = Tair",
        "  RETURN",
        "ENDIF",
        f"SET dt = ZoneTimeStep * 3600 / {nsub}",
        "SET Pa = Wair * Pb / (0.621945 + Wair)",
        "SET SumSens = 0",
        "SET SumLat = 0",
        "SET SumResp = 0",
        "SET k = 0",
        f"WHILE k < {nsub}",
        f"  SET Ts = (T{n} / {sm['Rk']:.6e} + Tair / {sm['Rc']:.6e}) / (1 / {sm['Rk']:.6e} + 1 / {sm['Rc']:.6e})",
        "  SET Psat = @PsatFnTemp Ts",
        "  SET VPD = 0.98 * Psat - Pa",
        "  IF VPD < 0",
        "    SET VPD = 0",
        "  ENDIF",
        f"  SET Mtr = {kt:.6e} * {sm['m_fruit']:.6e} * VPD",
        "  SET Hfg = @HfgAirFnWTdb Wair Ts",
        "  SET Qev = Mtr * Hfg",
        f"  SET Qout = (T{n} - Tair) / {Rs:.6e}",
    ]
    for i in range(1, n + 1):
        lines.append(f"  SET Q{i} = {a_resp:.6e} * ((1.8 * T{i} + 32) ^ {g}) * {m[i-1]:.6e}")
    for i in range(1, n + 1):
        terms = []
        if i > 1:
            terms.append(f"{Gs[i-2]:.6e} * (T{i-1} - T{i})")
        if i < n:
            terms.append(f"{Gs[i-1]:.6e} * (T{i+1} - T{i})")
        terms.append(f"Q{i}")
        if i == n:
            terms += ["(0 - Qout)", "(0 - Qev)"]
        lines.append(f"  SET D{i} = (" + " + ".join(terms) + f") * dt / {C[i-1]:.6e}")
    for i in range(1, n + 1):
        lines.append(f"  SET T{i} = T{i} + D{i}")
    lines += [
        f"  SET SumSens = SumSens + Qout * {sm['nfruit']:.6e}",
        f"  SET SumLat = SumLat + Qev * {sm['nfruit']:.6e}",
        "  SET SumResp = SumResp + (" + " + ".join(f"Q{i}" for i in range(1, n + 1)) + f") * {sm['nfruit']:.6e}",
        f"  SET WtLoss = WtLoss + Mtr * {sm['nfruit']:.6e} * dt",
        "  SET k = k + 1",
        "ENDWHILE",
        f"SET ProdSensAct = SumSens / {nsub}",
        # crates (lumped with room air through ZoneCapacitanceMultiplier) arrive warm:
        # release Ccr*(Tentry-Tset) as an exponential pulse with tau = Ccr/(h*A)
        "SET Age = Age + ZoneTimeStep * 3600",
        "SET CrateQ = 0",
        "IF Age < 14400",
        f"  SET Xc = Age / {Ccr / Gcr:.4f}",
        "  SET Xc = 0 - Xc",
        "  SET CrateQ = @Exp Xc",
        f"  SET CrateQ = CrateQ * {Ccr * (c['product_entry_c'] - c['room_setpoint_c']) / (Ccr / Gcr):.4f}",
        "ENDIF",
        "SET ProdSensAct = ProdSensAct + CrateQ",
        f"SET ProdLatAct = SumLat / {nsub}",
        f"SET RespTot = SumResp / {nsub}",
        "SET CoreT = T1",
        f"SET SurfT = (T{n} / {sm['Rk']:.6e} + Tair / {sm['Rc']:.6e}) / (1 / {sm['Rk']:.6e} + 1 / {sm['Rc']:.6e})",
        "SET MeanT = (" + " + ".join(f"T{i} * {m[i-1]:.6e}" for i in range(1, n + 1)) + f") / {sum(m):.6e}",
    ]
    return obj("EnergyManagementSystem:Program", *lines)


def ems_door(c):
    days = c["batch_days"]
    daycond = " || ".join(f"(DayOfMonth == {d})" for d in days)
    A = c["door_width_m"] * c["door_height_m"]
    H = c["door_height_m"]
    E = c["strip_curtain_effectiveness"]
    h = c["batch_hour"]
    return obj(
        "EnergyManagementSystem:Program",
        "DoorInfiltration",
        "SET Frac = 0",
        "IF (Hour == 8) || (Hour == 18)",
        "  SET Frac = 0.033",
        "ENDIF",
        f"IF ({daycond}) && ((Hour == {h - 1}) || (Hour == {h}))",
        "  SET Frac = 0.5",
        "ENDIF",
        "SET RhoI = @RhoAirFnPbTdbW Pb Tair Wair",
        "SET RhoO = @RhoAirFnPbTdbW Pb Tout Wout",
        "SET Qdoor = 0",
        "IF RhoI > RhoO",
        f"  SET Qdoor = 0.221 * {A:.4f} * ((1 - RhoO / RhoI) ^ 0.5) * ((9.81 * {H:.3f}) ^ 0.5) * ((2 / (1 + ((RhoI / RhoO) ^ 0.333333))) ^ 1.5)",
        "ENDIF",
        f"SET DoorInfilAct = Qdoor * Frac * (1 - {E})",
        "SET DoorFracOut = Frac",
    )


def ems_mcycle(c, on):
    if not on:
        return obj(
            "EnergyManagementSystem:Program",
            "CondenserInlet",
            "SET CondTdbAct = Tout",
            "SET CondTwbAct = @TwbFnTdbWPb Tout Wout Pb",
            "SET MCFracAct = 0",
            "SET MCWater = 0",
        )
    eps = c["mcycle_dewpoint_effectiveness"]
    mdot = 1.18 * c["condenser_airflow_m3s"]
    return obj(
        "EnergyManagementSystem:Program",
        "CondenserInlet",
        "SET Tdp = @TdpFnWPb Wout Pb",
        "SET CondTdbAct = Tout",
        "SET MCFracAct = 0",
        "SET MCWater = 0",
        f"IF Tout >= {c['mcycle_min_outdoor_c']}",
        f"  SET CondTdbAct = Tout - {eps} * (Tout - Tdp)",
        "  SET MCFracAct = CoilRTF",
        "  IF MCFracAct > 1",
        "    SET MCFracAct = 1",
        "  ENDIF",
        f"  SET MCWater = MCFracAct * {mdot:.4f} * 1006 * (Tout - CondTdbAct) / 2430000 * {c['mcycle_water_bleed_factor']}",
        "ENDIF",
        "SET CondTwbAct = @TwbFnTdbWPb CondTdbAct Wout Pb",
    )


def build(c, mcycle, tag):
    L, W, H = c["room_length_m"], c["room_width_m"], c["room_height_m"]
    sm = sphere_model(c)
    curves = dx_tables(c)
    epw_ground = [18.06, 19.39, 22.00, 24.46, 29.13, 31.58, 32.26, 31.01, 28.14, 24.55, 21.02, 18.69]
    rp = c["run_period"]
    parts = []
    P = parts.append
    P(f"! Patna tomato pull-down study  variant={tag}  (generated by build_idf.py)\n")
    P(obj("Version", "26.1"))
    P(obj("SimulationControl", "No", "No", "No", "No", "Yes", "No", 1))
    P(obj("Building", "Patna Tomato Cold Room", 0, "Country", 0.04, 0.4, "FullExterior", 25, 6))
    P(obj("ShadowCalculation", "PolygonClipping", "Periodic", 7, 15000))
    P(obj("SurfaceConvectionAlgorithm:Inside", "TARP"))
    P(obj("SurfaceConvectionAlgorithm:Outside", "DOE-2"))
    P(obj("HeatBalanceAlgorithm", "ConductionTransferFunction", 200))
    P(obj("ZoneAirHeatBalanceAlgorithm", "AnalyticalSolution"))
    P(obj("Timestep", c["timesteps_per_hour"]))
    P(obj("Site:Location", "Patna ISHRAE", 25.27, 85.17, 5.5, 53.0))
    P(obj("RunPeriod", "May", rp["begin_month"], rp["begin_day"], "", rp["end_month"], rp["end_day"], "",
          "", "No", "No", "No", "Yes", "Yes"))
    P(obj("Site:GroundTemperature:BuildingSurface", *[f"{t:.2f}" for t in epw_ground]))
    P(obj("GlobalGeometryRules", "UpperLeftCorner", "Counterclockwise", "Relative"))
    # schedules
    P(obj("ScheduleTypeLimits", "Any Number"))
    P(obj("ScheduleTypeLimits", "Fraction", 0, 1, "Continuous"))
    P(obj("ScheduleTypeLimits", "Control Type", 0, 4, "Discrete"))
    P(obj("Schedule:Constant", "Always On", "Fraction", 1))
    P(obj("Schedule:Constant", "Always Off", "Fraction", 0))
    P(obj("Schedule:Constant", "Dual Control Type", "Control Type", 4))
    P(obj("Schedule:Constant", "Cooling Setpoint", "Any Number", c["room_setpoint_c"]))
    P(obj("Schedule:Constant", "Heating Setpoint", "Any Number", 2.0))
    P(obj("Schedule:Constant", "Condenser Air Tdb", "Any Number", 35))
    P(obj("Schedule:Constant", "Condenser Air Twb", "Any Number", 25))
    P(obj("Schedule:Constant", "MCycle Run Fraction", "Any Number", 0))
    # materials
    P(obj("Material", "PPGI Skin", "Smooth", c["ppgi_thickness_m"], 45.0, 7850, 500, 0.9,
          c["outer_solar_absorptance"], c["outer_solar_absorptance"]))
    P(obj("Material", "PUF 80mm", "MediumSmooth", c["puf_thickness_m"], c["puf_conductivity"], c["puf_density"], c["puf_cp"], 0.9, 0.5, 0.5))
    P(obj("Material", "RCC Screed", "MediumRough", c["floor_screed_m"], 1.4, 2240, 900, 0.9, 0.7, 0.7))
    P(obj("Construction", "PUF Panel", "PPGI Skin", "PUF 80mm", "PPGI Skin"))
    P(obj("Construction", "PUF Floor", "PUF 80mm", "RCC Screed"))
    P(obj("Zone", "ColdRoom", 0, 0, 0, 0, 1, 1, H, L * W * H, L * W))
    air_cap = 1.2 * 1006 * L * W * H
    crate_cap = c["crate_mass_kg"] * c["crate_cp"]
    P(obj("ZoneCapacitanceMultiplier:ResearchSpecial", "Crates lumped with room air", "ColdRoom",
          f"{(air_cap + crate_cap) / air_cap:.4f}", 1.0, 1.0, 1.0))

    def surf(name, typ, cons, bc, sun, wind, vf, pts):
        flat = []
        for p in pts:
            flat += [f"{v:.4f}" for v in p]
        return obj("BuildingSurface:Detailed", name, typ, cons, "ColdRoom", "", bc, "", sun, wind, vf, len(pts), *flat)

    P(surf("Floor", "Floor", "PUF Floor", "Ground", "NoSun", "NoWind", 0, [(0, W, 0), (L, W, 0), (L, 0, 0), (0, 0, 0)]))
    P(surf("Roof", "Roof", "PUF Panel", "Outdoors", "SunExposed", "WindExposed", 0, [(0, 0, H), (L, 0, H), (L, W, H), (0, W, H)]))
    P(surf("South Wall", "Wall", "PUF Panel", "Outdoors", "SunExposed", "WindExposed", 0.5, [(0, 0, H), (0, 0, 0), (L, 0, 0), (L, 0, H)]))
    P(surf("East Wall", "Wall", "PUF Panel", "Outdoors", "SunExposed", "WindExposed", 0.5, [(L, 0, H), (L, 0, 0), (L, W, 0), (L, W, H)]))
    P(surf("North Wall", "Wall", "PUF Panel", "Outdoors", "SunExposed", "WindExposed", 0.5, [(L, W, H), (L, W, 0), (0, W, 0), (0, W, H)]))
    P(surf("West Wall", "Wall", "PUF Panel", "Outdoors", "SunExposed", "WindExposed", 0.5, [(0, W, H), (0, W, 0), (0, 0, 0), (0, 0, H)]))
    # infiltration
    P(obj("ZoneInfiltration:DesignFlowRate", "Panel Joint Leakage", "ColdRoom", "Always On", "AirChanges/Hour", "", "", "", c["base_infiltration_ach"], 1, 0, 0, 0))
    P(obj("ZoneInfiltration:DesignFlowRate", "Door Opening Infiltration", "ColdRoom", "Always On", "Flow/Zone", 0.0, "", "", "", 1, 0, 0, 0))
    # product heat + moisture (driven by EMS)
    P(obj("OtherEquipment", "Tomato Sensible", "None", "ColdRoom", "Always On", "EquipmentLevel", 0, "", "", 0, 0.3, 0))
    P(obj("OtherEquipment", "Tomato Transpiration", "None", "ColdRoom", "Always On", "EquipmentLevel", 0, "", "", 1, 0, 0))
    # thermostat + condensing unit (DX coil whose performance tables come from the compressor map)
    P(obj("ThermostatSetpoint:DualSetpoint", "Cold Room Setpoints", "Heating Setpoint", "Cooling Setpoint"))
    P(obj("ZoneControl:Thermostat", "Cold Room Thermostat", "ColdRoom", "Dual Control Type", "ThermostatSetpoint:DualSetpoint", "Cold Room Setpoints"))
    P(obj("ZoneHVAC:EquipmentConnections", "ColdRoom", "ColdRoom Equipment", "Unit Cooler Outlet Node", "Unit Cooler Inlet Node", "ColdRoom Air Node", "ColdRoom Return Node"))
    P(obj("ZoneHVAC:EquipmentList", "ColdRoom Equipment", "SequentialLoad", "AirLoopHVAC:UnitarySystem", "Unit Cooler System", 1, 1, "", ""))
    P(obj("AirLoopHVAC:UnitarySystem", "Unit Cooler System", "Load", "ColdRoom", "None", "Always On",
          "Unit Cooler Inlet Node", "Unit Cooler Outlet Node", "Fan:OnOff", "Unit Cooler Fans", "BlowThrough", "Always Off" if c.get("fan_cycling") else "Always On",
          "", "", "", "Coil:Cooling:DX:SingleSpeed", "Condensing Unit DX Coil", "No", 1.0, "SensibleOnlyLoadControl", "", "",
          "SupplyAirFlowRate", c["unit_cooler_airflow_m3s"], "", "", "", "None", "", "", "", "",
          "SupplyAirFlowRate", c["unit_cooler_airflow_m3s"], "", "", "", "", "", "No", 30, 21, "", 0, 0, "", "", "", "", "", ""))
    eta = 0.45
    dp = c["unit_cooler_fan_w"] * eta / c["unit_cooler_airflow_m3s"]
    P(obj("Fan:OnOff", "Unit Cooler Fans", "Always On", eta, f"{dp:.2f}", c["unit_cooler_airflow_m3s"], 0.85, 1.0,
          "Unit Cooler Inlet Node", "Unit Cooler Fan Outlet Node", "", "", "Unit Cooler Fans"))
    cur = curves
    P(obj("Table:IndependentVariable", "Coil Entering Wetbulb", "Linear", "Constant", min(cur["twb_grid"]), max(cur["twb_grid"]), "", "Temperature", "", "", "", *cur["twb_grid"]))
    P(obj("Table:IndependentVariable", "Condenser Entering Drybulb", "Linear", "Constant", min(cur["tc_grid"]), max(cur["tc_grid"]), "", "Temperature", "", "", "", *cur["tc_grid"]))
    P(obj("Table:IndependentVariableList", "Coil Variables", "Coil Entering Wetbulb", "Condenser Entering Drybulb"))
    P(obj("Table:Lookup", "CapFT from Compressor Map", "Coil Variables", "DivisorOnly", f"{cur['rated']['q']:.3f}", "", "", "Dimensionless", "", "", "", *[f"{v:.3f}" for v in cur["q_table"]]))
    P(obj("Table:Lookup", "EIRFT from Compressor Map", "Coil Variables", "DivisorOnly", f"{cur['rated']['pt'] / cur['rated']['q']:.6f}", "", "", "Dimensionless", "", "", "", *[f"{v:.6f}" for v in cur["eir_table"]]))
    P(obj("Curve:Quadratic", "Flow Fraction Unity", 1, 0, 0, 0, 1.5))
    P(obj("Curve:Quadratic", "PLF Cd 0.15", 0.85, 0.15, 0, 0, 1))
    P(obj("Coil:Cooling:DX:SingleSpeed", "Condensing Unit DX Coil", "Always On", f"{cur['rated']['q']:.2f}", f"{cur['rated_shr']:.4f}",
          f"{cur['rated_cop']:.4f}", c["unit_cooler_airflow_m3s"], "", "", "Unit Cooler Fan Outlet Node", "Unit Cooler Outlet Node",
          "CapFT from Compressor Map", "Flow Fraction Unity", "EIRFT from Compressor Map", "Flow Fraction Unity", "PLF Cd 0.15",
          -25, 1000, 1.5, 3, 45, "Condenser Air Inlet Node", "AirCooled", "", "", "", 0, "", 10, "", "", 0, 2, "", "", "", "No", ""))
    if mcycle:
        P(obj("OutdoorAir:Node", "Condenser Air Inlet Node", -1, "Condenser Air Tdb", "Condenser Air Twb"))
    else:
        P(obj("OutdoorAir:Node", "Condenser Air Inlet Node", -1))
    # M-cycle parasitic power
    P(obj("Exterior:FuelEquipment", "MCycle Fans and Pump", "Electricity", "MCycle Run Fraction", c["mcycle_parasitic_w"], "MCycle"))
    # ---------------- EMS ----------------
    S = lambda name, key, var: obj("EnergyManagementSystem:Sensor", name, key, var)
    A = lambda name, comp, typ, ctrl: obj("EnergyManagementSystem:Actuator", name, comp, typ, ctrl)
    P(S("Tair", "ColdRoom", "Zone Mean Air Temperature"))
    P(S("Wair", "ColdRoom", "Zone Mean Air Humidity Ratio"))
    P(S("Tout", "Environment", "Site Outdoor Air Drybulb Temperature"))
    P(S("Wout", "Environment", "Site Outdoor Air Humidity Ratio"))
    P(S("Pb", "Environment", "Site Outdoor Air Barometric Pressure"))
    P(S("CoilRTF", "Condensing Unit DX Coil", "Cooling Coil Runtime Fraction"))
    P(A("ProdSensAct", "Tomato Sensible", "OtherEquipment", "Power Level"))
    P(A("ProdLatAct", "Tomato Transpiration", "OtherEquipment", "Power Level"))
    P(A("DoorInfilAct", "Door Opening Infiltration", "Zone Infiltration", "Air Exchange Flow Rate"))
    if mcycle:
        P(A("CondTdbAct", "Condenser Air Tdb", "Schedule:Constant", "Schedule Value"))
        P(A("CondTwbAct", "Condenser Air Twb", "Schedule:Constant", "Schedule Value"))
        P(A("MCFracAct", "MCycle Run Fraction", "Schedule:Constant", "Schedule Value"))
    gv = ["Present", "BatchNo", "LoadedDay", "WtLoss", "CoreT", "SurfT", "MeanT", "RespTot", "DoorFracOut", "MCWater", "Age", "CrateQ"] + [f"T{i}" for i in range(1, 6)]
    P(obj("EnergyManagementSystem:GlobalVariable", *gv))
    P(ems_product(c, sm))
    P(ems_door(c))
    if mcycle:
        P(ems_mcycle(c, mcycle))
    progs = ["ProductModel", "DoorInfiltration"] + (["CondenserInlet"] if mcycle else [])
    P(obj("EnergyManagementSystem:ProgramCallingManager", "Product and Door", "BeginTimestepBeforePredictor", *progs))
    for var, units in [("CoreT", "C"), ("SurfT", "C"), ("MeanT", "C"), ("RespTot", "W"), ("WtLoss", "kg"), ("Present", ""), ("BatchNo", ""), ("DoorFracOut", ""), ("MCWater", "kg/s"), ("CrateQ", "W")]:
        P(obj("EnergyManagementSystem:OutputVariable", f"Tomato {var}", var, "Averaged", "ZoneTimestep", "", units))
    P(obj("Output:EnergyManagementSystem", "NotByUniqueKeyNames", "NotByUniqueKeyNames", "ErrorsOnly"))
    # ---------------- outputs ----------------
    rep = "Timestep"
    outvars = [
        ("Environment", "Site Outdoor Air Drybulb Temperature"),
        ("Environment", "Site Outdoor Air Dewpoint Temperature"),
        ("Environment", "Site Outdoor Air Relative Humidity"),
        ("ColdRoom", "Zone Mean Air Temperature"),
        ("ColdRoom", "Zone Air Relative Humidity"),
        ("ColdRoom", "Zone Air Heat Balance Surface Convection Rate"),
        ("ColdRoom", "Zone Air Heat Balance Internal Convective Heat Gain Rate"),
        ("ColdRoom", "Zone Air Heat Balance Outdoor Air Transfer Rate"),
        ("ColdRoom", "Zone Air Heat Balance System Convective Heat Gain Rate"),
        ("ColdRoom", "Zone Air Heat Balance Air Energy Storage Rate"),
        ("ColdRoom", "Zone Infiltration Sensible Heat Gain Energy"),
        ("ColdRoom", "Zone Infiltration Sensible Heat Loss Energy"),
        ("ColdRoom", "Zone Infiltration Latent Heat Gain Energy"),
        ("ColdRoom", "Zone Infiltration Latent Heat Loss Energy"),
        ("ColdRoom", "Zone Infiltration Current Density Volume Flow Rate"),
        ("*", "Surface Inside Face Conduction Heat Transfer Rate"),
        ("Condenser Air Inlet Node", "System Node Temperature"),
        ("*", "Exterior Equipment Fuel Rate"),
    ]
    for k, v in outvars:
        P(obj("Output:Variable", k, v, rep))
    for v in ["Cooling Coil Total Cooling Rate", "Cooling Coil Sensible Cooling Rate", "Cooling Coil Latent Cooling Rate",
              "Cooling Coil Electricity Rate", "Cooling Coil Runtime Fraction",
              "Fan Electricity Rate", "Fan Runtime Fraction", "Unitary System Compressor Part Load Ratio",
              "Unitary System Total Cooling Rate", "Unitary System Sensible Cooling Rate", "Unitary System Latent Cooling Rate",
              "Performance Curve Output Value", "Performance Curve Input Variable 1 Value", "Performance Curve Input Variable 2 Value",
              "Zone Air Humidity Ratio", "System Node Temperature", "System Node Humidity Ratio", "System Node Wetbulb Temperature",
              "Zone Predicted Sensible Load to Cooling Setpoint Heat Transfer Rate", "Zone Air Temperature",
              "Zone Thermostat Cooling Setpoint Temperature"]:
        P(obj("Output:Variable", "*", v, rep))
    for v in ["Tomato CoreT", "Tomato SurfT", "Tomato MeanT", "Tomato RespTot", "Tomato WtLoss", "Tomato Present", "Tomato BatchNo", "Tomato DoorFracOut", "Tomato MCWater", "Tomato CrateQ"]:
        P(obj("Output:Variable", "*", v, rep))
    P(obj("Output:Variable", "*", "Other Equipment Convective Heating Rate", rep))
    P(obj("Output:Variable", "*", "Other Equipment Total Heating Rate", rep))
    P(obj("Output:Variable", "ColdRoom", "Zone Air Heat Balance System Air Transfer Rate", rep))
    P(obj("Output:Variable", "ColdRoom", "Zone Air Heat Balance Deviation Rate", rep))
    P(obj("Output:Variable", "ColdRoom", "Zone Air Heat Balance Interzone Air Transfer Rate", rep))
    P(obj("Output:Variable", "*", "Other Equipment Latent Gain Rate", rep))
    P(obj("Output:Meter", "Electricity:Facility", "Hourly"))
    P(obj("Output:Meter", "Cooling:Electricity", "Hourly"))
    P(obj("Output:Meter", "Fans:Electricity", "Hourly"))
    P(obj("Output:Meter", "ExteriorEquipment:Electricity", "Hourly"))
    P(obj("Output:VariableDictionary", "Regular"))
    P(obj("Output:Diagnostics", "DisplayExtraWarnings", "DisplayUnusedSchedules"))
    P(obj("Output:Table:SummaryReports", "AllSummary"))
    P(obj("OutputControl:Table:Style", "HTML"))
    P(obj("Output:SQLite", "SimpleAndTabular"))
    meta = dict(sphere=sm, dx=curves)
    return "\n".join(parts), meta


VARIANTS = {
    "base": dict(mcycle=False, overrides={}),
    "mcycle": dict(mcycle=True, overrides={}),
    "base_hlow": dict(mcycle=False, overrides={"h_eff": 1.5}),
    "base_hhigh": dict(mcycle=False, overrides={"h_eff": 6.0}),
    "mcycle_hlow": dict(mcycle=True, overrides={"h_eff": 1.5}),
    "mcycle_hhigh": dict(mcycle=True, overrides={"h_eff": 6.0}),
    "mcycle_eps45": dict(mcycle=True, overrides={"mcycle_dewpoint_effectiveness": 0.45}),
    "mcycle_eps75": dict(mcycle=True, overrides={"mcycle_dewpoint_effectiveness": 0.75}),
    "base_fancycle": dict(mcycle=False, overrides={"fan_cycling": True}),
    "mcycle_fancycle": dict(mcycle=True, overrides={"fan_cycling": True}),
}


def main():
    names = sys.argv[1:] or list(VARIANTS)
    for name in names:
        v = VARIANTS[name]
        c = dict(CONFIG, **v["overrides"])
        txt, meta = build(c, v["mcycle"], name)
        d = HERE / "runs" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "in.idf").write_text(txt)
        (d / "config.json").write_text(json.dumps({"variant": name, "mcycle": v["mcycle"], "config": c,
                                                    "sphere": meta["sphere"], "dx": {k: meta["dx"][k] for k in ("rated", "rated_shr", "rated_cop", "twb_grid", "tc_grid", "table_rows", "unit")}}, indent=1))
        print("wrote", d / "in.idf")


if __name__ == "__main__":
    main()
