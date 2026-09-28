# KissanShroom Invention Engine — V1 screening loop

Render Cron starts this Python run every six hours (UTC). Each run generates 120
reproducible geometry candidates, calculates first-order airflow, fan input and
sensible cooling for dry and humid test points, rejects failed constraints, and
stores every candidate, reason and score in PostgreSQL. Later runs also generate
60 mutations of the previous best. It exits; the next run resumes with a new
seed from the saved generation number. No ChatGPT Schedule is involved.

**Status:** autonomous numerical search prototype, not a self-directed literature
researcher, CFD model, validated M-Cycle simulator or proven AC design. Dew-point
effectiveness is an assumed input. The face-area/pressure-drop model is a
surrogate; wet-channel losses, headers, actual blower curve, wettability,
evaporation, water quality, leakage, room humidity, and fabrication cost are
unmeasured. A screening pass is never a physical performance claim.

## Deployment

Push these files to a GitHub/GitLab/Bitbucket repository with `render.yaml` at
its root. In Render Dashboard create a Blueprint from that repository, review
the paid Cron and PostgreSQL plans, then Apply. Cron runs every six hours and
prints its candidate and verifier output to Render logs. Review costs before
Apply; the Blueprint intentionally includes no API keys. Render cron and DB
charges depend on current pricing. No phone or computer needs to stay on.

## Local test

`python -m unittest discover -s tests -v` needs Python 3.10+ and no database.
To run a generation locally, set `DATABASE_URL` to a PostgreSQL connection,
install `requirements.txt`, and run `python -m engine.run`.

## Next engineering gate

Measure air flow, pressure drop, supply DBT/RH, inlet DBT/RH, fan/pump power,
evaporated water and room heat load on a prototype. Fit effectiveness to those
measurements before using model outputs for procurement or savings claims.
