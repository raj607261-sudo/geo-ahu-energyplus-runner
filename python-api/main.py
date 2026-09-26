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
    cropCp: float = Field(3.7, ge=1, le=4.5)
    pullHours: float = Field(12, ge=2, le=24)
    room: float = Field(8, ge=0, le=20)
    ach: float = Field(.3, ge=0, le=4)
    dbt: float = Field(40, ge=5, le=50)
    wbt: float = Field(27, ge=0, le=40)
    subwb: float = Field(3.5, ge=0, le=6)
    blower: float = Field(.40, ge=0, le=2)
    mainPump: float = Field(.25, ge=0, le=2)
    wettingPump: float = Field(.07, ge=0, le=1)
    waterFlow: float = Field(60, ge=5, le=200)
    bpheApproach: float = Field(4, ge=1, le=12)
    mapHotCond: float = Field(49, ge=30, le=65)
    mapHotCapacity: float = Field(7, ge=.5, le=30)
    mapHotPower: float = Field(3.3, ge=.1, le=20)
    mapLowCond: float = Field(30, ge=20, le=50)
    mapLowCapacity: float = Field(9.1, ge=.5, le=30)
    mapLowPower: float = Field(2.15, ge=.1, le=20)
    tariff: float = Field(8, ge=0, le=30)

def sat_pressure(t):
    return .61094 * math.exp(17.625*t/(t+243.04))

def ratio(t, rh):
    e = min(sat_pressure(t)*rh, 100)
    return .62198*e/(101.325-e)

def enthalpy(t, w):
    return 1.006*t+w*(2501+1.86*t)

def cycle(evap, cond):
    fluid = "R410A"
    pe = PropsSI("P", "T", evap+273.15, "Q", 1, fluid)
    pc = PropsSI("P", "T", cond+273.15, "Q", 0, fluid)
    h1 = PropsSI("Hmass", "P", pe, "T", evap+273.15+5, fluid)
    s1 = PropsSI("Smass", "P", pe, "T", evap+273.15+5, fluid)
    rho = PropsSI("Dmass", "P", pe, "T", evap+273.15+5, fluid)
    h2s = PropsSI("Hmass", "P", pc, "Smass", s1, fluid)
    h3 = PropsSI("Hmass", "P", pc, "T", cond+273.15-3, fluid)
    qe = h1-h3
    work = (h2s-h1)/(.68*.90)
    if qe <= 0 or work <= 0:
        raise ValueError("Refrigerant state outside model range")
    return {"cop":qe/work, "pressure":pc/1e5, "qe":qe, "work":work, "rho":rho}

def compressor_map(c, evap, cond):
    # The two user-supplied operating points describe ONE compressor at
    # 1 C evaporating temperature. CoolProp corrects suction density,
    # refrigeration effect and specific work if the room target changes.
    blend=(cond-c.mapLowCond)/(c.mapHotCond-c.mapLowCond)
    cap=c.mapLowCapacity+(c.mapHotCapacity-c.mapLowCapacity)*blend
    power=c.mapLowPower+(c.mapHotPower-c.mapLowPower)*blend
    actual=cycle(evap,cond)
    reference=cycle(1,cond)
    mass_ratio=actual["rho"]/reference["rho"]
    cap*=mass_ratio*actual["qe"]/reference["qe"]
    power*=mass_ratio*actual["work"]/reference["work"]
    if cap<=0 or power<=0:
        raise ValueError("Compressor map extrapolation is outside its range")
    return {"capacity":cap,"power":power,"cop":cap/power,"pressure":actual["pressure"]}

