import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('Landing Page', () => {
  test.describe('with mocks', () => {
    test.beforeEach(async ({ page }) => {
      await mockAllApis(page);
      await page.goto('/');
    });

    test('app loads and shows landing page', async ({ page }) => {
      await expect(page.locator('.landing-hero')).toBeVisible();
      await expect(page.locator('img[alt="LoomAI"]').first()).toBeVisible();
    });

    test('landing page has quick link tiles', async ({ page }) => {
      const tiles = page.locator('.landing-tile');
      await expect(tiles).toHaveCount(4);
      const labels = tiles.locator('.landing-tile-label');
      await expect(labels.nth(0)).toHaveText('Slices');
      await expect(labels.nth(1)).toHaveText('Artifacts');
      await expect(labels.nth(2)).toHaveText('Infrastructure');
      await expect(labels.nth(3)).toHaveText('JupyterLab');
    });
  });

  test.describe('navigation (live server)', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await page.waitForTimeout(3000);
    });

    test('navigate to Slices via tile click', async ({ page }) => {
      const tile = page.locator('.landing-tile', { hasText: 'Slices' });
      if (!await tile.isVisible({ timeout: 3000 })) { test.skip(); return; }
      await tile.click();
      // "Slices" tile navigates to the Composite Slice view
      await expect(page.locator('.composite-bar')).toBeVisible({ timeout: 5000 });
    });

    test('navigate to Infrastructure via tile click', async ({ page }) => {
      const tile = page.locator('.landing-tile', { hasText: 'Infrastructure' });
      if (!await tile.isVisible({ timeout: 3000 })) { test.skip(); return; }
      await tile.click();
      await expect(page.locator('.fabric-bar')).toBeVisible({ timeout: 5000 });
    });

    test('navigate via View pill in title bar', async ({ page }) => {
      const viewPill = page.locator('[data-help-id="titlebar.view"]');
      if (!await viewPill.isVisible({ timeout: 3000 })) { test.skip(); return; }
      await viewPill.click();
      await page.locator('.title-pill-option', { hasText: 'FABRIC' }).click();
      await expect(page.locator('.fabric-bar')).toBeVisible({ timeout: 5000 });
    });
  });
});
