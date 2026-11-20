import { AwsClient } from "aws4fetch";

interface Env {
  DB: D1Database;
  OMNIINTEL_API_TOKEN: string;
  OMNIINTEL_WORKER_TOKEN: string;
  B2_KEY_ID: string;
  B2_APPLICATION_KEY: string;
  B2_BUCKET_NAME: string;
  B2_S3_ENDPOINT: string;
  MAX_ARTIFACT_BYTES?: string;
  MAX_UPLOAD_BYTES?: string;
  CORS_ORIGIN?: string;
}
type JobType = "YOUTUBE_TO_NOTES" | "UPLOADED_MEDIA_TO_NOTES";
type JobState = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", ...headers } });
const now = () => Math.floor(Date.now() / 1000);
const id = () => crypto.randomUUID();
const max = (value: string | undefined, fallback: number) => {
  const n = Number(value);
  return Number.isSafeInteger(n) && n > 0 ? n : fallback;
};
function b2(env: Env) {
  const endpoint = new URL(env.B2_S3_ENDPOINT);
  return new AwsClient({
    accessKeyId: env.B2_KEY_ID,
    secretAccessKey: env.B2_APPLICATION_KEY,
    service: "s3",
    region: endpoint.hostname.split(".")[1] || "us-east-1",
  });
}
function objectUrl(env: Env, key: string) {
  const endpoint = new URL(env.B2_S3_ENDPOINT);
  endpoint.pathname = `/${encodeURIComponent(env.B2_BUCKET_NAME)}/${key.split("/").map(encodeURIComponent).join("/")}`;
  endpoint.search = "";
  return endpoint;
}
async function signedDownload(env: Env, key: string) {
  const client = b2(env);
  const url = objectUrl(env, key);
  url.searchParams.set("X-Amz-Expires", "900");
  const signed = await client.sign(url, { method: "GET", aws: { signQuery: true } });
  return signed.url;
}
async function authorized(
  request: Request,
  expectedToken: string | undefined,
): Promise<boolean> {
  const supplied = request.headers.get("authorization") || "";
  if (!expectedToken || !supplied.startsWith("Bearer ")) return false;

  const candidate = supplied.slice(7);
  if (!candidate || candidate.length !== expectedToken.length) return false;

  const [actual, expected] = await Promise.all([
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(candidate)),
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(expectedToken)),
  ]);

  const left = new Uint8Array(actual);
  const right = new Uint8Array(expected);
  let difference = 0;
  for (let i = 0; i < left.length; i++) difference |= left[i] ^ right[i];
  return difference === 0;
}
async function readJson(request: Request, limit = 1024 * 1024): Promise<any> {
  const length = Number(request.headers.get("content-length") || "0");
  if (length > limit) throw new Error("Request body is too large.");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > limit) throw new Error("Request body is too large.");
  return JSON.parse(text);
}
function validatePayload(type: JobType, payload: any) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("payload must be an object");
  if (type === "YOUTUBE_TO_NOTES") {
    if (payload.approve_network !== true) throw new Error("Explicit network approval is required.");
    if (typeof payload.url !== "string" || payload.url.length > 2048 ||
      !/^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(payload.url)) throw new Error("A supported YouTube URL is required.");
  } else {
    if (payload.approve_media_upload !== true) throw new Error("Explicit media-upload approval is required.");
    if (typeof payload.filename !== "string" || payload.filename.length > 255) throw new Error("A valid filename is required.");
    if (!/\.(mp3|m4a|wav|aac|flac|ogg|opus|mp4|m4v|mov|mkv|webm)$/i.test(payload.filename)) throw new Error("Unsupported media file extension.");
  }
  if (payload.approve_ai !== undefined && typeof payload.approve_ai !== "boolean") throw new Error("approve_ai must be boolean");
  if (payload.approve_visual !== undefined && typeof payload.approve_visual !== "boolean") throw new Error("approve_visual must be boolean");
}
async function createJob(request: Request, env: Env) {
  const body = await readJson(request, 32 * 1024);
  const type = body.job_type as JobType;
  if (type !== "YOUTUBE_TO_NOTES" && type !== "UPLOADED_MEDIA_TO_NOTES") return json({ error: "Unsupported job_type" }, 400);
  try { validatePayload(type, body.payload); } catch (e) { return json({ error: String(e) }, 400); }
  const jobId = id();
  const timestamp = now();
  let inputKey: string | null = null;
  if (type === "UPLOADED_MEDIA_TO_NOTES") inputKey = `inputs/${jobId}/${crypto.randomUUID()}`;
  let uploadUrl: string | undefined;
  if (inputKey) {
    const client = b2(env);
    const url = objectUrl(env, inputKey);
    const signed = await client.sign(url, { method: "PUT", aws: { signQuery: true } });
    uploadUrl = signed.url;
  }
  // Sign storage access before creating the D1 row. If B2 configuration is invalid,
  // return an error without leaving an unuploadable job permanently awaiting input.
  await env.DB.prepare(
    "INSERT INTO jobs (id, job_type, state, payload_json, input_key, input_uploaded, created_at, updated_at) VALUES (?, ?, 'QUEUED', ?, ?, ?, ?, ?)"
  ).bind(jobId, type, JSON.stringify(body.payload), inputKey, inputKey ? 0 : 1, timestamp, timestamp).run();
  return json({ job_id: jobId, job_type: type, status: inputKey ? "AWAITING_UPLOAD" : "QUEUED", status_url: "/v1/jobs/" + jobId, upload_url: uploadUrl, upload_method: uploadUrl ? "PUT" : undefined, upload_complete_url: inputKey ? "/v1/jobs/" + jobId + "/upload-complete" : undefined }, 202);
}
async function finalizeUpload(env: Env, jobId: string) {
  const row = await env.DB.prepare("SELECT input_key, input_uploaded, state FROM jobs WHERE id=?").bind(jobId).first<any>();
  if (!row || !row.input_key) return json({ error: "Upload job not found" }, 404);
  if (row.input_uploaded === 1) return json({ job_id: jobId, status: row.state });
  if (row.state !== "QUEUED") {
    return json({ error: "Upload can no longer be finalized for this job" }, 409);
  }
  const response = await b2(env).fetch(objectUrl(env, row.input_key), { method: "HEAD" });
  if (!response.ok) return json({ error: "Uploaded object is not available yet", storage_status: response.status }, 409);
  const size = Number(response.headers.get("content-length") || "0");
  if (!size || size > max(env.MAX_UPLOAD_BYTES, 250 * 1024 * 1024)) {
    await b2(env).fetch(objectUrl(env, row.input_key), { method: "DELETE" });
    return json({ error: "Uploaded media is empty or exceeds the configured limit" }, 413);
  }
  const updated = await env.DB.prepare(
    "UPDATE jobs SET input_uploaded=1, updated_at=? WHERE id=? AND input_uploaded=0 AND state='QUEUED'"
  ).bind(now(), jobId).run();

  if (!updated.meta.changes) {
    const latest = await env.DB.prepare(
      "SELECT input_uploaded, state FROM jobs WHERE id=?"
    ).bind(jobId).first<any>();

    if (latest?.input_uploaded === 1) {
      return json({ job_id: jobId, status: latest.state });
    }
    return json({ error: "Upload can no longer be finalized for this job" }, 409);
  }

  return json({ job_id: jobId, status: "QUEUED", size_bytes: size });
}
async function claimJob(env: Env) {
  const timestamp = now();
  await env.DB.prepare("UPDATE jobs SET state='FAILED', last_error=COALESCE(last_error,'Worker lease expired after final attempt'), lease_token=NULL, lease_expires_at=NULL, updated_at=? WHERE state='RUNNING' AND lease_expires_at < ? AND attempt_count >= max_attempts").bind(timestamp, timestamp).run();
  await env.DB.prepare("UPDATE jobs SET state='QUEUED', available_at=? + MIN(900, 30 * (1 << MIN(attempt_count, 5))), lease_token=NULL, lease_expires_at=NULL, updated_at=? WHERE state='RUNNING' AND lease_expires_at < ? AND attempt_count < max_attempts").bind(timestamp, timestamp, timestamp).run();
  const leaseToken = id();
  const row = await env.DB.prepare(`
    UPDATE jobs
    SET state = 'RUNNING', attempt_count = attempt_count + 1,
        lease_token = ?, lease_expires_at = ?, updated_at = ?
    WHERE id = (
      SELECT id FROM jobs
      WHERE state = 'QUEUED' AND available_at <= ?
        AND attempt_count < max_attempts AND input_uploaded = 1
      ORDER BY created_at ASC LIMIT 1
    )
    RETURNING id, job_type, payload_json, input_key, attempt_count, lease_expires_at
  `).bind(leaseToken, timestamp + 900, timestamp, timestamp).first<any>();
  if (!row) return json({ job: null });
  const job: Record<string, unknown> = {
    job_id: row.id, job_type: row.job_type, payload: JSON.parse(row.payload_json),
    lease_token: leaseToken, attempt: row.attempt_count, lease_expires_at: row.lease_expires_at,
  };
  if (row.input_key) job.download_url = await signedDownload(env, row.input_key);
  return json({ job });
}
async function completeJob(request: Request, env: Env, jobId: string) {
  const body = await readJson(request, max(env.MAX_ARTIFACT_BYTES, 20 * 1024 * 1024));
  if (typeof body.lease_token !== "string" || !body.lease_token || !body.reader || typeof body.reader !== "object") {
    return json({ error: "lease_token and reader JSON are required" }, 400);
  }
  const bytes = new TextEncoder().encode(JSON.stringify(body.reader));
  if (bytes.byteLength > max(env.MAX_ARTIFACT_BYTES, 20 * 1024 * 1024)) return json({ error: "Reader artifact exceeds size limit" }, 413);
  const key = `readers/${jobId}/${body.lease_token}/reader.json`;
  const response = await b2(env).fetch(objectUrl(env, key), {
    method: "PUT", headers: { "content-type": "application/json", "x-amz-meta-job-id": jobId }, body: bytes,
  });
  if (!response.ok) return json({ error: "Artifact storage failed", storage_status: response.status }, 502);
  const result = await env.DB.prepare(
    "UPDATE jobs SET state='COMPLETED', result_key=?, lease_token=NULL, lease_expires_at=NULL, updated_at=? WHERE id=? AND state='RUNNING' AND lease_token=? AND lease_expires_at > ?"
  ).bind(key, now(), jobId, body.lease_token, now()).run();
  if (!result.meta.changes) {
    // The lease may expire while the artifact is being uploaded.
    // This key is lease-specific, so deleting it cannot remove another
    // worker's successful artifact.
    try {
      const cleanup = await b2(env).fetch(objectUrl(env, key), {
        method: "DELETE",
      });
      if (!cleanup.ok && cleanup.status !== 404) {
        console.error("Unable to clean up stale reader artifact", cleanup.status);
      }
    } catch (cleanupError) {
      console.error("Unable to clean up stale reader artifact", cleanupError);
    }
    return json({ error: "Lease lost or job is no longer running" }, 409);
  }
  return json({ job_id: jobId, status: "COMPLETED", result_key: key });
}

