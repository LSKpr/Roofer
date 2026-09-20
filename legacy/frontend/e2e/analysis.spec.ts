import { expect, test } from "@playwright/test";

test("visually switches between aerial imagery and the standard map", async ({ page }) => {
  await page.goto("/");
  const canvas = page.locator(".maplibregl-canvas");
  await expect(canvas).toBeVisible();
  await page.waitForTimeout(2000);
  const aerial = await canvas.screenshot();
  await page.getByRole("button", { name: "Standard map" }).click();
  await page.waitForTimeout(500);
  const standard = await canvas.screenshot();
  expect(Buffer.compare(aerial, standard)).not.toBe(0);
  await expect(page.getByRole("button", { name: "Aerial imagery" })).toBeVisible();
});

test("shows the selected region after dragging a rectangle", async ({ page }) => {
  await page.goto("/");
  const canvas = page.locator(".maplibregl-canvas");
  await expect(canvas).toBeVisible();
  await page.getByRole("button", { name: "Draw rectangle" }).click();
  await expect(page.getByRole("status")).toContainText("Press on the map");
  const bounds = await canvas.boundingBox();
  if (!bounds) throw new Error("Map canvas is not visible");
  const before = await canvas.screenshot();
  await page.mouse.move(bounds.x + 500, bounds.y + 300);
  await page.mouse.down();
  await page.mouse.move(bounds.x + 580, bounds.y + 360, { steps: 5 });
  const preview = await canvas.screenshot();
  await page.mouse.up();
  const selected = await canvas.screenshot();
  expect(Buffer.compare(before, preview)).not.toBe(0);
  expect(Buffer.compare(before, selected)).not.toBe(0);
  const boundingRectangle = page.locator(".overlay-selection");
  await expect(boundingRectangle).toBeVisible();
  const rectangleBox = await boundingRectangle.boundingBox();
  expect(rectangleBox?.width).toBeGreaterThan(70);
  expect(rectangleBox?.height).toBeGreaterThan(50);
  await expect(page.getByText("Selected area", { exact: true })).toBeVisible();
});

test("draws a polygon selection above the map", async ({ page }) => {
  await page.goto("/");
  const stage = page.locator(".map-stage");
  await expect(stage).toBeVisible();
  await page.getByRole("button", { name: "Draw polygon" }).click();
  const bounds = await stage.boundingBox();
  if (!bounds) throw new Error("Map stage is not visible");
  await page.mouse.click(bounds.x + 480, bounds.y + 280);
  await page.mouse.click(bounds.x + 620, bounds.y + 300);
  await page.mouse.move(bounds.x + 600, bounds.y + 420);
  await expect(page.locator(".overlay-draft-line")).toBeVisible();
  await expect(page.locator(".overlay-draft-vertex")).toBeVisible();
  await page.mouse.click(bounds.x + 600, bounds.y + 420);
  await page.mouse.dblclick(bounds.x + 470, bounds.y + 420);
  await expect(page.getByText("Selected area", { exact: true })).toBeVisible();
  const selection = page.locator(".overlay-selection");
  await expect(selection).toBeVisible();
  const selectionBox = await selection.boundingBox();
  expect(selectionBox?.width).toBeGreaterThan(90);
  expect(selectionBox?.height).toBeGreaterThan(90);
});

test("load demo area, analyze fixture, render a listed building, and open evidence", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Draw, verify, analyze" })).toBeVisible();
  await page.getByRole("button", { name: "Load Warsaw demo area" }).click();
  await expect(page.getByRole("button", { name: "Analyze area" })).toBeEnabled();
  await page.getByRole("button", { name: "Analyze area" }).click();
  await expect(page.getByText("Complete", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".stats > div").filter({ hasText: "registry listed asbestos buildings" })).toContainText("1");
  const detailResponse = page.waitForResponse((response) => response.url().includes("/api/v1/buildings/") && response.status() === 200);
  const canvas = page.locator(".maplibregl-canvas");
  const beforeSelection = await canvas.screenshot();
  const listedBuilding = page.getByRole("button", { name: /Building 100001/ });
  await listedBuilding.click();
  await expect(listedBuilding).toHaveClass(/selected/);
  await detailResponse;
  await page.waitForTimeout(1200);
  const afterSelection = await canvas.screenshot();
  expect(Buffer.compare(beforeSelection, afterSelection)).not.toBe(0);
  const buildingOutline = page.locator(".overlay-building");
  await expect(buildingOutline).toBeVisible();
  const outlineBox = await buildingOutline.boundingBox();
  expect(outlineBox?.width).toBeGreaterThan(40);
  expect(outlineBox?.height).toBeGreaterThan(40);
  await expect(page.getByText("Building evidence", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Listed in registry" })).toBeVisible();
});
