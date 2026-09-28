"""Scheduled, bounded engineering search. Estimates are screening only."""
import json
import math
import os
import random
from pathlib import Path
from datetime import datetime, timezone

TARGET_W = 5275  # 1.5 refrigeration tons, thermal
RHO = 1.16
CP = 1006
ASSUMED_EFFECTIVENESS = 0.75  # fixed hypothesis until bench calibration

CLIMATES = {
    "dry": (40.0, 22.0, 20.0),
    "humid": (35.0, 28.0, 26.0),
}


def evaluate(gap_mm, length_m, area_m2, flow_m3s, work_fraction, effectiveness):
    if not (2 <= gap_mm <= 12 and 0.3 <= length_m <= 2 and 1 <= area_m2 <= 50
            and 0.1 <= flow_m3s <= 1.5 and 0.2 <= work_fraction <= 0.6
            and 0.3 <= effectiveness <= 0.95):
        raise ValueError("Candidate outside screening bounds")
    product_flow = flow_m3s * (1 - work_fraction)
    # Face area is a surrogate for total parallel dry-channel cross-section.
    free_area = area_m2 * gap_mm / 1000 / length_m
    velocity = flow_m3s / free_area
    # Laminar plate friction plus an explicit entrance/turning loss allowance.
    dp = 12 * 1.8e-5 * length_m * velocity / (gap_mm / 1000) ** 2 + 3 * RHO * velocity ** 2 / 2
    fan_w = flow_m3s * dp / 0.35
    pump_w = 35.0
    results = {}
    for label, (dry_bulb, wet_bulb, dew_point) in CLIMATES.items():
        # Empirical effectiveness is an INPUT to verify with real test data.
        supply = dry_bulb - effectiveness * (dry_bulb - dew_point)
        capacity = RHO * CP * product_flow * (dry_bulb - supply)
        results[label] = {"supply_c": round(supply, 2), "capacity_w": round(capacity),
                          "dew_point_c": dew_point, "wet_bulb_c": wet_bulb}
    reasons = []
    if dp > 100: reasons.append("estimated core pressure drop >100 Pa")
    if fan_w + pump_w > 450: reasons.append("estimated electric input >450 W")
    if results["dry"]["capacity_w"] < TARGET_W: reasons.append("dry climate capacity <1.5 TR")
    if results["humid"]["capacity_w"] < TARGET_W: reasons.append("humid climate capacity <1.5 TR")
    for label, (_, _, dew_point) in CLIMATES.items():
        if results[label]["supply_c"] < dew_point:
            reasons.append(label + " dew-point bound violated")
    return {"geometry": {"gap_mm": gap_mm, "length_m": length_m, "area_m2": area_m2,
                         "flow_m3s": flow_m3s, "working_fraction": work_fraction,
                         "assumed_dp_effectiveness": effectiveness},
            "velocity_mps": round(velocity, 2), "core_dp_pa": round(dp, 1),
            "fan_w": round(fan_w), "pump_w": pump_w,
            "climates": results, "screening_pass": not reasons, "reasons": reasons,
            "status": "UNVALIDATED AIR-STREAM ESTIMATE; not room cooling capacity",
            "unverified_gates": ["room temperature/RH", "working-air exhaust outside",
                                 "water use", "wetting/leakage", "BOM", "measured effectiveness"]}


def candidates(seed, count=120):
    rng = random.Random(seed)
    for _ in range(count):
        yield evaluate(round(rng.uniform(3, 9), 2), round(rng.uniform(.5, 1.4), 2),
                       round(rng.uniform(6, 28), 2), round(rng.uniform(.35, 1.1), 3),
                       round(rng.uniform(.25, .45), 2), ASSUMED_EFFECTIVENESS)


