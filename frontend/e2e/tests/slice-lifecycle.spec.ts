import { test, expect } from '@playwright/test';
import { navigateToView, createSliceViaBar, cleanupAllE2ESlices } from '../helpers/gui-helpers';

test.describe('Slice Lifecycle', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('create a new slice', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }

    const name = `e2e-lifecycle-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'fabric-bar', name);

    // Wait for the slice to appear in the dropdown selector (retry up to 10s)
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
  });

  test('delete a slice', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }

    // Create a slice first
    const name = `e2e-del-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'fabric-bar', name);

    // Wait for the slice to appear in the dropdown selector
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });

    // Select the new slice
    const options = await select.locator('option').allTextContents();
    const match = options.find(o => o.includes(name));
    if (match) await select.selectOption({ label: match });
    await page.waitForTimeout(1000);

    // Handle the confirm dialog
    page.once('dialog', async (dialog) => {
      await dialog.accept();
    });

    // Click Delete button
    await page.locator('.fabric-bar-action-btn', { hasText: 'Delete' }).click();
    await page.waitForTimeout(2000);
  });
});
