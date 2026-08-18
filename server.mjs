import http from "node:http";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { stat } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { runEnergyPlusPair } from "./runner.mjs";

const port = Number(process.env.PORT || 8788);
const jobs = new Map();
const allowedOrigin = process.env.ALLOWED_ORIGIN || "*";
const serviceToken = process.env.SERVICE_TOKEN || "";
const MAX_BODY_BYTES = 64 * 1024;

const json = (response, status, body, headers = {}) => {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": allowedOrigin,
    "access-control-allow-headers": "authorization, content-type",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    ...headers,
  });
  response.end(JSON.stringify(body));
};

const authorized = (request) => !serviceToken || request.headers.authorization === `Bearer ${serviceToken}`;

async function bodyJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new Error("Request body exceeds 64 KB");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function publicJob(job) {
  return {
    id: job.id,
    status: job.status,
    queuedAt: job.queuedAt,
    startedAt: job.startedAt || null,
    completedAt: job.completedAt || null,
    result: job.result || null,
    error: job.error || null,
  };
}

function queueJob(design) {
  const id = randomUUID();
  const job = { id, status: "queued", queuedAt: new Date().toISOString(), design };
  jobs.set(id, job);
  void (async () => {
    job.status = "running";
    job.startedAt = new Date().toISOString();
    try {
      const { result, runDirectory } = await runEnergyPlusPair(design);
      job.status = "completed";
      job.completedAt = new Date().toISOString();
      job.result = result;
      job.runDirectory = runDirectory;
    } catch (error) {
      job.status = "failed";
      job.completedAt = new Date().toISOString();
      job.error = {
        message: error.message,
        diagnostics: error.details?.diagnostics || null,
        errTail: error.details?.errTail?.slice(-3000) || null,
      };
      console.error(`[${id}]`, error);
    }
  })();
  return job;
}

async function serveArtifact(response, job, relativePath) {
  if (!job.runDirectory || !relativePath) return json(response, 404, { error: "Artifact not found" });
  const root = path.resolve(job.runDirectory);
  const resolved = path.resolve(root, relativePath);
  if (!resolved.startsWith(root + path.sep)) return json(response, 400, { error: "Invalid artifact path" });
  const info = await stat(resolved).catch(() => null);
  if (!info?.isFile()) return json(response, 404, { error: "Artifact not found" });
  const extension = path.extname(resolved).toLowerCase();
  const contentTypes = { ".json": "application/json", ".csv": "text/csv", ".idf": "text/plain", ".err": "text/plain", ".htm": "text/html", ".sql": "application/vnd.sqlite3" };
  response.writeHead(200, {
    "content-type": contentTypes[extension] || "application/octet-stream",
    "content-length": info.size,
    "content-disposition": `attachment; filename="${path.basename(resolved)}"`,
    "access-control-allow-origin": allowedOrigin,
    "cache-control": "private, max-age=3600",
  });
  createReadStream(resolved).pipe(response);
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host || "localhost"}`);
    if (request.method === "OPTIONS") return json(response, 204, {});
    if (request.method === "GET" && url.pathname === "/health") {
      return json(response, 200, {
        status: "ok",
        engine: "DOE EnergyPlus 26.1.0",
        weather: path.basename(process.env.EPW_PATH || "not-configured"),
        queue: { active: [...jobs.values()].filter((job) => job.status === "running").length, total: jobs.size },
      });
    }
    if (!authorized(request)) return json(response, 401, { error: "Unauthorized" });
    if (request.method === "POST" && url.pathname === "/v1/runs") {
      const payload = await bodyJson(request);
      const job = queueJob(payload.design || payload);
      return json(response, 202, publicJob(job), { location: `/v1/runs/${job.id}` });
    }
    const artifactMatch = url.pathname.match(/^\/v1\/runs\/([^/]+)\/artifacts\/(.+)$/);
    if (request.method === "GET" && artifactMatch) {
      const job = jobs.get(artifactMatch[1]);
      if (!job) return json(response, 404, { error: "Run not found" });
      return serveArtifact(response, job, decodeURIComponent(artifactMatch[2]));
    }
    const runMatch = url.pathname.match(/^\/v1\/runs\/([^/]+)$/);
    if (request.method === "GET" && runMatch) {
      const job = jobs.get(runMatch[1]);
      return job ? json(response, 200, publicJob(job)) : json(response, 404, { error: "Run not found" });
    }
    return json(response, 404, { error: "Not found" });
  } catch (error) {
    return json(response, 400, { error: error.message });
  }
});

server.listen(port, "0.0.0.0", () => {
  console.log(`Geo-AHU EnergyPlus service listening on ${port}`);
});

