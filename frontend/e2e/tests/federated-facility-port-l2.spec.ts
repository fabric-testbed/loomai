import { test, expect } from '@playwright/test';

const API_URL = 'http://localhost:8000/api';

async function api(request: any, method: 'get' | 'post' | 'put' | 'delete', path: string, data?: unknown) {
  const response = await request[method](`${API_URL}${path}`, data === undefined ? {} : { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}`).toBeTruthy();
  if (response.status() === 204) return null;
  return response.json();
}

test.describe('Federated Facility Port L2 workflow', () => {
  test('creates and displays a Chameleon-TACC Facility Port L2 connection', async ({ page, request }) => {
    const stamp = Date.now();
    const fabName = `e2e-fab-fp-${stamp}`;
    const chiName = `e2e-chi-fp-${stamp}`;
    const fedName = `e2e-fed-fp-${stamp}`;

    const fab = await api(request, 'post', `/slices?name=${encodeURIComponent(fabName)}`);
    await api(request, 'post', `/slices/${encodeURIComponent(fabName)}/nodes`, {
      name: 'fab-router',
      site: 'TACC',
      cores: 2,
      ram: 8,
      disk: 10,
      image: 'default_ubuntu_22',
    });

    const chi = await api(request, 'post', '/chameleon/drafts', { name: chiName, site: 'CHI@TACC' });
    await api(request, 'post', `/chameleon/drafts/${encodeURIComponent(chi.id)}/nodes`, {
      name: 'chi-router',
      site: 'CHI@TACC',
      node_type: 'compute_icelake_r650',
      image: 'CC-Ubuntu22.04',
      count: 1,
    });

    const ports = await api(request, 'get', '/chameleon/facility-ports?site=CHI@TACC');
    expect(ports.facility_ports.length).toBeGreaterThan(0);
    const facilityPort = ports.facility_ports[0].name;
    const vlan = String(ports.suggested_vlan || 3210);

    const fed = await api(request, 'post', '/federated/slices', { name: fedName });
    await api(request, 'put', `/federated/slices/${encodeURIComponent(fed.id)}/members`, {
      members: [
        { provider: 'fabric', slice_id: fab.id, name: fabName },
        { provider: 'chameleon', slice_id: chi.id, name: chiName },
      ],
    });

    await api(request, 'post', `/federated/slices/${encodeURIComponent(fed.id)}/connections/add`, {
      type: 'facility_port_l2',
      vlan,
      facility_port: facilityPort,
      fabric_site: ports.fabric_site,
      chameleon_site: 'CHI@TACC',
      endpoint_a: {
        provider: 'fabric',
        slice_id: fab.id,
        site: ports.fabric_site,
        node: 'fab-router',
        facility_port: facilityPort,
        vlan,
      },
      endpoint_b: {
        provider: 'chameleon',
        slice_id: chi.id,
        site: 'CHI@TACC',
        node: 'chi-router',
        vlan,
      },
      fabric_slice: fab.id,
      fabric_node: 'fab-router',
      chameleon_slice: chi.id,
      chameleon_node: 'chi-router',
    });

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"]').click();
    await page.locator('.title-pill-option', { hasText: /Federated Slice|Composite/i }).click();
    await expect(page.locator('.composite-bar')).toBeVisible({ timeout: 10_000 });

    const select = page.locator('select.composite-bar-select');
    const options = await select.locator('option').all();
    let selected = false;
    for (const option of options) {
      const text = await option.textContent();
      if (text?.includes(fedName)) {
        await select.selectOption({ label: text });
        selected = true;
        break;
      }
    }
    expect(selected, `federated selector contains ${fedName}`).toBeTruthy();
    await expect(select).toHaveValue(fed.id);
    await expect(page.getByText(facilityPort).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(new RegExp(`VLAN\\s+${vlan}`)).first()).toBeVisible({ timeout: 10_000 });

    const graph = await api(request, 'get', `/federated/slices/${encodeURIComponent(fed.id)}/graph`);
    const edge = graph.edges.find((e: any) => e.data?.id?.startsWith('xconn:'));
    expect(edge?.classes).toContain('edge-facility-port-l2');
    expect(edge?.data?.label).toContain(facilityPort);
    expect(edge?.data?.label).toContain(`VLAN ${vlan}`);
  });
});
