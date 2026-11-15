import { expect, test } from "@playwright/test";
import { onboard, openFirstApproval } from "./helpers";

test("a draft shows its evidence, costs nothing until approved, then is submitted exactly once", async ({ page }) => {
  await onboard(page);
  await openFirstApproval(page);
  const claim = page.locator(".claim.supported, .claim.partly_supported").first();
  await claim.focus();                                                   // keyboard users get the evidence too
  await expect(claim.getByRole("tooltip")).toBeVisible();
  await expect(page.getByText("Connects this will spend")).toBeVisible();
  await page.getByText("Exactly what will be sent (dry run)").click();
  await expect(page.locator("pre")).toContainText("cover_letter");
  await page.getByRole("button", { name: /Approve and submit/ }).click();
  await expect(page.getByText(/Submitted\. Track it/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve and submit/ })).toHaveCount(0);   // cannot be approved twice
  await page.getByRole("link", { name: "pipeline board" }).click();
  await expect(page.getByRole("listitem", { name: /(submitted|viewed|replied|interview|hired|lost): 1/ })).toBeVisible();
});
