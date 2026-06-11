import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test';

const liveEnabled = process.env.E2E_FULL === '1';
const liveMutationsEnabled = process.env.E2E_LIVE_MUTATIONS === '1';
const backendBaseUrl = (process.env.E2E_BACKEND_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const apiBaseUrl = backendBaseUrl.endsWith('/api') ? backendBaseUrl : `${backendBaseUrl}/api`;

type Readiness = {
  health: Record<string, unknown>;
  config: Record<string, unknown>;
  views: Record<string, unknown>;
  chameleon: Record<string, unknown>;
};

async function expectOk(response: APIResponse, label: string): Promise<APIResponse> {
  if (!response.ok()) {
    expect(response.ok(), `${label} returned ${response.status()}: ${await response.text()}`).toBe(true);
  }
  expect(response.ok()).toBe(true);
  return response;
}

async function getJson(request: APIRequestContext, path: string, label = path): Promise<Record<string, unknown>> {
  const response = await expectOk(await request.get(`${apiBaseUrl}${path}`), label);
  return response.json();
}

async function readReadiness(request: APIRequestContext): Promise<Readiness> {
  const [health, config, views, chameleon] = await Promise.all([
    getJson(request, '/health', 'health'),
    getJson(request, '/config', 'config'),
    getJson(request, '/views/status', 'views status'),
    getJson(request, '/chameleon/status', 'chameleon status'),
  ]);

  return { health, config, views, chameleon };
}

function hasLiveFabricCredentials(readiness: Readiness): boolean {
  if (readiness.views.fabric_enabled === false || readiness.config.configured === false) {
    return false;
  }

  const tokenInfo = readiness.config.token_info as { exp?: unknown } | undefined;
  if (typeof tokenInfo?.exp === 'number' && tokenInfo.exp * 1000 <= Date.now()) {
    return false;
  }

  return true;
}

function hasLiveChameleonCredentials(readiness: Readiness): boolean {
  if (readiness.chameleon.enabled !== true || readiness.chameleon.configured !== true) {
    return false;
  }

  const sites = readiness.chameleon.sites as Record<string, { configured?: boolean }> | undefined;
  if (!sites) {
    return true;
  }

  return Object.values(sites).some(site => site.configured === true);
}

function requireLiveMutations(): void {
  test.skip(
    !liveMutationsEnabled,
    'Set E2E_LIVE_MUTATIONS=1 to allow guarded live draft/member mutations. This skeleton never submits provider resources.',
  );
}

async function deleteIfCreated(
  request: APIRequestContext,
  path: string,
  id: string | undefined,
): Promise<void> {
  if (!id) return;
  await request.delete(`${apiBaseUrl}${path}/${encodeURIComponent(id)}`).catch(() => undefined);
}

test.describe('live E2E preflight skeleton', () => {
  test.skip(!liveEnabled, 'Set E2E_FULL=1 to run live E2E preflight checks.');

  test('checks safe live backend status paths', async ({ request }) => {
    const readiness = await readReadiness(request);

    expect(readiness.health.status).toBe('ok');
    expect(readiness.config).toHaveProperty('configured');
    expect(readiness.views).toHaveProperty('fabric_enabled');
    expect(readiness.chameleon).toHaveProperty('enabled');

    const federated = await expectOk(
      await request.get(`${apiBaseUrl}/federated/slices`),
      'federated slice listing',
    );
    expect(await federated.json()).toEqual(expect.any(Array));

    if (hasLiveFabricCredentials(readiness)) {
      await expectOk(await request.get(`${apiBaseUrl}/slices?max_age=0`), 'FABRIC slice listing');
    } else {
      test.info().annotations.push({
        type: 'preflight',
        description: 'FABRIC slice listing was not queried because live FABRIC credentials/status are not ready.',
      });
    }

    if (hasLiveChameleonCredentials(readiness)) {
      const chameleonSlices = await expectOk(
        await request.get(`${apiBaseUrl}/chameleon/slices/all`),
        'Chameleon slice listing',
      );
      expect(await chameleonSlices.json()).toEqual(expect.any(Array));
    } else {
      test.info().annotations.push({
        type: 'preflight',
        description: 'Chameleon slice listing was not queried because live Chameleon credentials/status are not ready.',
      });
    }
  });

  test('guards the FABRIC critical path without submitting resources', async ({ request }) => {
    requireLiveMutations();

    const readiness = await readReadiness(request);
    test.skip(!hasLiveFabricCredentials(readiness), 'Live FABRIC credentials/status are not ready.');

    const name = `live-skeleton-fabric-${Date.now().toString(36)}`;
    let createdName: string | undefined;

    try {
      const created = await (await expectOk(
        await request.post(`${apiBaseUrl}/slices?name=${encodeURIComponent(name)}`),
        'create FABRIC draft',
      )).json();
      createdName = String(created.name || name);
      expect(created.state).toBe('Draft');

      const fetched = await (await expectOk(
        await request.get(`${apiBaseUrl}/slices/${encodeURIComponent(createdName)}`),
        'fetch FABRIC draft',
      )).json();
      expect(fetched.name).toBe(createdName);
    } finally {
      await deleteIfCreated(request, '/slices', createdName);
    }
  });

  test('guards the Chameleon critical path without provisioning resources', async ({ request }) => {
    requireLiveMutations();

    const readiness = await readReadiness(request);
    test.skip(!hasLiveChameleonCredentials(readiness), 'Live Chameleon credentials/status are not ready.');

    const sites = readiness.chameleon.sites as Record<string, { configured?: boolean }> | undefined;
    const site = Object.entries(sites ?? {}).find(([, value]) => value.configured)?.[0] ?? 'CHI@TACC';
    let sliceId: string | undefined;

    try {
      const created = await (await expectOk(
        await request.post(`${apiBaseUrl}/chameleon/drafts`, {
          data: { name: `live-skeleton-chi-${Date.now().toString(36)}`, site },
        }),
        'create Chameleon draft',
      )).json();
      sliceId = String(created.id);
      expect(created.site).toBe(site);
      expect(created.state).toBe('Draft');

      const graph = await (await expectOk(
        await request.get(`${apiBaseUrl}/chameleon/drafts/${encodeURIComponent(sliceId)}/graph`),
        'fetch Chameleon draft graph',
      )).json();
      expect(graph).toHaveProperty('nodes');
    } finally {
      await deleteIfCreated(request, '/chameleon/slices', sliceId);
    }
  });

  test('guards the Federated critical path without submitting member slices', async ({ request }) => {
    requireLiveMutations();

    const readiness = await readReadiness(request);
    test.skip(
      !hasLiveFabricCredentials(readiness) && !hasLiveChameleonCredentials(readiness),
      'No live provider credentials/status are ready for federated validation.',
    );

    let federatedId: string | undefined;

    try {
      const created = await (await expectOk(
        await request.post(`${apiBaseUrl}/federated/slices`, {
          data: { name: `live-skeleton-fed-${Date.now().toString(36)}` },
        }),
        'create federated skeleton',
      )).json();
      federatedId = String(created.id);
      expect(created.kind).toBe('federated');

      const graph = await (await expectOk(
        await request.get(`${apiBaseUrl}/federated/slices/${encodeURIComponent(federatedId)}/graph`),
        'fetch federated skeleton graph',
      )).json();
      expect(graph).toHaveProperty('nodes');
      expect(graph).toHaveProperty('edges');
    } finally {
      await deleteIfCreated(request, '/federated/slices', federatedId);
    }
  });
});
