"""KissanShroom screening model. Refrigerant states use CoolProp."""
import math
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from CoolProp.CoolProp import PropsSI

app = FastAPI(title="KissanShroom Python/CoolProp API")
app.add_middleware(CORSMiddleware, allow_origins=["https://kissanshroom-poc.raj607261.chatgpt.site"], allow_methods=["POST", "OPTIONS"], allow_headers=["*"])

class Conditions(BaseModel):
    area: float = Field(300, ge=50, le=2000)
    height: float = Field(10, ge=7, le=25)
    puf: float = Field(80, ge=40, le=200)
    stored: float = Field(10, ge=0, le=50)
    incoming: float = Field(2.5, ge=0, le=20)
    arrival: float = Field(30, ge=8, le=50)
    room: float = Field(8, ge=0, le=20)
    ach: float = Field(.3, ge=0, le=4)
    dbt: float = Field(40, ge=5, le=50)
    wbt: float = Field(27, ge=0, le=40)
    eff: float = Field(65, ge=20, le=90)
    hours: float = Field(20, ge=8, le=24)
    aux: float = Field(.55, ge=0, le=5)
    tariff: float = Field(8, ge=0, le=30)

def sat_pressure(t):
    return .61094 * math.exp(17.625*t/(t+243.04))

def ratio(t, rh):
    e = min(sat_pressure(t)*rh, 100)
    return .62198*e/(101.325-e)

def enthalpy(t, w):
    return 1.006*t+w*(2501+1.86*t)

def cycle(evap, cond):
    fluid = "R134a"
    pe = PropsSI("P", "T", evap+273.15, "Q", 1, fluid)
    pc = PropsSI("P", "T", cond+273.15, "Q", 0, fluid)
    h1 = PropsSI("Hmass", "P", pe, "T", evap+273.15+5, fluid)
    s1 = PropsSI("Smass", "P", pe, "T", evap+273.15+5, fluid)
    h2s = PropsSI("Hmass", "P", pc, "Smass", s1, fluid)
    h3 = PropsSI("Hmass", "P", pc, "T", cond+273.15-3, fluid)
    qe = h1-h3
    work = (h2s-h1)/(.68*.90)
    if qe <= 0 or work <= 0:
        raise ValueError("Refrigerant state outside model range")
    return {"cop":qe/work, "pressure":pc/1e5}

@app.post("/api/calculate")
def calculate(c: Conditions):
    if c.wbt > c.dbt or c.arrival < c.room:
        raise HTTPException(422, "Wet bulb must be <= dry bulb; arrival must be >= room target")
    floor=c.area*.092903
    h=c.height*.3048
    side=4*math.sqrt(floor)*h
    u=1/(.12+(c.puf/1000)/.024+.06)
    wall_roof=u*(side+floor)*max(0,c.dbt-c.room)/1000
    ground=.7*floor*max(0,28-c.room)/1000
    e_out=min(sat_pressure(c.dbt),max(0,sat_pressure(c.wbt)-.066*(c.dbt-c.wbt)))
    w_out=.62198*e_out/(101.325-e_out)
    infiltration=floor*h*c.ach*1.2/3600*max(0,enthalpy(c.dbt,w_out)-enthalpy(c.room,ratio(c.room,.85)))
    product=c.incoming*1000*3.7*(c.arrival-c.room)/86400
    respiration=c.stored*1000*.025/1000
    load=wall_roof+ground+infiltration+product+respiration
    design=load*24/c.hours
    evap=c.room-7
    air_cond=c.dbt+9
    sink=c.wbt+2+(c.dbt-c.wbt)*(1-c.eff/100)*.35
    mc_cond=sink+6
    try:
        base=cycle(evap,air_cond)
        mc=cycle(evap,mc_cond)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    base_comp=design/base["cop"]
    mc_comp=design/mc["cop"]
    base_energy=(base_comp+.35)*c.hours
    # The BPHE water loop replaces the conventional air condenser and its fan.
    # c.aux is the total M-Cycle condenser-side pump and blower allowance.
    mc_energy=(mc_comp+c.aux)*c.hours
    result={"load":load,"product":product,"wallRoof":wall_roof,"ground":ground,"infiltration":infiltration,"respiration":respiration,"sink":sink,"airCond":air_cond,"mcCond":mc_cond,"baseComp":base_comp,"mcComp":mc_comp,"baseEnergy":base_energy,"mcEnergy":mc_energy,"baseCop":base["cop"],"mcCop":mc["cop"],"basePressure":base["pressure"],"mcPressure":mc["pressure"],"saving":(base_energy-mc_energy)/base_energy*100,"engine":"Python + CoolProp 7.2.0"}
    return result
