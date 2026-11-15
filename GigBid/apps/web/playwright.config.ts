import { defineConfig } from "@playwright/test";

/** E2E against a running stack (`make dev`, or docker compose). BASE_URL defaults to http://localhost:3000.
 *  Set PW_CHANNEL=chrome to use an installed Chrome instead of Playwright's bundled Chromium. */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.BASE_URL || "http://localhost:3000", trace: "retain-on-failure", channel: process.env.PW_CHANNEL || undefined },
});
