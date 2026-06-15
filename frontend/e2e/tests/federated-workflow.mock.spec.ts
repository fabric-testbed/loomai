import { expect, test } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { acceptAppDialog, completeAppPrompt, dismissAppDialogIfVisible } from '../helpers/gui-helpers';
import {
  makeChameleonInstance,
  makeChameleonLease,
  makeChameleonNetwork,
  makeChameleonNode,
  makeChameleonSlice,
  makeFederatedSlice,
  makeNetwork,
  makeNode,
  makeSliceData,
  scenarioStaleFederatedMember,
} from '../fixtures/test-data';

test.describe('Federated mocked slice workflow', () => {
  test('refreshes selected subslice and resource statuses while members provision', async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('poll-interval', '1000');
    });

    const fabricNode = {
      ...makeNode('fabric-node-1', 'TACC'),
      reservation_state: 'Ticketed',
      management_ip: '',
    };
    const fabricSlice = makeSliceData('provisioning-fabric', 'provisioning-fabric-id', {
      state: 'Configuring',
      nodes: [fabricNode],
    });
    const leaseResource = {
      ...makeChameleonLease('chi-reservation', 'CHI@UC', {
        id: 'lease-1',
        status: 'PENDING',
        reservations: [{ id: 'reservation-host-1', resource_type: 'physical:host', status: 'PENDING', min: 1, max: 1 }],
      }),
      resource_id: 'lease-1',
      type: 'lease',
      lease_id: 'lease-1',
    };
    const chameleonSlice = makeChameleonSlice('provisioning-chameleon', 'provisioning-chameleon-id', {
      state: 'Deploying',
      site: 'CHI@UC',
      sites: ['CHI@UC'],
      nodes: [makeChameleonNode('chameleon-server-1', 'CHI@UC', { id: 'chi-node-1' })],
      resources: [leaseResource],
    });
    const federatedSlice = makeFederatedSlice('fed-live-status', 'fed-live-status-id', {
      fabricSlices: [{ id: fabricSlice.id, name: fabricSlice.name, state: 'Draft', node_count: 1 }],
      chameleonSlices: [{ id: chameleonSlice.id, name: chameleonSlice.name, state: 'Draft', site: 'CHI@UC', node_count: 1 }],
    });

    await mockAllApis(page, {
      slices: [fabricSlice],
      chameleonSlices: [chameleonSlice],
      federatedSlices: [federatedSlice],
    });

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('federated-bar-slice-select').selectOption(federatedSlice.id);
    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="slices"]').click();

    await expect(page.getByRole('cell', { name: federatedSlice.name })).toBeVisible();
    await page.getByTitle('Expand FABRIC resources').click();
    await expect(page.getByText('Ticketed')).toBeVisible();
    await page.getByTitle('Expand Chameleon resources').click();
    await expect(page.getByText('Waiting for lease PENDING')).toBeVisible();

    fabricSlice.state = 'StableOK';
    fabricNode.reservation_state = 'Active';
    fabricNode.management_ip = '198.51.100.20';
    leaseResource.status = 'ACTIVE';
    leaseResource.reservations = [{ id: 'reservation-host-1', resource_type: 'physical:host', status: 'ACTIVE', min: 1, max: 1 }];
    chameleonSlice.resources = [
      leaseResource,
      {
        ...makeChameleonInstance('chameleon-server-1', 'CHI@UC', {
          id: 'instance-1',
          status: 'SPAWNING',
          floating_ip: '',
          ip_addresses: [],
        }),
        resource_id: 'instance-1',
        type: 'instance',
        planned_node_id: 'chi-node-1',
        planned_node_name: 'chameleon-server-1',
      },
    ];

    await expect(page.getByText('198.51.100.20')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('SPAWNING')).toBeVisible({ timeout: 10_000 });
    chameleonSlice.state = 'Active';
    chameleonSlice.resources[1].status = 'ACTIVE';
    chameleonSlice.resources[1].floating_ip = '203.0.113.55';
    chameleonSlice.resources[1].ip_addresses = ['192.0.2.55'];

    await expect(page.getByText('203.0.113.55')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Waiting for lease PENDING')).toHaveCount(0);
  });

  test('refreshes federated topology when returning from a provider view', async ({ page }) => {
    const fabricSlice = makeSliceData('switchback-fabric', 'switchback-fabric-id', {
      state: 'Configuring',
      nodes: [makeNode('switchback-node-1', 'TACC')],
    });
    const federatedSlice = makeFederatedSlice('fed-switchback-refresh', 'fed-switchback-refresh-id', {
      fabricSlices: [{ id: fabricSlice.id, name: fabricSlice.name, state: 'Configuring', node_count: 1 }],
    });
    let graphRequests = 0;

    await mockAllApis(page, {
      slices: [fabricSlice],
      federatedSlices: [federatedSlice],
    });
    page.on('request', request => {
      if (request.url().includes(`/api/federated/slices/${federatedSlice.id}/graph`)) {
        graphRequests += 1;
      }
    });

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await page.getByTestId('federated-bar-slice-select').selectOption(federatedSlice.id);
    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]').click();
    await expect(page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]')).toHaveClass(/active/);
    await expect.poll(() => graphRequests).toBeGreaterThan(0);
    const requestsBeforeSwitch = graphRequests;

    fabricSlice.state = 'StableOK';
    fabricSlice.nodes[0].reservation_state = 'Active';
    fabricSlice.nodes[0].management_ip = '198.51.100.91';

    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^FABRIC$/ }).click();
    await expect(page.getByTestId('fabric-bar')).toBeVisible();

    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible();
    await expect(page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]')).toHaveClass(/active/);
    await expect.poll(() => graphRequests).toBeGreaterThan(requestsBeforeSwitch);
  });

  test('surfaces stale provider members without breaking the federated view', async ({ page }) => {
    const scenario = await mockAllApis(page, scenarioStaleFederatedMember());
    const federatedSlice = scenario.federatedSlices[0] as any;

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('federated-bar-slice-select').selectOption(federatedSlice.id);

    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="slices"]').click();
    await expect(page.getByRole('cell', { name: federatedSlice.name })).toBeVisible();
    await expect(page.getByText('1 FABRIC', { exact: true })).toBeVisible();
    await page.getByTitle('Expand FABRIC resources').click();
    await expect(page.getByText(/Could not load FABRIC resources/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();

    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]').click();
    await expect(page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]')).toHaveClass(/active/);
    await expect(page.getByTestId('topology-graph')).toBeVisible();
  });

  test('right-click deletes provider resources from the federated Slices detail view', async ({ page }) => {
    const fabricSlice = makeSliceData('delete-fabric-member', 'delete-fabric-member-id', {
      nodes: [makeNode('fabric-delete-node', 'TACC')],
      networks: [makeNetwork('fabric-delete-net')],
      facility_ports: [{
        name: 'fabric-delete-fp',
        site: 'TACC',
        vlan: '3300',
        bandwidth: '10',
        interfaces: [],
      }],
    });
    const chameleonSlice = makeChameleonSlice('delete-chameleon-member', 'delete-chameleon-member-id', {
      site: 'CHI@UC',
      sites: ['CHI@UC'],
      nodes: [makeChameleonNode('chi-delete-node', 'CHI@UC', { id: 'chi-delete-node-id' })],
      networks: [makeChameleonNetwork('chi-delete-net', 'CHI@UC', { id: 'chi-delete-net-id', connected_nodes: [] })],
      resources: [{
        resource_id: 'lease:delete-lease-id',
        type: 'lease',
        id: 'delete-lease-id',
        lease_id: 'delete-lease-id',
        name: 'delete-lease',
        site: 'CHI@UC',
        status: 'ACTIVE',
        reservations: [],
      }],
    });
    const federatedSlice = makeFederatedSlice('fed-delete-resources', 'fed-delete-resources-id', {
      fabricSlices: [{ id: fabricSlice.id, name: fabricSlice.name, state: fabricSlice.state, node_count: 1 }],
      chameleonSlices: [{ id: chameleonSlice.id, name: chameleonSlice.name, state: chameleonSlice.state, site: 'CHI@UC', node_count: 1 }],
    });

    await mockAllApis(page, {
      slices: [fabricSlice],
      chameleonSlices: [chameleonSlice],
      federatedSlices: [federatedSlice],
    });

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('federated-bar-slice-select').selectOption(federatedSlice.id);
    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="slices"]').click();

    await page.getByTitle('Expand FABRIC resources').click();
    const fabricNetwork = page.locator('[data-testid="federated-member-resource-row"][data-provider="fabric"][data-resource-type="network"][data-resource-name="fabric-delete-net"]');
    await expect(fabricNetwork).toBeVisible();
    await fabricNetwork.click({ button: 'right' });
    await expect(page.getByTestId('federated-resource-context-menu')).toBeVisible();
    await page.getByTestId('federated-resource-context-delete').click();
    await expect.poll(() => (fabricSlice.networks as any[]).some(network => network.name === 'fabric-delete-net')).toBe(false);
    await expect(fabricNetwork).toBeHidden();

    const fabricFacilityPort = page.locator('[data-testid="federated-member-resource-row"][data-provider="fabric"][data-resource-type="facility-port"][data-resource-name="fabric-delete-fp"]');
    await expect(fabricFacilityPort).toBeVisible();
    await fabricFacilityPort.click({ button: 'right' });
    await page.getByTestId('federated-resource-context-delete').click();
    await expect.poll(() => (fabricSlice.facility_ports as any[]).some(fp => fp.name === 'fabric-delete-fp')).toBe(false);
    await expect(fabricFacilityPort).toBeHidden();

    await page.getByTitle('Expand Chameleon resources').click();
    const chameleonNetwork = page.locator('[data-testid="federated-member-resource-row"][data-provider="chameleon"][data-resource-type="network"][data-resource-name="chi-delete-net"]');
    await expect(chameleonNetwork).toBeVisible();
    await chameleonNetwork.click({ button: 'right' });
    await page.getByTestId('federated-resource-context-delete').click();
    await expect.poll(() => (chameleonSlice.networks as any[]).some(network => network.name === 'chi-delete-net')).toBe(false);
    await expect(chameleonNetwork).toBeHidden();

    const chameleonLease = page.locator('[data-testid="federated-member-resource-row"][data-provider="chameleon"][data-resource-type="lease"][data-resource-name="delete-lease"]');
    await expect(chameleonLease).toBeVisible();
    await chameleonLease.click({ button: 'right' });
    await page.getByTestId('federated-resource-context-delete').click();
    await expect.poll(() => (chameleonSlice.resources as any[]).some(resource => resource.name === 'delete-lease')).toBe(false);
    await expect(chameleonLease).toBeHidden();
  });

  test('creates a federated slice, manages subslices, checks graph state, and deletes it', async ({ page }) => {
    const scenario = await mockAllApis(page, { federatedSlices: [] });
    const federatedName = 'mock-fed-workflow';
    const federatedId = `${federatedName}-id`;
    const fabricId = 'mock-fabric-id';
    const chameleonId = 'mock-chameleon-id';
    const getFederated = () => (scenario.federatedSlices as any[]).find(slice => slice.id === federatedId);

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Federated Slice$/ }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible({ timeout: 10_000 });

    await page.getByTestId('federated-bar-new-slice').click();
    await completeAppPrompt(page, federatedName, 'Federated slice name');

    await expect(page.getByTestId('federated-bar-slice-select')).toHaveValue(federatedId);
    await expect(page.locator('[data-testid="federated-bar-slice-select"] option:checked')).toContainText(federatedName);

    const editor = page.getByTestId('federated-editor-panel');
    await expect(editor).toBeVisible();
    await editor.getByTestId('federated-add-subslice').click();

    let modal = page.getByTestId('federated-subslice-modal');
    await expect(modal).toBeVisible();
    const fabricCandidate = modal.locator(`[data-testid="federated-subslice-candidate"][data-provider="fabric"][data-subslice-id="${fabricId}"]`);
    await fabricCandidate.getByTestId('federated-subslice-toggle').click();
    await expect(editor.locator(`[data-testid="federated-member-row"][data-provider="fabric"][data-subslice-id="${fabricId}"]`)).toBeVisible();

    modal = page.getByTestId('federated-subslice-modal');
    const chameleonCandidate = modal.locator(`[data-testid="federated-subslice-candidate"][data-provider="chameleon"][data-subslice-id="${chameleonId}"]`);
    await chameleonCandidate.getByTestId('federated-subslice-toggle').click();
    await expect(editor.locator(`[data-testid="federated-member-row"][data-provider="chameleon"][data-subslice-id="${chameleonId}"]`)).toBeVisible();
    await modal.getByTestId('federated-subslice-close').click();
    await expect(modal).toBeHidden();

    await expect.poll(() => getFederated()?.fabric_slices ?? []).toContain(fabricId);
    await expect.poll(() => getFederated()?.chameleon_slices ?? []).toContain(chameleonId);

    await expect(editor.getByTestId('federated-connection-fabric-slice')).toHaveValue(fabricId);
    await expect(editor.getByTestId('federated-connection-chameleon-slice')).toHaveValue(chameleonId);
    await expect(editor.getByTestId('federated-add-connection')).toBeEnabled();
    await editor.getByTestId('federated-add-connection').click();

    await expect.poll(() => getFederated()?.cross_connections?.length ?? 0).toBe(1);
    await expect.poll(() => getFederated()?.cross_connections?.[0]?.state).toBe('Draft');
    const connectionRow = editor.getByTestId('federated-connection-row');
    await expect(connectionRow).toBeVisible();
    await expect(connectionRow).toHaveAttribute('data-connection-type', 'fabnetv4_l3');
    const connections = await page.evaluate(async (id) => fetch(`/api/federated/slices/${id}/connections`).then(response => response.json()), federatedId);
    expect(connections).toHaveLength(1);
    expect(connections[0]).toMatchObject({
      type: 'fabnetv4_l3',
      state: 'Draft',
      fabric_slice: fabricId,
      chameleon_slice: chameleonId,
    });

    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="topology"]').click();
    await expect(page.getByTestId('topology-graph')).toBeVisible();
    const graph = await page.evaluate(async (id) => fetch(`/api/federated/slices/${id}/graph`).then(response => response.json()), federatedId);
    expect(graph.nodes.some((node: any) => node.data?.testbed === 'fabric')).toBe(true);
    expect(graph.nodes.some((node: any) => node.data?.testbed === 'chameleon')).toBe(true);

    await page.getByTestId('federated-bar-submit-slice').click();
    await expect.poll(() => getFederated()?.state).toBe('Provisioning');
    const graphAfterSubmit = await page.evaluate(async (id) => fetch(`/api/federated/slices/${id}/graph`).then(response => response.json()), federatedId);
    expect(graphAfterSubmit.nodes.some((node: any) => node.data?.testbed === 'fabric')).toBe(true);
    expect(graphAfterSubmit.nodes.some((node: any) => node.data?.testbed === 'chameleon')).toBe(true);
    await page.waitForTimeout(500);

    const fabricRow = editor.locator(`[data-testid="federated-member-row"][data-provider="fabric"][data-subslice-id="${fabricId}"]`);
    await fabricRow.getByTestId('federated-member-remove').click();
    await expect(fabricRow).toBeHidden();
    await expect(editor.locator(`[data-testid="federated-member-row"][data-provider="chameleon"][data-subslice-id="${chameleonId}"]`)).toBeVisible();
    await expect.poll(() => getFederated()?.fabric_slices ?? []).not.toContain(fabricId);

    await page.getByTestId('federated-bar-delete-slice').click();
    await acceptAppDialog(page, 'Delete federated slice');
    await dismissAppDialogIfVisible(page, 'Also delete all');
    await expect(page.getByTestId('federated-bar-slice-select')).toHaveValue('');
    await expect.poll(() => getFederated()).toBeUndefined();
  });
});
