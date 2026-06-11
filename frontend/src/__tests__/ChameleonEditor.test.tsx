import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import ChameleonEditor from '../components/ChameleonEditor';
import * as api from '../api/client';
import type { ChameleonDraft, ChameleonSite } from '../types/chameleon';

vi.mock('../components/CytoscapeGraph', () => ({
  default: () => <div data-testid="mock-cytoscape-graph" />,
}));

vi.mock('../api/client', () => ({
  getChameleonDraft: vi.fn(),
  getChameleonDraftGraph: vi.fn(),
  getChameleonNodeTypesDetail: vi.fn(),
  getChameleonImages: vi.fn(),
  listChameleonNetworks: vi.fn(),
  listChameleonFloatingIps: vi.fn(),
  listChameleonSecurityGroups: vi.fn(),
  listChameleonKeypairs: vi.fn(),
  listChameleonLeases: vi.fn(),
  updateChameleonNodeInterfaces: vi.fn(),
  importChameleonReservation: vi.fn(),
  removeChameleonSliceResource: vi.fn(),
  addChameleonSliceResource: vi.fn(),
  deleteChameleonLease: vi.fn(),
  deleteChameleonInstance: vi.fn(),
  deleteChameleonNetwork: vi.fn(),
  releaseChameleonFloatingIp: vi.fn(),
  deleteChameleonSecurityGroup: vi.fn(),
  extendChameleonLease: vi.fn(),
  precreateLeasesForDraft: vi.fn(),
  createChameleonNetwork: vi.fn(),
  allocateChameleonFloatingIp: vi.fn(),
  associateChameleonFloatingIp: vi.fn(),
  listUnaffiliatedChameleonInstances: vi.fn(),
  setDraftFloatingIps: vi.fn(),
  createChameleonDraft: vi.fn(),
  deleteChameleonDraft: vi.fn(),
  addChameleonDraftNode: vi.fn(),
  removeChameleonDraftNode: vi.fn(),
  updateChameleonDraftNode: vi.fn(),
  addChameleonDraftNetwork: vi.fn(),
  removeChameleonDraftNetwork: vi.fn(),
  getChameleonBootConfig: vi.fn(),
  saveChameleonBootConfig: vi.fn(),
  executeChameleonBootConfig: vi.fn(),
}));

const sites: ChameleonSite[] = [
  {
    name: 'CHI@TACC',
    auth_url: '',
    configured: true,
    location: { lat: 30.2672, lon: -97.7431, city: 'Austin' },
  },
];

const availableNetworks = [
  {
    id: 'net-public',
    name: 'public-net',
    site: 'CHI@TACC',
    status: 'ACTIVE',
    shared: true,
    subnet_details: [{ id: 'sub-public', name: 'public-subnet', cidr: '10.1.0.0/24' }],
  },
  {
    id: 'net-existing',
    name: 'existing-net',
    site: 'CHI@TACC',
    status: 'ACTIVE',
    shared: false,
    subnet_details: [{ id: 'sub-existing', name: 'existing-subnet', cidr: '192.168.10.0/24' }],
  },
  {
    id: 'net-tracked',
    name: 'tracked-net',
    site: 'CHI@TACC',
    status: 'ACTIVE',
    shared: false,
    subnet_details: [{ id: 'sub-tracked', name: 'tracked-subnet', cidr: '172.16.0.0/24' }],
  },
];

const availableLeases = [
  {
    id: 'lease-active-id',
    name: 'lease-active',
    site: 'CHI@TACC',
    _site: 'CHI@TACC',
    status: 'ACTIVE',
    start_date: '',
    end_date: '',
    reservations: [{ id: 'reservation-1', resource_type: 'physical:host', min: 1, max: 1 }],
  },
  {
    id: 'lease-spare-id',
    name: 'lease-spare',
    site: 'CHI@TACC',
    _site: 'CHI@TACC',
    status: 'PENDING',
    start_date: '',
    end_date: '',
    reservations: [{ id: 'reservation-2', resource_type: 'physical:host', min: 2, max: 2 }],
  },
];