async function heartbeatJob(request: Request, env: Env, jobId: string) {
  const body = await readJson(request, 8 * 1024);
  if (typeof body.lease_token !== "string" || !body.lease_token) return json({ error: "lease_token is required" }, 400);
  const expires = now() + 900;
  const result = await env.DB.prepare(
    "UPDATE jobs SET lease_expires_at=?, updated_at=? WHERE id=? AND state='RUNNING' AND lease_token=? AND lease_expires_at > ?"
  ).bind(expires, now(), jobId, body.lease_token, now()).run();
  if (!result.meta.changes) return json({ error: "Lease lost or job is no longer running" }, 409);
  return json({ job_id: jobId, lease_expires_at: expires });
}
async function failJob(request: Request, env: Env, jobId: string) {
  const body = await readJson(request, 16 * 1024);
  if (typeof body.lease_token !== "string" || typeof body.error !== "string") return json({ error: "lease_token and error are required" }, 400);
  const error = body.error.slice(0, 2000);
  const timestamp = now();
  const result = await env.DB.prepare(`
    UPDATE jobs SET state=CASE WHEN attempt_count < max_attempts THEN 'QUEUED' ELSE 'FAILED' END,
      available_at=CASE WHEN attempt_count < max_attempts THEN ? + MIN(900, 30 * (1 << MIN(attempt_count, 5))) ELSE 0 END,
      last_error=?, lease_token=NULL, lease_expires_at=NULL, updated_at=?
    WHERE id=? AND state='RUNNING' AND lease_token=? AND lease_expires_at > ?
  `).bind(timestamp, error, timestamp, jobId, body.lease_token, timestamp).run();
  if (!result.meta.changes) return json({ error: "Lease lost or job is no longer running" }, 409);
  return json({ job_id: jobId, status: "REQUEUED_OR_FAILED" });
}
async function jobStatus(env: Env, jobId: string) {
  const row = await env.DB.prepare(
    "SELECT id, job_type, state, attempt_count, last_error, result_key, created_at, updated_at FROM jobs WHERE id=?"
  ).bind(jobId).first<any>();
  if (!row) return json({ error: "Job not found" }, 404);
  return json({
    job_id: row.id, job_type: row.job_type, status: row.state, attempt: row.attempt_count,
    error: row.last_error, created_at: row.created_at, updated_at: row.updated_at,
    result_url: row.result_key ? await signedDownload(env, row.result_key) : undefined,
    status_url: "/v1/jobs/" + jobId,
  });
}
function withCors(response: Response, request: Request, env: Env): Response {
  const origin = request.headers.get("origin");
  const allowed = (env.CORS_ORIGIN || "").split(",").map((value) => value.trim()).filter(Boolean);
  const headers = new Headers(response.headers);
  if (origin && allowed.includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
    headers.append("Vary", "Origin");
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return withCors(new Response(null, { status: 204 }), request, env);
    if (request.method === "GET" && url.pathname === "/health") return withCors(json({ status: "ok", service: "omniintel-api" }), request, env);
    const workerOnly =
      url.pathname === "/v1/worker/claim" ||
      url.pathname.startsWith("/v1/worker/");
    const requiredToken = workerOnly
      ? env.OMNIINTEL_WORKER_TOKEN
      : env.OMNIINTEL_API_TOKEN;
    if (!(await authorized(request, requiredToken))) {
      return withCors(json({ error: "A valid bearer token is required" }, 401), request, env);
    }
    try {
      if (request.method === "POST" && url.pathname === "/v1/jobs") return withCors(await createJob(request, env), request, env);
      if (request.method === "POST" && url.pathname === "/v1/youtube/jobs") {
        const payload = await readJson(request, 32 * 1024);
        return withCors(await createJob(new Request(request.url, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": request.headers.get("authorization") || "" }, body: JSON.stringify({ job_type: "YOUTUBE_TO_NOTES", payload }) }), env), request, env);
      }
      if (request.method === "POST" && url.pathname === "/v1/media/jobs") {
        const payload = await readJson(request, 32 * 1024);
        return withCors(await createJob(new Request(request.url, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": request.headers.get("authorization") || "" }, body: JSON.stringify({ job_type: "UPLOADED_MEDIA_TO_NOTES", payload }) }), env), request, env);
      }
      if (request.method === "POST" && url.pathname === "/v1/worker/claim") return withCors(await claimJob(env), request, env);
      const complete = url.pathname.match(/^\/v1\/worker\/jobs\/([0-9a-f-]+)\/complete$/i);
      if (request.method === "POST" && complete) return withCors(await completeJob(request, env, complete[1]), request, env);
      const heartbeat = url.pathname.match(/^\/v1\/worker\/jobs\/([0-9a-f-]+)\/heartbeat$/i);
      if (request.method === "POST" && heartbeat) return withCors(await heartbeatJob(request, env, heartbeat[1]), request, env);
      const fail = url.pathname.match(/^\/v1\/worker\/jobs\/([0-9a-f-]+)\/fail$/i);
      if (request.method === "POST" && fail) return withCors(await failJob(request, env, fail[1]), request, env);
      const uploadDone = url.pathname.match(/^\/v1\/jobs\/([0-9a-f-]+)\/upload-complete$/i);
      if (request.method === "POST" && uploadDone) return withCors(await finalizeUpload(env, uploadDone[1]), request, env);
      const status = url.pathname.match(/^\/v1\/jobs\/([0-9a-f-]+)$/i);
      if (request.method === "GET" && status) return withCors(await jobStatus(env, status[1]), request, env);
      return withCors(json({ error: "Not found" }, 404), request, env);
    } catch (error) {
      return withCors(json({ error: error instanceof Error ? error.message : "Internal error" }, 400), request, env);
    }
  },
};
