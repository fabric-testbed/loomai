import { expect, test, type Page } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mockAllApis } from '../fixtures/api-mocks';
import {
  configStatus,
  makeChameleonInstance,
  makeChameleonLease,
  makeChameleonNetwork,
  makeChameleonNode,
  makeChameleonSlice,
  makeDefaultApiScenario,
  makeFederatedSlice,
  makeRemoteArtifact,
  makeNetwork,
  makeNode,
  makeSliceData,
} from '../fixtures/test-data';

const screenshotDir = fileURLToPath(new URL('../../public/help-screenshots/', import.meta.url));
const screenshotPath = (filename: string) => path.join(screenshotDir, filename);
const helpTopicPreviewPath = process.env.HELP_TOPIC_PREVIEW_PATH;
const marketplaceWeaveName = 'Hello, FABRIC';
const marketplaceWeaveDir = 'Hello_FABRIC';

const docsConfigStatus = {
  ...configStatus,
  project_id: 'docs-project',
  token_info: {
    ...configStatus.token_info,
    email: '',
    name: 'Docs User',
    projects: [{ uuid: 'docs-project', name: 'Docs Project' }],
  },
};

const docsSites = [
  {
    name: 'TACC', lat: 30.39, lon: -97.73, state: 'Active',
    hosts: 6, cores_available: 192, cores_capacity: 256,
    ram_available: 768, ram_capacity: 1024,
    disk_available: 6000, disk_capacity: 9000,
  },
  {
    name: 'STAR', lat: 41.88, lon: -87.63, state: 'Active',
    hosts: 4, cores_available: 128, cores_capacity: 192,
    ram_available: 512, ram_capacity: 768,
    disk_available: 4200, disk_capacity: 7200,
  },
  {
    name: 'MASS', lat: 42.36, lon: -71.06, state: 'Active',
    hosts: 3, cores_available: 96, cores_capacity: 160,
    ram_available: 384, ram_capacity: 640,
    disk_available: 3200, disk_capacity: 6400,
  },
];

const marketplaceWeave = makeRemoteArtifact(marketplaceWeaveName, {
  uuid: 'hello-fabric-weave-uuid',
  category: 'weave',
  description_short: 'Starter FABRIC weave for a first LoomAI artifact workflow.',
  description_long: 'A reusable starter weave for learning how marketplace artifacts move into the LoomAI workspace.',
  tags: ['weave', 'starter', 'tutorial'],
  artifact_downloads_active: 42,
  number_of_versions: 1,
  versions: [{
    uuid: 'hello-fabric-weave-version-1',
    version: '1.0.0',
    urn: 'urn:mock:hello-fabric-weave:1',
    active: true,
    created: '2026-06-08T12:00:00Z',
    version_downloads: 42,
  }],
});

const marketplaceNotebook = makeRemoteArtifact('STAR Telemetry Notebook', {
  uuid: 'star-telemetry-notebook-uuid',
  category: 'notebook',
  description_short: 'Notebook for exploring telemetry from STAR-hosted experiments.',
  tags: ['notebook', 'telemetry'],
  artifact_downloads_active: 18,
});

function addStableNodeColors(slice: any) {
  for (const node of slice.graph?.nodes || []) {
    if (String(node.classes || '').includes('vm')) {
      node.data = {
        ...node.data,
        state_bg: '#e0f2f1',
        state_bg_dark: '#1a3a30',
        state_color: '#008e7a',
        state_color_dark: '#4dd0b8',
      };
    }
  }
  for (const edge of slice.graph?.edges || []) {
    edge.classes = 'edge-l2';
    edge.data = { ...edge.data, label: edge.data.interface_name || '' };
  }
  return slice;
}

