import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, waitForText,
  clickBarTab, clickEditorTab, isAuthenticated,
  waitForSliceState, deleteSliceViaApi, cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

const SLICE_NAME = `e2e-fab-${Date.now().toString(36)}`;

test.describe('FABRIC View — GUI Tests', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('navigate to FABRIC view and verify bar', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    await expect(page.locator('.fabric-bar')).toBeVisible({ timeout: 5000 });
    // Verify tabs exist
    await expect(page.locator('.fabric-bar-tab', { hasText: 'Slices' })).toBeVisible();
    await expect(page.locator('.fabric-bar-tab', { hasText: 'Topology' })).toBeVisible();
    await expect(page.locator('.fabric-bar-tab', { hasText: 'Map' })).toBeVisible();
  });

  test('Slices tab shows slice table', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    await page.locator('.fabric-bar-tab', { hasText: 'Slices' }).click();
    await page.waitForTimeout(2000);
    // Table header "Slice Name" should be visible
    await expect(page.getByText('Slice Name').first()).toBeVisible({ timeout: 5000 });
  });

  test('create a new FABRIC slice via New button', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'fabric-bar', SLICE_NAME);
    // Wait for slice to appear in selector (retry up to 10s)
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(SLICE_NAME))).toBeTruthy();
    }).toPass({ timeout: 10000 });
  });

  test('select slice and verify editor panel appears', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    // Create a slice first
    await createSliceViaBar(page, 'fabric-bar', `e2e-editor-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
    // The editor panel should be visible
    const editorTabs = page.locator('.editor-top-tabs');
    await expect(editorTabs).toBeVisible({ timeout: 5000 });
    await expect(editorTabs.getByText('Slice').first()).toBeVisible();
    await expect(editorTabs.getByText('Slivers').first()).toBeVisible();
  });

  test('Topology tab shows graph', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'fabric-bar', `e2e-topo-${Date.now().toString(36)}`);
    await page.locator('.fabric-bar-tab', { hasText: 'Topology' }).click();
    // Should see the Cytoscape container
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('Map tab shows map', async ({ page }) => {
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(); return; }
    await page.locator('.fabric-bar-tab', { hasText: 'Map' }).click();
    // Leaflet map container
    await expect(page.locator('.leaflet-container')).toBeVisible({ timeout: 5000 });
  });

  // --- Real provisioning tests (require credentials) ---

  test('submit slice and wait for StableOK', async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated — skipping real provisioning test'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1 to run provisioning tests'); return; }

    const name = `e2e-submit-${Date.now().toString(36)}`;
    await navigateToView(page, 'fabric');
    await createSliceViaBar(page, 'fabric-bar', name);

    // Add a node via the editor
    await clickEditorTab(page, 'Slivers');
    // Click the add menu
    const addBtn = page.locator('[data-help-id="editor.add-menu"]').first();
    if (await addBtn.isVisible({ timeout: 3000 })) {
      await addBtn.click();
      // Select VM option
      const vmOption = page.getByText('VM').first();
      if (await vmOption.isVisible({ timeout: 2000 })) {
        await vmOption.click();
        await page.waitForTimeout(1000);
      }
    }

    // Submit
    const submitBtn = page.locator('.fabric-bar-action-btn', { hasText: 'Submit' });
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
      await page.waitForTimeout(5000);

      // Wait for slice to reach StableOK via API
      const ok = await waitForSliceState(name, 'StableOK', 600000);
      expect(ok).toBeTruthy();
    }

    // Cleanup
    await deleteSliceViaApi(name);
  });
});
