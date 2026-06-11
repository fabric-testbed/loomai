/** Mock API response data for E2E tests. */

export const healthResponse = { status: 'ok', configured: true };

export const configStatus = {
  configured: true,
  has_token: true,
  has_bastion_key: true,
  has_slice_key: true,
  ai_api_key_set: true,
  nrp_api_key_set: false,
  token_info: {
    email: 'test@example.com',
    name: 'Test User',
    uuid: 'user-uuid-1234',
    exp: Math.floor(Date.now() / 1000) + 86400,
    projects: [{ uuid: 'proj-uuid-1', name: 'TestProject' }],
  },
  project_id: 'proj-uuid-1',
  bastion_username: 'testuser_0000000000',
  slice_key_sets: ['default'],
  default_slice_key: 'default',
};

export const emptySliceList: unknown[] = [];

export const sitesList = [
  {
    name: 'RENC', lat: 35.78, lon: -78.64, state: 'Active',
    hosts: 4, cores_available: 120, cores_capacity: 200,
    ram_available: 480, ram_capacity: 800,
    disk_available: 4000, disk_capacity: 8000,
  },
  {
    name: 'MASS', lat: 42.36, lon: -71.06, state: 'Active',
    hosts: 3, cores_available: 96, cores_capacity: 160,
    ram_available: 384, ram_capacity: 640,
    disk_available: 3200, disk_capacity: 6400,
  },
  {
    name: 'UTAH', lat: 40.77, lon: -111.89, state: 'Active',
    hosts: 2, cores_available: 64, cores_capacity: 128,
    ram_available: 256, ram_capacity: 512,
    disk_available: 2400, disk_capacity: 4800,
  },
];

export const componentModels = [
  { model: 'NIC_Basic', type: 'SmartNIC', description: 'Basic NIC (100 Gbps)' },
  { model: 'NIC_ConnectX_6', type: 'SmartNIC', description: 'ConnectX-6 (100 Gbps)' },
  { model: 'GPU_RTX6000', type: 'GPU', description: 'NVIDIA RTX 6000' },
];

export const imageList = [
  'default_ubuntu_22', 'default_ubuntu_24', 'default_rocky_9',
  'default_centos_9', 'default_debian_12',
];

export const templatesList = [
  {
    name: 'Hello FABRIC', description: 'Single node', category: 'weave',
    dir_name: 'Hello_FABRIC', has_template: true,
    starred: false,
  },
  {
    name: 'L2 Bridge', description: 'Two nodes with L2 network', category: 'weave',
    dir_name: 'L2_Bridge', has_template: true,
    starred: false,
  },
];

export const vmTemplatesList = [
  {
    name: 'Basic Ubuntu', description: 'Ubuntu 22 VM', image: 'default_ubuntu_22',
    dir_name: 'Basic_Ubuntu', created: '2024-01-01',
    images: ['default_ubuntu_22'], variant_count: 0, version: '1.0',
  },
];

export function makeEmptyGraph() {
  return {
    nodes: [{ data: { id: 'slice', label: 'test-slice', type: 'slice' }, classes: 'slice' }],
    edges: [],
  };
}

