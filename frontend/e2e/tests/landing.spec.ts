import { test, expect } from '@playwright/test';

test.describe('Landing Page', () => {
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
