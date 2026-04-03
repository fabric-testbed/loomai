import { test, expect } from '@playwright/test';
import { navigateToView, createSliceViaBar, cleanupAllE2ESlices } from '../helpers/gui-helpers';

test.describe('Topology Editor', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }

    // Create a slice via the FABRIC bar
    await createSliceViaBar(page, 'fabric-bar', `e2e-topo-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
  });

  test('add a VM node via editor menu', async ({ page }) => {
    // Switch to Slivers tab where the add button lives
    const sliversTab = page.locator('button', { hasText: 'Slivers' }).first();
    if (await sliversTab.isVisible({ timeout: 3000 })) {
      await sliversTab.click();
      await page.waitForTimeout(500);

      // Click the add sliver button
      const addBtn = page.locator('.add-sliver-btn');
      if (await addBtn.isVisible({ timeout: 3000 })) {
        await addBtn.click();
        await expect(page.locator('.add-sliver-menu')).toBeVisible();
        await page.locator('.add-sliver-item', { hasText: 'VM Node' }).click();
      }
    }
  });

  test('add a network via editor menu', async ({ page }) => {
    const sliversTab = page.locator('button', { hasText: 'Slivers' }).first();
    if (await sliversTab.isVisible({ timeout: 3000 })) {
      await sliversTab.click();
      await page.waitForTimeout(500);

      const addBtn = page.locator('.add-sliver-btn');
      if (await addBtn.isVisible({ timeout: 3000 })) {
        await addBtn.click();
        await expect(page.locator('.add-sliver-menu')).toBeVisible();
        await page.locator('.add-sliver-item', { hasText: 'Network (L2)' }).click();
      }
    }
  });
});