function makeDocsScenario() {
  const taccNode = {
    ...makeNode('edge-tacc', 'TACC'),
    reservation_state: 'Active',
    management_ip: '198.51.100.21',
    interfaces: [{ name: 'edge-tacc-nic-p1', node_name: 'edge-tacc', network_name: 'analysis-l2' }],
  };
  const starNode = {
    ...makeNode('edge-star', 'STAR'),
    reservation_state: 'Active',
    management_ip: '198.51.100.22',
    interfaces: [{ name: 'edge-star-nic-p1', node_name: 'edge-star', network_name: 'analysis-l2' }],
  };
  const fabricNetwork = {
    ...makeNetwork('analysis-l2', 'L2Bridge'),
    interfaces: [
      { name: 'edge-tacc-nic-p1', node_name: 'edge-tacc', network_name: 'analysis-l2' },
      { name: 'edge-star-nic-p1', node_name: 'edge-star', network_name: 'analysis-l2' },
    ],
  };
  const fabricSlice = addStableNodeColors(makeSliceData('docs-fabric', 'docs-fabric-id', {
    state: 'StableOK',
    nodes: [taccNode, starNode],
    networks: [fabricNetwork],
  }));

  const chameleonSlice = makeChameleonSlice('docs-chameleon', 'docs-chameleon-id', {
    state: 'Draft',
    site: 'CHI@TACC',
    sites: ['CHI@TACC'],
    nodes: [makeChameleonNode('chi-server', 'CHI@TACC', { id: 'chi-server-id' })],
    networks: [makeChameleonNetwork('chi-private-net', 'CHI@TACC', {
      id: 'chi-private-net-id',
      connected_nodes: ['chi-server-id'],
    })],
    resources: [
      makeChameleonLease('chi-docs-lease', 'CHI@TACC'),
      makeChameleonInstance('chi-server', 'CHI@TACC', { id: 'chi-server-instance-id' }),
    ],
  });

  const federatedSlice = makeFederatedSlice('docs-federated', 'docs-federated-id', {
    state: 'Draft',
    fabricSlices: [{ id: fabricSlice.id, name: fabricSlice.name, state: fabricSlice.state, node_count: 2 }],
    chameleonSlices: [{ id: chameleonSlice.id, name: chameleonSlice.name, state: chameleonSlice.state, site: 'CHI@TACC', node_count: 1 }],
    crossConnections: [{
      id: 'docs-fp-l2',
      type: 'facility_port_l2',
      fabric_slice_id: fabricSlice.id,
      chameleon_slice_id: chameleonSlice.id,
      fabric_node: 'edge-tacc',
      chameleon_node: 'chi-server',
      facility_port: 'Chameleon-TACC',
      vlan: 3316,
      fabric_site: 'TACC',
      chameleon_site: 'CHI@TACC',
      state: 'Draft',
    }],
  });

  return makeDefaultApiScenario({
    configStatus: docsConfigStatus,
    sites: docsSites,
    slices: [fabricSlice],
    chameleonStatus: { enabled: true, configured: true, sites: { 'CHI@TACC': { configured: true } } },
    chameleonSlices: [chameleonSlice],
    chameleonLeases: [makeChameleonLease('chi-docs-lease', 'CHI@TACC')],
    chameleonInstances: [makeChameleonInstance('chi-server', 'CHI@TACC', { id: 'chi-server-instance-id' })],
    chameleonNetworks: [makeChameleonNetwork('chi-private-net', 'CHI@TACC', { id: 'chi-private-net-id' })],
    federatedSlices: [federatedSlice],
    remoteArtifacts: [marketplaceWeave, marketplaceNotebook],
    templates: [{
      name: marketplaceWeaveName,
      description: 'Starter FABRIC weave for a first LoomAI artifact workflow.',
      description_short: 'Starter FABRIC weave for a first LoomAI artifact workflow.',
      category: 'weave',
      dir_name: marketplaceWeaveDir,
      has_template: true,
      starred: false,
      is_from_marketplace: true,
      source_marketplace: 'artifact-manager',
    }],
  });
}

