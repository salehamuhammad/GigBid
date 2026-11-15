import { expect, test } from "@playwright/test";
import { onboard } from "./helpers";

test("run viewer shows nodes, cost and trace id; settings persist; analytics renders", async ({ page }) => {
  await onboard(page);
  await expect(page.locator("tbody tr").first().locator("td").nth(2)).toContainText("%");
  await page.getByRole("link", { name: "Agent runs" }).click();
  await expect(page.getByRole("heading", { name: "Agent runs" })).toBeVisible();
  await page.locator("tbody tr").first().getByRole("link").click();
  await expect(page.getByRole("heading", { name: "Node by node" })).toBeVisible();
  for (const node of ["analyst", "risk", "matcher", "decide"]) await expect(page.getByRole("cell", { name: node, exact: true }).first()).toBeVisible();
  await expect(page.getByText(/^tr-/).first()).toBeVisible();

  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByLabel("Weekly Connects budget").fill("42");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Settings saved." })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("42");
  await expect(page.getByRole("heading", { name: "What GigBid has learned" })).toBeVisible();

  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page.getByRole("heading", { name: "Funnel" })).toBeVisible();
});
