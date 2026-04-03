import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('Dark Mode', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('defaults to light mode', async ({ page }) => {
    await page.goto('/');
    // Wait for React to hydrate — landing hero section is the indicator
    await expect(page.locator('.landing-hero')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('toggle to dark mode', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-help-id="titlebar.theme"]').click();
    const theme = await page.locator('html').getAttribute('data-theme');
    expect(theme).toBe('dark');
  });

  test('toggle back to light mode', async ({ page }) => {
    await page.goto('/');
    // Toggle dark
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Toggle light
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('dark mode persists across reload', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Reload and check
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });
});
