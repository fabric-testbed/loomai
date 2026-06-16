import { test, expect } from '@playwright/test';
import { acceptAppDialog } from '../helpers/gui-helpers';

const FEDERATED_SLICE = {
  id: 'fed-regression-draft',
  name: 'fed-regression-draft',
  kind: 'federated',
  state: 'Draft',
  created: '2026-06-06T21:40:00Z',
  updated: '2026-06-06T21:40:00Z',
  fabric_slices: ['draft-fabric-member'],
  chameleon_slices: ['chi-slice-member'],
  members: [
    { provider: 'fabric', slice_id: 'draft-fabric-member', name: 'fabric-member', role: 'fabric-sub-slice', site: 'TACC' },
    { provider: 'chameleon', slice_id: 'chi-slice-member', name: 'chameleon-member', role: 'chameleon-sub-slice', site: 'CHI@UC' },
  ],
  cross_connections: [],
  fabric_member_summaries: [
    { id: 'draft-fabric-member', name: 'fabric-member', state: 'Draft', node_count: 1 },
  ],
  chameleon_member_summaries: [
    { id: 'chi-slice-member', name: 'chameleon-member', state: 'Draft', site: 'CHI@UC', node_count: 1 },
  ],
  other_member_summaries: [],
};

const FABRIC_MEMBER_SLICE = {
  id: 'draft-fabric-member',
  name: 'fabric-member',
  state: 'Draft',
  dirty: false,
  lease_start: '',
  lease_end: '',
  error_messages: [],
  nodes: [
    {
      name: 'fabric-node-1',
      site: 'TACC',
      host: 'worker-1',
      cores: 2,
      ram: 8,
      disk: 20,
      image: 'default_ubuntu_22',
      image_type: 'qcow2',
      management_ip: '192.0.2.10',
      reservation_state: 'Ticketed',
      error_message: '',
      username: 'ubuntu',
      components: [],
      interfaces: [],
    },
  ],
  networks: [
    {
      name: 'fabric-lan',
      type: 'L2Bridge',
      layer: 'L2',
      subnet: '',
      gateway: '',
      interfaces: [],
    },
  ],
  facility_ports: [],
  port_mirrors: [],
  graph: { nodes: [], edges: [] },
};

const FABRIC_SECOND_SUMMARY = {
  id: 'draft-fabric-second',
  name: 'fabric-second',
  state: 'Draft',
};

const CHAMELEON_MEMBER_SLICE = {
  id: 'chi-slice-member',
  name: 'chameleon-member',
  provider: 'chameleon',
  state: 'Deploying',
  created: '2026-06-06T21:40:00Z',
  site: 'CHI@UC',
  sites: ['CHI@UC'],
  nodes: [
    {
      id: 'chi-node-1',
      name: 'chameleon-server-1',
      node_type: 'compute_skylake',
      image: 'CC-Ubuntu22.04',
      count: 1,
      site: 'CHI@UC',
    },
  ],
  networks: [
    { id: 'chi-net-1', name: 'sharednet1', connected_nodes: ['chi-node-1'] },
  ],
  floating_ips: [],
  resources: [
    {
      resource_id: 'lease-1',
      type: 'lease',
      id: 'lease-1',
      name: 'chi-reservation',
      site: 'CHI@UC',
      status: 'PENDING',
      lease_id: 'lease-1',
      reservations: [
        {
          id: 'reservation-physical-host-1',
          resource_type: 'physical:host',
          status: 'PENDING',
          min: 1,
          max: 1,
        },
      ],
    },
  ],
};

const CHAMELEON_SECOND_SLICE = {
  id: 'chi-slice-second',
  name: 'chameleon-second',
  provider: 'chameleon',
  state: 'Draft',
  created: '2026-06-06T21:45:00Z',
  site: 'CHI@TACC',
  sites: ['CHI@TACC'],
  nodes: [],
  networks: [],
  floating_ips: [],
  resources: [],
};

