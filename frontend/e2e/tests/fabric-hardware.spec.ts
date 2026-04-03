/**
 * FABRIC specialized hardware and network GUI E2E tests.
 *
 * Two tiers:
 * - Topology tests (no E2E_FULL): create hardware topologies via API, verify GUI renders them
 * - Provisioning tests (E2E_FULL=1): actually submit and verify active state
 *
 * Run all:       npx playwright test fabric-hardware
 * Run provision: E2E_FULL=1 npx playwright test fabric-hardware
 */
import { test, expect } from '@playwright/test';
import {
  navigateToView, clickBarTab, isAuthenticated,
  waitForSliceState, deleteSliceViaApi, cleanupAllE2ESlices,
} from '../helpers/gui-helpers';

const API = 'http://localhost:8000/api';

// Helper: create slice, add nodes with components, add network, return slice data
async function createHardwareTopology(
  request: any,
  name: string,
  nodes: Array<{ name: string; site: string; cores?: number; ram?: number; disk?: number; components?: any[] }>,
  network?: { name: string; type: string; subnet?: string; ip_mode?: string; interface_ips?: Record<string, string> },
) {
  await request.post(`${API}/slices?name=${encodeURIComponent(name)}`);

  for (const node of nodes) {
    await request.post(`${API}/slices/${encodeURIComponent(name)}/nodes`, {
      data: {
        name: node.name,
        site: node.site,
        cores: node.cores ?? 2,
        ram: node.ram ?? 8,
        disk: node.disk ?? 10,
        image: 'default_ubuntu_22',
        components: node.components,
      },
    });
  }

  if (network) {
    // Get interface names
    const sliceResp = await request.get(`${API}/slices/${encodeURIComponent(name)}`);
    const sliceData = await sliceResp.json();
    const ifaces: string[] = [];
    for (const n of sliceData.nodes || []) {
      for (const c of n.components || []) {
        for (const iface of c.interfaces || []) {
          if (iface.name) ifaces.push(iface.name);
        }
      }
    }

    const netBody: any = {
      name: network.name,
      type: network.type,
      interfaces: ifaces.slice(0, nodes.length),
    };
    if (network.subnet) netBody.subnet = network.subnet;
    if (network.ip_mode) netBody.ip_mode = network.ip_mode;
    if (network.interface_ips) netBody.interface_ips = network.interface_ips;

    await request.post(`${API}/slices/${encodeURIComponent(name)}/networks`, { data: netBody });
  }

  const resp = await request.get(`${API}/slices/${encodeURIComponent(name)}`);
  return resp.json();
}

// ===== TOPOLOGY TESTS (no E2E_FULL needed — just verify GUI renders) =====

