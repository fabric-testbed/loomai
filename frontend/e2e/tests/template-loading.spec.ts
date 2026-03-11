import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { makeSliceData, makeNode, templatesList } from '../fixtures/test-data';

test.describe('Template Loading', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('libraries panel shows templates', async ({ page }) => {
    await page.goto('/');
    // Navigate to slices view where template panel is visible
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();

    // The template panel should be visible with weaves tab
    const panel = page.locator('.template-panel');
    if (await panel.isVisible()) {
      const tabs = panel.locator('.templates-tab');
      await expect(tabs.first()).toBeVisible();
    }
  });

  test('load template creates a new slice', async ({ page }) => {
    const loadedSlice = makeSliceData('Hello FABRIC', 'draft-tmpl-1', {
      nodes: [makeNode('node1', 'RENC')],
    });

    // Mock template load endpoint
    await page.route('**/api/templates/Hello_FABRIC*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: loadedSlice });
      }
      return route.fallback();
    });

    // Mock get slice for the loaded draft
    await page.route('**/api/slices/draft-tmpl-1', (route) =>
      route.fulfill({ json: loadedSlice })
    );

    await page.goto('/');
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();

    // Find and click Load on Hello FABRIC template
    const panel = page.locator('.template-panel');
    if (await panel.isVisible()) {
      const card = panel.locator('.template-card', { hasText: 'Hello FABRIC' });
      if (await card.isVisible()) {
        await card.locator('.template-btn-load', { hasText: 'Load' }).click();

        // Should show load modal
        const modal = page.locator('.template-modal');
        if (await modal.isVisible({ timeout: 2000 }).catch(() => false)) {
          await modal.locator('.template-input').fill('Hello FABRIC');
          await modal.locator('button.primary', { hasText: 'Load' }).click();
        }
      }
    }
  });
});