export function makeSliceData(name: string, id: string, opts?: Partial<{
  nodes: unknown[]; networks: unknown[]; state: string; facility_ports: unknown[]; port_mirrors: unknown[];
}>) {
  const nodes = opts?.nodes ?? [];
  const networks = opts?.networks ?? [];
  const nodeForInterface = (ifaceName: string) => (nodes as any[]).find((node: any) =>
    (node.interfaces || []).some((iface: any) => iface.name === ifaceName)
    || (node.components || []).some((component: any) =>
      (component.interfaces || []).some((iface: any) => iface.name === ifaceName),
    ),
  );
  const networkEdges = (networks as any[]).flatMap((net: any) => (net.interfaces || []).map((iface: any) => {
    const ifaceName = typeof iface === 'string' ? iface : iface?.name;
    const targetNode = iface?.node_name || nodeForInterface(ifaceName)?.name || ifaceName;
    return {
      data: {
        id: `edge:${net.name}:${ifaceName}`,
        source: targetNode,
        target: net.name,
        interface_name: ifaceName,
        network_name: net.name,
        element_type: 'link',
      },
      classes: 'link',
    };
  }).filter((edge: any) => edge.data.source && edge.data.target));
  return {
    name,
    id,
    state: opts?.state ?? 'Draft',
    dirty: false,
    lease_start: '',
    lease_end: '',
    error_messages: [],
    nodes,
    networks,
    facility_ports: opts?.facility_ports ?? [],
    port_mirrors: opts?.port_mirrors ?? [],
    graph: {
      nodes: [
        { data: { id: 'slice', label: name, type: 'slice' }, classes: 'slice' },
        ...(nodes as any[]).map((n: any) => ({
          data: { id: n.name, label: `${n.name}\n${n.site}\n${n.cores}c/${n.ram}G/${n.disk}G`, type: 'vm', element_type: 'node', name: n.name, parent: 'slice' },
          classes: 'vm',
        })),
        ...(networks as any[]).map((net: any) => ({
          data: { id: net.name, label: net.name, type: 'network', element_type: 'network', name: net.name, network_type: net.type, parent: 'slice' },
          classes: `network ${net.layer === 'L3' ? 'network-l3' : 'network-l2'}`,
        })),
      ],
      edges: networkEdges,
    },
  };
}

export function makeSliceSummary(name: string, id = name, state = 'Draft') {
  return { name, id, state, lease_end: '', archived: false, has_errors: false };
}

export function makeNode(name: string, site = 'RENC') {
  return {
    name, site, site_group: '', host: '', cores: 2, ram: 8, disk: 10,
    image: 'default_ubuntu_22', image_type: 'qcow2',
    management_ip: '', reservation_state: '', error_message: '',
    username: 'ubuntu', components: [], interfaces: [],
  };
}

export function makeNetwork(name: string, type = 'L2Bridge') {
  return {
    name, type, layer: type.startsWith('FABNet') ? 'L3' : 'L2',
    subnet: '', gateway: '', interfaces: [],
  };
}

export function makeChameleonNode(name: string, site = 'CHI@UC', overrides: Record<string, unknown> = {}) {
  return {
    id: `${name}-id`,
    name,
    node_type: 'compute_skylake',
    image: 'CC-Ubuntu22.04',
    count: 1,
    site,
    status: 'Draft',
    network: null,
    interfaces: [],
    ...overrides,
  };
}

export function makeChameleonNetwork(name: string, site = 'CHI@UC', overrides: Record<string, unknown> = {}) {
  return {
    id: `${name}-id`,
    name,
    site,
    status: 'ACTIVE',
    shared: false,
    subnet_details: [{ id: `${name}-subnet`, name: `${name}-subnet`, cidr: '192.168.10.0/24' }],
    ...overrides,
  };
}

export function makeChameleonLease(name: string, site = 'CHI@UC', overrides: Record<string, unknown> = {}) {
  return {
    id: `${name}-lease-id`,
    name,
    _site: site,
    site,
    status: 'ACTIVE',
    start_date: '2026-06-08 12:00',
    end_date: '2026-06-08 18:00',
    reservations: [{ id: `${name}-reservation`, resource_type: 'physical:host', status: 'active', min: 1, max: 1 }],
    ...overrides,
  };
}

export function makeChameleonInstance(name: string, site = 'CHI@UC', overrides: Record<string, unknown> = {}) {
  return {
    id: `${name}-instance-id`,
    name,
    site,
    status: 'ACTIVE',
    image: 'CC-Ubuntu22.04',
    ip_addresses: ['192.0.2.20'],
    floating_ip: '203.0.113.20',
    created: '2026-06-08T12:00:00Z',
    ...overrides,
  };
}

export function makeChameleonSlice(name: string, id = name, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name,
    provider: 'chameleon',
    state: 'Draft',
    created: '2026-06-08T12:00:00Z',
    site: 'CHI@UC',
    sites: ['CHI@UC'],
    nodes: [],
    networks: [],
    floating_ips: [],
    resources: [],
    ...overrides,
  };
}