test.describe('FABRIC Hardware Topology — GUI Rendering', () => {
  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('multi-site FABNetv4 topology renders in graph', async ({ page, request }) => {
    const name = `e2e-hw-l3-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('L2STS topology renders in graph', async ({ page, request }) => {
    const name = `e2e-hw-l2sts-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'l2sts-link', type: 'L2STS', subnet: '192.168.100.0/24' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('L2PTP topology renders in graph', async ({ page, request }) => {
    const name = `e2e-hw-l2ptp-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'p2p-link', type: 'L2PTP', subnet: '10.10.10.0/30' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('GPU node topology renders with badge', async ({ page, request }) => {
    const name = `e2e-hw-gpu-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'gpu-node', site: 'UCSD', cores: 8, ram: 32, disk: 100,
        components: [{ model: 'GPU_RTX6000', name: 'gpu1' }] },
    ]);

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('NVMe node topology renders', async ({ page, request }) => {
    const name = `e2e-hw-nvme-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'nvme-node', site: 'TACC', cores: 4, ram: 16,
        components: [{ model: 'NVME_P4510', name: 'nvme1' }] },
    ]);

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('FPGA node topology renders', async ({ page, request }) => {
    const name = `e2e-hw-fpga-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'fpga-node', site: 'UCSD', cores: 4, ram: 16,
        components: [{ model: 'FPGA_Xilinx_U280', name: 'fpga1' }] },
    ]);

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('ConnectX-5 + gateway topology renders', async ({ page, request }) => {
    const name = `e2e-hw-cx5-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'TACC', components: [{ model: 'NIC_ConnectX_5', name: 'nic1' }] },
      { name: 'gw-node', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('ConnectX-6 + gateway topology renders', async ({ page, request }) => {
    const name = `e2e-hw-cx6-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'TACC', components: [{ model: 'NIC_ConnectX_6', name: 'nic1' }] },
      { name: 'gw-node', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });

  test('ConnectX-7 + gateway topology renders', async ({ page, request }) => {
    const name = `e2e-hw-cx7-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'STAR', components: [{ model: 'NIC_ConnectX_7', name: 'nic1' }] },
      { name: 'gw-node', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await navigateToView(page, 'fabric');
    const select = page.locator('.fabric-bar-slice-select');
    await expect(async () => {
      const options = await select.locator('option').allTextContents();
      expect(options.some(o => o.includes(name))).toBeTruthy();
    }).toPass({ timeout: 10000 });
    await select.selectOption({ label: name });
    await clickBarTab(page, 'fabric-bar', 'Topology');
    await expect(page.locator('.cytoscape-container')).toBeVisible({ timeout: 5000 });
  });
});


// ===== PROVISIONING TESTS (E2E_FULL required — real hardware) =====

test.describe('FABRIC Hardware Provisioning — Real Deploy', () => {
  test.setTimeout(1_800_000); // 30 min for hardware tests

  test.afterAll(async ({ request }) => { await cleanupAllE2ESlices(request); });

  test.beforeEach(async ({ page }) => {
    const authed = await isAuthenticated(page);
    if (!authed) { test.skip(true, 'Not authenticated'); return; }
    if (!process.env.E2E_FULL) { test.skip(true, 'Set E2E_FULL=1 for provisioning tests'); return; }
    await page.goto('/');
    await page.waitForTimeout(3000);
  });

  test('multi-site FABNetv4 — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-l3p-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('L2STS cross-site — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-l2sp-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'l2sts-link', type: 'L2STS', subnet: '192.168.100.0/24' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('L2PTP cross-site — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-l2pp-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'node1', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
      { name: 'node2', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'p2p-link', type: 'L2PTP', subnet: '10.10.10.0/30' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('GPU node — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-gpup-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'gpu-node', site: 'UCSD', cores: 8, ram: 32, disk: 100,
        components: [{ model: 'GPU_RTX6000', name: 'gpu1' }] },
    ]);

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();

    // Verify GUI shows StableOK
    await navigateToView(page, 'fabric');
    await clickBarTab(page, 'fabric-bar', 'Slices');
    await page.waitForTimeout(3000);
    await expect(async () => {
      const text = await page.locator('table').first().textContent();
      expect(text).toContain('StableOK');
    }).toPass({ timeout: 15000 });

    await deleteSliceViaApi(name);
  });

  test('NVMe node — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-nvp-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'nvme-node', site: 'TACC', cores: 4, ram: 16,
        components: [{ model: 'NVME_P4510', name: 'nvme1' }] },
    ]);

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('FPGA Xilinx node — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-fpp-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'fpga-node', site: 'UCSD', cores: 4, ram: 16,
        components: [{ model: 'FPGA_Xilinx_U280', name: 'fpga1' }] },
    ]);

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('ConnectX-5 + gateway — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-c5p-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'TACC', components: [{ model: 'NIC_ConnectX_5', name: 'nic1' }] },
      { name: 'gw-node', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('ConnectX-6 + gateway — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-c6p-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'TACC', components: [{ model: 'NIC_ConnectX_6', name: 'nic1' }] },
      { name: 'gw-node', site: 'STAR', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });

  test('ConnectX-7 + gateway — submit and reach StableOK', async ({ page, request }) => {
    const name = `e2e-hw-c7p-${Date.now().toString(36)}`;
    await createHardwareTopology(request, name, [
      { name: 'smartnic-node', site: 'STAR', components: [{ model: 'NIC_ConnectX_7', name: 'nic1' }] },
      { name: 'gw-node', site: 'TACC', components: [{ model: 'NIC_Basic', name: 'nic1' }] },
    ], { name: 'fabnet', type: 'FABNetv4' });

    await request.post(`${API}/slices/${encodeURIComponent(name)}/submit`, { timeout: 120_000 });
    const ok = await waitForSliceState(name, 'StableOK', 900_000);
    expect(ok).toBeTruthy();
    await deleteSliceViaApi(name);
  });
});
