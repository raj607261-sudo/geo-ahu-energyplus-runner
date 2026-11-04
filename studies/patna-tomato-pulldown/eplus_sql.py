"""Minimal reader for EnergyPlus SQLite output.

series(path) -> (times, data) where times is the list of zone-timestep stamps
(month, day, hour, minute) of the RunPeriod (warm-up excluded) and data maps
(KeyValue, VariableName) -> list of floats aligned with times.
Hourly meters are returned separately by meters(path).
"""
import sqlite3


def _env(cur):
    return cur.execute("select EnvironmentPeriodIndex from EnvironmentPeriods where EnvironmentType=3").fetchone()[0]


def series(sql_path):
    con = sqlite3.connect(sql_path)
    cur = con.cursor()
    env = _env(cur)
    times = cur.execute("select TimeIndex, Month, Day, Hour, Minute from Time where EnvironmentPeriodIndex=? and WarmupFlag=0 "
                        "and IntervalType=-1 order by TimeIndex", (env,)).fetchall()
    pos = {t[0]: i for i, t in enumerate(times)}
    dic = {r[0]: (r[1], r[2]) for r in cur.execute(
        "select ReportDataDictionaryIndex, KeyValue, Name from ReportDataDictionary where ReportingFrequency='Zone Timestep'")}
    data = {k: [float("nan")] * len(times) for k in dic.values()}
    for di, ti, v in cur.execute("select ReportDataDictionaryIndex, TimeIndex, Value from ReportData"):
        if di in dic and ti in pos:
            data[dic[di]][pos[ti]] = v
    con.close()
    return [t[1:] for t in times], data


def meters(sql_path):
    con = sqlite3.connect(sql_path)
    cur = con.cursor()
    env = _env(cur)
    times = cur.execute("select TimeIndex, Month, Day, Hour from Time where EnvironmentPeriodIndex=? and WarmupFlag=0 "
                        "and IntervalType=1 order by TimeIndex", (env,)).fetchall()
    pos = {t[0]: i for i, t in enumerate(times)}
    dic = {r[0]: r[1] for r in cur.execute(
        "select ReportDataDictionaryIndex, Name from ReportDataDictionary where ReportingFrequency='Hourly'")}
    data = {k: [0.0] * len(times) for k in dic.values()}
    for di, ti, v in cur.execute("select ReportDataDictionaryIndex, TimeIndex, Value from ReportData"):
        if di in dic and ti in pos:
            data[dic[di]][pos[ti]] = v
    con.close()
    return [t[1:] for t in times], data
