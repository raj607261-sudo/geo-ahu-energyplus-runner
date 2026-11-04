#!/usr/bin/env python3
"""Turn the manufacturer compressor map into EnergyPlus DX-coil performance curves.

Why: EnergyPlus' Refrigeration:AirChiller (warehouse coil) put a large latent load on the
compressor without removing any water from the room in this application (RH pinned at 100 %),
so the condensing unit is modelled with Coil:Cooling:DX:SingleSpeed instead - the DX model
that is tested in ANSI/ASHRAE Standard 140 (CE100/CE200 cases).

The DX coil needs capacity/EIR as functions of (entering wet bulb, condenser air inlet dry
bulb). We get those from a steady-state balance of three physical components:

  compressor   Q = Qmap(Te, Tc),  P = Pmap(Te, Tc)
               Copeland ZS45K4E-TF5, R-404A, 50 Hz AHRI-540 bicubic map (EnergyPlus DataSets)
  condenser    Q + P = UA_c (Tc - Tair_in)          (THR per K of approach, fan fixed)
  evaporator   Q = m_air * eps * (h_in - h_sat(Te))  (wet-coil enthalpy effectiveness)
  suction cap  Te <= 4.4 C  (top of the manufacturer map = MOP / crankcase pressure regulator;
               a medium-temp unit cannot run at higher suction without overloading the motor)

The fit residuals against the balance are written next to the curves so they can be shown.
"""
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
P_ATM = 101325.0


def psat(t):
    # ASHRAE (Hyland-Wexler) over water, Pa
    T = t + 273.15
    c = (-5.8002206e3, 1.3914993, -4.8640239e-2, 4.1764768e-5, -1.4452093e-8, 6.5459673)
    return math.exp(c[0] / T + c[1] + c[2] * T + c[3] * T * T + c[4] * T ** 3 + c[5] * math.log(T))


def w_sat(t, p=P_ATM):
    ps = psat(t)
    return 0.621945 * ps / (p - ps)


def h_air(t, w):
    return 1006 * t + w * (2501000 + 1860 * t)


def h_sat(t):
    return h_air(t, w_sat(t))


def w_from_twb(tdb, twb, p=P_ATM):
    ws = w_sat(twb, p)
    return ((2501 - 2.326 * twb) * ws - 1.006 * (tdb - twb)) / (2501 + 1.86 * tdb - 4.186 * twb)


def load_map():
    src = (HERE / "compressor_curves.idf").read_text()
    curves = {}
    for m in re.finditer(r"Curve:Bicubic,(.*?);", src, re.S):
        f = [x.strip() for x in re.sub(r"!.*", "", m.group(1)).replace("\n", " ").split(",")]
        curves[f[0]] = [float(x) for x in f[1:11]]
    q = next(v for k, v in curves.items() if k.endswith("qcurv"))
    p = next(v for k, v in curves.items() if k.endswith("pwrcurv"))
    return q, p


def bicubic(a, x, y):
    return (a[0] + a[1] * x + a[2] * x * x + a[3] * y + a[4] * y * y + a[5] * x * y
            + a[6] * x ** 3 + a[7] * y ** 3 + a[8] * x * x * y + a[9] * x * y * y)


class Unit:
    def __init__(self, cfg):
        self.qa, self.pa = load_map()
        self.ua_c = cfg["condenser_ua_w_per_k"]
        self.fan_c = cfg["condenser_fan_w"]
        self.m_air = 1.2 * cfg["unit_cooler_airflow_m3s"]
        self.eps = cfg["evap_enthalpy_effectiveness"]
        self.te_max = 4.4

    def comp(self, te, tc):
        return bicubic(self.qa, te, tc), bicubic(self.pa, te, tc)

    def tc_for(self, te, tair):
        lo, hi = tair, tair + 60
        for _ in range(60):
            tc = (lo + hi) / 2
            q, p = self.comp(te, tc)
            if q + p > self.ua_c * (tc - tair):
                lo = tc
            else:
                hi = tc
        return (lo + hi) / 2

    def solve(self, twb_in, tair_c):
        h_in = h_sat(twb_in)
        lo, hi = -17.8, twb_in - 0.05
        for _ in range(60):
            te = (lo + hi) / 2
            tc = self.tc_for(te, tair_c)
            q, _ = self.comp(te, tc)
            q_evap = self.m_air * self.eps * (h_in - h_sat(te))
            if q > q_evap:   # compressor pulls more than coil supplies -> lower Te
                hi = te
            else:
                lo = te
        te = (lo + hi) / 2
        capped = te > self.te_max
        if capped:
            te = self.te_max
        tc = self.tc_for(te, tair_c)
        q, p = self.comp(te, tc)
        return dict(twb=twb_in, tcin=tair_c, te=te, tc=tc, q=q, p=p, pt=p + self.fan_c, capped=capped)


