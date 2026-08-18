# Geo-AHU EnergyPlus service

This service executes two real DOE EnergyPlus 26.1 annual models for each calculator design:

- conventional air-cooled refrigeration compressor rack;
- water-cooled refrigeration compressor rack connected to an EnergyPlus vertical G-function ground heat exchanger.

The generated IDF maps cold-room dimensions, PUF U-value, storage temperature, daily product pull-down, lights, evaporator fans, defrost, door schedule, COP, pump power, soil temperature, total pipe length, borefield top depth and bore spacing from the website calculator. A run is only marked complete when both EnergyPlus ERR files report successful completion with zero severe/fatal errors.

## Run locally

```sh
docker build -t geo-ahu-energyplus ./energyplus-service
docker run --rm -p 8788:8788 -e SERVICE_TOKEN=change-me geo-ahu-energyplus
```

Create a job with `POST /v1/runs`, poll `GET /v1/runs/:id`, and download the returned IDF, ERR, CSV, SQL and HTML artifacts from `/v1/runs/:id/artifacts/...`.

For production, deploy the container to any persistent container host, set `SERVICE_TOKEN`, and connect the website Worker using `ENERGYPLUS_API_URL` plus `ENERGYPLUS_API_TOKEN` or a Sites private HTTP tunnel binding named `energyplus`.

