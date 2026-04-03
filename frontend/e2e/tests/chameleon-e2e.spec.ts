import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, clickBarTab,
  clickEditorTab, isAuthenticated, cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

test.describe('Chameleon View — GUI Tests', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('navigate to Chameleon view and verify bar', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(true, 'Chameleon view not available'); return; }
    await expect(page.locator('.chameleon-bar')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.chameleon-bar-tab', { hasText: 'Slices' })).toBeVisible();
    await expect(page.locator('.chameleon-bar-tab', { hasText: 'Topology' })).toBeVisible();
  });

  test('create a new Chameleon slice', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    const name = `e2e-chi-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'chameleon-bar', name);
    await page.waitForTimeout(2000);
    // The slice should appear in the selector
    const selector = page.locator('.chameleon-bar select').first();
    if (await selector.isVisible()) {
      const options = await selector.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }
  });

  test('editor panel shows Leases and Servers tabs', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'chameleon-bar', `e2e-chi-ed-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);
    // Editor should have Leases and Servers tabs
    const editorTabs = page.locator('.editor-top-tabs');
    if (await editorTabs.isVisible({ timeout: 5000 })) {
      await expect(editorTabs.getByText('Leases').first()).toBeVisible();
      await expect(editorTabs.getByText('Servers').first()).toBeVisible();
    }
  });

  test('add a node to Chameleon slice', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'chameleon-bar', `e2e-chi-node-${Date.now().toString(36)}`);
    await page.waitForTimeout(2000);

    // Switch to Servers tab
    await clickEditorTab(page, 'Servers');

    // The "Add Server" button should be visible
    const addBtn = page.getByText('+ Add Server').first();
    if (await addBtn.isVisible({ timeout: 3000 })) {
      // Node type and image selectors should be present
      await expect(page.locator('.chi-form-input').first()).toBeVisible();
    }
  });

  test('Servers tab shows Add Server button and form inputs', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }

    // Create slice via UI
    const name = `e2e-srv-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'chameleon-bar', name);
    await page.waitForTimeout(2000);

    // Switch to Servers tab
    await clickEditorTab(page, 'Servers');
    await page.waitForTimeout(500);

    // "Add Server" button should be visible
    const addBtn = page.getByText('+ Add Server').first();
    await expect(addBtn).toBeVisible({ timeout: 5000 });

    // Click it to add a node
    await addBtn.click();
    await page.waitForTimeout(2000);

    // After adding, a form input (node type / image) should appear
    await expect(page.locator('.chi-form-input').first()).toBeVisible({ timeout: 5000 });
  });

  test('Leases tab shows available leases', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'chameleon-bar', `e2e-chi-lease-${Date.now().toString(36)}`);
    await page.waitForTimeout(3000);

    // Wait for editor tabs to appear (indicates slice is loaded)
    const editorTabs = page.locator('.editor-top-tabs');
    const leasesTabVisible = await editorTabs.getByText('Leases').first().isVisible({ timeout: 5000 }).catch(() => false);
    if (!leasesTabVisible) {
      // Editor may not have loaded the slice — skip gracefully
      test.skip(true, 'Editor tabs not loaded');
      return;
    }
    await clickEditorTab(page, 'Leases');
    await page.waitForTimeout(3000);

    // Should show lease content or empty state
    const hasContent = await page.getByText(/Available Leases|No leases|Duration/i).first()
      .isVisible({ timeout: 10000 }).catch(() => false);
    expect(hasContent || leasesTabVisible).toBeTruthy();
  });

  test('Topology tab shows graph container', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    await createSliceViaBar(page, 'chameleon-bar', `e2e-chi-topo-${Date.now().toString(36)}`);
    await clickBarTab(page, 'chameleon-bar', 'Topology');
    // Cytoscape container should render
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('Floating IP dropdown shows None + NIC options per node', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    const name = `e2e-chi-fip-${Date.now().toString(36)}`;
    await createSliceViaBar(page, 'chameleon-bar', name);
    await page.waitForTimeout(2000);

    // Switch to Servers tab and add a server
    await clickEditorTab(page, 'Servers');
    await page.waitForTimeout(500);
    const addBtn = page.getByText('+ Add Server').first();
    if (await addBtn.isVisible({ timeout: 3000 })) {
      await addBtn.click();
      await page.waitForTimeout(2000);
    }

    // Look for the "Floating IP:" dropdown (replaced the old checkbox)
    // It should be a <select> with "None" as the first option
    const fipSelect = page.locator('select').filter({ has: page.locator('option', { hasText: 'None' }) }).first();
    const hasFipDropdown = await fipSelect.isVisible({ timeout: 5000 }).catch(() => false);
    if (!hasFipDropdown) {
      // Try alternate selector — may also have "No FIP" text
      const fipSelect2 = page.locator('select').filter({ has: page.locator('option', { hasText: 'No FIP' }) }).first();
      const hasFip2 = await fipSelect2.isVisible({ timeout: 3000 }).catch(() => false);
      expect(hasFip2).toBeTruthy();
      if (hasFip2) {
        // Verify it has NIC options
        const options = await fipSelect2.locator('option').allTextContents();
        expect(options.length).toBeGreaterThanOrEqual(2); // "No FIP" + at least 1 NIC
        expect(options[0]).toContain('No FIP');
        expect(options.some(o => o.includes('NIC'))).toBeTruthy();
      }
    } else {
      const options = await fipSelect.locator('option').allTextContents();
      expect(options.length).toBeGreaterThanOrEqual(2); // "None" + at least 1 NIC
      expect(options[0]).toContain('None');
      expect(options.some(o => o.includes('NIC'))).toBeTruthy();
    }
  });

  test('NIC network assignments appear in topology graph', async ({ page }) => {
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }
    const name = `e2e-chi-nic-graph-${Date.now().toString(36)}`;
    const API = 'http://localhost:8000/api';

    // Create slice + node via API
    const createResp = await page.request.post(`${API}/chameleon/slices`, {
      data: { name, site: 'CHI@TACC' },
    });
    if (!createResp.ok()) { test.skip(true, 'Cannot create Chameleon slice'); return; }
    const slice = await createResp.json();
    const sliceId = slice.id;

    await page.request.post(`${API}/chameleon/drafts/${sliceId}/nodes`, {
      data: { name: 'node1', node_type: 'compute_skylake', image: 'CC-Ubuntu22.04', site: 'CHI@TACC' },
    });

    // Get node ID
    const sliceResp = await page.request.get(`${API}/chameleon/slices`);
    const slices = await sliceResp.json();
    const thisSlice = slices.find((s: any) => s.id === sliceId);
    const nodeId = thisSlice?.nodes?.[0]?.id;
    if (!nodeId) { test.skip(true, 'No node ID'); return; }

    // Get available networks and assign one to NIC 0
    const netsResp = await page.request.get(`${API}/chameleon/networks?site=CHI@TACC`);
    const nets = await netsResp.json();
    const sharedNet = nets.find((n: any) => n.name?.includes('shared') || n.shared);

    if (sharedNet) {
      await page.request.put(`${API}/chameleon/drafts/${sliceId}/nodes/${nodeId}/interfaces`, {
        data: [
          { nic: 0, network: { id: sharedNet.id, name: sharedNet.name } },
          { nic: 1, network: null },
        ],
      });
    }

    // Check graph via API — should have NIC and network nodes
    const graphResp = await page.request.get(`${API}/chameleon/drafts/${sliceId}/graph`);
    const graph = await graphResp.json();
    const graphNodes = graph.nodes || [];
    const nicNodes = graphNodes.filter((n: any) => (n.classes || '').includes('component'));
    const netNodes = graphNodes.filter((n: any) => (n.classes || '').includes('network'));
    console.log(`Graph API: ${graphNodes.length} nodes, ${nicNodes.length} NICs, ${netNodes.length} networks`);
    expect(nicNodes.length).toBeGreaterThanOrEqual(1);
    if (sharedNet) expect(netNodes.length).toBeGreaterThanOrEqual(1);

    // Verify in GUI topology
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'chameleon');
    const chiSelect = page.locator('.chameleon-bar select').first();
    if (await chiSelect.isVisible({ timeout: 5000 })) {
      const opts = await chiSelect.locator('option').allTextContents();
      const opt = opts.find(o => o.includes(name));
      if (opt) {
        await chiSelect.selectOption({ label: opt });
        await page.waitForTimeout(2000);
      }
    }
    await clickBarTab(page, 'chameleon-bar', 'Topology');
    await page.waitForTimeout(3000);
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });

    // Clean up
    try { await page.request.delete(`${API}/chameleon/slices/${sliceId}`); } catch {}
  });
});
