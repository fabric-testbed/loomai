import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('Dark Mode', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('defaults to light mode', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: /View FABRIC/ })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('toggle to dark mode', async ({ page }) => {
    await page.goto('/');
    // The theme toggle lives inside the title-user menu — open it first.
    await page.locator('[data-help-id="titlebar.user"]').click();
    await page.locator('[data-help-id="titlebar.theme"]').click();
    const theme = await page.locator('html').getAttribute('data-theme');
    expect(theme).toBe('dark');
  });

  test('toggle back to light mode', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-help-id="titlebar.user"]').click();   // open the user menu
    // Toggle dark (the menu stays open after a theme click)
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Toggle light
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('dark mode persists across reload', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-help-id="titlebar.user"]').click();   // open the user menu
    await page.locator('[data-help-id="titlebar.theme"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    // Reload and check
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });
});
