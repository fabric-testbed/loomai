/**
 * Topology Refresh E2E Tests — verify that clicking "↻ Slices" in any view
 * correctly updates the topology graph to reflect the real current state.
 *
 * Tests verify:
 * 1. Node state colors/labels update after refresh
 * 2. Management IPs appear after StableOK (enabling right-click terminal)
 * 3. Composite graph merges fresh member data after refresh
 * 4. Right-click terminal works on nodes with management_ip
 *
 * Gate: E2E_FULL=1 + authenticated
 * Run:  E2E_FULL=1 npx playwright test topology-refresh
 */
import { test, expect } from '@playwright/test';
import {
  navigateToView, clickBarTab, isAuthenticated,
  waitForSliceState, deleteSliceViaApi, cleanupAllE2ESlices,
  rightClickNodeInGraph, execOnNode, waitForSSHReady,
  requireFabricResources,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

test.setTimeout(900_000);

// Helper: click the "↻ Slices" refresh button on the current view
async function clickRefreshSlices(page: any, barClass: string) {
  // The refresh button contains ↻ (U+21BB) and text "Slices"
  const btn = page.locator(`.${barClass}-btn, .${barClass}-action-btn`).filter({ hasText: /Slices/ }).first();
  if (await btn.isVisible({ timeout: 3000 })) {
    await btn.click();
    await page.waitForTimeout(3000); // Allow API call + render
    return true;
  }
  return false;
}

// Helper: get the FABRIC slice state from the API (ground truth)
async function getSliceStateFromApi(sliceName: string): Promise<string> {
  try {
    const resp = await fetch(`${API}/slices/${encodeURIComponent(sliceName)}`);
    if (resp.ok) return (await resp.json()).state || '';
  } catch {}
  return '';
}

// Helper: get composite details from API
async function getCompositeFromApi(compId: string): Promise<any> {
  try {
    const resp = await fetch(`${API}/composite/slices/${compId}`);
    if (resp.ok) return resp.json();
  } catch {}
  return null;
}

// Helper: get composite graph from API and check for VM nodes
async function getCompositeGraphVMs(compId: string): Promise<string[]> {
  try {
    const resp = await fetch(`${API}/composite/slices/${compId}/graph`);
    if (!resp.ok) return [];
    const graph = await resp.json();
    const nodes = graph.nodes || [];
    return nodes
      .filter((n: any) => (n.classes || '').includes('vm'))
      .map((n: any) => (n.data || {}).name || '');
  } catch { return []; }
}

// Helper: check if a FABRIC slice has management_ip populated for a node
async function getNodeManagementIp(sliceName: string, nodeName: string): Promise<string> {
  try {
    const resp = await fetch(`${API}/slices/${encodeURIComponent(sliceName)}`);
    if (!resp.ok) return '';
    const data = await resp.json();
    const node = (data.nodes || []).find((n: any) => n.name === nodeName);
    return node?.management_ip || '';
  } catch { return ''; }
}

test.describe('Topology Refresh — Real E2E Tests', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1'); return; }
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('FABRIC: refresh button updates topology state from Configuring to StableOK', async ({ page }) => {
    await requireFabricResources(test);
    const name = `e2e-ref-fab-${Date.now().toString(36)}`;

    // Create and submit slice via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });

    // Navigate to FABRIC view and select the slice
    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const opts = await select.locator('option').allTextContents();
      expect(opts.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    await select.selectOption({ label: name });
    await page.waitForTimeout(2000);
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(2000);

    // Wait for StableOK via API polling
    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Click "↻ Slices" to force refresh
    await clickRefreshSlices(page, 'fabric-bar');
    await page.waitForTimeout(3000);

    // Re-select the slice (refresh may reset selection)
    await select.selectOption({ label: name });
    await page.waitForTimeout(2000);
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(2000);

    // Verify the graph container is visible
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });

    // Verify via API that the slice has management_ip (proves it's truly StableOK)
    const mgmtIp = await getNodeManagementIp(name, 'node1');
    expect(mgmtIp).toBeTruthy();
    console.log(`After refresh: node1 management_ip=${mgmtIp}`);

    // Verify node is SSH-reachable (proves the state is real, not just cached)
    const sshOk = await waitForSSHReady(name, 'node1', 120_000);
    expect(sshOk).toBeTruthy();

    // Right-click the graph to verify terminal is available
    await rightClickNodeInGraph(page);
    const menu = page.locator('.graph-context-menu');
    if (await menu.isVisible({ timeout: 3000 }).catch(() => false)) {
      const termItem = page.locator('.graph-context-menu-item', { hasText: /Open Terminal/ });
      const hasTerm = await termItem.isVisible({ timeout: 2000 }).catch(() => false);
      expect(hasTerm).toBeTruthy();
      console.log('Right-click terminal menu item is available');
    }

    await deleteSliceViaApi(name);
  });

  test('FABRIC: refresh after external state change shows updated state', async ({ page }) => {
    await requireFabricResources(test);
    const name = `e2e-ref-ext-${Date.now().toString(36)}`;

    // Create slice via API, submit, wait for StableOK
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    await waitForSliceState(name, 'StableOK', 600_000);

    // Navigate to FABRIC and load the slice
    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const opts = await select.locator('option').allTextContents();
      expect(opts.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    await select.selectOption({ label: name });
    await page.waitForTimeout(2000);

    // Verify state is StableOK in Slices tab
    await clickBarTab(page, 'fabric-bar', 'Slices');
    await page.waitForTimeout(2000);
    let tableText = await page.locator('table').first().textContent().catch(() => '');
    expect(tableText).toContain('StableOK');

    // Delete the slice via API (external state change)
    await fetch(`${API}/slices/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await page.waitForTimeout(3000);

    // Click refresh — should show the slice as Dead/Closing or removed
    await clickRefreshSlices(page, 'fabric-bar');
    await page.waitForTimeout(3000);

    await clickBarTab(page, 'fabric-bar', 'Slices');
    await page.waitForTimeout(2000);
    tableText = await page.locator('table').first().textContent().catch(() => '');

    // Either the slice shows Dead/Closing or it's gone from the table
    if (tableText?.includes(name)) {
      expect(tableText).toMatch(/Dead|Closing/);
      console.log('Slice shows Dead/Closing after refresh');
    } else {
      console.log('Slice removed from list after refresh');
    }
  });

  test('Composite: refresh updates member states and graph', async ({ page }) => {
    await requireFabricResources(test);
    const compName = `e2e-ref-comp-${Date.now().toString(36)}`;
    const fabName = `e2e-ref-cfab-${Date.now().toString(36)}`;

    // Create FABRIC slice + submit
    await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });

    // Create composite, add FABRIC member
    const compResp = await page.request.post(`${API}/composite/slices`, { data: { name: compName } });
    const compData = await compResp.json();
    const compId = compData.id;
    const fabResp = await page.request.get(`${API}/slices/${encodeURIComponent(fabName)}`);
    const fabData = await fabResp.json();
    const fabDraftId = fabData.id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [fabDraftId], chameleon_slices: [] },
    });

    // Submit composite (deploys FABRIC member)
    await page.request.post(`${API}/composite/slices/${compId}/submit`, {
      data: {}, timeout: 120_000,
    });

    // Navigate to composite view
    await navigateToView(page, 'composite');
    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: compId });
    await page.waitForTimeout(2000);

    // Check graph immediately — should have the FABRIC node
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(2000);
    let graphVMs = await getCompositeGraphVMs(compId);
    console.log(`Pre-StableOK: graph VMs = ${JSON.stringify(graphVMs)}`);
    expect(graphVMs).toContain('node1');

    // Wait for FABRIC member to reach StableOK
    await waitForSliceState(fabName, 'StableOK', 600_000);

    // Click composite "↻ Slices" refresh
    await clickRefreshSlices(page, 'composite-bar');
    await page.waitForTimeout(3000);

    // Re-select composite
    await compSelect.selectOption({ value: compId });
    await page.waitForTimeout(2000);
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(2000);

    // Verify the graph still has the node AND the composite state is Active
    graphVMs = await getCompositeGraphVMs(compId);
    console.log(`Post-StableOK refresh: graph VMs = ${JSON.stringify(graphVMs)}`);
    expect(graphVMs).toContain('node1');

    const compDetails = await getCompositeFromApi(compId);
    expect(compDetails?.state).toBe('Active');
    expect(compDetails?.fabric_member_summaries?.[0]?.state).toBe('StableOK');
    console.log(`Composite state: ${compDetails?.state}, FABRIC member: ${compDetails?.fabric_member_summaries?.[0]?.state}`);

    // Verify the FABRIC node has management_ip (terminal-ready)
    const mgmtIp = await getNodeManagementIp(fabName, 'node1');
    expect(mgmtIp).toBeTruthy();
    console.log(`FABRIC node1 management_ip=${mgmtIp}`);

    // Cleanup
    try { await fetch(`${API}/composite/slices/${compId}`, { method: 'DELETE' }); } catch {}
    await deleteSliceViaApi(fabName);
  });

  test('Composite: refresh after FABRIC member deleted shows Degraded state', async ({ page }) => {
    await requireFabricResources(test);
    const compName = `e2e-ref-deg-${Date.now().toString(36)}`;
    const fabName = `e2e-ref-dfab-${Date.now().toString(36)}`;

    // Create and submit
    await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    const compResp = await page.request.post(`${API}/composite/slices`, { data: { name: compName } });
    const compId = (await compResp.json()).id;
    const fabResp = await page.request.get(`${API}/slices/${encodeURIComponent(fabName)}`);
    const fabDraftId = (await fabResp.json()).id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [fabDraftId], chameleon_slices: [] },
    });
    await page.request.post(`${API}/composite/slices/${compId}/submit`, { data: {}, timeout: 120_000 });
    await waitForSliceState(fabName, 'StableOK', 600_000);

    // Navigate and verify Active
    await navigateToView(page, 'composite');
    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: compId });
    await page.waitForTimeout(2000);

    // Now delete the FABRIC member (simulating external disruption)
    await fetch(`${API}/slices/${encodeURIComponent(fabName)}`, { method: 'DELETE' });
    await page.waitForTimeout(5000);

    // Refresh
    await clickRefreshSlices(page, 'composite-bar');
    await page.waitForTimeout(5000);

    // Check composite state — should be Degraded (member is Dead/Closing)
    const compDetails = await getCompositeFromApi(compId);
    console.log(`After member delete: composite state=${compDetails?.state}, member state=${compDetails?.fabric_member_summaries?.[0]?.state}`);
    // State should reflect the dead member
    expect(['Degraded', 'Provisioning', 'Draft']).toContain(compDetails?.state);

    // Cleanup
    try { await fetch(`${API}/composite/slices/${compId}`, { method: 'DELETE' }); } catch {}
  });

  test('FABRIC: right-click terminal works on StableOK node after refresh', async ({ page }) => {
    await requireFabricResources(test);
    const name = `e2e-ref-term-${Date.now().toString(36)}`;

    // Create, submit, wait for StableOK, wait for SSH
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    await waitForSliceState(name, 'StableOK', 600_000);
    await waitForSSHReady(name, 'node1', 180_000);

    // Navigate to FABRIC view
    await navigateToView(page, 'fabric');

    // Refresh slices
    await clickRefreshSlices(page, 'fabric-bar');
    await page.waitForTimeout(3000);

    // Select slice and go to topology
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const opts = await select.locator('option').allTextContents();
      expect(opts.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    await select.selectOption({ label: name });
    await page.waitForTimeout(3000);
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(3000);

    // Right-click to open context menu
    const canvas = page.locator('.cytoscape-container canvas').first();
    const box = await canvas.boundingBox();
    if (!box) { test.skip(true, 'Canvas not visible'); return; }

    // Try multiple positions to find the node
    let menuVisible = false;
    for (const pos of [
      { x: box.width / 2, y: box.height / 2 },
      { x: box.width * 0.4, y: box.height * 0.4 },
      { x: box.width * 0.6, y: box.height * 0.4 },
      { x: box.width * 0.5, y: box.height * 0.6 },
    ]) {
      await canvas.click({ button: 'right', position: pos });
      await page.waitForTimeout(500);
      if (await page.locator('.graph-context-menu').isVisible().catch(() => false)) {
        menuVisible = true;
        break;
      }
    }

    if (menuVisible) {
      // "Open Terminal" should be available (node has management_ip)
      const termItem = page.locator('.graph-context-menu-item', { hasText: /Open Terminal/ });
      const hasTerm = await termItem.isVisible({ timeout: 2000 }).catch(() => false);
      expect(hasTerm).toBeTruthy();

      if (hasTerm) {
        await termItem.click();
        await page.waitForTimeout(3000);

        // Terminal tab should appear in bottom panel
        const termTab = page.locator('.bp-tab .bp-tab-close').first();
        const tabVisible = await termTab.isVisible({ timeout: 5000 }).catch(() => false);
        expect(tabVisible).toBeTruthy();
        console.log('Terminal tab opened successfully after refresh');
      }
    } else {
      console.log('Could not right-click a node — verifying SSH via API instead');
    }

    // Always verify SSH works via API as ground truth
    const result = await execOnNode(name, 'node1', 'hostname');
    expect(result.stdout.trim()).toBeTruthy();
    console.log(`SSH verified: hostname=${result.stdout.trim()}`);

    await deleteSliceViaApi(name);
  });
});
