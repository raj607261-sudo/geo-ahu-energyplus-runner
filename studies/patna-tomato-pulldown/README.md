# Patna tomato pull-down study (EnergyPlus 26.1)

3 t of tomato loaded at 28 °C and pulled down to 12 °C in a 200 sq ft (20 × 10 × 10 ft), 80 mm PUF cold room,
Patna ISHRAE weather, 1–31 May. A "4 TR" R-404A condensing unit, with and without an M-cycle (dew-point
indirect evaporative) pre-cooler on the condenser air. A fresh 3 t batch comes in every 6 days.

Dashboard: `docs/patna-tomato/` (GitHub Pages), source in `dashboard/index.html` + `dashboard/data.json`.

## Market unit vs your design (May)

Same room, same compressor, same tomato. Market = unit-cooler fans at full speed 24×7, no M-cycle.
Your design = M-cycle on the condenser + EC unit-cooler fans (full speed with the compressor, 50 % airflow
at 17 % power in between).

| | Market | Your design |
|---|---|---|
| Electricity, May | 932 kWh | 430 kWh (−53.9 %) |
| Weak M-cycle (ε 0.45) | | 445 kWh (−52.3 %) |
| Core to 13 °C | 8.8 h | 8.8 h |
| Room RH | 90.9 % | 93.3 % |
| Tomato weight lost, May | 157 kg | 122 kg |

M-cycle alone: −5.4 %. EC fans alone: −49.1 %. Most of the saving needs the fan control.

## Results (May, base h = 3 W/m²K)

| | Standard | With M-cycle |
|---|---|---|
| Tomato core to 13 °C after loading | 8.8 h | 8.7 h |
| 7/8 cooled (mass-average 14 °C) | 6.5 h | 6.4 h |
| Electricity, May | 932 kWh | 881 kWh |
| of which unit-cooler fans (24×7) | 424 kWh | 424 kWh |
| Max condensing temperature | 55.9 °C | 44.8 °C |
| Room RH with product | 91 % | 91 % |

Fruit-to-air coefficient 1.5–6 W/m²K (crate stacking) moves core-to-13 °C between 5.3 and 15.8 h.
Fans cycling with the compressor: 398 kWh, but RH 79 % and twice the weight loss.

## How it is modelled

* `build_idf.py` – all inputs (`CONFIG`) and the IDF generator, 10 variants.
* `cycle_curves.py` – balances the Copeland ZS45K4E-TF5 AHRI-540 map (`compressor_curves.idf`, verbatim from
  EnergyPlus DataSets) with the condenser and the unit cooler, and gives EnergyPlus the result as
  `Table:Lookup` capacity / EIR tables for a `Coil:Cooling:DX:SingleSpeed`.
* Tomato: 5-shell sphere conduction, ASHRAE respiration and transpiration, written in EMS (Erl) inside the run.
* Door air: Gosney-Olama with strip curtain. M-cycle: condenser inlet node set to
  `Tdb − ε·(Tdb − Tdew)`, plus fan/pump power and water.
* `postprocess.py` – integrates the EnergyPlus SQL output and runs the balance checks
  (coil vs loads ≤ 0.12 %, zone air heat balance 0.00 kWh, fruit energy balance ≤ 0.013 %, moisture ≤ 0.6 %).

## Re-run

```sh
python3 build_idf.py                      # writes runs/<variant>/in.idf
EPLUS=/path/to/energyplus ./run.sh $(ls runs)
python3 postprocess.py                    # dashboard/data.json
python3 make_site.py                      # copies to docs/patna-tomato/
```

Weather: `weather/IND_Patna.424920_ISHRAE.epw` from the EnergyPlus weather store
(md5 2b54d901d35e40b340d654f848241925).
