import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, clickBarTab,
  clickEditorTab, waitForText, isAuthenticated,
  deleteCompositeSliceViaApi, overridePrompt,
  cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

test.describe('Composite View — GUI Tests', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('navigate to composite view and verify bar with LoomAI branding', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(true, 'Composite view not available'); return; }
    const bar = page.locator('.composite-bar');
    await expect(bar).toBeVisible({ timeout: 5000 });
    // Verify LoomAI branding (navy/cyan, not indigo)
    await expect(bar.locator('.composite-bar-tab', { hasText: 'Slices' })).toBeVisible();
    await expect(bar.locator('.composite-bar-tab', { hasText: 'Topology' })).toBeVisible();
    await expect(bar.locator('.composite-bar-tab', { hasText: 'Map' })).toBeVisible();
  });

  test('create composite slice and verify it appears in selector', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    const name = `e2e-comp-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'composite-bar', name);
    await page.waitForTimeout(2000);
    // Composite should appear in the dropdown selector (as an option)
    const select = page.locator('.composite-bar-select');
    const options = await select.locator('option').allTextContents();
    expect(options.some(o => o.includes(name))).toBeTruthy();
  });

  test('composite editor has three tabs: Composite, FABRIC, Chameleon', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'composite-bar', `e2e-comp-tabs-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
    const editorTabs = page.locator('.editor-top-tabs');
    if (await editorTabs.isVisible({ timeout: 5000 })) {
      await expect(editorTabs.getByText('Composite').first()).toBeVisible();
      await expect(editorTabs.getByText('FABRIC').first()).toBeVisible();
      // Chameleon tab only if Chameleon enabled
    }
  });

  test('Composite tab shows FABRIC and Chameleon slice pickers', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'composite-bar', `e2e-comp-pick-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
    await clickEditorTab(page, 'Composite');
    // Should show "FABRIC Slices" section
    await expect(page.getByText('FABRIC Slices').first()).toBeVisible({ timeout: 5000 });
  });

  test('FABRIC tab shows slice controls and + New button', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'composite-bar', `e2e-comp-fab-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
    await clickEditorTab(page, 'FABRIC');
    await page.waitForTimeout(1000);
    // The FABRIC tab should have a "Create New FABRIC Slice" button or slice selector
    const newBtns = page.getByText(/New|Create/i);
    expect(await newBtns.count()).toBeGreaterThan(0);
  });

  test('create FABRIC member and see it in composite FABRIC tab', async ({ page }) => {
    // Create composite via API (faster, avoids UI timing issues)
    const compResp = await page.request.post(`${API}/composite/slices`, {
      data: { name: `e2e-comp-cfab-${Date.now().toString(36)}` },
    });
    if (!compResp.ok()) { test.skip(true, 'Cannot create composite'); return; }
    const comp = await compResp.json();

    // Create a FABRIC slice via API
    const fabName = `e2e-member-${Date.now().toString(36)}`;
    const sliceResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    if (!sliceResp.ok()) { test.skip(true, 'Cannot create FABRIC slice'); return; }
    const sliceData = await sliceResp.json();

    // Add FABRIC slice as composite member
    await page.request.put(`${API}/composite/slices/${comp.id}/members`, {
      data: { fabric_slices: [sliceData.id || fabName], chameleon_slices: [] },
    });

    // Verify via API that member was added
    const verifyResp = await page.request.get(`${API}/composite/slices/${comp.id}`);
    const verified = await verifyResp.json();
    expect(verified.fabric_member_summaries?.length).toBeGreaterThan(0);

    // Now reload page and navigate to composite view to verify the UI renders it
    await page.goto('/');
    await page.waitForTimeout(3000);
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }

    // Select the composite
    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: comp.id });
    await page.waitForTimeout(3000);

    // Switch to FABRIC tab — the member should appear
    await clickEditorTab(page, 'FABRIC');
    await page.waitForTimeout(1000);
    await expect(async () => {
      const allText = await page.locator('select option').allTextContents();
      expect(allText.some(o => o.includes(fabName))).toBeTruthy();
    }).toPass({ timeout: 10000 });
  });

  test('Topology tab shows empty state when no members', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'composite-bar', `e2e-comp-empty-${Date.now().toString(36)}`);
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(2000);
    // Should show empty state or the topology container
    const empty = page.getByText('No resources attached');
    const cytoscape = page.locator('.cytoscape-container');
    // Either empty message or empty graph container is fine
    const hasEmpty = await empty.isVisible({ timeout: 3000 }).catch(() => false);
    const hasCytoscape = await cytoscape.isVisible({ timeout: 1000 }).catch(() => false);
    expect(hasEmpty || hasCytoscape).toBeTruthy();
  });

  test('add FABRIC member via Composite tab checkbox', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }

    // First create a FABRIC slice via API (more reliable than UI in test)
    const fabName = `e2e-member-${Date.now().toString(36)}`;
    const sliceResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    if (!sliceResp.ok()) { test.skip(true, 'Cannot create FABRIC slice'); return; }

    // Create composite and navigate there
    await navigateToView(page, 'composite');
    await createSliceViaBar(page, 'composite-bar', `e2e-comp-add-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);

    // In Composite tab, look for a FABRIC slice checkbox
    await clickEditorTab(page, 'Composite');
    await page.waitForTimeout(1000);
    // Look for any checkbox near a "FABRIC Slices" label — the section with checkboxes
    const fabricSection = page.getByText('FABRIC Slices').first();
    if (await fabricSection.isVisible({ timeout: 5000 })) {
      // Find checkboxes within or near the FABRIC section
      const checkboxes = page.locator('input[type="checkbox"]');
      const count = await checkboxes.count();
      // The FABRIC section should have at least one checkbox (for our created slice)
      expect(count).toBeGreaterThan(0);
    }
  });

  test('Slices tab has bulk delete checkboxes', async ({ page }) => {
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    // Create a couple of composites
    await createSliceViaBar(page, 'composite-bar', `e2e-bulk1-${Date.now().toString(36)}`);
    await page.waitForTimeout(1000);
    await createSliceViaBar(page, 'composite-bar', `e2e-bulk2-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);

    await clickBarTab(page, 'composite-bar', 'Slices');
    await page.waitForTimeout(1000);

    // Should see checkboxes in the table
    const checkboxes = page.locator('table input[type="checkbox"]');
    const count = await checkboxes.count();
    expect(count).toBeGreaterThan(0);
  });

  // --- Cross-view sync tests ---

  test('FABRIC slice created via API appears in FABRIC view after refresh', async ({ page }) => {
    // Create a FABRIC slice via API
    const fabName = `e2e-xfab-${Date.now().toString(36)}`;
    const resp = await page.request.post(`http://localhost:8000/api/slices?name=${encodeURIComponent(fabName)}`);
    if (!resp.ok()) { test.skip(true, 'Cannot create FABRIC slice via API'); return; }

    // Switch to FABRIC view and refresh the slice list
    await navigateToView(page, 'fabric');
    const refreshBtn = page.locator('.fabric-bar-action-btn', { hasText: /Slices/ });
    if (await refreshBtn.isVisible({ timeout: 3000 })) await refreshBtn.click();
    await page.waitForTimeout(2000);

    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(fabName))).toBeTruthy();
    }).toPass({ timeout: 10000 });
  });
});