export function makeFederatedSlice(
  name: string,
  id = name,
  opts: Partial<{
    fabricSlices: Array<{ id: string; name: string; state?: string; node_count?: number }>;
    chameleonSlices: Array<{ id: string; name: string; state?: string; site?: string; node_count?: number }>;
    state: string;
    crossConnections: unknown[];
  }> = {},
) {
  const fabricSummaries = opts.fabricSlices ?? [];
  const chameleonSummaries = opts.chameleonSlices ?? [];
  return {
    id,
    name,
    kind: 'federated',
    state: opts.state ?? 'Draft',
    created: '2026-06-08T12:00:00Z',
    updated: '2026-06-08T12:00:00Z',
    fabric_slices: fabricSummaries.map(s => s.id),
    chameleon_slices: chameleonSummaries.map(s => s.id),
    members: [
      ...fabricSummaries.map(s => ({ provider: 'fabric', slice_id: s.id, name: s.name })),
      ...chameleonSummaries.map(s => ({ provider: 'chameleon', slice_id: s.id, name: s.name, site: s.site })),
    ],
    cross_connections: opts.crossConnections ?? [],
    fabric_member_summaries: fabricSummaries.map(s => ({ state: 'Draft', node_count: 0, ...s })),
    chameleon_member_summaries: chameleonSummaries.map(s => ({ state: 'Draft', site: 'CHI@UC', node_count: 0, ...s })),
    other_member_summaries: [],
  };
}

export function makeFederatedGraph(federated: any, fabricSlices: any[] = [], chameleonSlices: any[] = []) {
  const nodes = [
    { data: { id: `fed:${federated.id}`, label: federated.name, element_type: 'federated-slice' }, classes: 'slice federated-slice' },
    ...fabricSlices.flatMap(slice => (slice.graph?.nodes || []).map((node: any) => ({
      ...node,
      data: { ...(node.data || {}), parent: `fed:${federated.id}`, testbed: 'fabric' },
      classes: `${node.classes || ''} fabric-member`.trim(),
    }))),
    ...chameleonSlices.flatMap(slice => (slice.nodes || []).map((node: any) => ({
      data: {
        id: `chi:${slice.id}:${node.id || node.name}`,
        label: `${node.name}\n${node.site || slice.site || ''}`,
        name: node.name,
        site: node.site || slice.site || '',
        parent: `fed:${federated.id}`,
        testbed: 'chameleon',
        element_type: 'chameleon-node',
      },
      classes: 'chameleon-node chameleon-member',
    }))),
  ];
  return { nodes, edges: [] };
}

export function makeArtifact(name: string, overrides: Record<string, unknown> = {}) {
  return {
    name,
    description: `${name} artifact`,
    description_short: `${name} artifact`,
    description_long: `${name} artifact`,
    source: 'local',
    created: '2026-06-08T12:00:00Z',
    tags: ['mock'],
    category: 'weave',
    dir_name: name.replace(/\s+/g, '_'),
    has_template: true,
    starred: false,
    is_from_marketplace: false,
    remote_status: 'not_linked',
    is_author: false,
    remote_artifact: null,
    ...overrides,
  };
}

export function makeRemoteArtifact(title: string, overrides: Record<string, unknown> = {}) {
  const slug = title.replace(/\s+/g, '-').toLowerCase();
  return {
    uuid: `${slug}-uuid`,
    title,
    description_short: `${title} remote artifact`,
    description_long: `${title} remote artifact`,
    visibility: 'public',
    tags: ['mock', 'weave'],
    category: 'weave',
    authors: [{ name: 'Test User', affiliation: 'FABRIC' }],
    versions: [{ uuid: `${slug}-version-1`, version: '1.0.0', urn: `urn:mock:${slug}:1`, active: true, created: '2026-06-08T12:00:00Z', version_downloads: 3 }],
    artifact_views: 12,
    artifact_downloads_active: 3,
    number_of_versions: 1,
    created: '2026-06-08T12:00:00Z',
    modified: '2026-06-08T12:00:00Z',
    ...overrides,
  };
}

