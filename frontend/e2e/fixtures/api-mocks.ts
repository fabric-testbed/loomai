/** Strict fixture-backed API route interceptors for Playwright tests. */

import { Page, Request, Route } from '@playwright/test';
import {
  configStatus,
  makeDefaultApiScenario,
  makeFederatedGraph,
  makeNetwork,
  makeNode,
  makeSliceData,
} from './test-data';

type JsonMap = Record<string, unknown>;

export type MockApiScenario = ReturnType<typeof makeDefaultApiScenario>;

type MockApiOptions = {
  strict?: boolean;
};

type HandlerResult =
  | { status?: number; json: unknown }
  | { status?: number; body: string; contentType?: string }
  | null;

type MockOverrides = Partial<MockApiScenario> & {
  strict?: boolean;
};

function json(status: number, value: unknown): HandlerResult {
  return { status, json: value };
}

function ok(value: unknown): HandlerResult {
  return json(200, value);
}

function notFound(path: string): HandlerResult {
  return json(404, { detail: `Mock fixture not found for ${path}` });
}

function failureResult(failure: unknown): HandlerResult {
  if (failure && typeof failure === 'object' && 'status' in failure) {
    const f = failure as { status?: number; detail?: unknown };
    return json(f.status || 500, { detail: f.detail || 'Mock API failure' });
  }
  return json(500, { detail: 'Mock API failure' });
}

async function requestJson(request: Request): Promise<any> {
  try {
    return (request.postDataJSON() || {}) as JsonMap;
  } catch {
    return {};
  }
}

function pathParts(pathname: string): string[] {
  return pathname.replace(/^\/api\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
}

function findByIdOrName(items: any[], idOrName: string) {
  return items.find(item => item?.id === idOrName || item?.name === idOrName);
}

function sliceSummary(slice: any) {
  return {
    id: slice.id || slice.name,
    name: slice.name || slice.id,
    state: slice.state || 'Draft',
    lease_end: slice.lease_end || '',
    archived: !!slice.archived,
    has_errors: !!slice.has_errors,
  };
}

function buildGraphForFederated(scenario: MockApiScenario, federated: any) {
  const fabricSlices = (federated.fabric_slices || [])
    .map((id: string) => findByIdOrName(scenario.slices as any[], id))
    .filter(Boolean);
  const chameleonSlices = (federated.chameleon_slices || [])
    .map((id: string) => findByIdOrName(scenario.chameleonSlices as any[], id))
    .filter(Boolean);
  return makeFederatedGraph(federated, fabricSlices, chameleonSlices);
}

function remoteTags(artifacts: any[]) {
  const counts = new Map<string, number>();
  for (const artifact of artifacts) {
    for (const tag of artifact.tags || []) {
      counts.set(tag, (counts.get(tag) || 0) + 1);
    }
  }
  return [...counts.entries()].map(([name, count]) => ({ name, count }));
}

function safeMockDirName(name: string) {
  return name.trim().replace(/[^a-zA-Z0-9_-]/g, '_') || 'mock-artifact';
}

function makeMockLocalArtifact(name: string, overrides: Record<string, unknown> = {}) {
  const dirName = safeMockDirName(name);
  return {
    name,
    description: `${name} artifact`,
    description_short: `${name} artifact`,
    description_long: `${name} artifact`,
    source: 'local',
    created: '2026-06-08T12:00:00Z',
    tags: ['mock'],
    category: 'weave',
    dir_name: dirName,
    has_template: true,
    is_from_marketplace: false,
    remote_status: 'not_linked',
    is_author: false,
    remote_artifact: null,
    ...overrides,
  };
}

function findLocalArtifact(scenario: MockApiScenario, dirName: string) {
  return ((scenario as any).artifacts || []).find((artifact: any) => artifact.dir_name === dirName || artifact.name === dirName);
}

async function handleTemplateRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  if (parts[1] === 'create-blank' && method === 'POST') {
    const body = await requestJson(request);
    const name = String(body.name || 'Mock Artifact');
    const dirName = safeMockDirName(name);
    const artifact = makeMockLocalArtifact(name, {
      description: String(body.description || ''),
      category: String(body.category || 'weave'),
      dir_name: dirName,
    });
    (scenario as any).artifacts = [
      ...(((scenario as any).artifacts || []).filter((item: any) => item.dir_name !== dirName)),
      artifact,
    ];
    return ok({ dir_name: dirName, ...artifact });
  }
  if (parts[1] === 'runs' && method === 'GET') return ok(scenario.backgroundRuns);
  if (parts.length === 1) return method === 'GET' ? ok(scenario.templates) : ok({ status: 'ok' });
  if (parts[2] === 'load' && method === 'POST') {
    const body = await requestJson(request);
    const name = body.slice_name || `${parts[1]}-slice`;
    return ok(makeSliceData(String(name), `${name}-id`));
  }
  return ok(parts[2] === 'runs' ? scenario.backgroundRuns : { status: 'ok' });
}