const baseDraft: ChameleonDraft = {
  id: 'draft-1',
  name: 'Chameleon Alpha',
  provider: 'chameleon',
  state: 'Draft',
  created: '',
  site: 'CHI@TACC',
  sites: ['CHI@TACC'],
  nodes: [
    {
      id: 'node-1',
      name: 'server-a',
      node_type: 'compute_haswell',
      image: 'CC-Ubuntu22.04',
      count: 1,
      site: 'CHI@TACC',
      interfaces: [
        { nic: 0, network: null },
        { nic: 1, network: { id: 'net-existing', name: 'existing-net' } },
      ],
    },
  ],
  networks: [
    { id: 'draft-net-1', name: 'draft-mesh', connected_nodes: ['node-1'] },
  ],
  floating_ips: [{ node_id: 'node-1', nic: 1 }],
  resources: [
    {
      resource_id: 'res-lease-1',
      provider: 'chameleon',
      type: 'lease',
      id: 'lease-active-id',
      provider_id: 'lease-active-id',
      name: 'lease-active',
      site: 'CHI@TACC',
      status: 'ACTIVE',
      ownership: 'imported',
      managed: false,
      delete_with_slice: false,
    },
    {
      resource_id: 'res-instance-1',
      provider: 'chameleon',
      type: 'instance',
      id: 'inst-1',
      provider_id: 'inst-1',
      name: 'live-server',
      site: 'CHI@TACC',
      status: 'ACTIVE',
      ownership: 'imported',
      managed: false,
      delete_with_slice: false,
      lease_id: 'lease-active-id',
      floating_ip: '203.0.113.8',
      ip_addresses: ['10.0.0.8'],
      port_id: 'port-1',
    },
    {
      resource_id: 'res-network-1',
      provider: 'chameleon',
      type: 'network',
      id: 'net-tracked',
      provider_id: 'net-tracked',
      name: 'tracked-net',
      site: 'CHI@TACC',
      status: 'ACTIVE',
      ownership: 'managed',
      managed: true,
      delete_with_slice: true,
      cidr: '172.16.0.0/24',
    },
    {
      resource_id: 'res-fip-1',
      provider: 'chameleon',
      type: 'floating_ip',
      id: 'fip-1',
      provider_id: 'fip-1',
      floating_ip_id: 'fip-1',
      name: '203.0.113.8',
      site: 'CHI@TACC',
      status: 'ACTIVE',
      ownership: 'managed',
      managed: true,
      delete_with_slice: true,
      floating_ip: '203.0.113.8',
      port_id: 'port-1',
    },
    {
      resource_id: 'res-sg-1',
      provider: 'chameleon',
      type: 'security_group',
      id: 'sg-1',
      provider_id: 'sg-1',
      name: 'ssh-only',
      site: 'CHI@TACC',
      status: '',
      ownership: 'imported',
      managed: false,
      delete_with_slice: false,
    },
  ],
};

function cloneDraft(draft: ChameleonDraft = baseDraft): ChameleonDraft {
  return JSON.parse(JSON.stringify(draft));
}

function renderEditor(draft: ChameleonDraft = baseDraft, props: Partial<ComponentProps<typeof ChameleonEditor>> = {}) {
  return render(
    <ChameleonEditor
      sites={sites}
      formsOnly
      draftId={draft.id}
      draftData={cloneDraft(draft)}
      draftVersion={1}
      onError={() => {}}
      {...props}
    />,
  );
}

function labelForText(text: string): HTMLElement {
  const label = screen.getAllByText(text)
    .map(element => element.closest('label'))
    .find(Boolean);
  if (!label) throw new Error(`Could not find label for ${text}`);
  return label as HTMLElement;
}

