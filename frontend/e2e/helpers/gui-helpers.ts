import { Page, APIRequestContext, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:3000';
const API_URL = 'http://localhost:8000/api';
const PREFERRED_CHAMELEON_NODE_TYPES = [
  'compute_skylake',
  'compute_cascadelake',
  'compute_cascadelake_r',
  'compute_icelake_r650',
  'compute_icelake_r750',
  'compute_zen3',
  'compute_haswell_ib',
  'compute_haswell',
];
const PREFERRED_CHAMELEON_IMAGES = ['CC-Ubuntu22.04', 'CC-Ubuntu24.04'];

// Track slice IDs created during tests for cleanup
const createdFabricSlices: string[] = [];
const createdChameleonSlices: string[] = [];
const createdCompositeSlices: string[] = [];

function currentWorkerPrefix(): string | null {
  if (process.env.E2E_WORKER_SCOPED_CLEANUP !== '1') return null;
  const worker = process.env.TEST_WORKER_INDEX ?? process.env.TEST_PARALLEL_INDEX;
  const run = process.env.E2E_RUN_ID?.replace(/[^a-zA-Z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
  return `e2e-${run ? `${run}-` : ''}w${worker ?? '0'}-`;
}

function shouldCleanupE2EResource(name?: string): boolean {
  if (!name?.startsWith('e2e-')) return false;
  const workerPrefix = currentWorkerPrefix();
  if (workerPrefix) return name.startsWith(workerPrefix);
  return process.env.E2E_WORKER_SCOPED_CLEANUP !== '1';
}

export function e2eResourceName(label: string): string {
  const workerPrefix = currentWorkerPrefix();
  const safeLabel = label.replace(/[^a-zA-Z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
  const prefix = workerPrefix || 'e2e-';
  return `${prefix}${safeLabel}-${Date.now().toString(36)}`;
}

function isArmChameleonNodeType(nodeType: any): boolean {
  const value = `${nodeType?.cpu_arch || ''} ${nodeType?.node_type || nodeType?.name || nodeType || ''}`.toLowerCase();
  return value.includes('arm') || value.includes('aarch64');
}

function isGpuChameleonNodeType(nodeType: any): boolean {
  const value = `${nodeType?.gpu || ''} ${nodeType?.node_type || nodeType?.name || nodeType || ''}`.toLowerCase();
  return value.includes('gpu');
}

function chameleonNodeTypeName(nodeType: any): string {
  return nodeType?.node_type || nodeType?.name || nodeType || '';
}

export function chooseChameleonNodeType(nodeTypes: any[]): string {
  const reservable = nodeTypes.filter(nt => (nt?.reservable ?? nt?.available ?? 1) > 0);
  const candidates = reservable.length > 0 ? reservable : nodeTypes;
  const x86Compute = candidates.filter(nt => !isArmChameleonNodeType(nt) && !isGpuChameleonNodeType(nt));
  for (const preferred of PREFERRED_CHAMELEON_NODE_TYPES) {
    if (x86Compute.some(nt => chameleonNodeTypeName(nt) === preferred)) return preferred;
  }
  return chameleonNodeTypeName(x86Compute[0] || candidates[0] || 'compute_skylake');
}

export function chooseChameleonImage(images: any[]): string {
  const active = images.filter(img => !img?.status || String(img.status).toLowerCase() === 'active');
  const candidates = active.length > 0 ? active : images;
  for (const preferred of PREFERRED_CHAMELEON_IMAGES) {
    const match = candidates.find(img => img?.name === preferred || img?.id === preferred);
    if (match) return match.id || match.name;
  }
  const nonCuda = candidates.find(img => !`${img?.name || ''} ${img?.id || ''}`.toLowerCase().includes('cuda'));
  return nonCuda?.id || nonCuda?.name || 'CC-Ubuntu22.04';
}

/**
 * Navigate to a specific view (FABRIC, Chameleon, Composite).
 */
export async function navigateToView(page: Page, view: 'fabric' | 'chameleon' | 'composite') {
  const viewPill = page.locator('[data-help-id="titlebar.view"]');
  if (!await viewPill.isVisible({ timeout: 5000 })) return false;
  await viewPill.click();
  await page.waitForTimeout(500);

  const labels: Record<string, RegExp> = {
    fabric: /FABRIC/i,
    chameleon: /Chameleon/i,
    composite: /Composite|Federated/i,
  };
  const option = page.locator('.title-pill-option', { hasText: labels[view] });
  if (!await option.isVisible({ timeout: 3000 })) return false;
  await option.click();
  await page.waitForTimeout(2000);
  return true;
}

/**
 * Create a slice via the bar's "New" button + prompt dialog.
 */
export async function createSliceViaBar(page: Page, barClass: string, name: string) {
  // Set up a persistent dialog auto-accepter
  const handler = async (dialog: any) => {
    await dialog.accept(name);
  };
  page.on('dialog', handler);

  // Find and click the New button
  const btn = page.locator(`.${barClass}`).locator('button', { hasText: /New/ }).first();
  await btn.click();
  await page.waitForTimeout(4000);

  // Remove handler after use
  page.off('dialog', handler);
}

/**
 * Override window.prompt to return a specific value (one-shot).
 * Call this BEFORE clicking a button that triggers prompt().
 */
export async function overridePrompt(page: Page, value: string) {
  await page.evaluate((v) => {
    const orig = window.prompt;
    window.prompt = () => {
      window.prompt = orig;
      return v;
    };
  }, value);
}

/**
 * Wait for text to appear on the page.
 */
export async function waitForText(page: Page, text: string, timeout = 10000) {
  await expect(page.getByText(text).first()).toBeVisible({ timeout });
}

/**
 * Select a slice from a bar's dropdown.
 */
export async function selectSliceFromBar(page: Page, barClass: string, sliceName: string) {
  const selector = page.locator(`.${barClass} select`).first();
  const options = await selector.locator('option').allTextContents();
  const match = options.find(o => o.includes(sliceName));
  if (match) {
    await selector.selectOption({ label: match });
    await page.waitForTimeout(2000);
    return true;
  }
  return false;
}

/**
 * Click a bar tab.
 */
export async function clickBarTab(page: Page, barClass: string, tabName: string) {
  const tab = page.locator(`.${barClass}-tab`, { hasText: tabName });
  if (await tab.isVisible({ timeout: 2000 })) {
    await tab.click();
    await page.waitForTimeout(1000);
    return true;
  }
  return false;
}

/**
 * Click an editor panel tab.
 */
export async function clickEditorTab(page: Page, tabName: string) {
  const tab = page.locator('.editor-top-tabs button', { hasText: tabName });
  if (await tab.isVisible({ timeout: 2000 })) {
    await tab.click();
    await page.waitForTimeout(500);
    return true;
  }
  return false;
}

/**
 * Check if the app is authenticated (has FABRIC token).
 */
export async function isAuthenticated(page: Page): Promise<boolean> {
  try {
    const resp = await page.request.get(`${API_URL}/config`);
    const data = await resp.json();
    return !!(data.token_info?.exp && data.token_info.exp * 1000 > Date.now());
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Resource availability checks — skip tests when resources unavailable
// ---------------------------------------------------------------------------

/**
 * Check if FABRIC has enough resources for a basic VM (2 cores, 8 GB RAM).
 * Queries GET /api/sites and checks for any active site with available capacity.
 * Returns the best site name, or '' if none available.
 */
export async function findAvailableFabricSite(
  cores = 2, ram = 8, components?: string[],
): Promise<string> {
  try {
    const resp = await fetch(`${API_URL}/sites?max_age=60`);
    if (!resp.ok) return '';
    const sites = await resp.json();
    for (const site of sites) {
      if (site.state !== 'Active') continue;
      const avail_cores = site.cores_available ?? 0;
      const avail_ram = site.ram_available ?? 0;
      if (avail_cores >= cores && avail_ram >= ram) {
        // If specific components needed, check site has them
        if (components && components.length > 0) {
          const siteComps = site.components || {};
          const hasAll = components.every(c => (siteComps[c]?.available ?? 0) > 0);
          if (!hasAll) continue;
        }
        return site.name;
      }
    }
  } catch {}
  return '';
}

/**
 * Check if Chameleon is configured and has available node types at a site.
 * Returns { site, nodeType } or null if unavailable.
 */
export async function findAvailableChameleonSite(): Promise<{ site: string; nodeType: string } | null> {
  try {
    const sitesResp = await fetch(`${API_URL}/chameleon/sites`);
    if (!sitesResp.ok) return null;
    const sites = await sitesResp.json();
    if (!sites || sites.length === 0) return null;

    for (const preferred of ['CHI@UC', 'CHI@TACC', 'KVM@TACC']) {
      const site = sites.find((s: any) => (s.name || s) === preferred);
      if (!site) continue;
      const siteName = site.name || site;

      // Check node types available
      try {
        const ntResp = await fetch(`${API_URL}/chameleon/sites/${siteName}/node-types`);
        if (!ntResp.ok) continue;
        const ntData = await ntResp.json();
        const nodeTypes = ntData.node_types || ntData;
        if (nodeTypes && nodeTypes.length > 0) {
          return { site: siteName, nodeType: chooseChameleonNodeType(nodeTypes) };
        }
      } catch { continue; }
    }

    // Fallback to first site
    const siteName = sites[0].name || sites[0];
    return { site: siteName, nodeType: 'compute_skylake' };
  } catch {}
  return null;
}

/**
 * Pre-flight check: verify FABRIC has resources for the test.
 * Call at the start of a provisioning test. Returns the site to use,
 * or skips the test if no resources available.
 */
export async function requireFabricResources(
  test: any, cores = 2, ram = 8, components?: string[],
): Promise<string> {
  const site = await findAvailableFabricSite(cores, ram, components);
  if (!site) {
    test.skip(true, `No FABRIC site with ${cores}c/${ram}G${components ? ' + ' + components.join(',') : ''} available`);
    return '';
  }
  return site;
}

/**
 * Pre-flight check: verify Chameleon is available for the test.
 * Call at the start of a provisioning test.
 */
export async function requireChameleonResources(
  test: any,
): Promise<{ site: string; nodeType: string }> {
  const result = await findAvailableChameleonSite();
  if (!result) {
    test.skip(true, 'No Chameleon site available');
    return { site: '', nodeType: '' };
  }
  return result;
}

/**
 * Right-click a node in the Cytoscape graph to open the context menu.
 * Since Cytoscape renders to <canvas>, we click at the center of the container
 * where nodes are typically rendered after layout.
 */
export async function rightClickNodeInGraph(page: Page, nodeName?: string): Promise<boolean> {
  const container = page.locator('.cytoscape-container canvas').first();
  if (!await container.isVisible({ timeout: 5000 })) return false;

  const box = await container.boundingBox();
  if (!box) return false;

  // Click near center of the canvas where nodes typically render
  await container.click({
    button: 'right',
    position: { x: box.width / 2, y: box.height / 2 },
  });
  await page.waitForTimeout(500);

  // Check if context menu appeared
  const menu = page.getByTestId('topology-context-menu');
  return menu.isVisible({ timeout: 3000 }).catch(() => false);
}

/**
 * Click "Open Terminal" in the graph context menu.
 * Returns true if the terminal tab appears in the bottom panel.
 */
export async function openTerminalFromContextMenu(page: Page): Promise<boolean> {
  const menuItem = page.getByTestId('topology-context-open-terminal');
  if (!await menuItem.isVisible({ timeout: 3000 })) return false;

  await menuItem.click();
  await page.waitForTimeout(2000);

  // Verify a terminal tab appeared in the bottom panel
  // Terminal tabs have class bp-tab and are closeable (have bp-tab-close child)
  const termTab = page.locator('.bp-tab .bp-tab-close').first();
  return termTab.isVisible({ timeout: 5000 }).catch(() => false);
}

/**
 * Verify the bottom panel has a terminal tab open.
 */
export async function hasTerminalTab(page: Page): Promise<boolean> {
  // Look for terminal-related tab in the bottom panel
  const tabs = page.locator('.bottom-panel-tabs .bp-tab');
  const count = await tabs.count();
  for (let i = 0; i < count; i++) {
    const tab = tabs.nth(i);
    const hasClose = await tab.locator('.bp-tab-close').isVisible().catch(() => false);
    if (hasClose) return true;
  }
  return false;
}

/**
 * Execute a command on a FABRIC node via the backend API.
 * Returns { stdout, stderr }.
 */
export async function execOnNode(
  sliceName: string, nodeName: string, command: string, timeout = 60000,
): Promise<{ stdout: string; stderr: string }> {
  const resp = await fetch(`${API_URL}/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
    signal: AbortSignal.timeout(timeout),
  });
  if (!resp.ok) throw new Error(`Execute failed: ${resp.status}`);
  return resp.json();
}

/**
 * Wait for SSH to be reachable on a FABRIC node.
 */
export async function waitForSSHReady(
  sliceName: string, nodeName: string, timeoutMs = 180000,
): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const result = await execOnNode(sliceName, nodeName, 'echo ok', 15000);
      if (result.stdout?.includes('ok')) return true;
    } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 10000));
  }
  return false;
}

/**
 * Check if Chameleon is enabled and configured.
 */
export async function isChameleonEnabled(): Promise<boolean> {
  try {
    const resp = await fetch(`${API_URL}/chameleon/status`);
    const data = await resp.json();
    return data.enabled === true;
  } catch {
    return false;
  }
}

/**
 * Wait for a FABRIC slice to reach a target state via API polling.
 */
export async function waitForSliceState(
  sliceName: string,
  targetState: string,
  timeoutMs = 600000,
  pollMs = 10000,
): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(`${API_URL}/slices/${encodeURIComponent(sliceName)}/state`);
      const data = await resp.json();
      if (data.state === targetState) return true;
      if (data.state === 'StableError' || data.state === 'Dead') return false;
    } catch { /* continue polling */ }
    await new Promise(r => setTimeout(r, pollMs));
  }
  return false;
}

/**
 * Delete a FABRIC slice via API (cleanup).
 */
export async function deleteSliceViaApi(sliceName: string) {
  try {
    await fetch(`${API_URL}/slices/${encodeURIComponent(sliceName)}`, { method: 'DELETE' });
  } catch { /* best effort */ }
}

/**
 * Delete a Chameleon slice via API (cleanup).
 */
export async function deleteChameleonSliceViaApi(sliceId: string) {
  try {
    await fetch(`${API_URL}/chameleon/slices/${encodeURIComponent(sliceId)}?delete_resources=true`, { method: 'DELETE' });
  } catch { /* best effort */ }
}

/**
 * Delete a composite slice via API (cleanup).
 */
export async function deleteCompositeSliceViaApi(compositeId: string) {
  try {
    await fetch(`${API_URL}/composite/slices/${encodeURIComponent(compositeId)}`, { method: 'DELETE' });
  } catch { /* best effort */ }
}

/**
 * Check if Chameleon is configured and has active sessions (for provisioning tests).
 */
export async function isChameleonConfigured(): Promise<boolean> {
  try {
    const resp = await fetch(`${API_URL}/chameleon/sites`);
    if (!resp.ok) return false;
    const sites = await resp.json();
    return Array.isArray(sites) && sites.length > 0;
  } catch {
    return false;
  }
}

/**
 * Wait for all instances in a Chameleon slice to reach ACTIVE status via API polling.
 */
export async function waitForChameleonSliceActive(
  sliceId: string,
  timeoutMs = 900000,
  pollMs = 15000,
): Promise<boolean> {
  const start = Date.now();
  let lastSummary = 'no draft response yet';
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(`${API_URL}/chameleon/drafts/${encodeURIComponent(sliceId)}`);
      if (!resp.ok) {
        lastSummary = `GET draft returned ${resp.status}`;
        await new Promise(r => setTimeout(r, pollMs));
        continue;
      }
      const data = await resp.json();
      const resources = data.resources || [];
      const leases = resources.filter((r: any) => r.type === 'lease');
      const instances = resources.filter((r: any) => r.type === 'instance');
      lastSummary = JSON.stringify({
        state: data.state,
        leases: leases.map((l: any) => ({ id: l.id, site: l.site, status: l.status })),
        instances: instances.map((i: any) => ({ id: i.id, name: i.name, site: i.site, status: i.status, image: i.image })),
        resources: resources.map((r: any) => ({ type: r.type, id: r.id, site: r.site, status: r.status })),
      });
      if (instances.length > 0 && instances.every((i: any) => i.status === 'ACTIVE')) return true;
      if (data.state === 'Error' || leases.some((l: any) => l.status === 'ERROR') || instances.some((i: any) => i.status === 'ERROR')) {
        console.warn(`Chameleon slice ${sliceId} entered error state: ${lastSummary}`);
        return false;
      }
    } catch (error: any) {
      lastSummary = `poll failed: ${error?.message || error}`;
    }
    await new Promise(r => setTimeout(r, pollMs));
  }
  console.warn(`Timed out waiting for Chameleon slice ${sliceId} ACTIVE: ${lastSummary}`);
  return false;
}

/**
 * Wait for a composite slice to reach Active state via API polling.
 */
export async function waitForCompositeActive(
  compositeId: string,
  timeoutMs = 900000,
  pollMs = 15000,
): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(`${API_URL}/composite/slices/${encodeURIComponent(compositeId)}`);
      if (!resp.ok) { await new Promise(r => setTimeout(r, pollMs)); continue; }
      const data = await resp.json();
      if (data.state === 'Active') return true;
      if (data.state === 'Degraded') return false;
    } catch { /* continue polling */ }
    await new Promise(r => setTimeout(r, pollMs));
  }
  return false;
}

/**
 * Deploy a Chameleon draft via API (full_deploy: creates lease, launches instances).
 */
export async function deployChameleonDraftViaApi(draftId: string, leaseName: string, durationHours = 1): Promise<any> {
  const resp = await fetch(`${API_URL}/chameleon/drafts/${encodeURIComponent(draftId)}/deploy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lease_name: leaseName, duration_hours: durationHours, full_deploy: true }),
  });
  return resp.json();
}

/**
 * Clean up all e2e-* test slices from all testbeds.
 * Call this in afterAll/afterEach to prevent accumulation across runs.
 */
export async function cleanupAllE2ESlices(request: APIRequestContext) {
  // Clean FABRIC drafts
  try {
    const resp = await request.get(`${API_URL}/slices?max_age=300`);
    if (resp.ok()) {
      const slices = await resp.json();
      for (const s of slices) {
        if (shouldCleanupE2EResource(s.name)) {
          await request.delete(`${API_URL}/slices/${encodeURIComponent(s.name)}`).catch(() => {});
        }
      }
    }
  } catch { /* best effort */ }

  // Clean composite slices
  try {
    const resp = await request.get(`${API_URL}/composite/slices`);
    if (resp.ok()) {
      const slices = await resp.json();
      for (const s of slices) {
        if (shouldCleanupE2EResource(s.name)) {
          await request.delete(`${API_URL}/composite/slices/${s.id}`).catch(() => {});
        }
      }
    }
  } catch { /* best effort */ }

  // Clean Chameleon slices
  try {
    const resp = await request.get(`${API_URL}/chameleon/slices`);
    if (resp.ok()) {
      const slices = await resp.json();
      for (const s of slices) {
        if (shouldCleanupE2EResource(s.name)) {
          await request.delete(`${API_URL}/chameleon/slices/${s.id}?delete_resources=true`).catch(() => {});
        }
      }
    }
  } catch { /* best effort */ }
}
