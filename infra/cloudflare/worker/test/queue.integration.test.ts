import { env } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";

const runtime = env as unknown as {
  DB: D1Database;
  OMNIINTEL_API_TOKEN: string;
  OMNIINTEL_WORKER_TOKEN: string;
};

const apiToken = "public-api-test-secret";
const workerToken = "internal-worker-test-secret";

async function call(
  path: string,
  token: string,
  body?: unknown,
): Promise<Response> {
  return worker.fetch(
    new Request(`https://omniintel.test${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }),
    runtime as never,
  );
}

async function createJob(): Promise<string> {
  const response = await call("/v1/jobs", apiToken, {
    job_type: "YOUTUBE_TO_NOTES",
    payload: {
      url: "https://www.youtube.com/watch?v=test-video",
      approve_network: true,
    },
  });

  expect(response.status).toBe(202);
  const result = await response.json() as { job_id: string };
  return result.job_id;
}

async function claimJob(): Promise<{
  job_id: string;
  lease_token: string;
  attempt: number;
}> {
  const response = await call("/v1/worker/claim", workerToken, {});
  expect(response.status).toBe(200);

  const result = await response.json() as {
    job: {
      job_id: string;
      lease_token: string;
      attempt: number;
    } | null;
  };

  expect(result.job).not.toBeNull();
  return result.job!;
}

async function readJob(jobId: string) {
  return runtime.DB.prepare(
    `SELECT state, attempt_count, max_attempts, available_at,
            lease_token, lease_expires_at, last_error
       FROM jobs WHERE id = ?`,
  ).bind(jobId).first<{
    state: string;
    attempt_count: number;
    max_attempts: number;
    available_at: number;
    lease_token: string | null;
    lease_expires_at: number | null;
    last_error: string | null;
  }>();
}

describe("Cloudflare D1 queue integration", () => {
  beforeEach(async () => {
    await runtime.DB.prepare("DELETE FROM jobs").run();
  });

  it("claims a queued job and increments its attempt count", async () => {
    const jobId = await createJob();
    const claimed = await claimJob();

    expect(claimed.job_id).toBe(jobId);
    expect(claimed.lease_token).toBeTruthy();
    expect(claimed.attempt).toBe(1);

    const row = await readJob(jobId);
    expect(row?.state).toBe("RUNNING");
    expect(row?.attempt_count).toBe(1);
  });

  it("requeues a failed first attempt with bounded backoff", async () => {
    const jobId = await createJob();
    const claimed = await claimJob();

    const response = await call(
      `/v1/worker/jobs/${jobId}/fail`,
      workerToken,
      {
        lease_token: claimed.lease_token,
        error: "Simulated provider failure",
      },
    );

    expect(response.status).toBe(200);

    const row = await readJob(jobId);
    const timestamp = Math.floor(Date.now() / 1000);

    expect(row?.state).toBe("QUEUED");
    expect(row?.attempt_count).toBe(1);
    expect(row?.lease_token).toBeNull();
    expect(row?.last_error).toBe("Simulated provider failure");
    expect(row!.available_at).toBeGreaterThanOrEqual(timestamp + 50);
    expect(row!.available_at).toBeLessThanOrEqual(timestamp + 65);

    const nextClaim = await call("/v1/worker/claim", workerToken, {});
    expect((await nextClaim.json()).job).toBeNull();
  });

  it("marks a job FAILED after its final permitted attempt", async () => {
    const jobId = await createJob();
    const first = await claimJob();

    await call(`/v1/worker/jobs/${jobId}/fail`, workerToken, {
      lease_token: first.lease_token,
      error: "First failure",
    });

    await runtime.DB.prepare(
      "UPDATE jobs SET available_at = 0 WHERE id = ?",
    ).bind(jobId).run();

    const second = await claimJob();
    expect(second.attempt).toBe(2);

    const response = await call(
      `/v1/worker/jobs/${jobId}/fail`,
      workerToken,
      {
        lease_token: second.lease_token,
        error: "Final failure",
      },
    );

    expect(response.status).toBe(200);

    const row = await readJob(jobId);
    expect(row?.state).toBe("FAILED");
    expect(row?.attempt_count).toBe(2);
    expect(row?.lease_token).toBeNull();
  });

  it("requeues an expired lease with backoff", async () => {
    const jobId = await createJob();
    await claimJob();

    await runtime.DB.prepare(
      "UPDATE jobs SET lease_expires_at = 0 WHERE id = ?",
    ).bind(jobId).run();

    const response = await call("/v1/worker/claim", workerToken, {});
    expect((await response.json()).job).toBeNull();

    const row = await readJob(jobId);
    expect(row?.state).toBe("QUEUED");
    expect(row?.lease_token).toBeNull();
    expect(row?.attempt_count).toBe(1);
    expect(row!.available_at).toBeGreaterThan(
      Math.floor(Date.now() / 1000),
    );
  });

  it("rejects a stale lease token without changing job ownership", async () => {
    const jobId = await createJob();
    const claimed = await claimJob();

    const response = await call(
      `/v1/worker/jobs/${jobId}/fail`,
      workerToken,
      {
        lease_token: "stale-lease-token",
        error: "Should not be accepted",
      },
    );

    expect(response.status).toBe(409);

    const row = await readJob(jobId);
    expect(row?.state).toBe("RUNNING");
    expect(row?.lease_token).toBe(claimed.lease_token);
  });

  it("marks an expired final-attempt lease as FAILED", async () => {
    const jobId = await createJob();
    await claimJob();

    await runtime.DB.prepare(
      `UPDATE jobs
          SET attempt_count = max_attempts, lease_expires_at = 0
        WHERE id = ?`,
    ).bind(jobId).run();

    await call("/v1/worker/claim", workerToken, {});

    const row = await readJob(jobId);
    expect(row?.state).toBe("FAILED");
    expect(row?.lease_token).toBeNull();
    expect(row?.lease_expires_at).toBeNull();
  });
});
