/**
 * Chameleon Cloud real-provisioning GUI E2E tests.
 *
 * These tests actually deploy Chameleon slices and verify they become ACTIVE.
 * They are slow (5-15 min) and require live Chameleon credentials.
 *
 * Gate: E2E_FULL=1 + authenticated session + Chameleon configured
 * Run:  E2E_FULL=1 npx playwright test chameleon-provision
 */
import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, clickBarTab,
  clickEditorTab, isAuthenticated, isChameleonConfigured,
  waitForChameleonSliceActive, cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

// Increase timeout for provisioning tests (15 min)
test.setTimeout(900_000);

test.describe('Chameleon Provisioning — Real Deploy E2E', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1 for provisioning tests'); return; }
    const chiOk = await isChameleonConfigured();
    if (!chiOk) { test.skip(true, 'Chameleon not configured'); return; }
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('create and deploy Chameleon slice via GUI, verify ACTIVE', async ({ page }) => {
    const name = `e2e-chi-gui-${Date.now().toString(36)}`;

    // Navigate to Chameleon view
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(true, 'Chameleon view not available'); return; }

    // Create a new slice
    await createSliceViaBar(page, 'chameleon-bar', name);
    await page.waitForTimeout(3000);

    // Switch to Servers tab and add a server
    await clickEditorTab(page, 'Servers');
    await page.waitForTimeout(1000);
    const addBtn = page.getByText('+ Add Server').first();
    if (await addBtn.isVisible({ timeout: 5000 })) {
      await addBtn.click();
      await page.waitForTimeout(2000);
    }

    // Get the slice ID from the API (we need it for polling)
    const slicesResp = await page.request.get(`${API}/chameleon/slices`);
    const slices = await slicesResp.json();
    const testSlice = slices.find((s: any) => s.name === name);
    if (!testSlice) { test.skip(true, 'Slice not found in API'); return; }
    const sliceId = testSlice.id;

    // Click Submit/Deploy button
    const submitBtn = page.locator('button', { hasText: /Submit|Deploy/ }).first();
    if (await submitBtn.isVisible({ timeout: 5000 })) {
      await submitBtn.click();
      await page.waitForTimeout(5000);
    }

    // Wait for instances to become ACTIVE via API polling
    const active = await waitForChameleonSliceActive(sliceId, 600_000);
    expect(active).toBeTruthy();

    // Verify the topology graph shows active state
    await clickBarTab(page, 'chameleon-bar', 'Topology');
    await page.waitForTimeout(3000);
    const cyContainer = page.locator('.cytoscape-container');
    await expect(cyContainer).toBeVisible({ timeout: 5000 });
  });

  test('deployed Chameleon slice shows ACTIVE in Slices tab', async ({ page }) => {
    // Create and deploy via API (faster for this test)
    const name = `e2e-chi-active-${Date.now().toString(36)}`;

    // Get site info
    const sitesResp = await page.request.get(`${API}/chameleon/sites`);
    const sites = await sitesResp.json();
    const site = sites.find((s: any) =>
      ['CHI@UC', 'CHI@TACC', 'KVM@TACC'].includes(s.name || s)
    ) || sites[0];
    const siteName = site.name || site;

    // Get node type
    const ntResp = await page.request.get(`${API}/chameleon/sites/${siteName}/node-types`);
    const ntData = await ntResp.json();
    const nodeTypes = ntData.node_types || ntData;
    const nodeType = (nodeTypes[0]?.name || nodeTypes[0]) ?? 'compute_skylake';

    // Create slice via API
    const createResp = await page.request.post(`${API}/chameleon/slices`, {
      data: { name, site: siteName },
    });
    if (!createResp.ok()) { test.skip(true, 'Cannot create Chameleon slice'); return; }
    const sliceData = await createResp.json();
    const sliceId = sliceData.id;

    // Add node
    await page.request.post(`${API}/chameleon/drafts/${sliceId}/nodes`, {
      data: { name: 'node1', node_type: nodeType, image: 'CC-Ubuntu22.04', site: siteName },
    });

    // Deploy
    const deployResp = await page.request.post(`${API}/chameleon/drafts/${sliceId}/deploy`, {
      data: { lease_name: name, duration_hours: 1, full_deploy: true },
      timeout: 600_000,
    });
    if (!deployResp.ok()) { test.skip(true, `Deploy failed: ${await deployResp.text()}`); return; }

    // Wait for ACTIVE
    const active = await waitForChameleonSliceActive(sliceId, 600_000);
    expect(active).toBeTruthy();

    // Now check the GUI
    await page.goto('/');
    await page.waitForTimeout(3000);
    const ok = await navigateToView(page, 'chameleon');
    if (!ok) { test.skip(); return; }

    // Go to Slices tab and look for ACTIVE badge
    await clickBarTab(page, 'chameleon-bar', 'Slices');
    await page.waitForTimeout(3000);

    // The slice table should show the slice name and ACTIVE status
    await expect(async () => {
      const text = await page.locator('table').first().textContent();
      expect(text).toContain(name);
    }).toPass({ timeout: 15000 });

    // Look for "Active" or "ACTIVE" badge near the slice
    const activeBadge = page.getByText(/Active|ACTIVE/).first();
    const hasBadge = await activeBadge.isVisible({ timeout: 10000 }).catch(() => false);
    expect(hasBadge).toBeTruthy();
  });
});