@app.post("/api/calculate")
def calculate(c: Conditions):
    if c.wbt > c.dbt or c.arrival < c.room or c.mapHotCond<=c.mapLowCond:
        raise HTTPException(422, "Wet bulb <= dry bulb, arrival >= room target, and hot map temperature > low map temperature")
    floor=c.area*.092903
    h=c.height*.3048
    side=4*math.sqrt(floor)*h
    u=1/(.12+(c.puf/1000)/.024+.06)
    wall_roof=u*(side+floor)*max(0,c.dbt-c.room)/1000
    ground=.7*floor*max(0,28-c.room)/1000
    e_out=min(sat_pressure(c.dbt),max(0,sat_pressure(c.wbt)-.066*(c.dbt-c.wbt)))
    w_out=.62198*e_out/(101.325-e_out)
    infiltration=floor*h*c.ach*1.2/3600*max(0,enthalpy(c.dbt,w_out)-enthalpy(c.room,ratio(c.room,.85)))
    crop_energy=c.incoming*1000*c.cropCp*(c.arrival-c.room)/3600
    product=crop_energy/24
    respiration=c.stored*1000*.025/1000
    standing=wall_roof+ground+infiltration+respiration
    crop_peak=crop_energy/c.pullHours
    peak_load=standing+crop_peak
    # Compare the same crop batch over the same pull-down window.
    event_thermal=crop_energy+standing*c.pullHours
    design=peak_load
    evap=c.room-7
    air_cond=c.dbt+9
    # A user-specified sub-wet-bulb WATER outlet is a design scenario, not
    # a prediction of M-Cycle tower capacity. Keep it above estimated dew point.
    log_vapor=math.log(max(e_out,.001)/.61094)
    dewpoint=243.04*log_vapor/(17.625-log_vapor)
    sink=max(c.wbt-c.subwb,dewpoint+1)
    try:
        base=compressor_map(c,evap,air_cond)
        # Condenser rejects evaporator heat plus compressor shaft work. The
        # loop warms across the BPHE; condensing must exceed HOT water outlet.
        mc_cond=sink+6
        for _ in range(20):
            mc=compressor_map(c,evap,mc_cond)
            reject=mc["capacity"]+mc["power"]*.90
            water_rise=reject*60/(c.waterFlow*4.186)
            updated=sink+water_rise+c.bpheApproach
            if abs(updated-mc_cond)<.00001:
                mc_cond=updated
                break
            mc_cond=updated
        mc=compressor_map(c,evap,mc_cond)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    base_comp=base["power"]
    mc_comp=mc["power"]
    reject=mc["capacity"]+mc_comp*.90
    water_rise=reject*60/(c.waterFlow*4.186)
    # Equal pull-down comparison over c.pullHours, assuming ideal modulation
    # at map COP; rated capacity must meet event heat/c.pullHours.
    base_effective_comp=event_thermal/base["cop"]/c.pullHours
    mc_effective_comp=event_thermal/mc["cop"]/c.pullHours
    base_energy=(base_effective_comp+.35)*c.pullHours
    # The BPHE water loop replaces the conventional air condenser and its fan.
    aux_total=c.blower+c.mainPump+c.wettingPump
    mc_energy=(mc_effective_comp+aux_total)*c.pullHours
    feasible=(base["capacity"]>=design and mc["capacity"]>=design)
    extrapolated=(air_cond<c.mapLowCond or air_cond>c.mapHotCond or mc_cond<c.mapLowCond or mc_cond>c.mapHotCond)
    result={"product":product,"cropEnergy":crop_energy,"cropPeak":crop_peak,"standing":standing,"eventThermal":event_thermal,"peakLoad":peak_load,"design":design,"reject":reject,"waterRise":water_rise,"waterReturn":sink+water_rise,"auxTotal":aux_total,"baseCapacity":base["capacity"],"mcCapacity":mc["capacity"],"baseEffectiveComp":base_effective_comp,"mcEffectiveComp":mc_effective_comp,"feasible":feasible,"mapExtrapolated":extrapolated,"wallRoof":wall_roof,"ground":ground,"infiltration":infiltration,"respiration":respiration,"sink":sink,"dewpoint":dewpoint,"airCond":air_cond,"mcCond":mc_cond,"baseComp":base_comp,"mcComp":mc_comp,"baseEnergy":base_energy,"mcEnergy":mc_energy,"baseCop":base["cop"],"mcCop":mc["cop"],"basePressure":base["pressure"],"mcPressure":mc["pressure"],"saving":(base_energy-mc_energy)/base_energy*100,"engine":"Python + CoolProp 7.2.0"}
    return result
