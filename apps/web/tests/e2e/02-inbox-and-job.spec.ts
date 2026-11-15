import { expect, test } from "@playwright/test";
import { onboard } from "./helpers";

test("inbox filters and sorts; job detail shows the requirement-to-evidence matrix, risk and price", async ({ page }) => {
  await onboard(page);
  const rows = page.locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first().locator("td").nth(2)).toContainText("%");    // analysed: a fit score is shown
  await page.getByLabel("Sort").selectOption("budget");
  await page.getByRole("button", { name: "Skipped" }).click();
  await expect(page.getByRole("button", { name: "Skipped" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Needs my approval" }).click();
  await expect(rows.first()).toBeVisible();
  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(/\/jobs\//);
  await expect(page.getByRole("heading", { name: /Requirement/ })).toBeVisible();
  await expect(page.getByText("Evidence from your portfolio", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Risk/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Recommendation/ })).toBeVisible();
});
