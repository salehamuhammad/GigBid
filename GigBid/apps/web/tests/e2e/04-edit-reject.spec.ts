import { expect, test } from "@playwright/test";
import { onboard, openFirstApproval } from "./helpers";

test("an edit is diffed and re-checked by Compliance; a reject needs a reason", async ({ page }) => {
  await onboard(page);
  await openFirstApproval(page);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const box = page.getByLabel("Edit the draft");
  await box.fill((await box.inputValue()) + " Email me at someone@example.com.");
  await page.getByRole("button", { name: "Save edit and re-check" }).click();
  await expect(page.getByRole("heading", { name: "Your last edit" })).toBeVisible();
  await expect(page.getByTestId("letter")).not.toContainText("someone@example.com");       // contact details removed
  await expect(page.getByText(/Removed: contact_email/)).toBeVisible();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByRole("button", { name: "Confirm reject" })).toBeDisabled();       // reason is required
  await page.getByLabel("Why are you rejecting it?").fill("Budget is too low for the scope");
  await page.getByRole("button", { name: "Confirm reject" }).click();
  await page.goto("/pipeline");
  await expect(page.getByText("Budget is too low for the scope")).toBeVisible();
});
