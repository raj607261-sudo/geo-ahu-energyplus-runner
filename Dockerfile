FROM ubuntu:24.04

ARG ENERGYPLUS_VERSION=26.1.0
ARG ENERGYPLUS_BUILD=6f2e40d102
ARG ENERGYPLUS_SHA256=b651f4197bfc147a0f66dc92c58895d1748bdadb7a0288145fa9d50375edfbca
ARG WEATHER_URL=https://climate.onebuilding.org/WMO_Region_2_Asia/IND_India/BR_Bihar/IND_BR_Darbhanga.423910_TMYx.2011-2025.zip

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl libexpat1 libgomp1 libx11-6 nodejs unzip \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/energyplus /opt/weather /app /data/runs \
  && curl -fL "https://github.com/NatLabRockies/EnergyPlus/releases/download/v${ENERGYPLUS_VERSION}/EnergyPlus-${ENERGYPLUS_VERSION}-${ENERGYPLUS_BUILD}-Linux-Ubuntu24.04-x86_64.tar.gz" -o /tmp/energyplus.tar.gz \
  && echo "${ENERGYPLUS_SHA256}  /tmp/energyplus.tar.gz" | sha256sum -c - \
  && tar -xzf /tmp/energyplus.tar.gz -C /opt/energyplus --strip-components=1 \
  && rm /tmp/energyplus.tar.gz \
  && curl -fL "${WEATHER_URL}" -o /tmp/weather.zip \
  && unzip -j /tmp/weather.zip '*.epw' -d /opt/weather \
  && rm /tmp/weather.zip

WORKDIR /app
COPY package.json model.mjs runner.mjs server.mjs ./

ENV PORT=8788 \
    ENERGYPLUS_EXE=/opt/energyplus/energyplus \
    EPW_PATH=/opt/weather/IND_BR_Darbhanga.423910_TMYx.2011-2025.epw \
    RUN_ROOT=/data/runs \
    NODE_ENV=production

EXPOSE 8788
VOLUME ["/data/runs"]
CMD ["node", "server.mjs"]