def fit_biquadratic(rows, key):
    # least squares for z = a + b x + c x^2 + d y + e y^2 + f x y  (x = Twb, y = Tcond_in)
    import itertools
    X = [[1, r["twb"], r["twb"] ** 2, r["tcin"], r["tcin"] ** 2, r["twb"] * r["tcin"]] for r in rows]
    z = [r[key] for r in rows]
    n = 6
    A = [[sum(X[k][i] * X[k][j] for k in range(len(X))) for j in range(n)] for i in range(n)]
    b = [sum(X[k][i] * z[k] for k in range(len(X))) for i in range(n)]
    # Gaussian elimination
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(A[r][i]))
        A[i], A[piv] = A[piv], A[i]
        b[i], b[piv] = b[piv], b[i]
        for r in range(i + 1, n):
            f = A[r][i] / A[i][i]
            for cidx in range(i, n):
                A[r][cidx] -= f * A[i][cidx]
            b[r] -= f * b[i]
    coef = [0] * n
    for i in reversed(range(n)):
        coef[i] = (b[i] - sum(A[i][j] * coef[j] for j in range(i + 1, n))) / A[i][i]
    return coef


def biq(c, x, y):
    return c[0] + c[1] * x + c[2] * x * x + c[3] * y + c[4] * y * y + c[5] * x * y


def make_curves(cfg):
    u = Unit(cfg)
    rated = u.solve(19.44, 35.0)
    grid = [u.solve(twb, tc) for twb in [6, 8, 10, 12, 14, 16, 18, 20, 22, 24] for tc in [15, 20, 25, 30, 35, 38, 41, 44, 47, 50]]
    for r in grid:
        r["capr"] = r["q"] / rated["q"]
        r["eirr"] = (r["pt"] / r["q"]) / (rated["pt"] / rated["q"])
    cap = fit_biquadratic(grid, "capr")
    eir = fit_biquadratic(grid, "eirr")
    err_q = max(abs(biq(cap, r["twb"], r["tcin"]) * rated["q"] - r["q"]) / r["q"] for r in grid)
    err_p = max(abs(biq(cap, r["twb"], r["tcin"]) * biq(eir, r["twb"], r["tcin"]) * rated["pt"] - r["pt"]) / r["pt"] for r in grid)
    # rated sensible heat ratio from the same coil (bypass factor = 1 - eps)
    tdb, twb = 26.67, 19.44
    w_in = w_from_twb(tdb, twb)
    h_in = h_air(tdb, w_in)
    h_out = h_in - rated["q"] / u.m_air
    h_adp = h_in - (h_in - h_out) / u.eps
    lo, hi = -10, 30
    for _ in range(60):
        t = (lo + hi) / 2
        if h_sat(t) > h_adp:
            hi = t
        else:
            lo = t
    t_adp = (lo + hi) / 2
    bf = 1 - u.eps
    t_out = t_adp + bf * (tdb - t_adp)
    shr = min(1.0, u.m_air * (1006 + 1860 * w_in) * (tdb - t_out) / rated["q"])
    return dict(rated=rated, cap=cap, eir=eir, grid=grid, max_cap_fit_err=err_q, max_power_fit_err=err_p,
                rated_shr=shr, rated_cop=rated["q"] / rated["pt"], unit=dict(ua_c=u.ua_c, fan_c=u.fan_c, m_air=u.m_air, eps=u.eps))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE))
    from build_idf import CONFIG
    res = make_curves(CONFIG)
    print(json.dumps({k: v for k, v in res.items() if k != "grid"}, indent=1))
    u = Unit(CONFIG)
    for twb in (9, 10.5, 12, 16, 20):
        for tc in (25, 30, 35, 40, 43):
            r = u.solve(twb, tc)
            print(f"Twb {twb:5.1f} Tair_cond {tc:4.0f}: Te {r['te']:5.2f} Tc {r['tc']:5.1f} Q {r['q']/1000:6.2f} kW  P {r['pt']/1000:5.2f} kW  COP {r['q']/r['pt']:4.2f} {'MOP-capped' if r['capped'] else ''}")
