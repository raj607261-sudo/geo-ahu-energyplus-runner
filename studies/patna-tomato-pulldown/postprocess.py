#!/usr/bin/env python3
"""Read every EnergyPlus run of the study and write dashboard/data.json.

Nothing here changes a simulated number: it only integrates EnergyPlus time series,
extracts pull-down times and builds independent hand checks / balance closures.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from eplus_sql import meters, series

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
DT_H = None  # set from timestep


def g(d, name, key=None):
    for (k, n), v in d.items():
        if n.lower() == name.lower() and (key is None or k.lower() == key.lower()):
            return v
    raise KeyError(name)


def err_summary(path):
    txt = path.read_text(errors="replace")
    last = [l for l in txt.splitlines() if "EnergyPlus Completed" in l or "Terminated" in l]
    m = re.search(r"(\d+) Warning; (\d+) Severe Errors", last[-1] if last else "")
    kinds = {}
    for line in txt.splitlines():
        mm = re.match(r"\s*(?:\*+\s+)?\*\* Warning \*\* (.*)", line)
        if mm:
            key = re.sub(r"\d[\d.E+-]*", "#", mm.group(1))[:120]
            kinds[key] = kinds.get(key, 0) + 1
    rec = re.findall(r"\*\* Warning \*\* (.*?)\n.*?This error occurred (\d+) total times", txt, re.S)
    return dict(completed="Completed Successfully" in txt, warnings=int(m.group(1)) if m else None,
                severe=int(m.group(2)) if m else None,
                recurring=[{"msg": r[0].strip()[:160], "count": int(r[1])} for r in rec],
                unique=[k for k in kinds])


def first_index(arr, cond, start, stop):
    for i in range(start, stop):
        if cond(arr[i]):
            return i
    return None


def analyse(variant):
    d_run = RUNS / variant
    cfg = json.loads((d_run / "config.json").read_text())
    c = cfg["config"]
    times, d = series(d_run / "eplusout.sql")
    mt, m = meters(d_run / "eplusout.sql")
    n = len(times)
    dt_h = 1.0 / c["timesteps_per_hour"]
    J = 3.6e6

    s = {
        "tout": g(d, "Site Outdoor Air Drybulb Temperature"),
        "tdp": g(d, "Site Outdoor Air Dewpoint Temperature"),
        "tair": g(d, "Zone Mean Air Temperature"),
        "rh": g(d, "Zone Air Relative Humidity"),
        "tmean": g(d, "Tomato MeanT"),
        "tcore": g(d, "Tomato CoreT"),
        "tsurf": g(d, "Tomato SurfT"),
        "present": g(d, "Tomato Present"),
        "batch": g(d, "Tomato BatchNo"),
        "wtloss": g(d, "Tomato WtLoss"),
        "resp": g(d, "Tomato RespTot"),
        "crate": g(d, "Tomato CrateQ"),
        "mcwater": g(d, "Tomato MCWater"),
        "door": g(d, "Tomato DoorFracOut"),
        "qtot": g(d, "Cooling Coil Total Cooling Rate"),
        "qsen": g(d, "Cooling Coil Sensible Cooling Rate"),
        "qlat": g(d, "Cooling Coil Latent Cooling Rate"),
        "pcoil": g(d, "Cooling Coil Electricity Rate"),
        "rtf": g(d, "Cooling Coil Runtime Fraction"),
        "pfan": g(d, "Fan Electricity Rate"),
        "tcond_in": g(d, "System Node Temperature", "CONDENSER AIR INLET NODE"),
        "capft": g(d, "Performance Curve Output Value", "CAPFT FROM COMPRESSOR MAP"),
        "eirft": g(d, "Performance Curve Output Value", "EIRFT FROM COMPRESSOR MAP"),
        "plf": g(d, "Performance Curve Output Value", "PLF CD 0.15"),
        "prod_sens": g(d, "Other Equipment Total Heating Rate", "TOMATO SENSIBLE"),
        "prod_lat": g(d, "Other Equipment Latent Gain Rate", "TOMATO TRANSPIRATION"),
        "hb_surf": g(d, "Zone Air Heat Balance Surface Convection Rate"),
        "hb_int": g(d, "Zone Air Heat Balance Internal Convective Heat Gain Rate"),
        "hb_oa": g(d, "Zone Air Heat Balance Outdoor Air Transfer Rate"),
        "hb_sys": g(d, "Zone Air Heat Balance System Convective Heat Gain Rate"),
        "hb_sysair": g(d, "Zone Air Heat Balance System Air Transfer Rate"),
        "hb_store": g(d, "Zone Air Heat Balance Air Energy Storage Rate"),
        "inf_lat_gain": g(d, "Zone Infiltration Latent Heat Gain Energy"),
        "inf_lat_loss": g(d, "Zone Infiltration Latent Heat Loss Energy"),
        "inf_sen_gain": g(d, "Zone Infiltration Sensible Heat Gain Energy"),
        "inf_sen_loss": g(d, "Zone Infiltration Sensible Heat Loss Energy"),
        "mc_w": g(d, "Exterior Equipment Fuel Rate") if any(k[1] == "Exterior Equipment Fuel Rate" for k in d) else [0.0] * n,
        "infil": g(d, "Zone Infiltration Current Density Volume Flow Rate"),
    }
    # condensing temperature each step, from the same balance table EnergyPlus interpolates
    import bisect
    tw, tcg, rows = cfg["dx"]["twb_grid"], cfg["dx"]["tc_grid"], cfg["dx"]["table_rows"]
    x1 = g(d, "Performance Curve Input Variable 1 Value", "CAPFT FROM COMPRESSOR MAP")
    x2 = g(d, "Performance Curve Input Variable 2 Value", "CAPFT FROM COMPRESSOR MAP")
    def interp(key, x, y):
        x = min(max(x, tw[0]), tw[-1]); y = min(max(y, tcg[0]), tcg[-1])
        i = max(0, min(len(tw) - 2, bisect.bisect_right(tw, x) - 1)); j = max(0, min(len(tcg) - 2, bisect.bisect_right(tcg, y) - 1))
        f = lambda a, b: rows[a * len(tcg) + b][key]
        tx = (x - tw[i]) / (tw[i + 1] - tw[i]); ty = (y - tcg[j]) / (tcg[j + 1] - tcg[j])
        return (1 - tx) * (1 - ty) * f(i, j) + tx * (1 - ty) * f(i + 1, j) + (1 - tx) * ty * f(i, j + 1) + tx * ty * f(i + 1, j + 1)
    s["tcond_sat"] = [interp("tc", x1[i], x2[i]) for i in range(n)]
    s["tevap_sat"] = [interp("te", x1[i], x2[i]) for i in range(n)]
    # surface conduction (inside face, positive = into surface) -> envelope gain into room
    cond = [0.0] * n
    for (k, nm), v in d.items():
        if nm == "Surface Inside Face Conduction Heat Transfer Rate":
            for i in range(n):
                cond[i] += v[i]   # EnergyPlus sign: positive = heat conducted from the surface into the zone
    s["envelope"] = cond

    integ = lambda arr: sum(x for x in arr if not math.isnan(x)) * dt_h / 1000.0  # kWh from W
    energy = {
        "compressor_and_condenser_fan_kwh": m["Cooling:Electricity"] and sum(m["Cooling:Electricity"]) / J,
        "unit_cooler_fans_kwh": sum(m["Fans:Electricity"]) / J,
        "mcycle_kwh": sum(m.get("ExteriorEquipment:Electricity", [0])) / J,
        "facility_kwh": sum(m["Electricity:Facility"]) / J,
    }
    energy["cost_inr"] = energy["facility_kwh"] * c["tariff_inr_per_kwh"]
    energy["mcycle_water_litre"] = sum(s["mcwater"]) * dt_h * 3600
    energy["coil_total_kwh_th"] = integ(s["qtot"])
    energy["coil_latent_kwh_th"] = integ(s["qlat"])
    energy["seasonal_cop_compressor_unit"] = energy["coil_total_kwh_th"] / energy["compressor_and_condenser_fan_kwh"]
    energy["condensate_litre"] = integ(s["qlat"]) * 3.6e6 / 2.47e6

    # loads into the room (kWh thermal) - independent of the coil
    loads = {
        "envelope_conduction": integ(s["envelope"]),
        "infiltration_sensible": (sum(s["inf_sen_gain"]) - sum(s["inf_sen_loss"])) / J,
        "infiltration_latent": (sum(s["inf_lat_gain"]) - sum(s["inf_lat_loss"])) / J,
        "product_sensible_incl_respiration_and_crates": integ(s["prod_sens"]),
        "product_transpiration_latent": integ(s["prod_lat"]),
        "unit_cooler_fan_heat": integ(s["pfan"]),
    }
    loads["respiration_part"] = integ(s["resp"])
    loads["crate_part"] = integ(s["crate"])
    sum_loads = sum(v for k, v in loads.items() if k not in ("respiration_part", "crate_part"))
    store = integ(s["hb_store"])
    checks = {}
    checks["coil_vs_loads_closure_pct"] = 100 * (energy["coil_total_kwh_th"] - sum_loads) / energy["coil_total_kwh_th"]
    hb_res = [s["hb_surf"][i] + s["hb_int"][i] + s["hb_oa"][i] + s["hb_sys"][i] + s["hb_sysair"][i] - s["hb_store"][i] for i in range(n)]
    checks["zone_air_heat_balance_residual_kwh"] = integ(hb_res)
    checks["zone_air_heat_balance_gross_kwh"] = integ([abs(x) for x in s["hb_sysair"]])
    checks["latent_closure_pct"] = 100 * (energy["coil_latent_kwh_th"] - loads["infiltration_latent"] - loads["product_transpiration_latent"]) / energy["coil_latent_kwh_th"]

    # per batch pull-down
    entry, target = c["product_entry_c"], c["product_target_c"]
    t78 = entry - 7 / 8 * (entry - target)
    starts = []
    for i in range(1, n):
        if s["batch"][i] > s["batch"][i - 1] + 0.5:
            starts.append(i)
    batches = []
    for b, i0 in enumerate(starts):
        i1 = starts[b + 1] if b + 1 < len(starts) else n
        def hrs(idx):
            return None if idx is None else round((idx - i0) * dt_h, 2)
        i_78 = first_index(s["tmean"], lambda v: v <= t78, i0 + 1, i1)
        i_c13 = first_index(s["tcore"], lambda v: v <= 13.0, i0 + 1, i1)
        i_c125 = first_index(s["tcore"], lambda v: v <= 12.5, i0 + 1, i1)
        i_m125 = first_index(s["tmean"], lambda v: v <= 12.5, i0 + 1, i1)
        w12 = range(i0, min(i1, i0 + int(12 / dt_h)))
        # product energy balance over the batch (kWh): heat out of fruit = field heat + respiration - stored at end
        q_out = (sum(s["prod_sens"][i] - s["crate"][i] for i in range(i0, i1)) + sum(s["prod_lat"][i] for i in range(i0, i1))) * dt_h / 1000
        resp = sum(s["resp"][i] for i in range(i0, i1)) * dt_h / 1000
        mcp = c["product_mass_kg"] * c["tomato_cp"] / 3.6e6
        stored_drop = mcp * (entry - s["tmean"][i1 - 1])
        mass_loss = s["wtloss"][i1 - 1]
        day = times[i0][1]
        batches.append({
            "batch": b + 1, "load_day": day, "load_time": f"May {day} {times[i0][2]:02d}:{times[i0][3]:02d}",
            "hold_hours": round((i1 - i0) * dt_h, 1),
            "outdoor_max_c_during_first_24h": round(max(s["tout"][i0:min(i1, i0 + int(24 / dt_h))]), 1),
            "h_to_7_8_cooling_mean": hrs(i_78), "h_core_to_13": hrs(i_c13), "h_core_to_12_5": hrs(i_c125), "h_mean_to_12_5": hrs(i_m125),
            "peak_coil_kw": round(max(s["qtot"][i] for i in w12) / 1000, 2),
            "peak_runtime_fraction": round(max(s["rtf"][i] for i in w12), 3),
            "capacity_at_peak_kw": round(max(s["capft"][i] for i in w12) * cfg["dx"]["rated"]["q"] / 1000, 2),
            "max_air_c": round(max(s["tair"][i] for i in w12), 2),
            "min_rh_pct": round(min(s["rh"][i] for i in w12), 1),
            "mean_rh_hold_pct": round(sum(s["rh"][i] for i in range(min(i1, i0 + int(24 / dt_h)), i1)) / max(1, i1 - min(i1, i0 + int(24 / dt_h))), 1),
            "weight_loss_kg": round(mass_loss, 1), "weight_loss_pct": round(100 * mass_loss / c["product_mass_kg"], 2),
            "energy_kwh": round(sum(s["pcoil"][i] + s["pfan"][i] + s["mc_w"][i] for i in range(i0, i1)) * dt_h / 1000, 1),
            "energy_first_24h_kwh": round(sum(s["pcoil"][i] + s["pfan"][i] + s["mc_w"][i] for i in range(i0, min(i1, i0 + int(24 / dt_h)))) * dt_h / 1000, 1),
            "product_balance": {"heat_out_kwh": round(q_out, 2), "respiration_kwh": round(resp, 2),
                                "field_heat_released_kwh": round(stored_drop, 2),
                                "closure_pct": round(100 * (q_out - (stored_drop + resp)) / (stored_drop + resp), 3)},
            "i0": i0, "i1": i1,
        })

    # downsampled series
    step = max(1, int(round(1 / dt_h)))  # hourly
    def hourly(arr):
        out = []
        for i in range(0, n, step):
            seg = [x for x in arr[i:i + step] if not math.isnan(x)]
            out.append(round(sum(seg) / len(seg), 3) if seg else None)
        return out
    month = {k: hourly(s[k]) for k in ["tout", "tdp", "tair", "rh", "tmean", "tcore", "rtf", "tcond_in"]}
    month["tcond_sat"] = hourly(s["tcond_sat"])
    month["p_total_kw"] = hourly([(s["pcoil"][i] + s["pfan"][i] + s["mc_w"][i]) / 1000 for i in range(n)])
    month["q_coil_kw"] = hourly([x / 1000 for x in s["qtot"]])
    month["cap_avail_kw"] = hourly([x * cfg["dx"]["rated"]["q"] / 1000 for x in s["capft"]])
    win = []
    w_step = 3  # 6 minutes
    for bt in batches:
        i0 = bt["i0"]
        i1 = min(bt["i1"], i0 + int(36 / dt_h))
        idx = list(range(i0 - int(1 / dt_h), i1, w_step))
        pick = lambda arr, f=1.0: [round(arr[i] * f, 3) for i in idx]
        win.append({
            "t_h": [round((i - i0) * dt_h, 3) for i in idx],
            "tmean": pick(s["tmean"]), "tcore": pick(s["tcore"]), "tsurf": pick(s["tsurf"]), "tair": pick(s["tair"]),
            "rh": pick(s["rh"]), "tout": pick(s["tout"]), "tcond_in": pick(s["tcond_in"]),
            "q_coil_kw": pick(s["qtot"], 1e-3), "q_prod_kw": pick([s["prod_sens"][i] + s["prod_lat"][i] for i in range(n)], 1e-3),
            "cap_avail_kw": pick([x * cfg["dx"]["rated"]["q"] for x in s["capft"]], 1e-3),
            "p_kw": pick([s["pcoil"][i] + s["pfan"][i] + s["mc_w"][i] for i in range(n)], 1e-3), "rtf": pick(s["rtf"]),
        })
    for bt in batches:
        bt.pop("i0"); bt.pop("i1")
    hold = [i for i in range(n) if s["present"][i] > 0.5]
    run_h = sum(s["rtf"]) * dt_h
    summary_extra = {
        "compressor_run_hours": round(run_h, 1),
        "run_hours_condensing_above_map_48_9C": round(sum(s["rtf"][i] for i in range(n) if s["tcond_sat"][i] > 48.9) * dt_h, 1),
        "max_condensing_c": round(max(s["tcond_sat"][i] for i in range(n) if s["rtf"][i] > 0.01), 1),
        "run_hours_suction_capped_4_4C": round(sum(s["rtf"][i] for i in range(n) if s["tevap_sat"][i] >= 4.399) * dt_h, 1),
    }
    summary = {**summary_extra,
        "air_temp_mean": round(sum(s["tair"][i] for i in hold) / len(hold), 2),
        "air_temp_max": round(max(s["tair"]), 2), "air_temp_min": round(min(s["tair"]), 2),
        "rh_mean_loaded": round(sum(s["rh"][i] for i in hold) / len(hold), 1),
        "hours_rh_below_85": round(sum(1 for i in hold if s["rh"][i] < 85) * dt_h, 1),
        "max_rtf": round(max(s["rtf"]), 3), "mean_rtf": round(sum(s["rtf"]) / n, 3),
        "hours_rtf_100": round(sum(1 for x in s["rtf"] if x > 0.999) * dt_h, 2),
        "cond_inlet_mean_when_hot": round(sum(s["tcond_in"][i] for i in range(n) if s["tout"][i] > 38) / max(1, sum(1 for i in range(n) if s["tout"][i] > 38)), 2),
        "tout_mean_when_hot": round(sum(s["tout"][i] for i in range(n) if s["tout"][i] > 38) / max(1, sum(1 for i in range(n) if s["tout"][i] > 38)), 2),
    }
    return {
        "variant": variant, "mcycle": cfg["mcycle"], "config": c, "sphere": cfg["sphere"],
        "energy": {k: round(v, 2) for k, v in energy.items()}, "loads_kwh_th": {k: round(v, 2) for k, v in loads.items()},
        "checks": {k: round(v, 4) for k, v in checks.items()}, "summary": summary, "batches": batches,
        "month_hourly": month, "pulldown_windows": win, "errfile": err_summary(d_run / "eplusout.err"),
        "dx": cfg["dx"], "air_storage_kwh": round(store, 3),
    }


def hand_checks(r):
    c = r["config"]
    L, W, H = c["room_length_m"], c["room_width_m"], c["room_height_m"]
    A_walls_roof = L * W + 2 * H * (L + W)
    R_panel = 2 * c["ppgi_thickness_m"] / 45 + c["puf_thickness_m"] / c["puf_conductivity"]
    R_si, R_so = 0.12, 0.04
    U_panel = 1 / (R_si + R_panel + R_so)
    U_floor = 1 / (R_si + c["puf_thickness_m"] / c["puf_conductivity"] + c["floor_screed_m"] / 1.4)
    field = c["product_mass_kg"] * c["tomato_cp"] * (c["product_entry_c"] - c["product_target_c"]) / 3.6e6
    return {
        "U_panel_W_m2K": round(U_panel, 4), "U_floor_W_m2K": round(U_floor, 4),
        "UA_total_W_K": round(U_panel * A_walls_roof + U_floor * L * W, 2),
        "floor_area_sqft": round(L * W / 0.3048 ** 2, 1), "volume_m3": round(L * W * H, 2),
        "field_heat_per_batch_kwh": round(field, 2),
        "min_pulldown_h_at_13kW": round(field / 13.0, 2),
        "respiration_w_at_12C": round(10.7 * c["resp_f"] / 3600 * (1.8 * 12 + 32) ** c["resp_g"] * c["product_mass_kg"], 1),
        "respiration_w_at_28C": round(10.7 * c["resp_f"] / 3600 * (1.8 * 28 + 32) ** c["resp_g"] * c["product_mass_kg"], 1),
        "biot_number": round(c["h_eff"] * c["tomato_diameter_m"] / 2 / c["tomato_k"], 3),
    }


def main():
    variants = sorted(p.name for p in RUNS.iterdir() if (p / "eplusout.sql").exists())
    res = {v: analyse(v) for v in variants}
    epw = HERE / "weather" / "IND_Patna.424920_ISHRAE.epw"
    import csv
    rows = [r for r in csv.reader(epw.open())][8:]
    may = [r for r in rows if r[1] == "5"]
    daily = []
    for day in range(1, 32):
        dd = [r for r in may if int(r[2]) == day]
        daily.append({"day": day, "tmax": max(float(r[6]) for r in dd), "tmin": min(float(r[6]) for r in dd),
                      "tdp_mean": round(sum(float(r[7]) for r in dd) / 24, 1), "rh_mean": round(sum(float(r[8]) for r in dd) / 24, 1)})
    base = res["base"]
    out = {
        "generated_by": "studies/patna-tomato-pulldown/postprocess.py",
        "energyplus_version": (RUNS / "base" / "eplusout.err").read_text(errors="replace").splitlines()[0].strip(),
        "weather": {"file": epw.name, "md5": hashlib.md5(epw.read_bytes()).hexdigest(),
                    "source": "https://energyplus-weather.s3.amazonaws.com/asia_wmo_region_2/IND/IND_Patna.424920_ISHRAE/",
                    "header": rows and open(epw).readline().strip(), "may_daily": daily},
        "hand_checks": hand_checks(base),
        "variants": res,
    }
    main_v = {"base", "mcycle", "base_fancycle", "mcycle_fancycle", "base_ec", "mcycle_ec"}
    for v, r in res.items():
        if v not in main_v:
            r.pop("month_hourly"); r.pop("pulldown_windows")
        r.pop("sphere", None)
        dx = r.pop("dx")
    out["dx"] = {"rated": dx["rated"], "rated_shr": dx["rated_shr"], "rated_cop": dx["rated_cop"], "unit": dx["unit"],
                 "twb_grid": dx["twb_grid"], "tc_grid": dx["tc_grid"],
                 "rows": [{k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()} for row in dx["table_rows"]]}
    dest = HERE / "dashboard"
    dest.mkdir(exist_ok=True)
    (dest / "data.json").write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", dest / "data.json", round((dest / "data.json").stat().st_size / 1024), "KB")
    for v, r in res.items():
        b = r["batches"]
        print(f"{v:14s} kWh {r['energy']['facility_kwh']:7.1f} comp {r['energy']['compressor_and_condenser_fan_kwh']:6.1f} fan {r['energy']['unit_cooler_fans_kwh']:6.1f} mc {r['energy']['mcycle_kwh']:5.1f} "
              f"| 7/8 h {[x['h_to_7_8_cooling_mean'] for x in b]} core13 {[x['h_core_to_13'] for x in b]} | peakRTF {[x['peak_runtime_fraction'] for x in b]} "
              f"| closure {r['checks']['coil_vs_loads_closure_pct']:.2f}% HBres {r['checks']['zone_air_heat_balance_residual_kwh']:.2f} prodbal {[x['product_balance']['closure_pct'] for x in b]}")
    print(json.dumps(base["loads_kwh_th"], indent=1), json.dumps(base["energy"], indent=1), json.dumps(out["hand_checks"], indent=1), json.dumps(base["summary"], indent=1))
    print(json.dumps(base["batches"][3], indent=1))


if __name__ == "__main__":
    main()
