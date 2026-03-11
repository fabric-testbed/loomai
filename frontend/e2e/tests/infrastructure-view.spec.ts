import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('Infrastructure View', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/');
    // Navigate to infrastructure view
    await page.locator('.landing-tile', { hasText: 'Infrastructure' }).click();
  });

  test('infrastructure view loads', async ({ page }) => {
    await expect(page.locator('.infra-view')).toBeVisible();
  });

  test('has Map and Browse tabs', async ({ page }) => {
    const tabs = page.locator('.infra-subtab');
    await expect(tabs).toHaveCount(2);
    await expect(tabs.nth(0)).toHaveText('Map');
    await expect(tabs.nth(1)).toHaveText('Browse');
  });

  test('Browse tab shows site list', async ({ page }) => {
    // Click Browse tab
    await page.locator('.infra-subtab', { hasText: 'Browse' }).click();
    // Should show site data from our mock
    await expect(page.locator('.infra-content')).toBeVisible();
  });

  test('update resources button exists', async ({ page }) => {
    const refreshBtn = page.locator('.infra-refresh-btn');
    await expect(refreshBtn).toBeVisible();
  });
});
