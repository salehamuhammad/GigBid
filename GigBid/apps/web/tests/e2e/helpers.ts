import { expect, type Page } from "@playwright/test";

/** Register a fresh user, finish onboarding with the AI-engineer sample portfolio, land on the inbox. */
export async function onboard(page: Page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e5)}@example.com`;
  await page.goto("/signin");
  await page.getByRole("button", { name: /create an account/i }).click();
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/onboarding/);
  await page.getByRole("button", { name: /Ayesha Raza/ }).click();
  await page.getByRole("button", { name: /Finish and open my inbox/ }).click();
  await expect(page).toHaveURL(/inbox/);
  return email;
}

/** Wait until the agents have a draft waiting for approval, then open its proposal studio. */
export async function openFirstApproval(page: Page) {
  await page.getByRole("button", { name: "Needs my approval" }).click();
  const row = page.locator("tbody tr").first();
  await expect(async () => {
    if (!(await row.isVisible())) await page.getByRole("button", { name: "Scout now" }).click();
    await expect(row).toBeVisible({ timeout: 15_000 });
  }).toPass({ timeout: 110_000 });
  await row.getByRole("link").click();
  await page.getByRole("link", { name: /Review and approve/ }).click();
  await expect(page.getByRole("heading", { name: "Approve this proposal?" })).toBeVisible();
}
