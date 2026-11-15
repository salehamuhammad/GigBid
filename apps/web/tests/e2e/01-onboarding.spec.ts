import { expect, test } from "@playwright/test";
import { onboard } from "./helpers";

test("signed-out users are sent to sign-in; a new user onboards and sees scouted jobs", async ({ page }) => {
  await page.goto("/inbox");
  await expect(page).toHaveURL(/signin/);
  await onboard(page);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();          // the Scout ran on onboarding
  await expect(page.getByText(/Simulator: GigSim/)).toBeVisible();
});

test("wrong password shows a clear error, not a blank screen", async ({ page }) => {
  await page.goto("/signin");
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Wrong email or password/)).toBeVisible();
});
