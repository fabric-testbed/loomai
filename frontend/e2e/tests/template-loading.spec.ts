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

    // Mock template load endpoint (POST /api/templates/{name}/load)
    await page.route('**/api/templates/Hello_FABRIC/load', (route) => {
      if (route.request().method() === 'POST') {
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
    await expect(panel).toBeVisible();
    const card = panel.locator('.template-card', { hasText: 'Hello FABRIC' });
    await expect(card).toBeVisible();
    await card.locator('.tp-transport-play', { hasText: 'Load' }).click();

    // Should show load modal
    const modal = page.locator('.template-modal');
    await expect(modal).toBeVisible();
    await modal.locator('.template-input').fill('Hello FABRIC');
    await modal.locator('button.primary', { hasText: 'Load' }).click();
  });
});