test.describe('Federated Slice listing', () => {
  test('shows Draft federated slices and loads the selected graph', async ({ page }) => {
    let graphRequests = 0;
    let currentFederatedSlice = structuredClone(FEDERATED_SLICE);

    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      const apiPath = url.pathname.slice(url.pathname.indexOf('/api') + 4);

      if (apiPath === '/config') {
        await route.fulfill({
          json: {
            configured: false,
            has_token: false,
            has_bastion_key: false,
            has_slice_key: false,
            token_info: null,
            project_id: '',
            bastion_username: '',
          },
        });
        return;
      }
      if (apiPath === '/config/check-update') {
        await route.fulfill({ json: { update_available: false, current_version: 'test', latest_version: 'test' } });
        return;
      }
      if (apiPath === '/config/ai-tools') {
        await route.fulfill({ json: {} });
        return;
      }
      if (apiPath === '/chameleon/status') {
        await route.fulfill({ json: { enabled: true, configured: true } });
        return;
      }
      if (apiPath === '/views/status') {
        await route.fulfill({ json: { fabric_enabled: true, chameleon_enabled: false, federated_enabled: true } });
        return;
      }
      if (apiPath === '/federated/slices') {
        await route.fulfill({ json: [currentFederatedSlice] });
        return;
      }
      if (apiPath === `/federated/slices/${FEDERATED_SLICE.id}`) {
        await route.fulfill({ json: currentFederatedSlice });
        return;
      }
      if (apiPath === `/federated/slices/${FEDERATED_SLICE.id}/graph`) {
        graphRequests += 1;
        await route.fulfill({
          json: {
            nodes: [{ data: { id: 'fed-node', label: 'Federated node' }, classes: 'node-federated' }],
            edges: [],
          },
        });
        return;
      }
      if (apiPath === `/federated/slices/${FEDERATED_SLICE.id}/members/add`) {
        const member = route.request().postDataJSON();
        currentFederatedSlice = {
          ...currentFederatedSlice,
          fabric_slices: member.provider === 'fabric'
            ? [...currentFederatedSlice.fabric_slices, member.slice_id]
            : currentFederatedSlice.fabric_slices,
          chameleon_slices: member.provider === 'chameleon'
            ? [...currentFederatedSlice.chameleon_slices, member.slice_id]
            : currentFederatedSlice.chameleon_slices,
          members: [...currentFederatedSlice.members, member],
          fabric_member_summaries: member.provider === 'fabric'
            ? [...currentFederatedSlice.fabric_member_summaries, { id: member.slice_id, name: member.name, state: 'Draft', node_count: 0 }]
            : currentFederatedSlice.fabric_member_summaries,
          chameleon_member_summaries: member.provider === 'chameleon'
            ? [...currentFederatedSlice.chameleon_member_summaries, { id: member.slice_id, name: member.name, state: 'Draft', site: 'CHI@TACC', node_count: 0 }]
            : currentFederatedSlice.chameleon_member_summaries,
        };
        await route.fulfill({ json: currentFederatedSlice });
        return;
      }
      if (apiPath === `/federated/slices/${FEDERATED_SLICE.id}/members/remove`) {
        const member = route.request().postDataJSON();
        currentFederatedSlice = {
          ...currentFederatedSlice,
          fabric_slices: currentFederatedSlice.fabric_slices.filter(id => !(member.provider === 'fabric' && id === member.slice_id)),
          chameleon_slices: currentFederatedSlice.chameleon_slices.filter(id => !(member.provider === 'chameleon' && id === member.slice_id)),
          members: currentFederatedSlice.members.filter(m => !(m.provider === member.provider && m.slice_id === member.slice_id)),
          fabric_member_summaries: currentFederatedSlice.fabric_member_summaries.filter(m => !(member.provider === 'fabric' && m.id === member.slice_id)),
          chameleon_member_summaries: currentFederatedSlice.chameleon_member_summaries.filter(m => !(member.provider === 'chameleon' && m.id === member.slice_id)),
        };
        await route.fulfill({ json: currentFederatedSlice });
        return;
      }
      if (apiPath === `/slices/${FABRIC_MEMBER_SLICE.id}`) {
        await route.fulfill({ json: FABRIC_MEMBER_SLICE });
        return;
      }
      if (apiPath === `/chameleon/drafts/${CHAMELEON_MEMBER_SLICE.id}`) {
        await route.fulfill({ json: CHAMELEON_MEMBER_SLICE });
        return;
      }
      if (apiPath === '/slices' || apiPath.startsWith('/slices?')) {
        await route.fulfill({ json: [
          { id: FABRIC_MEMBER_SLICE.id, name: FABRIC_MEMBER_SLICE.name, state: FABRIC_MEMBER_SLICE.state },
          FABRIC_SECOND_SUMMARY,
        ] });
        return;
      }
      if (apiPath === '/chameleon/slices') {
        await route.fulfill({ json: [CHAMELEON_MEMBER_SLICE, CHAMELEON_SECOND_SLICE] });
        return;
      }
      if (apiPath === '/chameleon/instances' || apiPath === '/chameleon/leases') {
        await route.fulfill({ json: [] });
        return;
      }
      if (apiPath === '/projects') {
        await route.fulfill({ json: { projects: [], active_project_id: '' } });
        return;
      }

      await route.fulfill({ json: {} });
    });

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"]').click();
    await page.locator('.title-pill-option', { hasText: 'Federated Slice' }).click();

    await expect(page.locator('.composite-bar')).toBeVisible();

    const selector = page.locator('select.composite-bar-select');
    await expect(selector.locator('option', { hasText: 'fed-regression-draft (Draft)' })).toHaveCount(1);

    await selector.selectOption(FEDERATED_SLICE.id);
    await expect(selector).toHaveValue(FEDERATED_SLICE.id);
    await expect.poll(() => graphRequests).toBeGreaterThan(0);

    await page.locator('.composite-bar-tab', { hasText: 'Slices' }).click();
    await expect(page.getByRole('cell', { name: FEDERATED_SLICE.name })).toBeVisible();
    await expect(page.getByText('1 FABRIC', { exact: true })).toBeVisible();
    await expect(page.getByText('1 Chameleon', { exact: true })).toBeVisible();
    await expect(page.getByRole('table').getByRole('button', { name: 'Open' })).toHaveCount(2);

    await page.getByTitle('Expand FABRIC resources').click();
    await expect(page.getByText('fabric-node-1')).toBeVisible();
    await expect(page.getByText('fabric-lan')).toBeVisible();

    await page.getByTitle('Expand Chameleon resources').click();
    await expect(page.getByText('chameleon-server-1')).toBeVisible();
    await expect(page.getByText('Waiting for lease PENDING')).toBeVisible();
    await expect(page.getByText('chi-reservation')).toBeVisible();
    await expect(page.getByText('reservation-...')).toBeVisible();

    await page.getByRole('button', { name: 'Add Sub-slice' }).click();
    await expect(page.getByRole('heading', { name: 'Add Sub-slice' })).toBeVisible();
    await page.getByLabel('Filter candidate sub-slices').fill('fabric-second');
    const fabricSecondRow = page.getByRole('row', { name: /FABRIC fabric-second/ });
    await expect(fabricSecondRow).toBeVisible();
    await fabricSecondRow.getByRole('button', { name: 'Add' }).click();
    await expect(page.getByText('2 FABRIC', { exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /FABRIC fabric-second/ })).toBeVisible();

    await page.getByRole('button', { name: 'Add Sub-slice' }).click();
    await page.getByLabel('Filter candidate sub-slices').fill('chameleon-second');
    const chameleonSecondRow = page.getByRole('row', { name: /Chameleon chameleon-second/ });
    await expect(chameleonSecondRow).toBeVisible();
    await chameleonSecondRow.getByRole('button', { name: 'Add' }).click();
    await expect(page.getByText('2 Chameleon', { exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /Chameleon chameleon-second/ })).toBeVisible();

    await page.getByTitle('Detach this FABRIC slice from the federated slice').last().click();
    await acceptAppDialog(page, 'Remove FABRIC slice');
    await expect(page.getByText('1 FABRIC', { exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /FABRIC fabric-second/ })).toHaveCount(0);
  });
});
