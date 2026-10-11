import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  outputDir: process.env.FSP_TEST_OUTPUT || "test-results",
  workers: 1,
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
  timeout: 45000,
  use: {
    baseURL: process.env.FSP_TEST_URL || "http://127.0.0.1:8470",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
