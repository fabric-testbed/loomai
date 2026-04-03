import { test, expect } from '@playwright/test';
import { navigateToView } from '../helpers/gui-helpers';

test.describe('Infrastructure View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
    // Navigate to FABRIC view via the view pill
    const ok = await navigateToView(page, 'fabric');
    if (!ok) test.skip(true, 'FABRIC view not available');
  });

  test('infrastructure view loads', async ({ page }) => {
    await expect(page.locator('.fabric-bar')).toBeVisible();
  });

  test('has Slices, Topology, Map, and Resources tabs', async ({ page }) => {
    const bar = page.locator('.fabric-bar');
    await expect(bar.locator('.fabric-bar-tab', { hasText: 'Slices' })).toBeVisible();
    await expect(bar.locator('.fabric-bar-tab', { hasText: 'Topology' })).toBeVisible();
    await expect(bar.locator('.fabric-bar-tab', { hasText: 'Map' })).toBeVisible();
    await expect(bar.locator('.fabric-bar-tab', { hasText: 'Resources' })).toBeVisible();
  });

  test('Resources tab is clickable', async ({ page }) => {
    await page.locator('.fabric-bar-tab', { hasText: 'Resources' }).click();
    await page.waitForTimeout(500);
  });

  test('Calendar tab is clickable', async ({ page }) => {
    await page.locator('.fabric-bar-tab', { hasText: 'Calendar' }).click();
    await page.waitForTimeout(500);
  });

  test('refresh button exists', async ({ page }) => {
    await expect(page.locator('.fabric-bar-action-btn', { hasText: /Slices/ })).toBeVisible();
    await expect(page.locator('.fabric-bar-action-btn', { hasText: /Resources/ })).toBeVisible();
  });
});