def evolve(parent, seed, count=60):
    """Explore near the previous best, while retaining broad search diversity."""
    rng = random.Random(seed + 773)
    g = parent["geometry"]
    bounds = [("gap_mm", 2, 12), ("length_m", .3, 2), ("area_m2", 1, 50),
              ("flow_m3s", .1, 1.5), ("working_fraction", .2, .6)]
    for _ in range(count):
        v = [max(lo, min(hi, g[k] * rng.uniform(.8, 1.2))) for k, lo, hi in bounds]
        yield evaluate(*v, ASSUMED_EFFECTIVENESS)


def score(item):
    c = item["climates"]
    return (min(c["dry"]["capacity_w"], TARGET_W) / TARGET_W
            + min(c["humid"]["capacity_w"], TARGET_W) / TARGET_W
            - (item["fan_w"] + item["pump_w"]) / 450
            - max(0, item["core_dp_pa"] - 100) / 100
            - 0.15 * item["geometry"]["area_m2"] / 28)


def run():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return run_file_memory()
    import psycopg
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS runs (
                id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                best JSONB NOT NULL, screening_pass BOOLEAN NOT NULL, note TEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS candidates (
                run_id BIGINT REFERENCES runs(id), rank INTEGER NOT NULL,
                design JSONB NOT NULL, score DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (run_id, rank))""")
            cur.execute("SELECT pg_try_advisory_xact_lock(88442211)")
            if not cur.fetchone()[0]:
                print("Another run is active; exiting")
                return
            cur.execute("SELECT coalesce(max(id), 0) FROM runs")
            generation = cur.fetchone()[0] + 1
            pool = list(candidates(generation))
            cur.execute("SELECT best FROM runs ORDER BY id DESC LIMIT 1")
            previous = cur.fetchone()
            if previous:
                pool.extend(evolve(previous[0], generation))
            valid = [c for c in pool if c["screening_pass"]]
            best = max(valid or pool, key=score)
            note = ("Screening pass only; validate pressure drop, flow, humidity, capacity, "
                    "water use, wetting and BOM experimentally. Humid climate alone cannot "
                    "guarantee AC-like comfort or dehumidification.")
            cur.execute("INSERT INTO runs(best, screening_pass, note) VALUES (%s, %s, %s) RETURNING id",
                        (json.dumps(best), bool(valid), note))
            run_id = cur.fetchone()[0]
            for rank, item in enumerate(sorted(pool, key=score, reverse=True), 1):
                cur.execute("INSERT INTO candidates(run_id, rank, design, score) VALUES (%s, %s, %s, %s)",
                            (run_id, rank, json.dumps(item), score(item)))
            print(json.dumps({"generation": generation, "candidates": len(pool),
                              "best": best, "note": note}, indent=2))


def run_file_memory():
    """Durable Git-backed fallback; workflow commits state after each run."""
    path = Path(os.environ.get("STATE_PATH", "state/memory.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    memory = json.loads(path.read_text()) if path.exists() else {"runs": []}
    generation = len(memory["runs"]) + 1
    pool = list(candidates(generation))
    if memory["runs"]:
        pool.extend(evolve(memory["runs"][-1]["best"], generation))
    valid = [c for c in pool if c["screening_pass"]]
    best = max(valid or pool, key=score)
    run_record = {"generation": generation, "created_at": datetime.now(timezone.utc).isoformat(),
                  "best": best, "candidate_count": len(pool), "screening_pass": bool(valid),
                  "failure_summary": {reason: sum(reason in c["reasons"] for c in pool)
                                      for reason in sorted({r for c in pool for r in c["reasons"]})},
                  "note": "Unvalidated screening; physical measurements required."}
    run_record["next_problem"] = max(run_record["failure_summary"],
                                     key=run_record["failure_summary"].get,
                                     default="measure real HMX effectiveness")
    if not memory.get("research_leads") or generation % 28 == 0:
        try:
            from engine.research import scout
            memory["research_leads"] = scout()
            memory["research_error"] = None
        except Exception as exc:
            memory["research_error"] = type(exc).__name__
    memory["runs"].append(run_record)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(memory, indent=2) + "\n")
    temp.replace(path)
    print(json.dumps(run_record, indent=2))


if __name__ == "__main__":
    run()