export function makeSettings(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    paths: {
      storage_dir: '/home/fabric/work',
      config_dir: '/home/fabric/work/fabric_config',
      slices_dir: '/home/fabric/work/my_slices',
      artifacts_dir: '/home/fabric/work/my_artifacts',
      notebooks_dir: '/home/fabric/work/notebooks',
      ai_tools_dir: '/home/fabric/work/.ai-tools',
      token_file: '/home/fabric/work/fabric_config/id_token.json',
      bastion_key_file: '/home/fabric/work/fabric_config/fabric_bastion_key',
      slice_keys_dir: '/home/fabric/work/fabric_config/slice_keys',
      ssh_config_file: '/home/fabric/work/fabric_config/ssh_config',
      log_file: '/tmp/fablib/fablib.log',
    },
    fabric: {
      project_id: 'proj-uuid-1',
      bastion_username: 'testuser_0000000000',
      hosts: {
        credmgr: 'cm.fabric-testbed.net',
        orchestrator: 'orchestrator.fabric-testbed.net',
        core_api: 'uis.fabric-testbed.net',
        bastion: 'bastion.fabric-testbed.net',
        artifact_manager: 'artifacts.fabric-testbed.net',
      },
      logging: { level: 'INFO' },
      avoid_sites: [],
      ssh_command_line: 'ssh -F {config_dir}/ssh_config {{ _self_.username }}@{{ _self_.management_ip }}',
    },
    views: { composite_enabled: true },
    chameleon: { enabled: true, sites: {} },
    ai: {
      fabric_api_key: 'mock-ai-key',
      nrp_api_key: '',
      ai_server_url: 'https://ai.fabric-testbed.net',
      nrp_server_url: 'https://ellm.nrp-nautilus.io',
      default_model: 'fabric/mock-model',
      custom_providers: [],
      tools: {
        antigravity: false,
        codex: false,
        claude: false,
        aider: true,
        opencode: true,
        crush: true,
        deepagents: true,
      },
    },
    services: { jupyter_port: 8889, model_proxy_port: 9199 },
    tool_configs: {},
    ...overrides,
  };
}

export function makeAiModels(overrides: Record<string, unknown> = {}) {
  return {
    default: 'fabric/mock-model',
    fabric: [{ id: 'fabric/mock-model', name: 'fabric/mock-model', healthy: true, context_length: 128000, tier: 'large', supports_tools: true }],
    nrp: [{ id: 'nrp/mock-model', name: 'nrp/mock-model', healthy: true, context_length: 64000, tier: 'standard', supports_tools: true }],
    custom: {},
    has_key: { fabric: true, nrp: false },
    models: ['fabric/mock-model'],
    nrp_models: ['nrp/mock-model'],
    ...overrides,
  };
}

export function makeFileEntry(name: string, type: 'file' | 'dir' = 'file', overrides: Record<string, unknown> = {}) {
  return {
    name,
    path: `/home/fabric/work/${name}`,
    type,
    size: type === 'file' ? 128 : 0,
    modified: 1717848000,
    ...overrides,
  };
}

export function makeTunnel(name: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `${name}-tunnel`,
    slice_name: 'mock-fabric',
    node_name: name,
    local_port: 9101,
    remote_port: 80,
    protocol: 'http',
    url: 'http://localhost:9101',
    status: 'running',
    ...overrides,
  };
}

export function makeJupyterStatus(overrides: Record<string, unknown> = {}) {
  return {
    running: false,
    url: '',
    token: '',
    ...overrides,
  };
}

export function makeApiFailure(message: string, status = 500) {
  return { status, detail: message };
}

