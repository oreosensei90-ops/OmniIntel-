import { describe, expect, it } from "vitest";
import worker from "./index";

const env = {
  OMNIINTEL_API_TOKEN: "public-api-test-secret",
  OMNIINTEL_WORKER_TOKEN: "internal-worker-test-secret",
} as never;

describe("OmniIntel Worker API authentication", () => {
  it("exposes health without credentials", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/health"),
      {} as never,
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      status: "ok",
      service: "omniintel-api",
    });
  });

  it("rejects missing credentials on protected routes", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/worker/claim", {
        method: "POST",
      }),
      env,
    );
    expect(response.status).toBe(401);
  });

  it("accepts the worker token on worker-only routes", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/worker/not-a-route", {
        method: "POST",
        headers: {
          Authorization: "Bearer internal-worker-test-secret",
        },
      }),
      env,
    );
    expect(response.status).toBe(404);
  });

  it("rejects the public API token on worker-only routes", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/worker/not-a-route", {
        method: "POST",
        headers: {
          Authorization: "Bearer public-api-test-secret",
        },
      }),
      env,
    );
    expect(response.status).toBe(401);
  });

  it("accepts the API token on client routes", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/not-a-route", {
        headers: {
          Authorization: "Bearer public-api-test-secret",
        },
      }),
      env,
    );
    expect(response.status).toBe(404);
  });

  it("rejects the worker token on client routes", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/not-a-route", {
        headers: {
          Authorization: "Bearer internal-worker-test-secret",
        },
      }),
      env,
    );
    expect(response.status).toBe(401);
  });

  it("answers preflight only for configured exact origins", async () => {
    const request = new Request("https://omniintel.example/v1/jobs", {
      method: "OPTIONS",
      headers: { Origin: "https://reader.example" },
    });
    const response = await worker.fetch(
      request,
      { CORS_ORIGIN: "https://reader.example" } as never,
    );
    expect(response.status).toBe(204);
    expect(response.headers.get("access-control-allow-origin"))
      .toBe("https://reader.example");

    const rejected = await worker.fetch(
      request,
      { CORS_ORIGIN: "https://other.example" } as never,
    );
    expect(rejected.headers.get("access-control-allow-origin")).toBeNull();
  });
});
