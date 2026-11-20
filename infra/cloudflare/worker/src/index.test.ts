import { describe, expect, it } from "vitest";
import worker from "./index";

describe("OmniIntel Worker API", () => {
  it("exposes a health endpoint without credentials", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/health"),
      {} as never
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ status: "ok", service: "omniintel-api" });
  });

  it("rejects protected requests without a bearer token", async () => {
    const response = await worker.fetch(
      new Request("https://omniintel.example/v1/worker/claim", { method: "POST" }),
      {} as never
    );
    expect(response.status).toBe(401);
  });

  it("answers preflight only for configured exact origins", async () => {
    const request = new Request("https://omniintel.example/v1/jobs", {
      method: "OPTIONS",
      headers: { Origin: "https://reader.example" }
    });
    const response = await worker.fetch(request, { CORS_ORIGIN: "https://reader.example" } as never);
    expect(response.status).toBe(204);
    expect(response.headers.get("access-control-allow-origin")).toBe("https://reader.example");
    const rejected = await worker.fetch(request, { CORS_ORIGIN: "https://other.example" } as never);
    expect(rejected.headers.get("access-control-allow-origin")).toBeNull();
  });
});