async function preparePage(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    window.localStorage.setItem('theme', 'light');
    window.localStorage.setItem('poll-interval', '0');
  });
  const scenario = await mockAllApis(page, makeDocsScenario() as any);
  await page.goto('/');
  await page.addStyleTag({
    content: [
      'button[aria-label="Open Next.js Dev Tools"]',
      'nextjs-portal',
      '[data-nextjs-devtools-button]',
      '[data-nextjs-toast]',
      '{ display: none !important; visibility: hidden !important; }',
    ].join(' '),
  });
  await expect(page.locator('img[alt="LoomAI"]').first()).toBeVisible();
  return scenario;
}

function ensureMarketplaceWeaveInstalled(scenario: any) {
  const otherArtifacts = (scenario.artifacts || []).filter((artifact: any) => (
    artifact.name !== marketplaceWeaveName
    && artifact.dir_name !== marketplaceWeaveDir
    && artifact.artifact_uuid !== marketplaceWeave.uuid
  ));
  scenario.artifacts = [
    ...otherArtifacts,
    {
      name: marketplaceWeaveName,
      description: 'Starter FABRIC weave for a first LoomAI artifact workflow.',
      description_short: 'Starter FABRIC weave for a first LoomAI artifact workflow.',
      description_long: 'A reusable starter weave for learning how marketplace artifacts move into the LoomAI workspace.',
      source: 'local',
      created: '2026-06-08T12:00:00Z',
      tags: ['weave', 'starter', 'tutorial'],
      category: 'weave',
      dir_name: marketplaceWeaveDir,
      has_template: true,
      is_from_marketplace: true,
      remote_status: 'linked',
      artifact_uuid: marketplaceWeave.uuid,
      remote_artifact: marketplaceWeave,
      is_author: false,
    },
  ];
}

async function openTopView(page: Page, label: RegExp | string) {
  await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
  await page.locator('.title-pill-dropdown .title-pill-option', { hasText: label }).first().click();
}

async function hideNextDevTools(page: Page) {
  await page.locator('nextjs-portal, [data-nextjs-devtools-button], [data-nextjs-toast]')
    .evaluateAll(elements => elements.forEach(element => element.remove()))
    .catch(() => {});
  await page.getByRole('button', { name: 'Open Next.js Dev Tools' })
    .evaluateAll(buttons => buttons.forEach(button => button.remove()))
    .catch(() => {});
}

