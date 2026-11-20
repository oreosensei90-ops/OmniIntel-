import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: {
        configPath: "./wrangler.toml",
      },
      miniflare: {
        bindings: {
          TEST_MIGRATIONS: await readD1Migrations(
            resolve(process.cwd(), "migrations"),
          ),
          OMNIINTEL_API_TOKEN: "public-api-test-secret",
          OMNIINTEL_WORKER_TOKEN: "internal-worker-test-secret",
        },
      },
    })),
  ],
  test: {
    setupFiles: ["./test/apply-migrations.ts"],
  },
});