export function makeDefaultApiScenario(overrides: Record<string, unknown> = {}) {
  const fabricSlice = makeSliceData('mock-fabric', 'mock-fabric-id', { nodes: [makeNode('node1')], networks: [makeNetwork('net1')] });
  const chameleonSlice = makeChameleonSlice('mock-chameleon', 'mock-chameleon-id', {
    nodes: [makeChameleonNode('chi-node')],
    networks: [makeChameleonNetwork('chi-net')],
    resources: [makeChameleonLease('chi-lease'), makeChameleonInstance('chi-node')],
  });
  const federatedSlice = makeFederatedSlice('mock-federated', 'mock-federated-id', {
    fabricSlices: [{ id: fabricSlice.id, name: fabricSlice.name, state: fabricSlice.state, node_count: fabricSlice.nodes.length }],
    chameleonSlices: [{ id: chameleonSlice.id, name: chameleonSlice.name, state: chameleonSlice.state, site: chameleonSlice.site }],
  });
  return {
    health: healthResponse,
    configStatus,
    viewsStatus: { fabric_enabled: true, chameleon_enabled: true, composite_enabled: true },
    slices: [fabricSlice],
    sites: sitesList,
    links: [],
    facilityPorts: [],
    componentModels,
    images: imageList,
    templates: templatesList,
    vmTemplates: vmTemplatesList,
    chameleonStatus: { enabled: true, configured: true, sites: { 'CHI@UC': { configured: true } } },
    chameleonSlices: [chameleonSlice],
    chameleonLeases: [makeChameleonLease('chi-lease')],
    chameleonInstances: [makeChameleonInstance('chi-node')],
    chameleonNetworks: [makeChameleonNetwork('chi-net')],
    federatedSlices: [federatedSlice],
    artifacts: [makeArtifact('Mock Artifact')],
    remoteArtifacts: [makeRemoteArtifact('Remote Mock Artifact')],
    authoredRemoteOnly: [],
    fileContents: { 'README.md': '# Mock README\n' },
    vmFiles: [makeFileEntry('vm-readme.txt')],
    vmFileContents: { '/home/ubuntu/vm-readme.txt': 'vm readme\n' },
    recipes: [],
    backgroundRuns: [],
    aiModels: makeAiModels(),
    settings: makeSettings(),
    files: [makeFileEntry('README.md'), makeFileEntry('experiments', 'dir')],
    tunnels: [makeTunnel('node1')],
    jupyter: makeJupyterStatus(),
    users: { users: [], active_user: '' },
    ...overrides,
  };
}

export function scenarioChameleonDisabled(overrides: Record<string, unknown> = {}) {
  return makeDefaultApiScenario({
    chameleonStatus: { enabled: false, configured: false, sites: {} },
    viewsStatus: { fabric_enabled: true, chameleon_enabled: false, composite_enabled: true },
    chameleonSlices: [],
    ...overrides,
  });
}

export function scenarioExpiredToken(overrides: Record<string, unknown> = {}) {
  return makeDefaultApiScenario({
    configStatus: {
      ...configStatus,
      has_token: false,
      token_info: { ...configStatus.token_info, exp: Math.floor(Date.now() / 1000) - 60 },
    },
    ...overrides,
  });
}

export function scenarioBackendUnavailable(overrides: Record<string, unknown> = {}) {
  return makeDefaultApiScenario({
    health: makeApiFailure('Backend unavailable', 503),
    ...overrides,
  });
}

export function scenarioNoSlices(overrides: Record<string, unknown> = {}) {
  return makeDefaultApiScenario({
    slices: [],
    chameleonSlices: [],
    federatedSlices: [],
    ...overrides,
  });
}

export function scenarioProvisioningError(overrides: Record<string, unknown> = {}) {
  return makeDefaultApiScenario({
    submitFailure: makeApiFailure('Mock provisioning failed', 409),
    ...overrides,
  });
}

export function scenarioStaleFederatedMember(overrides: Record<string, unknown> = {}) {
  const federatedSlice = makeFederatedSlice('stale-member-fed', 'stale-member-fed-id', {
    fabricSlices: [{ id: 'missing-fabric-id', name: 'missing-fabric', state: 'Missing' }],
    chameleonSlices: [],
  });
  return makeDefaultApiScenario({
    slices: [],
    federatedSlices: [federatedSlice],
    ...overrides,
  });
}