test.describe('Help screenshot examples', () => {
  test.skip(process.env.UPDATE_HELP_SCREENSHOTS !== '1', 'Set UPDATE_HELP_SCREENSHOTS=1 to regenerate Help screenshot assets.');

  test.beforeAll(async () => {
    await mkdir(screenshotDir, { recursive: true });
  });

  test('captures deterministic GUI screenshots for Help docs', async ({ page }) => {
    test.setTimeout(90_000);
    const scenario = await preparePage(page);

    await openTopView(page, /FABRIC/);
    await expect(page.getByTestId('fabric-bar')).toBeVisible();
    await page.getByTestId('fabric-bar-slice-select').selectOption('docs-fabric-id');
    await page.locator('[data-testid="fabric-bar-tab"][data-tab="topology"]').click();
    await expect(page.getByTestId('topology-panel')).toBeVisible();
    await page.waitForTimeout(1200);
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-fabric-topology.png'),
      fullPage: false,
      animations: 'disabled',
    });

    await openTopView(page, /Chameleon/);
    await expect(page.getByTestId('chameleon-bar')).toBeVisible();
    await page.getByTestId('chameleon-bar-slice-select').selectOption('docs-chameleon-id');
    await expect(page.getByTestId('topology-panel')).toBeVisible();
    await page.waitForTimeout(1200);
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-chameleon-planning.png'),
      fullPage: false,
      animations: 'disabled',
    });

    await openTopView(page, /Federated Slice/);
    await expect(page.getByTestId('federated-bar')).toBeVisible();
    await page.getByTestId('federated-bar-slice-select').selectOption('docs-federated-id');
    await page.locator('[data-testid="federated-bar-tab"][data-federated-bar-tab="slices"]').click();
    const expandFederatedRow = page.getByRole('button', { name: 'Expand docs-federated' });
    if (await expandFederatedRow.isVisible({ timeout: 1000 }).catch(() => false)) {
      await expandFederatedRow.click();
    }
    await expect(page.getByRole('table').getByText('docs-fabric', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('table').getByText('docs-chameleon', { exact: true }).first()).toBeVisible();
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-federated-overview.png'),
      fullPage: false,
      animations: 'disabled',
    });

    await openTopView(page, /Marketplace/);
    await expect(page.getByTestId('libraries-view')).toBeVisible();
    await page.getByRole('button', { name: /FABRIC Marketplace/ }).click();
    await page.getByPlaceholder('Search by title, description, author, or tag...').fill('Hello, FABRIC');
    const marketplaceCard = page.getByTestId('library-marketplace-card').filter({ hasText: marketplaceWeaveName });
    await expect(marketplaceCard).toBeVisible();
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-marketplace-hello-fabric-search.png'),
      fullPage: false,
      animations: 'disabled',
    });

    page.once('dialog', async dialog => {
      await dialog.accept();
    });
    await marketplaceCard.getByRole('button', { name: 'Get' }).click();
    ensureMarketplaceWeaveInstalled(scenario);
    await page.reload();
    await expect(page.locator('img[alt="LoomAI"]').first()).toBeVisible();
    await openTopView(page, /Marketplace/);
    await expect(page.getByTestId('libraries-view')).toBeVisible();
    await page.getByPlaceholder('Search local artifacts...').fill('Hello, FABRIC');
    const installedCard = page.getByTestId('library-artifact-card').filter({ hasText: marketplaceWeaveName });
    await expect(installedCard).toBeVisible();
    await expect(installedCard.getByText('Installed')).toBeVisible();
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-marketplace-hello-fabric-get.png'),
      fullPage: false,
      animations: 'disabled',
    });

    await installedCard.getByRole('button', { name: 'Open' }).click();
    await expect(page.getByTestId('federated-bar')).toBeVisible();
    const sidePanelWeave = page.locator('[data-help-id="templates.panel"]').getByText(marketplaceWeaveName, { exact: true });
    await expect(sidePanelWeave).toBeVisible();
    await hideNextDevTools(page);
    await page.screenshot({
      path: screenshotPath('loomai-marketplace-hello-fabric-open.png'),
      fullPage: false,
      animations: 'disabled',
    });

    await page.locator('[data-help-id="titlebar.user"]').click();
    await page.locator('[data-help-id="titlebar.help"]').click();
    await expect(page.locator('.help-view')).toBeVisible();
    await page.getByLabel('Search help').fill('GUI Walkthroughs');
    await expect(page.locator('.help-screenshot img')).toHaveCount(3);
    await expect(page.locator('.help-screenshot figcaption').first()).toContainText('FABRIC topology editor');
    await page.getByLabel('Search help').fill('Marketplace Weave');
    await expect(page.locator('.help-screenshot img')).toHaveCount(3);
    await expect(page.locator('.help-screenshot').first()).toHaveCSS('margin-left', '0px');
    await expect(page.locator('.help-screenshot-callout')).toHaveCount(9);
    await expect(page.locator('.help-screenshot-arrow-line')).toHaveCount(9);
    await expect(page.locator('.help-screenshot-target')).toHaveCount(1);
    await expect(page.locator('.help-screenshot figcaption').first()).toContainText('Marketplace search results');
    if (helpTopicPreviewPath) {
      await page.setViewportSize({ width: 1440, height: 1800 });
      await page.locator('#help-entry-libraries\\.marketplace-weave-workflow').screenshot({
        path: helpTopicPreviewPath,
        animations: 'disabled',
      });
    }
  });
});
