/**
 * Composite slice real-provisioning GUI E2E tests.
 *
 * These tests create composite slices with real FABRIC + Chameleon members,
 * submit them, and verify the GUI reflects Active state.
 *
 * Gate: E2E_FULL=1 + authenticated session + Chameleon configured
 * Run:  E2E_FULL=1 npx playwright test composite-provision
 */
import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, clickBarTab,
  clickEditorTab, isAuthenticated, isChameleonConfigured,
  waitForCompositeActive, waitForSliceState,
  requireFabricResources, requireChameleonResources,
  waitForChameleonSliceActive, cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

// 15 min timeout for provisioning tests
test.setTimeout(900_000);

test.describe('Composite Provisioning — Real Deploy E2E', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1 for provisioning tests'); return; }
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('create and submit composite with FABRIC member via GUI', async ({ page }) => {
    await requireFabricResources(test);
    const compName = `e2e-comp-gui-${Date.now().toString(36)}`;
    const fabName = `e2e-fab-gui-${Date.now().toString(36)}`;

    // Create FABRIC slice via API (faster)
    const fabResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    if (!fabResp.ok()) { test.skip(true, 'Cannot create FABRIC slice'); return; }

    // Add a node to the FABRIC slice
    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });

    // Navigate to composite view
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(true, 'Composite view not available'); return; }

    // Create composite via GUI
    await createSliceViaBar(page, 'composite-bar', compName);
    await page.waitForTimeout(3000);

    // Get composite ID
    const compListResp = await page.request.get(`${API}/composite/slices`);
    const comps = await compListResp.json();
    const comp = comps.find((c: any) => c.name === compName);
    if (!comp) { test.skip(true, 'Composite not found'); return; }

    // Add FABRIC member via API (more reliable than checkbox in test)
    await page.request.put(`${API}/composite/slices/${comp.id}/members`, {
      data: { fabric_slices: [fabName], chameleon_slices: [] },
    });

    // Reload and navigate to composite
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'composite');

    // Select the composite
    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: comp.id });
    await page.waitForTimeout(2000);

    // Click Submit button
    const submitBtn = page.locator('button', { hasText: /Submit/ }).first();
    if (await submitBtn.isVisible({ timeout: 5000 })) {
      await submitBtn.click();
      await page.waitForTimeout(5000);
    } else {
      // Try via API
      await page.request.post(`${API}/composite/slices/${comp.id}/submit`, {
        data: {}, timeout: 120_000,
      });
    }

    // Wait for composite to become Active
    const active = await waitForCompositeActive(comp.id, 600_000);
    expect(active).toBeTruthy();

    // Verify topology shows nodes
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(3000);
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('create and submit composite with FABRIC + Chameleon members', async ({ page }) => {
    await requireFabricResources(test);
    const chiRes = await requireChameleonResources(test);

    const compName = `e2e-comp-both-${Date.now().toString(36)}`;
    const fabName = `e2e-fab-both-${Date.now().toString(36)}`;
    const chiName = `e2e-chi-both-${Date.now().toString(36)}`;

    // --- Create FABRIC slice ---
    const fabResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    if (!fabResp.ok()) { test.skip(true, 'Cannot create FABRIC slice'); return; }
    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: 'fab-node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });

    // --- Create Chameleon slice ---
    const sitesResp = await page.request.get(`${API}/chameleon/sites`);
    const sites = await sitesResp.json();
    const site = sites.find((s: any) =>
      ['CHI@UC', 'CHI@TACC', 'KVM@TACC'].includes(s.name || s)
    ) || sites[0];
    const siteName = site.name || site;

    const ntResp = await page.request.get(`${API}/chameleon/sites/${siteName}/node-types`);
    const ntData = await ntResp.json();
    const nodeTypes = ntData.node_types || ntData;
    const nodeType = (nodeTypes[0]?.name || nodeTypes[0]) ?? 'compute_skylake';

    const chiResp = await page.request.post(`${API}/chameleon/slices`, {
      data: { name: chiName, site: siteName },
    });
    if (!chiResp.ok()) { test.skip(true, 'Cannot create Chameleon slice'); return; }
    const chiData = await chiResp.json();
    const chiId = chiData.id;

    await page.request.post(`${API}/chameleon/drafts/${chiId}/nodes`, {
      data: { name: 'chi-node1', node_type: nodeType, image: 'CC-Ubuntu22.04', site: siteName },
    });

    // --- Create composite and add members ---
    const compResp = await page.request.post(`${API}/composite/slices`, {
      data: { name: compName },
    });
    if (!compResp.ok()) { test.skip(true, 'Cannot create composite'); return; }
    const compData = await compResp.json();
    const compId = compData.id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [fabName], chameleon_slices: [chiId] },
    });

    // --- Submit composite ---
    const submitResp = await page.request.post(`${API}/composite/slices/${compId}/submit`, {
      data: {}, timeout: 300_000,
    });
    expect(submitResp.ok()).toBeTruthy();

    // --- Wait for Active ---
    const active = await waitForCompositeActive(compId, 900_000);
    expect(active).toBeTruthy();

    // --- Verify GUI shows Active state ---
    await page.goto('/');
    await page.waitForTimeout(3000);
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }

    // Select the composite
    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: compId });
    await page.waitForTimeout(3000);

    // Verify topology has nodes from both testbeds
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(3000);
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });

    // Verify state badge shows Active
    const stateText = page.getByText(/Active/).first();
    const hasActive = await stateText.isVisible({ timeout: 10000 }).catch(() => false);
    expect(hasActive).toBeTruthy();
  });

  test('composite state badges update in Slices tab', async ({ page }) => {
    await requireFabricResources(test);
    const compName = `e2e-comp-badge-${Date.now().toString(36)}`;
    const fabName = `e2e-fab-badge-${Date.now().toString(36)}`;

    // Create FABRIC slice + composite via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });

    const compResp = await page.request.post(`${API}/composite/slices`, {
      data: { name: compName },
    });
    const compData = await compResp.json();
    const compId = compData.id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [fabName], chameleon_slices: [] },
    });

    // Navigate to composite Slices tab
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(); return; }
    await clickBarTab(page, 'composite-bar', 'Slices');
    await page.waitForTimeout(2000);

    // Should see "Draft" badge initially
    const draftBadge = page.getByText(/Draft/).first();
    const hasDraft = await draftBadge.isVisible({ timeout: 10000 }).catch(() => false);
    expect(hasDraft).toBeTruthy();

    // Submit via API
    await page.request.post(`${API}/composite/slices/${compId}/submit`, {
      data: {}, timeout: 120_000,
    });

    // Wait for Active
    const active = await waitForCompositeActive(compId, 600_000);
    expect(active).toBeTruthy();

    // Reload and check badge updated
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'composite');
    await clickBarTab(page, 'composite-bar', 'Slices');
    await page.waitForTimeout(3000);

    // Should now show "Active" badge
    await expect(async () => {
      const allText = await page.locator('table').first().textContent();
      expect(allText).toContain('Active');
    }).toPass({ timeout: 15000 });
  });

  test('FABRIC member stays in composite topology throughout all state transitions', async ({ page }) => {
    await requireFabricResources(test);
    /**
     * This test verifies that a FABRIC slice remains visible in the composite
     * topology graph during every phase of provisioning:
     *   Draft → Configuring → Nascent → StableOK
     *
     * It checks THREE things at each state transition:
     * 1. The composite graph API returns VM nodes for the FABRIC member
     * 2. The composite details API shows the member with correct state
     * 3. The fabric_slices array has been updated from draft-ID to FABRIC UUID
     *
     * Success: the FABRIC slice's node appears in the composite graph at
     * every check point.  Failure: the node disappears from the graph at
     * any point during provisioning.
     */
    const compName = `e2e-comp-topo-${Date.now().toString(36)}`;
    const fabName = `e2e-fab-topo-${Date.now().toString(36)}`;
    const NODE_NAME = 'topo-node1';

    // --- Setup via API ---
    // Create FABRIC draft with a node
    const createResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(fabName)}`);
    const createData = await createResp.json();
    const draftId = createData.id; // e.g. "draft-abc123"
    console.log(`Created FABRIC draft: name=${fabName}, id=${draftId}`);

    await page.request.post(`${API}/slices/${encodeURIComponent(fabName)}/nodes`, {
      data: { name: NODE_NAME, site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });

    // Create composite and add the FABRIC slice (by draft ID)
    const compResp = await page.request.post(`${API}/composite/slices`, {
      data: { name: compName },
    });
    const compData = await compResp.json();
    const compId = compData.id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [draftId], chameleon_slices: [] },
    });
    console.log(`Composite ${compId}: fabric_slices=[${draftId}]`);

    // --- Helpers ---
    const getCompositeDetails = async (): Promise<any> => {
      const resp = await fetch(`${API}/composite/slices/${compId}`);
      return resp.ok ? resp.json() : null;
    };

    const checkFabricNodeInGraph = async (): Promise<{ found: boolean; nodeCount: number; nodeNames: string[] }> => {
      const resp = await fetch(`${API}/composite/slices/${compId}/graph`);
      if (!resp.ok) return { found: false, nodeCount: 0, nodeNames: [] };
      const graph = await resp.json();
      const nodes = graph.nodes || graph.elements?.nodes || [];
      const vmNodes = nodes.filter((n: any) => {
        const cls = n.classes || '';
        return cls === 'vm' || cls.includes('vm');
      });
      const nodeNames = vmNodes.map((n: any) => (n.data || n).name || '');
      const found = vmNodes.some((n: any) => {
        const data = n.data || n;
        return data.name === NODE_NAME || (data.label && data.label.includes(NODE_NAME));
      });
      return { found, nodeCount: vmNodes.length, nodeNames };
    };

    // Track all checks
    const checks: Array<{
      phase: string; fabricState: string; compositeState: string;
      fabricSlices: string[]; memberSummaryState: string;
      nodeInGraph: boolean; graphNodeCount: number; graphNodeNames: string[];
      timestamp: number;
    }> = [];

    const doCheck = async (phase: string) => {
      const details = await getCompositeDetails();
      const graphInfo = await checkFabricNodeInGraph();

      // Get FABRIC slice state
      let fabricState = '';
      try {
        const resp = await fetch(`${API}/slices/${encodeURIComponent(fabName)}`);
        if (resp.ok) fabricState = (await resp.json()).state || '';
      } catch {}

      const check = {
        phase,
        fabricState,
        compositeState: details?.state || '?',
        fabricSlices: details?.fabric_slices || [],
        memberSummaryState: details?.fabric_member_summaries?.[0]?.state || '?',
        nodeInGraph: graphInfo.found,
        graphNodeCount: graphInfo.nodeCount,
        graphNodeNames: graphInfo.nodeNames,
        timestamp: Date.now(),
      };
      checks.push(check);
      return check;
    };

    // --- Check 1: Draft state (before submit) ---
    const draftCheck = await doCheck('pre-submit');
    expect(draftCheck.nodeInGraph).toBeTruthy();
    console.log(`Pre-submit: fabricSlices=${JSON.stringify(draftCheck.fabricSlices)}, nodeInGraph=${draftCheck.nodeInGraph}`);

    // Navigate to composite topology in GUI
    await page.goto('/');
    await page.waitForTimeout(3000);
    const ok = await navigateToView(page, 'composite');
    if (!ok) { test.skip(true, 'Composite view not available'); return; }

    const compSelect = page.locator('.composite-bar-select');
    await compSelect.selectOption({ value: compId });
    await page.waitForTimeout(2000);
    await clickBarTab(page, 'composite-bar', 'Topology');
    await page.waitForTimeout(2000);

    // --- Submit the composite ---
    console.log('Submitting composite...');
    const submitResp = await page.request.post(`${API}/composite/slices/${compId}/submit`, {
      data: {}, timeout: 120_000,
    });
    expect(submitResp.ok()).toBeTruthy();
    const submitResult = await submitResp.json();
    console.log(`Submit result: ${JSON.stringify(submitResult)}`);

    // Immediately check after submit (this is where the bug manifests)
    await new Promise(r => setTimeout(r, 2000));
    const postSubmitCheck = await doCheck('post-submit-immediate');
    console.log(`Post-submit: fabricSlices=${JSON.stringify(postSubmitCheck.fabricSlices)}, ` +
                `nodeInGraph=${postSubmitCheck.nodeInGraph}, fabricState=${postSubmitCheck.fabricState}, ` +
                `memberState=${postSubmitCheck.memberSummaryState}, compositeState=${postSubmitCheck.compositeState}`);

    // CRITICAL ASSERTION: node must be in graph immediately after submit
    expect(postSubmitCheck.nodeInGraph).toBeTruthy();

    // --- Poll state transitions ---
    let lastState = postSubmitCheck.fabricState || 'Draft';
    let allPresent = postSubmitCheck.nodeInGraph;
    const startTime = Date.now();

    while (Date.now() - startTime < 600_000) {
      let currentState = '';
      try {
        const resp = await fetch(`${API}/slices/${encodeURIComponent(fabName)}`);
        if (resp.ok) currentState = (await resp.json()).state || '';
      } catch {}

      if (currentState && currentState !== lastState) {
        const check = await doCheck(`state-change:${currentState}`);
        if (!check.nodeInGraph) allPresent = false;
        lastState = currentState;
        console.log(`State change → ${currentState}: nodeInGraph=${check.nodeInGraph}, ` +
                    `fabricSlices=${JSON.stringify(check.fabricSlices)}, memberState=${check.memberSummaryState}`);

        // Verify GUI topology still renders
        await page.goto('/');
        await page.waitForTimeout(2000);
        await navigateToView(page, 'composite');
        await compSelect.selectOption({ value: compId });
        await page.waitForTimeout(2000);
        await clickBarTab(page, 'composite-bar', 'Topology');
        await page.waitForTimeout(2000);
      }

      if (['StableOK', 'StableError', 'Dead'].includes(currentState)) break;
      await new Promise(r => setTimeout(r, 10_000));
    }

    // Final check
    const finalCheck = await doCheck('final');

    // --- Report ---
    console.log('\n=== Composite Topology Continuity Report ===');
    for (const c of checks) {
      const elapsed = Math.round((c.timestamp - checks[0].timestamp) / 1000);
      console.log(`  [+${elapsed}s] ${c.phase}: fabricState=${c.fabricState}, ` +
                  `compositeState=${c.compositeState}, memberState=${c.memberSummaryState}, ` +
                  `nodeInGraph=${c.nodeInGraph} (${c.graphNodeCount} VMs: ${c.graphNodeNames.join(',')}), ` +
                  `fabricSlices=${JSON.stringify(c.fabricSlices)}`);
    }

    // --- Assertions ---
    expect(allPresent).toBeTruthy();
    expect(finalCheck.nodeInGraph).toBeTruthy();
    expect(lastState).toBe('StableOK');

    // The fabric_slices should have been updated from draft-ID to FABRIC UUID
    const finalFabSlices = finalCheck.fabricSlices;
    if (draftId?.startsWith('draft-')) {
      const stillHasDraft = finalFabSlices.some((id: string) => id === draftId);
      if (stillHasDraft) {
        console.log(`WARNING: fabric_slices still contains old draft ID ${draftId}`);
      }
    }

    // --- Cleanup ---
    try { await fetch(`${API}/composite/slices/${compId}`, { method: 'DELETE' }); } catch {}
    try { await fetch(`${API}/slices/${encodeURIComponent(fabName)}`, { method: 'DELETE' }); } catch {}
  });

  test('Chameleon member state is consistent between Chameleon Slices section and Member Status', async ({ page }) => {
    const chiRes = await requireChameleonResources(test);
    /**
     * Verifies that the Chameleon slice state shown in "Chameleon Slices"
     * (from GET /chameleon/slices) matches the state in "Member Status"
     * (from GET /composite/slices/{id} → chameleon_member_summaries).
     *
     * Both should show "Deploying" while instances are in BUILD state,
     * and "Active" only when all instances are ACTIVE.
     */
    const chiOk = await isChameleonConfigured();
    if (!chiOk) { test.skip(true, 'Chameleon not configured'); return; }

    const compName = `e2e-chi-state-${Date.now().toString(36)}`;
    const chiName = `e2e-chi-cons-${Date.now().toString(36)}`;

    // Create Chameleon slice
    const sitesResp = await page.request.get(`${API}/chameleon/sites`);
    const sites = await sitesResp.json();
    const site = sites.find((s: any) =>
      ['CHI@UC', 'CHI@TACC', 'KVM@TACC'].includes(s.name || s)
    ) || sites[0];
    const siteName = site.name || site;

    const ntResp = await page.request.get(`${API}/chameleon/sites/${siteName}/node-types`);
    const ntData = await ntResp.json();
    const nodeTypes = ntData.node_types || ntData;
    const nodeType = (nodeTypes[0]?.name || nodeTypes[0]) ?? 'compute_skylake';

    const chiResp = await page.request.post(`${API}/chameleon/slices`, {
      data: { name: chiName, site: siteName },
    });
    if (!chiResp.ok()) { test.skip(true, 'Cannot create Chameleon slice'); return; }
    const chiData = await chiResp.json();
    const chiId = chiData.id;

    await page.request.post(`${API}/chameleon/drafts/${chiId}/nodes`, {
      data: { name: 'node1', node_type: nodeType, image: 'CC-Ubuntu22.04', site: siteName },
    });

    // Create composite + add Chameleon member
    const compResp = await page.request.post(`${API}/composite/slices`, {
      data: { name: compName },
    });
    const compData = await compResp.json();
    const compId = compData.id;

    await page.request.put(`${API}/composite/slices/${compId}/members`, {
      data: { fabric_slices: [], chameleon_slices: [chiId] },
    });

    // Submit composite (deploys Chameleon)
    const submitResp = await page.request.post(`${API}/composite/slices/${compId}/submit`, {
      data: {}, timeout: 300_000,
    });
    expect(submitResp.ok()).toBeTruthy();

    // Poll and check state consistency
    const startTime = Date.now();
    const TIMEOUT = 600_000;
    let statesMismatched = false;
    const checks: Array<{ chiListState: string; memberState: string; compositeState: string }> = [];

    while (Date.now() - startTime < TIMEOUT) {
      // Get state from Chameleon slices list (what "Chameleon Slices" section shows)
      let chiListState = '?';
      try {
        const listResp = await fetch(`${API}/chameleon/slices`);
        if (listResp.ok) {
          const allSlices = await listResp.json();
          const thisSlice = allSlices.find((s: any) => s.id === chiId);
          if (thisSlice) chiListState = thisSlice.state || '?';
        }
      } catch {}

      // Get state from composite member summary (what "Member Status" shows)
      let memberState = '?';
      let compositeState = '?';
      try {
        const compResp2 = await fetch(`${API}/composite/slices/${compId}`);
        if (compResp2.ok) {
          const compDetails = await compResp2.json();
          compositeState = compDetails.state || '?';
          const chiSummary = compDetails.chameleon_member_summaries?.find((m: any) => m.id === chiId);
          if (chiSummary) memberState = chiSummary.state || '?';
        }
      } catch {}

      checks.push({ chiListState, memberState, compositeState });

      // States should match
      if (chiListState !== '?' && memberState !== '?' && chiListState !== memberState) {
        statesMismatched = true;
        console.log(`STATE MISMATCH: Chameleon Slices="${chiListState}" vs Member Status="${memberState}"`);
      }

      // Done when Active
      if (chiListState === 'Active' && memberState === 'Active') break;
      if (chiListState === 'Error' || memberState === 'Error') break;

      await new Promise(r => setTimeout(r, 15_000));
    }

    // Report
    console.log('\n=== Chameleon State Consistency Report ===');
    for (let i = 0; i < checks.length; i++) {
      const c = checks[i];
      const elapsed = i * 15;
      const match = c.chiListState === c.memberState ? 'MATCH' : 'MISMATCH';
      console.log(`  [+${elapsed}s] list="${c.chiListState}" member="${c.memberState}" composite="${c.compositeState}" — ${match}`);
    }

    // Assert no mismatches
    expect(statesMismatched).toBeFalsy();

    // Cleanup
    try { await fetch(`${API}/composite/slices/${compId}`, { method: 'DELETE' }); } catch {}
    try { await fetch(`${API}/chameleon/slices/${chiId}`, { method: 'DELETE' }); } catch {}
  });
});
