import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function accessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""));
  expect(serious.map((item) => `${item.id}: ${item.nodes.map((node) => node.target).join(" ")}`)).toEqual([]);
}

async function tabTo(page: Page, name: string) {
  for (let presses = 0; presses < 120; presses++) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") || document.activeElement?.textContent?.trim());
    if (focused === name) return;
  }
  throw new Error(`"${name}" cannot be reached with the keyboard`);
}

const calls: string[] = [];
test.afterEach(() => expect(calls, "demo mode needs no backend").toEqual([]));
test.beforeEach(async ({ page }) => {
  page.on("request", (request) => request.url().includes("/api/") && calls.push(request.url()));
  await page.goto("/");
  await expect(page.getByText("Demo mode · recorded runs from the deployed system")).toBeVisible();
});

test("the empty state offers the recorded questions only and passes axe", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Which trains should we inspect this week?" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Is the model drifting?" })).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "Message" })).toBeDisabled();
  await accessible(page);
});

test("a planner gets this week's list as a table and rates it with the keyboard only", async ({ page }) => {
  await tabTo(page, "Which trains should we inspect this week?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("table")).toContainText("EMU 2417");
  await expect(page.getByText("Model version 2; inspection budget")).toBeVisible();
  await tabTo(page, "Helpful");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Helpful", exact: true })).toHaveAttribute("aria-pressed", "true");
  await accessible(page);
});

test("a model owner approves a retraining with the keyboard only", async ({ page }) => {
  await tabTo(page, "Retraining approval");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article", { name: "Approval" })).toContainText("Retrain on the latest fleet data");
  await accessible(page);
  await tabTo(page, "Approve");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await expect(page.getByText(/Retraining started: pipeline job quiet_signal_8/)).toBeVisible();
  await accessible(page);
});

test("a model owner takes a challenger through shadow, canary and 100 % with the keyboard only", async ({ page }) => {
  await tabTo(page, "Shadow, canary and promotion");
  await page.keyboard.press("Enter");
  await tabTo(page, "Approve");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("table")).toContainText("Model 3 · challenger");
  await accessible(page);
  await tabTo(page, "Stop shadow");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("This step is not part of the recording.");
  await tabTo(page, "Start canary");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Promote to 100 %" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Promote to 100 %" })).toBeEnabled({ timeout: 10_000 });
  await accessible(page);
  await tabTo(page, "Promote to 100 %");
  await page.keyboard.press("Enter");
  await tabTo(page, "Close window");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Model 3 serves 100 %; model 2 was removed.")).toBeVisible();
  await accessible(page);
});
