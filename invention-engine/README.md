# KissanShroom Invention Engine — V1 screening loop

GitHub Actions starts this Python run every six hours (UTC). Each run generates 120
reproducible geometry candidates, calculates first-order airflow, fan input and
sensible cooling for dry and humid test points, rejects failed constraints, and
stores a candidate summary and failure counts in public Git memory. Later runs also generate
60 mutations of the previous best. It exits; the next run resumes with a new
seed from the saved generation number. No ChatGPT Schedule is involved.

Without `DATABASE_URL`, the GitHub Actions workflow writes `state/memory.json`
and commits it to the repository after each run. This is durable public Git
memory for a free trial, not PostgreSQL. Never place personal information or
secrets in the state file. Set `DATABASE_URL` to migrate the execution path to
PostgreSQL; migration of previous JSON history is not automatic.

The file-memory mode asks Crossref for DOI/title metadata every 28 generations
(about weekly). These are leads to read, **not** extracted experimental data or
validated performance. An API error is recorded without stopping calculations.

**Status:** autonomous numerical search prototype, not a self-directed literature
researcher, CFD model, validated M-Cycle simulator or proven AC design. Dew-point
effectiveness is an assumed input. The face-area/pressure-drop model is a
surrogate; wet-channel losses, headers, actual blower curve, wettability,
evaporation, water quality, leakage, room humidity, and fabrication cost are
unmeasured. A screening pass is never a physical performance claim.
The assumed dew-point effectiveness is fixed at 0.75 for every candidate until
measured, so the search cannot improve its score by inventing effectiveness.
The air-stream sensible reduction is **not** verified room cooling duty. The
score includes a small core-area proxy penalty, not a real manufacturing BOM.

## Deployment

The `.github/workflows/kissanshroom-rnd.yml` workflow runs on the default branch
every six hours and can also be started with `workflow_dispatch`. Standard
GitHub-hosted runners are free for this public repo. The workflow commits its
JSON state after each run; do not add confidential project information to it.
For private PostgreSQL memory, create a database and set the repository Actions
secret `INVENTION_DATABASE_URL` to its connection string. The code then uses
PostgreSQL and imports existing Git JSON run history on its first empty database
run. Past candidate-by-candidate records were never saved by the Git fallback;
only past best designs and failure summaries exist. Never commit a database URL.

## Local test

`python -m unittest discover -s tests -v` needs Python 3.10+ and no database.
To run a generation locally, install `requirements.txt`, set `STATE_PATH` to
a disposable path, and run `python -m engine.run`. Set `DATABASE_URL` to use
PostgreSQL instead.

## Next engineering gate

Measure air flow, pressure drop, supply DBT/RH, inlet DBT/RH, fan/pump power,
evaporated water and room heat load on a prototype. Fit effectiveness to those
measurements before using model outputs for procurement or savings claims.
