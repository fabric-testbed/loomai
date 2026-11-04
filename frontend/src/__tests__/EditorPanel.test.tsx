import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import EditorPanel from '../components/EditorPanel';
import * as api from '../api/client';
import type { FacilityPortInfo, SliceData } from '../types/fabric';

vi.mock('../api/client', () => ({
  listSliceKeySets: vi.fn().mockResolvedValue([]),
  getSliceKeyAssignment: vi.fn().mockResolvedValue({ slice_key_id: '' }),
  setSliceKeyAssignment: vi.fn().mockResolvedValue({ status: 'ok' }),
  listFacilityPorts: vi.fn(),
  addFacilityPort: vi.fn(),
  listSiteHosts: vi.fn().mockResolvedValue([]),
  addNode: vi.fn(),
  addComponent: vi.fn(),
  addNetwork: vi.fn(),
  saveBootConfig: vi.fn(),
  getVmTemplate: vi.fn(),
  getVmTemplateVariant: vi.fn(),
  resolveSites: vi.fn(),
  getChameleonNodeTypes: vi.fn().mockResolvedValue({ node_types: [] }),
  getChameleonImages: vi.fn().mockResolvedValue([]),
  renewLease: vi.fn(),
}));

const facilityPorts: FacilityPortInfo[] = [
  {
    name: 'Chameleon-TACC',
    site: 'TACC',
    interfaces: [
      {
        name: 'HundredGigE0/0/0/1',
        vlan_range: ['3300-3302'],
        local_name: 'HundredGigE0/0/0/1',
        device_name: 'tacc-border',
        allocated_vlans: ['3301'],
        region: 'Austin',
      },
    ],
  },
  {
    name: 'StarLight',
    site: 'STAR',
    interfaces: [
      {
        name: 'Ethernet1/1',
        vlan_range: ['1800-1802'],
        local_name: 'Ethernet1/1',
        device_name: 'star-border',
        allocated_vlans: [],
        region: 'Chicago',
      },
    ],
  },
];

const sliceData: SliceData = {
  name: 'draft-slice',
  id: 'slice-1',
  state: 'Draft',
  dirty: false,
  lease_start: '',
  lease_end: '',
  error_messages: [],
  nodes: [],
  networks: [],
  facility_ports: [],
  port_mirrors: [],
  graph: { nodes: [], edges: [] },
};

function renderPanel(overrides: Partial<ComponentProps<typeof EditorPanel>> = {}) {
  return render(
    <EditorPanel
      sliceData={sliceData}
      sliceName="draft-slice"
      onSliceUpdated={() => {}}
      onCollapse={() => {}}
      sites={[]}
      images={[]}
      componentModels={[]}
      facilityPorts={[]}
      viewContext="fabric"
      {...overrides}
    />
  );
}