describe('ChameleonEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getChameleonDraft).mockResolvedValue(cloneDraft());
    vi.mocked(api.getChameleonDraftGraph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(api.getChameleonNodeTypesDetail).mockResolvedValue({
      site: 'CHI@TACC',
      node_types: [
        {
          node_type: 'compute_haswell',
          total: 4,
          reservable: 2,
          cpu_arch: 'x86_64',
          cpu_count: 24,
          ram_gb: 128,
        },
      ],
    });
    vi.mocked(api.getChameleonImages).mockResolvedValue([
      { id: 'CC-Ubuntu22.04', name: 'CC-Ubuntu22.04', status: 'active' },
    ]);
    vi.mocked(api.listChameleonNetworks).mockResolvedValue(availableNetworks);
    vi.mocked(api.listChameleonFloatingIps).mockResolvedValue([
      {
        id: 'fip-extra',
        floating_ip_address: '203.0.113.55',
        status: 'DOWN',
        site: 'CHI@TACC',
        _site: 'CHI@TACC',
        port_id: '',
      },
    ]);
    vi.mocked(api.listChameleonSecurityGroups).mockResolvedValue([
      { id: 'sg-extra', name: 'project-web', site: 'CHI@TACC', security_group_rules: [] },
    ]);
    vi.mocked(api.listChameleonKeypairs).mockResolvedValue([
      { name: 'project-key', fingerprint: 'aa:bb', _site: 'CHI@TACC' },
      { name: 'loomai-key', fingerprint: 'cc:dd', _site: 'CHI@TACC' },
    ]);
    vi.mocked(api.listChameleonLeases).mockResolvedValue(availableLeases);
    vi.mocked(api.importChameleonReservation).mockResolvedValue({ status: 'ok' });
    vi.mocked(api.addChameleonSliceResource).mockResolvedValue(cloneDraft());
    vi.mocked(api.removeChameleonSliceResource).mockResolvedValue(cloneDraft());
    vi.mocked(api.deleteChameleonLease).mockResolvedValue(undefined);
    vi.mocked(api.deleteChameleonInstance).mockResolvedValue(undefined);
    vi.mocked(api.deleteChameleonNetwork).mockResolvedValue(undefined);
    vi.mocked(api.releaseChameleonFloatingIp).mockResolvedValue(undefined);
    vi.mocked(api.deleteChameleonSecurityGroup).mockResolvedValue(undefined);
    vi.mocked(api.associateChameleonFloatingIp).mockResolvedValue({
      id: 'fip-1',
      floating_ip_address: '203.0.113.8',
      status: 'ACTIVE',
      port_id: '',
    });
    vi.mocked(api.setDraftFloatingIps).mockResolvedValue(cloneDraft());
    vi.mocked(api.listUnaffiliatedChameleonInstances).mockResolvedValue([]);
  });

  it('defaults new servers to an x86 compute node type and stable Ubuntu image', async () => {
    vi.mocked(api.getChameleonNodeTypesDetail).mockResolvedValue({
      site: 'CHI@TACC',
      node_types: [
        { node_type: 'compute_arm64', total: 8, reservable: 8, cpu_arch: 'aarch64' },
        { node_type: 'compute_skylake', total: 32, reservable: 31, cpu_arch: 'x86_64' },
      ],
    });
    vi.mocked(api.getChameleonImages).mockResolvedValue([
      { id: 'cuda-image-id', name: 'ady-ubuntu16.04-cuda-10.01', status: 'active' },
      { id: 'ubuntu-22-id', name: 'CC-Ubuntu22.04', status: 'active' },
    ]);
    const updatedDraft = cloneDraft();
    updatedDraft.nodes.push({
      id: 'node-2',
      name: 'node-2',
      node_type: 'compute_skylake',
      image: 'ubuntu-22-id',
      count: 1,
      site: 'CHI@TACC',
      interfaces: [],
    });
    vi.mocked(api.addChameleonDraftNode).mockResolvedValue(updatedDraft);

    renderEditor();

    await screen.findAllByText('compute_skylake');
    await screen.findAllByText('CC-Ubuntu22.04');
    fireEvent.click(screen.getByTestId('chameleon-add-server'));

    await waitFor(() => {
      expect(api.addChameleonDraftNode).toHaveBeenCalledWith('draft-1', expect.objectContaining({
        node_type: 'compute_skylake',
        image: 'ubuntu-22-id',
        site: 'CHI@TACC',
      }));
    });
  });

  it('stores a selected SSH key override when adding a planned server', async () => {
    const updatedDraft = cloneDraft();
    updatedDraft.nodes.push({
      id: 'node-2',
      name: 'node-2',
      node_type: 'compute_haswell',
      image: 'CC-Ubuntu22.04',
      count: 1,
      site: 'CHI@TACC',
      key_name: 'project-key',
      interfaces: [],
    });
    vi.mocked(api.addChameleonDraftNode).mockResolvedValue(updatedDraft);

    renderEditor();

    await screen.findByText('project-key');
    await screen.findAllByText('CC-Ubuntu22.04');
    fireEvent.change(screen.getByTestId('chameleon-server-key-select'), { target: { value: 'project-key' } });
    fireEvent.click(screen.getByTestId('chameleon-add-server'));

    await waitFor(() => {
      expect(api.addChameleonDraftNode).toHaveBeenCalledWith('draft-1', expect.objectContaining({
        key_name: 'project-key',
      }));
    });
  });

  it('saves a planned server SSH key override from the edit form', async () => {
    const updatedDraft = cloneDraft();
    updatedDraft.nodes[0].key_name = 'project-key';
    vi.mocked(api.updateChameleonDraftNode).mockResolvedValue(updatedDraft);

    renderEditor();

    const row = await screen.findByTestId('chameleon-planned-server-row');
    fireEvent.click(within(row).getByTitle('Edit this server'));
    await waitFor(() => expect(screen.getByTestId('chameleon-server-edit-key-select')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('chameleon-server-edit-key-select'), { target: { value: 'project-key' } });
    fireEvent.click(within(row).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.updateChameleonDraftNode).toHaveBeenCalledWith('draft-1', 'node-1', expect.objectContaining({
        key_name: 'project-key',
      }));
    });
  });

  it('updates planned server NIC assignments from the Servers tab', async () => {
    const updatedDraft = cloneDraft();
    updatedDraft.nodes[0].interfaces = [
      { nic: 0, network: { id: 'net-public', name: 'public-net' } },
      { nic: 1, network: { id: 'net-existing', name: 'existing-net' } },
    ];
    vi.mocked(api.updateChameleonNodeInterfaces).mockResolvedValue(updatedDraft);
    const onDraftUpdated = vi.fn();

    renderEditor(baseDraft, { onDraftUpdated });

    const row = await screen.findByTestId('chameleon-planned-server-row');
    await waitFor(() => {
      expect(within(row).getAllByRole('option', { name: /public-net/ }).length).toBeGreaterThan(0);
    });

    const [nic0Select] = within(row).getAllByRole('combobox');
    fireEvent.change(nic0Select, { target: { value: 'net-public' } });

    await waitFor(() => {
      expect(api.updateChameleonNodeInterfaces).toHaveBeenCalledWith('draft-1', 'node-1', [
        { nic: 0, network: { id: 'net-public', name: 'public-net' } },
        { nic: 1, network: { id: 'net-existing', name: 'existing-net' } },
      ]);
    });
    expect(onDraftUpdated).toHaveBeenCalledWith(expect.objectContaining({ id: 'draft-1' }));
  });

  it('attaches and detaches leases through the lease checklist without live services', async () => {
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Leases' }));
    await screen.findByText('Available Leases');
    await screen.findByText('lease-spare');

    fireEvent.click(within(labelForText('lease-spare')).getByRole('checkbox'));
    await waitFor(() => {
      expect(api.importChameleonReservation).toHaveBeenCalledWith(
        'draft-1',
        'CHI@TACC',
        'lease-spare-id',
        { include_lease: true },
      );
    });
    expect(api.getChameleonDraft).toHaveBeenCalledWith('draft-1');

    fireEvent.click(within(labelForText('lease-active')).getByRole('checkbox'));
    await waitFor(() => {
      expect(api.removeChameleonSliceResource).toHaveBeenCalledWith('draft-1', 'res-lease-1');
    });
  });

  it('attaches an existing Chameleon network as imported slice membership', async () => {
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Networks' }));
    const networkSelect = await screen.findByDisplayValue('-- Select Network --');
    await waitFor(() => {
      expect(within(networkSelect).getByRole('option', { name: /public-net/ })).toBeInTheDocument();
    });

    fireEvent.change(networkSelect, { target: { value: 'net-public' } });
    fireEvent.click(screen.getByRole('button', { name: 'Attach to slice' }));

    await waitFor(() => {
      expect(api.addChameleonSliceResource).toHaveBeenCalledWith(
        'draft-1',
        expect.objectContaining({
          type: 'network',
          id: 'net-public',
          name: 'public-net',
          site: 'CHI@TACC',
          cidr: '10.1.0.0/24',
          ownership: 'imported',
          managed: false,
          delete_with_slice: false,
        }),
      );
    });
  });

  it('shows resource audit rows and toggles cleanup policy explicitly', async () => {
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Resources' }));
    const table = await screen.findByTestId('chameleon-resource-table');
    const rows = within(table).getAllByTestId('chameleon-resource-row');
    const leaseRow = rows.find(row => row.getAttribute('data-resource-id') === 'res-lease-1');
    expect(leaseRow).toBeTruthy();
    expect(leaseRow).toHaveAttribute('data-resource-type', 'lease');
    expect(leaseRow).toHaveAttribute('data-provider-id', 'lease-active-id');
    expect(within(leaseRow as HTMLElement).getByText('lease-active')).toBeInTheDocument();
    expect(within(leaseRow as HTMLElement).getByText('ACTIVE')).toBeInTheDocument();
    expect(within(leaseRow as HTMLElement).getByText('imported')).toBeInTheDocument();
    expect(within(leaseRow as HTMLElement).getByText('Detach')).toBeInTheDocument();

    fireEvent.click(within(leaseRow as HTMLElement).getByRole('button', { name: 'Delete with slice' }));

    await waitFor(() => {
      expect(api.addChameleonSliceResource).toHaveBeenCalledWith(
        'draft-1',
        expect.objectContaining({
          resource_id: 'res-lease-1',
          type: 'lease',
          delete_with_slice: true,
        }),
      );
    });
  });

  it('uses explicit action wording for draft, IP, and provider resource actions', async () => {
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Networks' }));
    const draftNetworkTable = await screen.findByTestId('chameleon-draft-network-table');
    expect(within(draftNetworkTable).getByRole('button', { name: 'Remove from draft' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'IPs' }));
    const ipTable = await screen.findByTestId('chameleon-floating-ip-table');
    const fipRow = within(ipTable).getByText('203.0.113.8').closest('tr');
    expect(fipRow).toBeTruthy();
    expect(within(fipRow as HTMLElement).getByRole('button', { name: 'Disassociate IP' })).toBeInTheDocument();
    expect(within(fipRow as HTMLElement).getByRole('button', { name: 'Detach from slice' })).toBeInTheDocument();
    expect(within(fipRow as HTMLElement).getByRole('button', { name: 'Release floating IP' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Resources' }));
    const resourceTable = await screen.findByTestId('chameleon-resource-table');
    expect(within(resourceTable).getAllByRole('button', { name: 'Detach from slice' }).length).toBeGreaterThan(0);
    expect(within(resourceTable).getAllByRole('button', { name: 'Delete from Chameleon' }).length).toBeGreaterThan(0);
  });
});
