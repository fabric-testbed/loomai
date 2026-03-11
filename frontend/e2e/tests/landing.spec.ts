import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('Landing Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/');
  });

  test('app loads and shows landing page', async ({ page }) => {
    await expect(page.locator('.landing-hero-title')).toBeVisible();
    await expect(page.locator('.landing-brand')).toHaveText('LoomAI');
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

  test('navigate to Slices via tile click', async ({ page }) => {
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();
    // Should switch to slices view — toolbar becomes visible
    await expect(page.locator('.toolbar-btn-new')).toBeVisible();
  });

  test('navigate to Infrastructure via tile click', async ({ page }) => {
    await page.locator('.landing-tile', { hasText: 'Infrastructure' }).click();
    await expect(page.locator('.infra-view')).toBeVisible();
  });

  test('navigate via View pill in title bar', async ({ page }) => {
    // Open view dropdown
    await page.locator('[data-help-id="titlebar.view"]').click();
    // Click "Slices" option
    await page.locator('.title-pill-option', { hasText: 'Slices' }).click();
    await expect(page.locator('.toolbar-btn-new')).toBeVisible();
  });
});
