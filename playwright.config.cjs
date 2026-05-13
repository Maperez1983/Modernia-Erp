// @ts-check
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./playwright",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PW_BASE_URL || "http://127.0.0.1:8011",
    headless: true,
    viewport: { width: 1400, height: 900 },
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});

