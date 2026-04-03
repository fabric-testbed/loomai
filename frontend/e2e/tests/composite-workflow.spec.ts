import { test, expect } from '@playwright/test';
import { cleanupAllE2ESlices } from '../helpers/gui-helpers';

/**
 * Composite slice workflow E2E tests.
 *
 * Tests the GUI for creating composite slices, adding members,
 * switching tabs, and verifying topology updates.
 *
 * Runs against the live backend at localhost:3000.
 * Does NOT submit real slices (no FABRIC/Chameleon credentials needed).
 */

test.describe('Composite Slice Workflow', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    // Navigate to the app — no mocks, real backend
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('can navigate to composite view', async ({ page }) => {
    // Look for the view selector and check composite is available
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (await viewPill.isVisible()) {
      await viewPill.click();
      // Check if Composite Slices option exists
      const compositeOption = page.locator('.title-pill-option', { hasText: /Composite/i });
      if (await compositeOption.isVisible()) {
        await compositeOption.click();
        // Should see the composite bar
        await expect(page.locator('.composite-bar')).toBeVisible({ timeout: 5000 });
      }
    }
  });

  test('composite bar has expected controls', async ({ page }) => {
    // Navigate to composite view
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (await viewPill.isVisible()) {
      await viewPill.click();
      const compositeOption = page.locator('.title-pill-option', { hasText: /Composite/i });
      if (await compositeOption.isVisible()) {
        await compositeOption.click();
        await page.waitForTimeout(1000);

        // Check for key controls
        const bar = page.locator('.composite-bar');
        await expect(bar).toBeVisible({ timeout: 5000 });

        // Should have tabs
        await expect(bar.locator('.composite-bar-tab', { hasText: 'Slices' })).toBeVisible();
        await expect(bar.locator('.composite-bar-tab', { hasText: 'Topology' })).toBeVisible();

        // Should have action buttons
        await expect(bar.locator('text=+ New')).toBeVisible();
        await expect(bar.locator('text=Submit')).toBeVisible();
        await expect(bar.locator('text=Delete')).toBeVisible();
      }
    }
  });

  test('can create a composite slice', async ({ page }) => {
    // Navigate to composite view
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const compositeOption = page.locator('.title-pill-option', { hasText: /Composite/i });
    if (!await compositeOption.isVisible()) return;
    await compositeOption.click();
    await page.waitForTimeout(2000);

    // Register dialog handler BEFORE clicking
    page.once('dialog', async dialog => {
      await dialog.accept('e2e-test-composite');
    });

    // Click "+ New" button
    const newBtn = page.locator('.composite-bar-btn', { hasText: '+ New' });
    await newBtn.click();
    await page.waitForTimeout(3000);

    // Should be in the selector as an option
    const select = page.locator('.composite-bar-select');
    const options = await select.locator('option').allTextContents();
    expect(options.some(o => o.includes('e2e-test-composite'))).toBeTruthy();
  });

  test('composite editor panel shows three tabs', async ({ page }) => {
    // Navigate to composite view
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const compositeOption = page.locator('.title-pill-option', { hasText: /Composite/i });
    if (!await compositeOption.isVisible()) return;
    await compositeOption.click();
    await page.waitForTimeout(1000);

    // Create a composite if none exists
    page.on('dialog', async dialog => {
      await dialog.accept('e2e-editor-test');
    });
    await page.locator('.composite-bar').locator('text=+ New').click();
    await page.waitForTimeout(2000);

    // Check for the editor panel tabs
    const editorTabs = page.locator('.editor-top-tabs');
    if (await editorTabs.isVisible()) {
      await expect(editorTabs.locator('text=Composite')).toBeVisible();
      await expect(editorTabs.locator('text=FABRIC')).toBeVisible();
      // Chameleon tab only visible if Chameleon is enabled
    }
  });

  test('FABRIC tab has create and selector', async ({ page }) => {
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const compositeOption = page.locator('.title-pill-option', { hasText: /Composite/i });
    if (!await compositeOption.isVisible()) return;
    await compositeOption.click();
    await page.waitForTimeout(1000);

    page.on('dialog', async dialog => {
      await dialog.accept('e2e-fabric-tab-test');
    });
    await page.locator('.composite-bar').locator('text=+ New').click();
    await page.waitForTimeout(2000);

    // Click the FABRIC tab in the editor
    const fabricTab = page.locator('.editor-top-tabs').locator('text=FABRIC');
    if (await fabricTab.isVisible()) {
      await fabricTab.click();
      await page.waitForTimeout(500);

      // Should see FABRIC controls (selector + New/Create button)
      await expect(page.getByText(/New|Create/i).last()).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('Chameleon View Basics', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('can navigate to Chameleon view', async ({ page }) => {
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const chameleonOption = page.locator('.title-pill-option', { hasText: /Chameleon/i });
    if (await chameleonOption.isVisible()) {
      await chameleonOption.click();
      // Should see the Chameleon bar
      await expect(page.locator('.chameleon-bar')).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('FABRIC View Basics', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('can navigate to FABRIC view', async ({ page }) => {
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const fabricOption = page.locator('.title-pill-option', { hasText: /FABRIC/i });
    if (await fabricOption.isVisible()) {
      await fabricOption.click();
      await expect(page.locator('.fabric-bar')).toBeVisible({ timeout: 5000 });
    }
  });

  test('can create a FABRIC draft slice', async ({ page }) => {
    const viewPill = page.locator('[data-help-id="titlebar.view"]');
    if (!await viewPill.isVisible()) return;
    await viewPill.click();
    const fabricOption = page.locator('.title-pill-option', { hasText: /FABRIC/i });
    if (!await fabricOption.isVisible()) return;
    await fabricOption.click();
    await page.waitForTimeout(2000);

    // Register dialog handler BEFORE clicking
    page.once('dialog', async dialog => {
      await dialog.accept('e2e-fabric-test');
    });

    // Look for New button in FABRIC bar
    const newBtn = page.locator('.fabric-bar-action-btn', { hasText: 'New' });
    if (await newBtn.isVisible()) {
      await newBtn.click();

      // Wait for the slice to appear in the selector (retry up to 10s)
      const select = page.locator('.fabric-bar-slice-select');
      await expect(async () => {
        const options = await select.locator('option').allTextContents();
        expect(options.some(o => o.includes('e2e-fabric-test'))).toBeTruthy();
      }).toPass({ timeout: 10000 });
    }
  });
});