describe('EditorPanel facility port selector', () => {
  beforeEach(() => {
    vi.mocked(api.listFacilityPorts).mockResolvedValue(facilityPorts);
    vi.mocked(api.addFacilityPort).mockResolvedValue({
      ...sliceData,
      facility_ports: [{ name: 'fp1', site: 'TACC', vlan: '3300', bandwidth: '10 Gbps', interfaces: [] }],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('loads project facility ports on demand and filters the selectable list', async () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Slivers' }));
    fireEvent.click(screen.getByTestId('add-sliver-button'));
    const facilityPortOption = screen
      .getAllByTestId('add-sliver-option')
      .find((option) => option.getAttribute('data-sliver-type') === 'facility-port');
    expect(facilityPortOption).toBeTruthy();
    fireEvent.click(facilityPortOption!);

    await waitFor(() => expect(api.listFacilityPorts).toHaveBeenCalled());
    expect(await screen.findByText('2 of 2 facility ports')).toBeInTheDocument();

    const searchInput = screen.getByTestId('facility-port-search-input');
    fireEvent.focus(searchInput);
    expect(await screen.findByText('Chameleon-TACC')).toBeInTheDocument();
    expect(screen.getByText('StarLight')).toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: 'tacc-border' } });
    expect(screen.getByText('Chameleon-TACC')).toBeInTheDocument();
    expect(screen.queryByText('StarLight')).not.toBeInTheDocument();
    expect(screen.getByText('1 of 2 facility ports')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Chameleon-TACC'));
    expect(screen.getByTestId('facility-port-search-input')).toHaveValue('Chameleon-TACC (TACC)');
    expect(screen.getByTestId('facility-port-name-input')).toHaveValue('Chameleon-TACC');

    const vlanInput = screen.getByTestId('facility-port-vlan-input');
    fireEvent.focus(vlanInput);
    const vlanOptions = screen.getByTestId('facility-port-vlan-options');
    fireEvent.click(within(vlanOptions).getByText('3300'));

    fireEvent.click(screen.getByTestId('facility-port-submit'));
    expect(api.addFacilityPort).toHaveBeenCalledWith('draft-slice', {
      name: 'Chameleon-TACC',
      site: 'TACC',
      vlan: '3300',
      bandwidth: 10,
    });
  });

  it('adds a FABRIC VM with a pending NIC component from the editor form', async () => {
    const onSliceUpdated = vi.fn();
    vi.mocked(api.addNode).mockResolvedValue({
      ...sliceData,
      nodes: [{
        name: 'fabric-node-1',
        site: 'RENC',
        cores: 4,
        ram: 16,
        disk: 40,
        image: 'default_ubuntu_22',
        image_type: 'qcow2',
        username: 'ubuntu',
        components: [],
        interfaces: [],
      }],
    } as any);
    vi.mocked(api.addComponent).mockResolvedValue({
      ...sliceData,
      nodes: [{
        name: 'fabric-node-1',
        site: 'RENC',
        cores: 4,
        ram: 16,
        disk: 40,
        image: 'default_ubuntu_22',
        image_type: 'qcow2',
        username: 'ubuntu',
        components: [{ name: 'nic1', model: 'NIC_Basic', interfaces: [] }],
        interfaces: [],
      }],
    } as any);

    renderPanel({
      onSliceUpdated,
      sites: [{
        name: 'RENC',
        state: 'Active',
        cores_available: 64,
        ram_available: 256,
        disk_available: 1000,
      } as any],
      images: ['default_ubuntu_22'],
      componentModels: [{ model: 'NIC_Basic', type: 'SmartNIC', description: 'Basic NIC' } as any],
    });

    fireEvent.click(screen.getByRole('button', { name: 'Slivers' }));
    fireEvent.click(screen.getByTestId('add-sliver-button'));
    const nodeOption = screen
      .getAllByTestId('add-sliver-option')
      .find((option) => option.getAttribute('data-sliver-type') === 'node');
    expect(nodeOption).toBeTruthy();
    fireEvent.click(nodeOption!);

    fireEvent.change(screen.getByTestId('node-name-input'), { target: { value: 'fabric-node-1' } });
    fireEvent.change(screen.getByTestId('node-site-select'), { target: { value: 'RENC' } });
    fireEvent.change(screen.getByTestId('node-cores-input'), { target: { value: '4' } });
    fireEvent.change(screen.getByTestId('node-ram-input'), { target: { value: '16' } });
    fireEvent.change(screen.getByTestId('node-disk-input'), { target: { value: '40' } });
    fireEvent.change(screen.getByTestId('node-component-name-input'), { target: { value: 'nic1' } });
    fireEvent.click(screen.getByTestId('node-component-add'));

    expect(screen.queryByTestId('node-image-type-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('node-username-input')).not.toBeInTheDocument();
    expect(screen.queryByTestId('node-instance-type-input')).not.toBeInTheDocument();

    expect(screen.getByTestId('node-pending-component-row')).toHaveAttribute('data-component-name', 'nic1');

    fireEvent.click(screen.getByTestId('node-submit'));

    await waitFor(() => expect(api.addNode).toHaveBeenCalled());
    expect(api.addNode).toHaveBeenCalledWith('draft-slice', expect.objectContaining({
      name: 'fabric-node-1',
      site: 'RENC',
      cores: 4,
      ram: 16,
      disk: 40,
      image: 'default_ubuntu_22',
      _pendingComponents: [{ name: 'nic1', model: 'NIC_Basic' }],
    }));
    await waitFor(() => expect(api.addComponent).toHaveBeenCalledWith('draft-slice', 'fabric-node-1', {
      name: 'nic1',
      model: 'NIC_Basic',
    }));
    expect(onSliceUpdated).toHaveBeenCalled();
  });
});

describe('EditorPanel lease renew panel', () => {
  const HOUR = 3600 * 1000;
  const activeSlice = (leaseEndOffsetHours: number, maxLeaseHours?: number): SliceData => ({
    ...sliceData,
    name: 'active-slice',
    state: 'StableOK',
    lease_start: new Date(Date.now() - HOUR).toISOString(),
    lease_end: new Date(Date.now() + leaseEndOffsetHours * HOUR).toISOString(),
    ...(maxLeaseHours ? { max_lease_hours: maxLeaseHours } : {}),
  });
  const renderActive = (data: SliceData) => renderPanel({ sliceData: data, sliceName: 'active-slice' });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('replaces the picker with an explanation when the lease already exceeds the cap', () => {
    renderActive(activeSlice(24, 6));

    expect(screen.getByText(/already runs past the 6 h lease policy/)).toBeInTheDocument();
    expect(screen.getByText(/Renewal opens after/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Renew Lease' })).not.toBeInTheDocument();
  });

  it('bounds the picker by the cap and defaults to it', () => {
    const { container } = renderActive(activeSlice(2, 6));

    const input = container.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    expect(input.max).toBeTruthy();
    expect(input.min).toBeTruthy();
    // Default is lease_end + 1 day, clamped to the 6 h cap.
    expect(input.value).toBe(input.max);
    expect(screen.getByText(/Policy limit: 6 h from now/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Renew Lease' })).toBeEnabled();
  });

  it('blocks a date past the cap before calling the API', () => {
    const { container } = renderActive(activeSlice(2, 6));

    const input = container.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2099-01-01T00:00' } });

    expect(screen.getByText(/Policy allows at most 6 h from now/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Renew Lease' })).toBeDisabled();
    expect(api.renewLease).not.toHaveBeenCalled();
  });

  it('leaves the picker unbounded when no cap is configured', () => {
    const { container } = renderActive(activeSlice(24));

    const input = container.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    expect(input.max).toBe('');
    expect(screen.queryByText(/Policy limit/)).not.toBeInTheDocument();
  });

  it('shows the backend detail message instead of raw JSON on failure', async () => {
    vi.mocked(api.renewLease).mockRejectedValue(new Error(
      'API error 422: {"detail":{"code":"LEASE_ALREADY_EXCEEDS_POLICY","message":"Nothing to renew."}}',
    ));
    renderActive(activeSlice(2, 6));

    fireEvent.click(screen.getByRole('button', { name: 'Renew Lease' }));

    expect(await screen.findByText('Nothing to renew.')).toBeInTheDocument();
    expect(screen.queryByText(/API error 422/)).not.toBeInTheDocument();
  });

  it('reports a policy clamp rather than a plain success', async () => {
    const onSliceUpdated = vi.fn();
    vi.mocked(api.renewLease).mockResolvedValue({
      ...activeSlice(6, 6),
      warnings: [{ code: 'LEASE_CLAMPED_TO_POLICY', message: 'Renewed to the 6 h cap instead.' }],
    });
    renderPanel({ sliceData: activeSlice(2, 6), sliceName: 'active-slice', onSliceUpdated });

    fireEvent.click(screen.getByRole('button', { name: 'Renew Lease' }));

    expect(await screen.findByText('Renewed to the 6 h cap instead.')).toBeInTheDocument();
    expect(onSliceUpdated).toHaveBeenCalled();
  });
});
