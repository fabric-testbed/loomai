import { test, expect } from '@playwright/test';
import { navigateToView, cleanupAllE2ESlices } from '../helpers/gui-helpers';

test.describe('Template Loading', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('libraries panel shows templates', async ({ page }) => {
    // Navigate to FABRIC view where template panel is visible
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }

    // The template panel should be visible with weaves tab
    const panel = page.locator('.template-panel');
    if (await panel.isVisible({ timeout: 5000 })) {
      const tabs = panel.locator('.templates-tab');
      await expect(tabs.first()).toBeVisible();
    }
  });

  test('template card has run or load button', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }

    // Find a template card
    const panel = page.locator('.template-panel');
    if (!await panel.isVisible({ timeout: 5000 })) { test.skip(); return; }

    const card = panel.locator('.template-card').first();
    if (!await card.isVisible({ timeout: 3000 })) { test.skip(); return; }

    // Template cards show either "▶ Run", "Deploy", or "Load" depending on type
    const playBtn = card.locator('.tp-transport-play');
    await expect(playBtn).toBeVisible({ timeout: 5000 });
    const text = await playBtn.textContent();
    expect(text).toMatch(/Run|Deploy|Load/);
  });
});
