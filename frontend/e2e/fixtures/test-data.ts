/** Mock API response data for E2E tests. */

export const healthResponse = { status: 'ok', configured: true };

export const configStatus = {
  configured: true,
  has_token: true,
  has_bastion_key: true,
  has_slice_key: true,
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
    dir_name: 'Hello_FABRIC', builtin: true, node_count: 1,
    network_count: 0, has_run_script: false, starred: false,
  },
  {
    name: 'L2 Bridge', description: 'Two nodes with L2 network', category: 'weave',
    dir_name: 'L2_Bridge', builtin: true, node_count: 2,
    network_count: 1, has_run_script: false, starred: false,
  },
];

export const vmTemplatesList = [
  {
    name: 'Basic Ubuntu', description: 'Ubuntu 22 VM', image: 'default_ubuntu_22',
    dir_name: 'Basic_Ubuntu', builtin: true, created: '2024-01-01',
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
  nodes: unknown[]; networks: unknown[]; state: string;
}>) {
  return {
    name,
    id,
    state: opts?.state ?? 'Draft',
    dirty: false,
    lease_start: '',
    lease_end: '',
    error_messages: [],
    nodes: opts?.nodes ?? [],
    networks: opts?.networks ?? [],
    facility_ports: [],
    graph: {
      nodes: [
        { data: { id: 'slice', label: name, type: 'slice' }, classes: 'slice' },
        ...(opts?.nodes ?? []).map((n: any) => ({
          data: { id: n.name, label: `${n.name}\n${n.site}\n${n.cores}c/${n.ram}G/${n.disk}G`, type: 'vm', parent: 'slice' },
          classes: 'vm',
        })),
      ],
      edges: [],
    },
  };
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
