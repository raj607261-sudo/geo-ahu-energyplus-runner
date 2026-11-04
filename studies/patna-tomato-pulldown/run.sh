#!/bin/sh
# usage: EPLUS=/path/to/energyplus ./run.sh variant...
set -e
cd "$(dirname "$0")"
EPLUS=${EPLUS:-energyplus}
for v in "$@"; do
  ( cd runs/$v && "$EPLUS" -w ../../weather/IND_Patna.424920_ISHRAE.epw -d . -r in.idf > stdout.txt 2>&1 || true; tail -1 eplusout.err )
done