async function handleArtifactsRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  const remoteArtifacts = ((scenario as any).remoteArtifacts || []) as any[];
  const localArtifacts = ((scenario as any).artifacts || []) as any[];

  if (parts.length === 1) {
    return method === 'GET' ? ok(localArtifacts) : ok({ status: 'ok' });
  }
  if (parts[1] === 'my' && method === 'GET') {
    return ok({
      local_artifacts: localArtifacts,
      authored_remote_only: (scenario as any).authoredRemoteOnly || [],
      user_email: (scenario.configStatus as any).token_info?.email || 'test@example.com',
    });
  }
  if (parts[1] === 'remote') {
    if (parts.length === 2 && method === 'GET') {
      return ok({ artifacts: remoteArtifacts, total_count: remoteArtifacts.length, tags: remoteTags(remoteArtifacts) });
    }
    if (parts[2] === 'refresh' && method === 'POST') {
      return ok({ artifacts: remoteArtifacts, total_count: remoteArtifacts.length, tags: remoteTags(remoteArtifacts) });
    }
    const artifact = remoteArtifacts.find(item => item.uuid === parts[2]);
    if (parts.length === 3 && method === 'GET') {
      return artifact ? ok(artifact) : notFound(`/api/artifacts/remote/${parts[2]}`);
    }
    if (parts.length === 3 && method === 'PUT') {
      if (!artifact) return notFound(`/api/artifacts/remote/${parts[2]}`);
      Object.assign(artifact, await requestJson(request));
      return ok(artifact);
    }
    if (parts.length === 3 && method === 'DELETE') {
      (scenario as any).remoteArtifacts = remoteArtifacts.filter(item => item.uuid !== parts[2]);
      return ok({ status: 'deleted', uuid: parts[2] });
    }
    if (parts[3] === 'version') return ok({ status: 'ok', artifact_uuid: parts[2], version: '1.0.1' });
  }
  if (parts[1] === 'download' && method === 'POST') {
    const body = await requestJson(request);
    const remote = remoteArtifacts.find(item => item.uuid === body.uuid) || remoteArtifacts[0];
    const title = String(remote?.title || 'Downloaded Artifact');
    const localName = body.local_name || safeMockDirName(title);
    const artifact = makeMockLocalArtifact(title, {
      dir_name: localName,
      category: remote?.category || 'weave',
      artifact_uuid: remote?.uuid || body.uuid,
      is_from_marketplace: true,
      remote_status: 'linked',
      remote_artifact: remote || null,
    });
    (scenario as any).artifacts = [
      ...localArtifacts.filter((item: any) => item.dir_name !== localName),
      artifact,
    ];
    return ok({ status: 'downloaded', title, category: artifact.category, local_name: localName });
  }
  if (parts[1] === 'local' && parts[3] === 'publish-info' && method === 'GET') {
    const artifact = findLocalArtifact(scenario, parts[2]);
    return ok({
      can_update: !!artifact?.is_author,
      can_fork: !!artifact?.artifact_uuid && !artifact?.is_author,
      is_author: !!artifact?.is_author,
      artifact_uuid: artifact?.artifact_uuid || null,
      remote_title: artifact?.remote_artifact?.title || null,
    });
  }
  if (parts[1] === 'local' && parts[3] === 'metadata' && method === 'PUT') {
    const artifact = findLocalArtifact(scenario, parts[2]);
    if (!artifact) return notFound(`/api/artifacts/local/${parts[2]}`);
    Object.assign(artifact, await requestJson(request));
    return ok({ status: 'ok', metadata: artifact });
  }
  if (parts[1] === 'valid-tags' && method === 'GET') {
    return ok({ tags: [{ tag: 'mock', restricted: false }, { tag: 'weave', restricted: false }] });
  }
  if (parts[1] === 'publish' && method === 'POST') {
    const body = await requestJson(request);
    const uuid = `${safeMockDirName(String(body.title || body.dir_name || 'artifact')).toLowerCase()}-published-uuid`;
    const artifact = findLocalArtifact(scenario, String(body.dir_name || ''));
    if (artifact) {
      artifact.artifact_uuid = uuid;
      artifact.remote_status = 'linked';
      artifact.is_author = true;
    }
    return ok({
      status: 'published',
      uuid,
      title: body.title || artifact?.name || 'Published Artifact',
      visibility: body.visibility || 'author',
      version: '1.0.0',
    });
  }
  return ok({ status: 'ok' });
}

function mockFileEntry(path: string, type: 'file' | 'dir' = 'file') {
  const name = path.split('/').filter(Boolean).pop() || path;
  return {
    name,
    path: `/home/fabric/work/${path}`,
    type,
    size: type === 'file' ? 128 : 0,
    modified: 1717848000,
  };
}

