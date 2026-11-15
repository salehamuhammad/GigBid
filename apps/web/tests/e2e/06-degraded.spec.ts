import { expect, test } from "@playwright/test";
import { onboard } from "./helpers";

test("an unavailable marketplace shows queued work and clears after recovery", async ({ page }) => {
  await onboard(page);
  const health = "**/api/system/health";
  await page.route(health, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, status: "degraded", marketplace: { ok: false }, queued_jobs: 2 },
    });
  });
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Marketplace unavailable." }))
    .toContainText("2 jobs queued");
  await page.unroute(health);
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Marketplace unavailable." })).toHaveCount(0);
});
