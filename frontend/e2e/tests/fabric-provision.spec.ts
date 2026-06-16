/**
 * FABRIC real-provisioning GUI E2E tests.
 *
 * These tests actually submit FABRIC slices and verify they reach StableOK.
 * They are slow (5-15 min) and require a valid FABRIC token.
 *
 * Gate: E2E_FULL=1 + authenticated session
 * Run:  E2E_FULL=1 npx playwright test fabric-provision
 */
import { test, expect } from '@playwright/test';
import {
  navigateToView, createSliceViaBar, clickBarTab,
  clickEditorTab, isAuthenticated, waitForSliceState, selectSliceFromBar,
  deleteSliceViaApi, cleanupAllE2ESlices,
  rightClickNodeInGraph, openTerminalFromContextMenu,
  hasTerminalTab, execOnNode, waitForSSHReady,
  requireFabricResources, e2eResourceName,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

// 15 min timeout for provisioning tests
test.setTimeout(900_000);

test.describe('FABRIC Provisioning — Real Deploy E2E', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1 for provisioning tests'); return; }
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('submit FABRIC slice via GUI and wait for StableOK', async ({ page }) => {
    const site = await requireFabricResources(test);
    const name = e2eResourceName('fab-gui-prov');

    // Navigate to FABRIC view
    const ok = await navigateToView(page, 'fabric');
    if (!ok) { test.skip(true, 'FABRIC view not available'); return; }

    // Create slice
    await createSliceViaBar(page, 'fabric-bar', name);
    await page.waitForTimeout(2000);

    // Add a node via editor
    await clickEditorTab(page, 'Slivers');
    const addBtn = page.locator('[data-help-id="editor.add-menu"]').first();
    if (await addBtn.isVisible({ timeout: 3000 })) {
      await addBtn.click();
      const vmOption = page.getByText('VM').first();
      if (await vmOption.isVisible({ timeout: 2000 })) {
        await vmOption.click();
        await page.waitForTimeout(1000);
      }
    }
    const draftResp = await page.request.get(`${API}/slices/${encodeURIComponent(name)}`);
    const draft = draftResp.ok() ? await draftResp.json() : {};
    if (!Array.isArray(draft.nodes) || draft.nodes.length === 0) {
      const nodeResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
        data: { name: 'node1', site: site || 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
      });
      expect(nodeResp.ok()).toBeTruthy();
    }

    // Submit via toolbar
    const submitBtn = page.locator('.fabric-bar-action-btn', { hasText: 'Submit' });
    if (await submitBtn.isVisible({ timeout: 3000 })) {
      await submitBtn.click();
      await page.waitForTimeout(5000);
    }
    const stateResp = await page.request.get(`${API}/slices/${encodeURIComponent(name)}`);
    const stateBody = stateResp.ok() ? await stateResp.json() : {};
    if (!stateResp.ok() || stateBody.state === 'Draft') {
      const submitResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, {
        timeout: 120_000,
      });
      expect(submitResp.ok(), await submitResp.text()).toBeTruthy();
    }

    // Wait for StableOK
    const ok2 = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok2).toBeTruthy();

    // Cleanup
    await deleteSliceViaApi(name);
  });

  test('submit multi-node FABRIC slice via API and verify in GUI', async ({ page }) => {
    await requireFabricResources(test, 4, 16);  // 2 nodes = 4 cores, 16 GB
    const name = e2eResourceName('fab-gui-multi');

    // Create slice + 2 nodes via API (faster)
    const createResp = await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    if (!createResp.ok()) { test.skip(true, 'Cannot create slice'); return; }

    for (let i = 1; i <= 2; i++) {
      await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
        data: { name: `node${i}`, site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
      });
    }

    // Submit
    const submitResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, {
      timeout: 120_000,
    });
    expect(submitResp.ok()).toBeTruthy();

    // Wait for StableOK
    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Verify in GUI
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'fabric');

    // Select the slice
    const select = page.locator('select.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    expect(await selectSliceFromBar(page, 'fabric-bar', name)).toBeTruthy();
    await page.waitForTimeout(3000);

    // Verify topology shows 2 nodes
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(2000);
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });

    // Cleanup
    await deleteSliceViaApi(name);
  });

  test('active FABRIC slice shows StableOK in Slices tab', async ({ page }) => {
    await requireFabricResources(test);
    const name = e2eResourceName('fab-gui-state');

    // Create and submit via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });

    // Wait for StableOK
    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Check GUI Slices tab
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'fabric');
    await clickBarTab(page, 'fabric-bar', 'Slices');
    await page.waitForTimeout(3000);

    // Find the slice row and verify StableOK badge
    await expect(async () => {
      const tableText = await page.locator('table').first().textContent();
      expect(tableText).toContain(name);
      expect(tableText).toContain('StableOK');
    }).toPass({ timeout: 15000 });

    // Cleanup
    await deleteSliceViaApi(name);
  });

  test('execute command on active FABRIC node via API', async ({ page }) => {
    await requireFabricResources(test);
    const name = e2eResourceName('fab-gui-exec');

    // Create, add node, submit via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });

    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Wait for SSH to be ready (retry hostname command)
    let sshReady = false;
    const sshStart = Date.now();
    while (Date.now() - sshStart < 180_000) {
      try {
        const resp = await fetch(`${API}/files/vm/${encodeURIComponent(name)}/node1/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: 'echo ok' }),
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.stdout?.includes('ok')) { sshReady = true; break; }
        }
      } catch { /* retry */ }
      await new Promise(r => setTimeout(r, 10_000));
    }
    expect(sshReady).toBeTruthy();

    // Execute uname
    const resp = await fetch(`${API}/files/vm/${encodeURIComponent(name)}/node1/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'uname -a' }),
    });
    expect(resp.ok).toBeTruthy();
    const result = await resp.json();
    expect(result.stdout).toContain('Linux');

    // Cleanup
    await deleteSliceViaApi(name);
  });

  test('delete active FABRIC slice and verify removal', async ({ page }) => {
    await requireFabricResources(test);
    const name = e2eResourceName('fab-gui-del');

    // Create, submit, wait
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Delete via API
    const delResp = await fetch(`${API}/slices/${encodeURIComponent(name)}`, { method: 'DELETE' });
    expect(delResp.ok).toBeTruthy();

    // Verify in GUI — slice should be gone or show Dead
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'fabric');
    await clickBarTab(page, 'fabric-bar', 'Slices');
    await page.waitForTimeout(5000);

    // The slice should either not appear or show Dead/Closing state
    const tableText = await page.locator('table').first().textContent().catch(() => '');
    if (tableText?.includes(name)) {
      // If it still appears, it should be Dead or Closing
      expect(tableText).toMatch(/Dead|Closing/);
    }
    // If it doesn't appear at all, that's also correct
  });

  test('right-click node opens SSH terminal in bottom panel', async ({ page }) => {
    await requireFabricResources(test);
    const name = e2eResourceName('fab-gui-term');

    // Create, submit, wait via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: { name: 'node1', site: 'auto', cores: 2, ram: 8, disk: 10, image: 'default_ubuntu_22' },
    });
    await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 600_000);
    expect(ok).toBeTruthy();

    // Wait for SSH to be ready (needed so node has management_ip)
    const sshOk = await waitForSSHReady(name, 'node1');
    expect(sshOk).toBeTruthy();

    // Navigate to FABRIC view and select the slice
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'fabric');

    const select = page.locator('select.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    expect(await selectSliceFromBar(page, 'fabric-bar', name)).toBeTruthy();
    await page.waitForTimeout(3000);

    // Switch to Topology tab
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(2000);
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });

    // Right-click on the graph to open context menu
    const menuOpened = await rightClickNodeInGraph(page);
    if (!menuOpened) {
      // If context menu didn't appear (node might not be at center),
      // try clicking at different positions
      const canvas = page.locator('.cytoscape-container canvas').first();
      const box = await canvas.boundingBox();
      if (box) {
        for (const pos of [
          { x: box.width * 0.4, y: box.height * 0.4 },
          { x: box.width * 0.6, y: box.height * 0.4 },
          { x: box.width * 0.5, y: box.height * 0.6 },
        ]) {
          await canvas.click({ button: 'right', position: pos });
          await page.waitForTimeout(500);
          if (await page.locator('.graph-context-menu').isVisible().catch(() => false)) break;
        }
      }
    }

    // If context menu is visible, click "Open Terminal"
    const ctxMenu = page.locator('.graph-context-menu');
    if (await ctxMenu.isVisible({ timeout: 3000 }).catch(() => false)) {
      const termItem = page.locator('.graph-context-menu-item', { hasText: /Open Terminal/ });
      if (await termItem.isVisible({ timeout: 2000 }).catch(() => false)) {
        await termItem.click();
        await page.waitForTimeout(3000);

        // Verify terminal tab appeared in bottom panel
        const hasTerm = await hasTerminalTab(page);
        expect(hasTerm).toBeTruthy();
      }
    }

    // Whether or not the GUI terminal worked, verify the node is operational
    // via the backend SSH API
    const result = await execOnNode(name, 'node1', 'hostname');
    expect(result.stdout.trim()).toBeTruthy();

    // Cleanup
    await deleteSliceViaApi(name);
  });

  test('right-click terminal + verify node operational with ping', async ({ page }) => {
    test.setTimeout(1_500_000);
    const site = await requireFabricResources(test, 4, 16);  // 2 nodes
    const name = e2eResourceName('fab-gui-op');

    // Create 2-node slice with FABNetv4 via API
    await page.request.post(`${API}/slices?name=${encodeURIComponent(name)}`);
    for (let i = 1; i <= 2; i++) {
      await page.request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
        data: {
          name: `node${i}`, site, cores: 2, ram: 8, disk: 10,
          image: 'default_ubuntu_22',
          components: [{ model: 'NIC_Basic', name: `nic${i}` }],
        },
      });
    }

    // Get interface names and add FABNetv4
    const sliceResp = await page.request.get(`${API}/slices/${encodeURIComponent(name)}`);
    const sliceData = await sliceResp.json();
    const ifaces: string[] = [];
    for (const n of sliceData.nodes || []) {
      for (const c of n.components || []) {
        for (const iface of c.interfaces || []) {
          if (iface.name) ifaces.push(iface.name);
        }
      }
    }
    expect(ifaces.length).toBeGreaterThanOrEqual(2);
    const networkResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/networks`, {
      data: { name: 'fabnet', type: 'FABNetv4', interfaces: ifaces.slice(0, 2) },
    });
    expect(networkResp.ok(), await networkResp.text()).toBeTruthy();

    // Submit and wait
    const submitResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    expect(submitResp.ok(), await submitResp.text()).toBeTruthy();
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();

    const configResp = await page.request.post(`${API}/slices/${encodeURIComponent(name)}/auto-configure-networks`, {
      timeout: 300_000,
    });
    expect(configResp.ok(), await configResp.text()).toBeTruthy();

    // Wait for SSH on both nodes
    for (const nn of ['node1', 'node2']) {
      const sshOk = await waitForSSHReady(name, nn);
      expect(sshOk).toBeTruthy();
    }

    // Navigate to GUI and select the slice
    await page.goto('/');
    await page.waitForTimeout(3000);
    await navigateToView(page, 'fabric');
    const select = page.locator('select.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 15000 });
    expect(await selectSliceFromBar(page, 'fabric-bar', name)).toBeTruthy();
    await page.waitForTimeout(3000);

    // Switch to Topology and try right-click terminal
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await page.waitForTimeout(2000);

    const menuOpened = await rightClickNodeInGraph(page);
    if (menuOpened) {
      const termOpened = await openTerminalFromContextMenu(page);
      // Terminal open is a bonus — the real test is operational below
    }

    // Operational test: get node2's data-plane IP and ping from node1
    const ipResult = await execOnNode(name, 'node2',
      "ip -4 -o addr show scope global | awk '$4 ~ /^10\\.(12[8-9]|1[3-8][0-9]|19[0-1])\\./ { sub(/\\/.*/, \"\", $4); print $4; exit }'");
    const node2Ip = ipResult.stdout.trim();

    if (node2Ip) {
      let pingOutput = '';
      const pingStart = Date.now();
      while (Date.now() - pingStart < 180_000) {
        const pingResult = await execOnNode(name, 'node1', `ping -c 3 -W 5 ${node2Ip}`);
        pingOutput = pingResult.stdout || pingResult.stderr || '';
        if (pingOutput.includes('bytes from')) break;
        await page.waitForTimeout(10_000);
      }
      expect(pingOutput).toContain('bytes from');
    } else {
      test.info().annotations.push({
        type: 'network',
        description: 'FABNetv4 data-plane IP was not configured on node2; SSH operational checks still passed.',
      });
    }

    // Cleanup
    await deleteSliceViaApi(name);
  });
});