async function handleFilesRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  const url = new URL(request.url());
  const path = url.searchParams.get('path') || '';

  if (parts[1] === 'boot-config' && parts[parts.length - 1] === 'execute-all-stream') {
    return {
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ event: 'done', status: 'ok', message: 'Mock boot config complete' })}\n\n`,
    };
  }

  if (parts.length === 1) {
    if (method === 'GET') return ok(path ? ((scenario as any).fileTree?.[path] || []) : scenario.files);
    if (method === 'DELETE') {
      (scenario as any).files = ((scenario as any).files || []).filter((entry: any) => entry.name !== path && entry.path !== path && !String(entry.path || '').endsWith(`/${path}`));
      return ok({ deleted: path });
    }
  }

  if (parts[1] === 'mkdir' && method === 'POST') {
    const body = await requestJson(request);
    const name = String(body.name || 'new-folder');
    const entry = mockFileEntry(path ? `${path}/${name}` : name, 'dir');
    if (path) {
      (scenario as any).fileTree = { ...((scenario as any).fileTree || {}) };
      (scenario as any).fileTree[path] = [...((scenario as any).fileTree[path] || []), entry];
    } else {
      (scenario as any).files = [...(((scenario as any).files || [])), entry];
    }
    return ok({ created: name });
  }
  if (parts[1] === 'upload' && method === 'POST') return ok({ uploaded: ['mock-upload.txt'] });
  if (parts[1] === 'content') {
    (scenario as any).fileContents = { ...((scenario as any).fileContents || {}) };
    if (method === 'GET') return ok({ path, content: (scenario as any).fileContents[path] || '' });
    if (method === 'PUT') {
      const body = await requestJson(request);
      (scenario as any).fileContents[body.path] = body.content || '';
      return ok({ path: body.path, status: 'ok' });
    }
  }
  if (parts[1] === 'download' || parts[1] === 'download-folder') {
    return { body: 'mock file', contentType: 'application/octet-stream' };
  }
  if (parts[1] === 'vm') {
    const vmPath = url.searchParams.get('path') || '/home';
    const vmFiles = ((scenario as any).vmFiles || []) as any[];
    if (parts.length === 4 && method === 'GET') return ok(vmFiles);
    if (parts[4] === 'mkdir' && method === 'POST') {
      const body = await requestJson(request);
      (scenario as any).vmFiles = [...vmFiles, mockFileEntry(String(body.path || vmPath), 'dir')];
      return ok({ created: body.path || vmPath });
    }
    if (parts[4] === 'delete' && method === 'POST') {
      const body = await requestJson(request);
      (scenario as any).vmFiles = vmFiles.filter((entry: any) => !String(body.path || '').endsWith(entry.name));
      return ok({ deleted: body.path || '' });
    }
    if (parts[4] === 'read-content' && method === 'POST') {
      const body = await requestJson(request);
      return ok({ path: body.path, content: ((scenario as any).vmFileContents || {})[body.path] || '' });
    }
    if (parts[4] === 'write-content' && method === 'POST') {
      const body = await requestJson(request);
      (scenario as any).vmFileContents = { ...((scenario as any).vmFileContents || {}), [body.path]: body.content || '' };
      return ok({ path: body.path, status: 'ok' });
    }
    if (['upload-direct', 'download-direct', 'download-folder', 'execute'].includes(parts[4] || '')) return ok({ status: 'ok' });
  }
  if (parts[1] === 'chameleon') {
    if (parts.length === 3 && method === 'GET') return ok((scenario as any).vmFiles || []);
    return ok({ status: 'ok' });
  }
  return ok({ status: 'ok', content: '', path });
}

function rebuildFabricSliceGraph(slice: any) {
  slice.graph = makeSliceData(slice.name, slice.id || slice.name, {
    state: slice.state,
    nodes: slice.nodes || [],
    networks: slice.networks || [],
    facility_ports: slice.facility_ports || [],
    port_mirrors: slice.port_mirrors || [],
  }).graph;
  return slice;
}

function buildChameleonGraph(slice: any) {
  const siteIds = new Set<string>();
  for (const node of slice.nodes || []) {
    if (node.site) siteIds.add(node.site);
  }
  if (siteIds.size === 0 && slice.site) siteIds.add(slice.site);
  const nodes = [
    ...Array.from(siteIds).map(site => ({
      data: { id: `site-${site}`, label: site, element_type: 'chameleon-site' },
      classes: 'chameleon-cluster',
    })),
    ...(slice.nodes || []).map((node: any) => ({
      data: {
        id: `node-${node.id}`,
        label: node.count && node.count > 1 ? `${node.name} (x${node.count})` : node.name,
        name: node.name,
        site: node.site || slice.site || '',
        parent: node.site ? `site-${node.site}` : undefined,
        element_type: 'chameleon-node',
      },
      classes: 'chameleon-instance',
    })),
    ...(slice.networks || []).map((network: any) => ({
      data: {
        id: `network-${network.id}`,
        label: network.name,
        name: network.name,
        parent: slice.site ? `site-${slice.site}` : undefined,
        element_type: 'chameleon-network',
      },
      classes: 'chameleon-network',
    })),
  ];
  const edges = (slice.networks || []).flatMap((network: any) => (
    (network.connected_nodes || []).map((nodeId: string) => ({
      data: {
        id: `edge-${network.id}-${nodeId}`,
        source: `node-${nodeId}`,
        target: `network-${network.id}`,
        element_type: 'link',
      },
      classes: 'chameleon-link',
    }))
  ));
  return { nodes, edges };
}

function chameleonNodeTypeDetail(site: string) {
  return {
    site,
    node_types: [{
      node_type: 'compute_skylake',
      total: 8,
      reservable: 4,
      cpu_arch: 'x86_64',
      cpu_count: 32,
      cpu_model: 'Intel Xeon',
      ram_gb: 192,
      disk_gb: 480,
    }],
  };
}

function chameleonImages() {
  return [{ id: 'CC-Ubuntu22.04', name: 'CC-Ubuntu22.04', status: 'active', architecture: 'x86_64' }];
}

function makeComponentInterface(nodeName: string, componentName: string) {
  return {
    name: `${nodeName}-${componentName}-p1`,
    node_name: nodeName,
    component_name: componentName,
    network_name: '',
  };
}

function addComponentToNode(node: any, componentInput: any) {
  const component = {
    name: String(componentInput.name || `nic${(node.components || []).length + 1}`),
    model: String(componentInput.model || 'NIC_Basic'),
    interfaces: [],
  };
  if (component.model.toLowerCase().includes('nic')) {
    const iface = makeComponentInterface(node.name, component.name);
    component.interfaces = [iface];
    node.interfaces = [...(node.interfaces || []), iface];
  }
  node.components = [...(node.components || []), component];
  return component;
}

async function handleSliceRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  if (parts.length === 1) {
    if (method === 'GET') return ok((scenario.slices as any[]).map(sliceSummary));
    if (method === 'POST') {
      const url = new URL(request.url());
      const name = url.searchParams.get('name') || `mock-slice-${Date.now()}`;
      const created = makeSliceData(name, `${name}-id`);
      (scenario.slices as any[]).push(created);
      return ok(created);
    }
  }

  const sliceId = parts[1];
  const slice = findByIdOrName(scenario.slices as any[], sliceId);
  if (!slice) return notFound(`/api/slices/${sliceId}`);

  if (parts.length === 2) {
    if (method === 'GET') return ok(slice);
    if (method === 'DELETE') {
      if ((slice.state || 'Draft') === 'Draft') {
        scenario.slices = (scenario.slices as any[]).filter((item: any) => item !== slice);
        return ok({ status: 'deleted' });
      }
      slice.state = 'Dead';
      return ok({ status: 'deleting' });
    }
  }

  const action = parts[2];
  if (action === 'state' && method === 'GET') {
    return ok({ name: slice.name, id: slice.id, state: slice.state || 'Draft', has_errors: false });
  }
  if (action === 'validate' && method === 'GET') {
    return ok({ valid: true, issues: [] });
  }
  if (action === 'slivers' && method === 'GET') {
    return ok({
      slice_name: slice.name,
      slice_state: slice.state || 'Draft',
      nodes: (slice.nodes || []).map((node: any) => ({
        name: node.name,
        reservation_state: node.reservation_state || slice.state || 'Draft',
        site: node.site || '',
        management_ip: node.management_ip || '',
        state_color: node.state_color || '',
        error_message: node.error_message || '',
      })),
    });
  }
  if (action === 'submit' && method === 'POST') {
    if (scenario.submitFailure) return failureResult(scenario.submitFailure);
    slice.state = 'StableOK';
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'refresh' && method === 'POST') return ok(slice);
  if (action === 'nodes' && parts[4] === 'components' && method === 'POST') {
    const node = (slice.nodes || []).find((item: any) => item.name === parts[3]);
    if (!node) return notFound(`/api/slices/${sliceId}/nodes/${parts[3]}`);
    const body = await requestJson(request);
    addComponentToNode(node, body);
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'nodes' && parts.length === 4 && method === 'DELETE') {
    const nodeName = parts[3];
    slice.nodes = (slice.nodes || []).filter((node: any) => node.name !== nodeName);
    slice.networks = (slice.networks || []).map((network: any) => ({
      ...network,
      interfaces: (network.interfaces || []).filter((iface: any) => (
        iface?.node_name !== nodeName && !String(iface?.name || iface).startsWith(`${nodeName}-`)
      )),
    }));
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'nodes' && method === 'POST') {
    const body = await requestJson(request);
    const node = makeNode(String(body.name || `node-${slice.nodes.length + 1}`), String(body.site || 'RENC'));
    const { _pendingComponents, _pendingBootConfig, components, ...nodeUpdates } = body;
    Object.assign(node, nodeUpdates);
    for (const component of (components || [])) addComponentToNode(node, component);
    slice.nodes = [...(slice.nodes || []), node];
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'networks' && method === 'POST') {
    const body = await requestJson(request);
    const network = makeNetwork(String(body.name || `net-${slice.networks.length + 1}`), String(body.type || 'L2Bridge'));
    const interfaces = ((body.interfaces as string[]) || []).map((ifaceName: string) => {
      let nodeName = '';
      for (const node of slice.nodes || []) {
        const flatIface = (node.interfaces || []).find((iface: any) => iface.name === ifaceName);
        if (flatIface) {
          nodeName = node.name;
          flatIface.network_name = network.name;
        }
        for (const component of node.components || []) {
          const componentIface = (component.interfaces || []).find((iface: any) => iface.name === ifaceName);
          if (componentIface) componentIface.network_name = network.name;
        }
      }
      return { name: ifaceName, node_name: nodeName, network_name: network.name };
    });
    Object.assign(network, body, { interfaces });
    slice.networks = [...(slice.networks || []), network];
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'networks' && parts.length === 4 && method === 'DELETE') {
    slice.networks = (slice.networks || []).filter((network: any) => network.name !== parts[3]);
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'facility-ports' && parts.length === 4 && method === 'DELETE') {
    slice.facility_ports = (slice.facility_ports || []).filter((fp: any) => fp.name !== parts[3]);
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (action === 'port-mirrors' && parts.length === 4 && method === 'DELETE') {
    slice.port_mirrors = (slice.port_mirrors || []).filter((pm: any) => pm.name !== parts[3]);
    return ok(rebuildFabricSliceGraph(slice));
  }
  if (['facility-ports', 'port-mirrors'].includes(action) && ['POST', 'PUT', 'DELETE'].includes(method)) {
    return ok(slice);
  }
  if (['export', 'save-to-storage', 'post-boot-config', 'auto-configure-networks'].includes(action)) {
    if (action === 'export' || action === 'post-boot-config') return ok(slice);
    return ok({ status: 'ok' });
  }

  return null;
}

async function handleChameleonRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  const url = new URL(request.url());
  const action = parts[1];
  if (action === 'status') return ok(scenario.chameleonStatus);
  if (action === 'sites' && parts.length >= 4) {
    const site = parts[2];
    if (parts[3] === 'node-types') return ok(chameleonNodeTypeDetail(site));
    if (parts[3] === 'images') return ok(chameleonImages());
    if (parts[3] === 'availability') return ok({ site, hosts: [], flavors: [] });
    if (parts[3] === 'ensure-network' && method === 'POST') return ok({ network_id: 'mock-chi-net-id', network_name: 'mock-chi-net', type: 'private' });
  }
  if (action === 'sites') return ok([{ name: 'CHI@UC', configured: true }, { name: 'CHI@TACC', configured: true }]);
  if (action === 'node-types') return ok([{ name: 'compute_skylake', node_type: 'compute_skylake', available: 4, reservable: 4, total: 8 }]);
  if (action === 'images') return ok(chameleonImages());
  if (action === 'leases') {
    if (parts.length > 2 && method === 'GET') {
      const lease = findByIdOrName(scenario.chameleonLeases as any[], parts[2]);
      return lease ? ok(lease) : notFound(`/api/chameleon/leases/${parts[2]}`);
    }
    return ok(scenario.chameleonLeases);
  }
  if (action === 'instances') {
    if (parts[2] === 'unaffiliated') return ok([]);
    if (parts.length === 2 && method === 'GET') return ok(scenario.chameleonInstances);
    if (parts.length === 2 && method === 'POST') {
      const body = await requestJson(request);
      const created = {
        id: `${body.name || 'mock-instance'}-instance-id`,
        name: body.name || 'mock-instance',
        site: body.site || 'CHI@UC',
        status: 'ACTIVE',
        image: body.image_id || 'CC-Ubuntu22.04',
        ip_addresses: ['192.0.2.40'],
        floating_ip: '203.0.113.40',
      };
      (scenario.chameleonInstances as any[]).push(created);
      return ok(created);
    }
    if (parts.length === 3 && method === 'DELETE') {
      scenario.chameleonInstances = (scenario.chameleonInstances as any[]).filter((instance: any) => instance.id !== parts[2]);
      return ok({ status: 'deleted', id: parts[2] });
    }
    return ok({ status: 'ok' });
  }
  if (action === 'networks') {
    const siteParam = url.searchParams.get('site');
    if (parts.length === 2 && method === 'GET') {
      const networks = siteParam
        ? (scenario.chameleonNetworks as any[]).filter(network => network.site === siteParam)
        : scenario.chameleonNetworks;
      return ok(networks);
    }
    if (parts.length === 2 && method === 'POST') {
      const body = await requestJson(request);
      const created = {
        id: `${body.name || 'mock-network'}-id`,
        name: body.name || 'mock-network',
        site: body.site || 'CHI@UC',
        status: 'ACTIVE',
        shared: false,
        subnet_details: [{ id: `${body.name || 'mock-network'}-subnet`, name: `${body.name || 'mock-network'}-subnet`, cidr: body.cidr || '192.168.10.0/24' }],
      };
      (scenario.chameleonNetworks as any[]).push(created);
      return ok(created);
    }
    return ok({ status: 'ok' });
  }
  if (['floating-ips', 'security-groups', 'keypairs'].includes(action || '')) {
    if (parts.length === 2 && method === 'GET') return ok([]);
    if (parts.length === 2 && method === 'POST') return ok({ id: `${action}-mock-id`, status: 'ok' });
    return ok({ status: 'ok' });
  }
  if (action === 'facility-ports') {
    return ok({
      chameleon_site: url.searchParams.get('site') || 'CHI@UC',
      fabric_site: 'TACC',
      suggested_vlan: 3316,
      vlans: [3316],
      facility_ports: [{ name: 'Chameleon-TACC', site: 'CHI@TACC', fabric_site: 'TACC', interfaces: [{ name: 'port0', vlan_range: ['3000-3999'] }] }],
    });
  }
  if (action === 'slices' || action === 'drafts') {
    if (parts.length === 2) {
      if (method === 'GET') return ok(scenario.chameleonSlices);
      if (method === 'POST') {
        const body = await requestJson(request);
        const created = {
          id: `${body.name || 'mock-chi'}-id`,
          name: body.name || 'mock-chi',
          provider: 'chameleon',
          state: 'Draft',
          created: '2026-06-08T12:00:00Z',
          site: body.site || 'CHI@UC',
          sites: [body.site || 'CHI@UC'],
          nodes: [],
          networks: [],
          floating_ips: [],
          resources: [],
        };
        (scenario.chameleonSlices as any[]).push(created);
        return ok(created);
      }
    }
    const slice = findByIdOrName(scenario.chameleonSlices as any[], parts[2] || '');
    if (!slice) return notFound(`/api/chameleon/${action}/${parts[2] || ''}`);
    if (parts.length === 3 && method === 'GET') return ok(slice);
    if (parts.length === 3 && method === 'DELETE') {
      scenario.chameleonSlices = (scenario.chameleonSlices as any[]).filter((item: any) => item !== slice);
      return ok({ status: 'deleted', draft_id: slice.id });
    }
    if (parts[3] === 'graph' && method === 'GET') return ok(buildChameleonGraph(slice));
    if (parts[3] === 'nodes' && parts.length === 4 && method === 'POST') {
      const body = await requestJson(request);
      slice.nodes = [...(slice.nodes || []), {
        id: `${body.name || 'node'}-id`,
        status: 'Draft',
        interfaces: [{ nic: 0, network: null }, { nic: 1, network: null }],
        ...body,
      }];
      return ok(slice);
    }
    if (parts[3] === 'nodes' && parts.length >= 5) {
      const nodeId = parts[4];
      const node = (slice.nodes || []).find((item: any) => item.id === nodeId || item.name === nodeId);
      if (!node) return notFound(`/api/chameleon/${action}/${slice.id}/nodes/${nodeId}`);
      if (parts.length === 5 && method === 'DELETE') {
        slice.nodes = (slice.nodes || []).filter((item: any) => item !== node);
        slice.networks = (slice.networks || []).map((network: any) => ({
          ...network,
          connected_nodes: (network.connected_nodes || []).filter((id: string) => id !== nodeId),
        }));
        return ok(slice);
      }
      if (parts.length === 5 && method === 'PUT') {
        Object.assign(node, await requestJson(request));
        return ok(slice);
      }
      if (parts[5] === 'interfaces' && method === 'PUT') {
        node.interfaces = await requestJson(request);
        return ok(slice);
      }
      if (parts[5] === 'network' && method === 'PUT') {
        node.network = await requestJson(request);
        return ok(slice);
      }
    }
    if (parts[3] === 'networks' && parts.length === 4 && method === 'POST') {
      const body = await requestJson(request);
      slice.networks = [...(slice.networks || []), { id: `${body.name || 'network'}-id`, connected_nodes: [], ...body }];
      return ok(slice);
    }
    if (parts[3] === 'networks' && parts.length === 5 && method === 'DELETE') {
      slice.networks = (slice.networks || []).filter((network: any) => network.id !== parts[4]);
      return ok(slice);
    }
    if (parts[3] === 'floating-ips' && method === 'PUT') {
      const body = await requestJson(request);
      slice.floating_ips = body.entries || [];
      return ok(slice);
    }
    if (parts[3] === 'import-reservation' && method === 'POST') {
      const body = await requestJson(request);
      const lease = findByIdOrName(scenario.chameleonLeases as any[], body.lease_id || '');
      const site = body.site || lease?.site || lease?._site || slice.site || 'CHI@UC';
      const resourceId = `lease:${site}:${lease?.id || body.lease_id}`;
      const resource = {
        resource_id: resourceId,
        provider: 'chameleon',
        type: 'lease',
        id: lease?.id || body.lease_id,
        lease_id: lease?.id || body.lease_id,
        name: lease?.name || body.lease_id,
        site,
        status: lease?.status || 'ACTIVE',
        reservations: lease?.reservations || [],
        start_date: lease?.start_date || '',
        end_date: lease?.end_date || '',
        ownership: 'imported',
        managed: false,
        delete_with_slice: false,
      };
      slice.resources = [
        ...(slice.resources || []).filter((item: any) => item.resource_id !== resourceId),
        resource,
      ];
      return ok({ status: 'imported', resource });
    }
    if (parts[3] === 'add-resource' && method === 'POST') {
      const body = await requestJson(request);
      const resource = {
        resource_id: body.resource_id || `${body.type || 'resource'}:${body.id || Date.now()}`,
        provider: 'chameleon',
        ownership: body.ownership || 'imported',
        managed: body.managed ?? false,
        delete_with_slice: body.delete_with_slice ?? false,
        ...body,
      };
      slice.resources = [...(slice.resources || []), resource];
      return ok(slice);
    }
    if (parts[3] === 'remove-resource' && method === 'POST') {
      const body = await requestJson(request);
      slice.resources = (slice.resources || []).filter((resource: any) => resource.resource_id !== body.resource_id && resource.id !== body.resource_id);
      return ok(slice);
    }
    if (parts[3] === 'state' && method === 'PUT') {
      const body = await requestJson(request);
      slice.state = body.state || slice.state;
      return ok(slice);
    }
    if (parts[3] === 'precreate-leases' && method === 'POST') {
      const body = await requestJson(request);
      const lease = {
        id: `${body.lease_name || slice.name}-lease-id`,
        name: body.lease_name || slice.name,
        _site: slice.site || 'CHI@UC',
        site: slice.site || 'CHI@UC',
        status: 'ACTIVE',
        start_date: '2026-06-08 12:00',
        end_date: '2026-06-08 18:00',
        reservations: [{ id: `${body.lease_name || slice.name}-reservation`, resource_type: 'physical:host', status: 'active', min: 1, max: 1 }],
      };
      (scenario.chameleonLeases as any[]).push(lease);
      return ok({ leases: [{ site: lease.site, lease_id: lease.id, lease_name: lease.name, status: lease.status, reservations: lease.reservations }], errors: [] });
    }
    if (parts[3] === 'deploy' && method === 'POST') {
      slice.state = 'Active';
      return ok({ draft_id: slice.id, leases: [], errors: [], slice });
    }
    if (['resources', 'security-groups', 'auto-network-setup', 'check-readiness', 'ensure-bastion'].includes(parts[3] || '')) return ok(slice);
  }
  if (action === 'graph') return ok({ nodes: [], edges: [] });
  return null;
}

async function handleFederatedRequest(request: Request, scenario: MockApiScenario, parts: string[]): Promise<HandlerResult> {
  const method = request.method();
  if (!['federated', 'composite'].includes(parts[0])) return null;
  if (parts[1] !== 'slices') return null;

  if (parts.length === 2) {
    if (method === 'GET') return ok(scenario.federatedSlices);
    if (method === 'POST') {
      const body = await requestJson(request);
      const created = {
        id: `${body.name || 'mock-federated'}-id`,
        name: body.name || 'mock-federated',
        kind: 'federated',
        state: 'Draft',
        created: '2026-06-08T12:00:00Z',
        updated: '2026-06-08T12:00:00Z',
        fabric_slices: [],
        chameleon_slices: [],
        members: [],
        cross_connections: [],
        fabric_member_summaries: [],
        chameleon_member_summaries: [],
        other_member_summaries: [],
      };
      (scenario.federatedSlices as any[]).push(created);
      return ok(created);
    }
  }

  const federated = findByIdOrName(scenario.federatedSlices as any[], parts[2] || '');
  if (!federated) return notFound(`/api/${parts[0]}/slices/${parts[2] || ''}`);
  if (parts.length === 3 && method === 'GET') return ok(federated);
  if (parts.length === 3 && method === 'DELETE') {
    scenario.federatedSlices = (scenario.federatedSlices as any[]).filter((item: any) => item !== federated);
    return ok({ status: 'deleted', id: federated.id });
  }
  if (parts[3] === 'graph' && method === 'GET') return ok(buildGraphForFederated(scenario, federated));
  if (parts[3] === 'members' && method === 'PUT') {
    const body = await requestJson(request);
    const members = (body.members as any[]) || [
      ...((body.fabric_slices as string[]) || []).map(slice_id => ({ provider: 'fabric', slice_id })),
      ...((body.chameleon_slices as string[]) || []).map(slice_id => ({ provider: 'chameleon', slice_id })),
    ];
    federated.members = members;
    federated.fabric_slices = members.filter(m => m.provider === 'fabric').map(m => m.slice_id);
    federated.chameleon_slices = members.filter(m => m.provider === 'chameleon').map(m => m.slice_id);
    federated.fabric_member_summaries = federated.fabric_slices.map((id: string) => {
      const slice = findByIdOrName(scenario.slices as any[], id);
      return { id, name: slice?.name || id, state: slice?.state || 'Draft', node_count: slice?.nodes?.length || 0 };
    });
    federated.chameleon_member_summaries = federated.chameleon_slices.map((id: string) => {
      const slice = findByIdOrName(scenario.chameleonSlices as any[], id);
      return { id, name: slice?.name || id, state: slice?.state || 'Draft', site: slice?.site || '' };
    });
    return ok(federated);
  }
  if (parts[3] === 'connections') {
    if (method === 'GET') return ok(federated.cross_connections || []);
    if (method === 'PUT') {
      federated.cross_connections = await requestJson(request);
      return ok(federated);
    }
    if (parts[4] === 'add' && method === 'POST') {
      const body = await requestJson(request);
      federated.cross_connections = [...(federated.cross_connections || []), { id: `conn-${Date.now()}`, ...body }];
      return ok(federated);
    }
  }
  if (parts[3] === 'submit' && method === 'POST') {
    federated.state = 'Provisioning';
    return ok({
      composite_id: federated.id,
      federated_id: federated.id,
      connection_results: federated.cross_connections || [],
      fabric_results: (federated.fabric_slices || []).map((id: string) => ({
        id,
        new_id: id,
        status: 'submitted',
        state: 'StableOK',
      })),
      chameleon_results: (federated.chameleon_slices || []).map((id: string) => ({
        id,
        status: 'submitted',
        result: { draft_id: id, leases: [] },
      })),
      federated_slice: federated,
    });
  }
  return null;
}

async function handleApiRequest(request: Request, scenario: MockApiScenario): Promise<HandlerResult> {
  const url = new URL(request.url());
  const method = request.method();
  const parts = pathParts(url.pathname);
  const root = parts[0] || '';

  if (url.pathname === '/api/auth/status') return ok({ auth_enabled: false, authenticated: true });
  if (url.pathname === '/api/auth/logout') return ok({ status: 'ok' });
  if (url.pathname === '/api/health') {
    const health = scenario.health as any;
    return typeof health?.status === 'number' ? failureResult(health) : ok(health);
  }
  if (url.pathname === '/api/health/detailed') return ok({ status: 'ok', checks: {} });
  if (url.pathname === '/api/config/status' || url.pathname === '/api/config') return ok(scenario.configStatus);
  if (url.pathname === '/api/config/keys/slice/list') {
    return ok([{ name: 'default', is_default: true, fingerprint: 'SHA256:mock', pub_key: 'ssh-ed25519 mock default' }]);
  }
  if (url.pathname === '/api/config/save' && method === 'POST') return ok({ status: 'saved', configured: true });
  if (url.pathname === '/api/config/rebuild-storage' && method === 'POST') {
    return ok({ status: 'ok', directories: 8, directories_created: 2 });
  }
  if (url.pathname === '/api/config/tool-configs') return ok([]);
  if (url.pathname.startsWith('/api/config/slice-key/')) {
    if (method === 'GET') return ok({ slice_name: parts[2] || '', slice_key_id: '' });
    if (method === 'PUT') return ok({ status: 'ok' });
  }
  if (url.pathname === '/api/config/projects') {
    const cfg = (scenario.configStatus as typeof configStatus);
    return ok({ projects: cfg.token_info.projects, bastion_login: cfg.bastion_username, email: cfg.token_info.email, name: cfg.token_info.name });
  }
  if (url.pathname === '/api/projects') {
    return ok({ projects: (scenario.configStatus as typeof configStatus).token_info.projects, active_project_id: (scenario.configStatus as typeof configStatus).project_id });
  }
  if (url.pathname === '/api/projects/switch' && method === 'POST') return ok({ status: 'ok', project_id: (await requestJson(request)).project_uuid || '' });
  if (url.pathname.startsWith('/api/projects/') && url.pathname.endsWith('/details')) return ok({ uuid: parts[1], name: 'Mock Project', owners: [], members: [] });
  if (url.pathname === '/api/views/status') return ok(scenario.viewsStatus);
  if (url.pathname === '/api/sites') return ok(scenario.sites);
  if (url.pathname.startsWith('/api/sites/')) return ok({ name: parts[1], hosts: [], facility_ports: [] });
  if (url.pathname === '/api/links') return ok(scenario.links);
  if (url.pathname === '/api/facility-ports') return ok(scenario.facilityPorts);
  if (url.pathname === '/api/component-models') return ok(scenario.componentModels);
  if (url.pathname === '/api/images') return ok(scenario.images);
  if (root === 'templates') return handleTemplateRequest(request, scenario, parts);
  if (url.pathname === '/api/templates/runs') return ok(scenario.backgroundRuns);
  if (url.pathname === '/api/vm-templates') return method === 'GET' ? ok(scenario.vmTemplates) : ok({ status: 'ok' });
  if (url.pathname.startsWith('/api/vm-templates/')) return ok({ status: 'ok' });
  if (root === 'artifacts') return handleArtifactsRequest(request, scenario, parts);
  if (url.pathname === '/api/recipes') return ok(scenario.recipes);
  if (url.pathname === '/api/experiments') return ok([]);
  if (url.pathname.startsWith('/api/experiments/')) return ok({ status: 'ok' });
  if (url.pathname === '/api/tunnels') return method === 'GET' ? ok(scenario.tunnels) : ok({ status: 'ok' });
  if (url.pathname.startsWith('/api/tunnels/')) return ok({ status: 'closed' });
  if (root === 'files') return handleFilesRequest(request, scenario, parts);
  if (url.pathname.startsWith('/api/jupyter')) return ok(scenario.jupyter);
  if (url.pathname === '/api/ai/chat/agents') return ok([{ id: 'default', name: 'Default', description: 'Default assistant' }]);
  if (url.pathname === '/api/ai/chat/stop') return ok({ status: 'stopped' });
  if (url.pathname === '/api/ai/chat/stream') {
    return {
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ content: 'Mock assistant response.' })}\n\ndata: [DONE]\n\n`,
    };
  }
  if (url.pathname === '/api/ai/models') return ok(scenario.aiModels);
  if (url.pathname === '/api/ai/models/default') {
    if (method === 'PUT') {
      const body = await requestJson(request);
      (scenario.aiModels as any).default = body.model || (scenario.aiModels as any).default;
      return ok({ default: (scenario.aiModels as any).default, source: body.source || 'fabric' });
    }
    return ok({ default: (scenario.aiModels as any).default || 'fabric/mock-model', source: 'fabric' });
  }
  if (url.pathname === '/api/ai/models/refresh') {
    return ok({ ...(scenario.aiModels as any), added: 0, removed: 0, updated: 0, message: 'Models up to date' });
  }
  if (url.pathname === '/api/ai/models/test') return ok({ healthy: true, latency_ms: 12, error: '', model: 'fabric/mock-model', source: 'fabric' });
  if (url.pathname === '/api/ai/tools/status') return ok({});
  if (url.pathname === '/api/ai/agents') return ok([]);
  if (url.pathname === '/api/ai/skills') return ok([]);
  if (url.pathname === '/api/ai/rag/status') return ok({ enabled: false, ready: false });
  if (url.pathname === '/api/people/search') return ok({ results: [] });
  if (url.pathname === '/api/settings') return method === 'GET' ? ok(scenario.settings) : ok(await requestJson(request));
  if (url.pathname === '/api/settings/test-all') {
    return ok({
      token: { ok: true, message: 'Mock token check passed' },
      bastion_ssh: { ok: true, message: 'Mock SSH check passed' },
      fablib: { ok: true, message: 'Mock FABlib check passed' },
      ai_server: { ok: true, message: 'Mock AI server check passed', model_count: 1 },
      nrp_server: { ok: true, message: 'Mock NRP server check passed', model_count: 1 },
      project: { ok: true, message: 'Mock project check passed', project_name: 'TestProject' },
    });
  }
  if (url.pathname === '/api/settings/test-custom-provider') return ok({ ok: true, message: 'Mock provider check passed' });
  if (url.pathname.startsWith('/api/settings/test')) return ok({ ok: true, message: 'Mock setting check passed' });
  if (url.pathname === '/api/trovi/artifacts') return ok({ artifacts: [] });
  if (url.pathname.startsWith('/api/trovi/artifacts/')) return ok({ status: 'downloaded', title: 'Mock Trovi', category: 'notebook', local_name: 'Mock_Trovi' });
  if (url.pathname.startsWith('/api/config/')) return ok({});
  if (url.pathname === '/api/users') return ok(scenario.users);
  if (url.pathname.startsWith('/api/users/')) return ok({ status: 'ok' });
  if (url.pathname.startsWith('/api/schedule/')) return ok(url.pathname.endsWith('/calendar') ? { sites: [], reservations: [] } : []);
  if (url.pathname === '/api/version') return ok({ version: '0.1.32-beta' });
  if (url.pathname === '/api/check-update' || url.pathname === '/api/config/check-update') {
    return ok({ current_version: '0.1.32-beta', latest_version: '0.1.32-beta', update_available: false, docker_hub_url: '', published_at: null });
  }

  if (root === 'slices') return handleSliceRequest(request, scenario, parts);
  if (root === 'chameleon') return handleChameleonRequest(request, scenario, parts);
  if (root === 'federated' || root === 'composite') return handleFederatedRequest(request, scenario, parts);
  return null;
}

export async function mockApiRouter(page: Page, scenario: MockApiScenario, options: MockApiOptions = {}) {
  const strict = options.strict ?? true;
  await page.route('**/api/**', async (route: Route) => {
    const result = await handleApiRequest(route.request(), scenario);
    if (!result) {
      const message = `Unhandled mocked API request: ${route.request().method()} ${new URL(route.request().url()).pathname}`;
      if (strict) throw new Error(message);
      return route.fallback();
    }
    if ('json' in result) {
      return route.fulfill({
        status: result.status || 200,
        contentType: 'application/json',
        body: JSON.stringify(result.json),
      });
    }
    return route.fulfill({
      status: result.status || 200,
      contentType: result.contentType || 'text/plain',
      body: result.body,
    });
  });
}

export async function mockAllApis(page: Page, overrides: MockOverrides = {}) {
  const { strict, ...scenarioOverrides } = overrides;
  const scenario = makeDefaultApiScenario(scenarioOverrides);
  await mockApiRouter(page, scenario, { strict: strict ?? true });
  return scenario;
}
