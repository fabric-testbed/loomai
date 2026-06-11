import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import CompositeEditorPanel from '../components/CompositeEditorPanel';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  updateFederatedProviderMembers: vi.fn().mockResolvedValue({
    id: 'fed-1',
    name: 'Federated Alpha',
    state: 'Draft',
    fabric_slices: ['fab-selected'],
    chameleon_slices: ['chi-selected'],
    members: [],
    cross_connections: [],
  }),
  getSlice: vi.fn().mockResolvedValue({
    id: 'fab-selected',
    name: 'Selected FABRIC',
    state: 'StableOK',
    dirty: false,
    lease_start: '',
    lease_end: '',
    error_messages: [],
    nodes: [
      {
        name: 'fabric-node-1',
        site: 'TACC',
        host: '',
        cores: 2,
        ram: 8,
        disk: 20,
        image: 'default_ubuntu_22',
        image_type: 'qcow2',
        management_ip: '',
        reservation_state: '',
        error_message: '',
        username: 'ubuntu',
        components: [],
        interfaces: [],
      },
    ],
    networks: [],
    facility_ports: [],
    port_mirrors: [],
    graph: { nodes: [], edges: [] },
  }),
  getChameleonDraft: vi.fn().mockResolvedValue({
    id: 'chi-selected',
    name: 'Selected Chameleon',
    state: 'Active',
    created: '',
    site: 'CHI@TACC',
    sites: ['CHI@TACC'],
    nodes: [
      {
        id: 'chi-node-1',
        name: 'chi-node-1',
        node_type: 'compute_haswell',
        image: 'CC-Ubuntu22.04',
        count: 1,
        site: 'CHI@TACC',
      },
    ],
    networks: [],
    floating_ips: [],
    resources: [],
  }),
  listChameleonFacilityPorts: vi.fn().mockResolvedValue({
    chameleon_site: 'CHI@TACC',
    fabric_site: 'TACC',
    facility_ports: [
      {
        name: 'Chameleon-TACC',
        site: 'TACC',
        fabric_site: 'TACC',
        chameleon_site: 'CHI@TACC',
        interfaces: [
          { name: 'HundredGigE0/0/0/1', vlan_range: ['3300-3302'] },
        ],
      },
    ],
    vlans: [3300, 3301, 3302],
    suggested_vlan: 3301,
  }),
  addFederatedConnection: vi.fn().mockResolvedValue({
    id: 'fed-1',
    name: 'Federated Alpha',
    state: 'Draft',
    fabric_slices: ['fab-selected'],
    chameleon_slices: ['chi-selected'],
    members: [],
    cross_connections: [],
  }),
  removeFederatedConnection: vi.fn().mockResolvedValue({
    id: 'fed-1',
    name: 'Federated Alpha',
    state: 'Draft',
    fabric_slices: ['fab-selected'],
    chameleon_slices: ['chi-selected'],
    members: [],
    cross_connections: [],
  }),
  updateFederatedConnections: vi.fn(),
}));

vi.mock('../components/EditorPanel', () => ({
  default: (props: any) => (
    <div data-testid="mock-fabric-editor" data-slice-name={props.sliceName}>
      FABRIC editor {props.sliceName}
      <button
        onClick={() => props.onSliceUpdated?.({
          ...props.sliceData,
          name: `${props.sliceData.name} Updated`,
        })}
      >
        Emit FABRIC update
      </button>
    </div>
  ),
}));
vi.mock('../components/ChameleonEditor', () => ({
  default: (props: any) => (
    <div data-testid="mock-chameleon-editor" data-draft-id={props.draftId} data-forms-only={String(Boolean(props.formsOnly))}>
      Chameleon editor {props.draftId}
      <button
        onClick={() => props.onDraftUpdated?.({
          id: props.draftId,
          name: 'Selected Chameleon Updated',
          state: 'Active',
          created: '',
          site: 'CHI@TACC',
          sites: ['CHI@TACC'],
          nodes: [],
          networks: [],
          floating_ips: [],
          resources: [],
        })}
      >
        Emit Chameleon update
      </button>
    </div>
  ),
}));

const compositeSlice = {
  id: 'fed-1',
  name: 'Federated Alpha',
  state: 'Draft',
  fabric_slices: ['fab-selected'],
  chameleon_slices: ['chi-selected'],
  members: [],
  cross_connections: [],
  fabric_member_summaries: [
    { id: 'fab-selected', name: 'Selected FABRIC', state: 'StableOK', node_count: 2 },
  ],
  chameleon_member_summaries: [
    { id: 'chi-selected', name: 'Selected Chameleon', state: 'Active', site: 'CHI@TACC' },
  ],
};

function renderPanel(overrides: Partial<ComponentProps<typeof CompositeEditorPanel>> = {}) {
  return render(
    <CompositeEditorPanel
      compositeSliceId="fed-1"
      compositeSlice={compositeSlice}
      fabricSlices={[
        { id: 'fab-selected', name: 'Selected FABRIC', state: 'StableOK', nodes: [{}, {}] },
        { id: 'fab-candidate', name: 'Candidate FABRIC', state: 'Draft', nodes: [{}] },
      ]}
      chameleonSlices={[
        { id: 'chi-selected', name: 'Selected Chameleon', state: 'Active', site: 'CHI@TACC' },
        { id: 'chi-candidate', name: 'Candidate Chameleon', state: 'Draft', site: 'CHI@UC' },
      ]}
      chameleonEnabled
      onMembersUpdated={() => {}}
      onCompositeGraphRefresh={() => {}}
      onError={() => {}}
      dark={false}
      {...overrides}
    />,
  );
}

describe('CompositeEditorPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows selected subslices in the federated tab without listing all candidates', async () => {
    renderPanel();

    expect(screen.getByText('Subslices')).toBeInTheDocument();
    expect(screen.queryByText('Member Status')).not.toBeInTheDocument();
    expect((await screen.findAllByText('Selected FABRIC')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Selected Chameleon').length).toBeGreaterThan(0);
    expect(screen.queryByText('Candidate FABRIC')).not.toBeInTheDocument();
    expect(screen.queryByText('Candidate Chameleon')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Add Subslice' }));

    expect(screen.getByRole('dialog', { name: 'Manage Subslices' })).toBeInTheDocument();
    expect(screen.getAllByText('Selected FABRIC').length).toBeGreaterThan(1);
    expect(screen.getByText('Candidate FABRIC')).toBeInTheDocument();
    expect(screen.getByText('Candidate Chameleon')).toBeInTheDocument();
  });

  it('filters the subslice modal by provider and search text', async () => {
    renderPanel();
    await screen.findAllByText('Selected FABRIC');

    fireEvent.click(screen.getByRole('button', { name: 'Add Subslice' }));
    const dialog = screen.getByRole('dialog', { name: 'Manage Subslices' });

    fireEvent.change(within(dialog).getByTestId('federated-subslice-provider-filter'), {
      target: { value: 'chameleon' },
    });
    expect(within(dialog).queryByText('Candidate FABRIC')).not.toBeInTheDocument();
    expect(within(dialog).getByText('Candidate Chameleon')).toBeInTheDocument();

    fireEvent.change(within(dialog).getByTestId('federated-subslice-filter'), {
      target: { value: 'CHI@UC' },
    });
    expect(within(dialog).getByText('Candidate Chameleon')).toBeInTheDocument();
    expect(within(dialog).queryByText('Selected Chameleon')).not.toBeInTheDocument();
  });

  it('adds a candidate subslice from the modal', async () => {
    renderPanel();
    await screen.findAllByText('Selected FABRIC');

    fireEvent.click(screen.getByRole('button', { name: 'Add Subslice' }));
    const dialog = screen.getByRole('dialog', { name: 'Manage Subslices' });
    const candidateRow = within(dialog).getByText('Candidate FABRIC').closest('tr');
    expect(candidateRow).not.toBeNull();
    fireEvent.click(within(candidateRow as HTMLTableRowElement).getByRole('button', { name: 'Add' }));

    await waitFor(() => {
      expect(api.updateFederatedProviderMembers).toHaveBeenCalledWith('fed-1', [
        { provider: 'fabric', slice_id: 'fab-selected' },
        { provider: 'fabric', slice_id: 'fab-candidate' },
        { provider: 'chameleon', slice_id: 'chi-selected' },
      ]);
    });
  });

  it('removes selected subslices from the compact member list', async () => {
    renderPanel();
    await screen.findAllByText('Selected FABRIC');

    const selectedRow = screen.getByText('Selected FABRIC').parentElement?.parentElement;
    expect(selectedRow).toBeTruthy();
    fireEvent.click(within(selectedRow as HTMLElement).getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(api.updateFederatedProviderMembers).toHaveBeenCalledWith('fed-1', [
        { provider: 'chameleon', slice_id: 'chi-selected' },
      ]);
    });
  });

  it('removes selected subslices from the manage modal', async () => {
    renderPanel();
    await screen.findAllByText('Selected FABRIC');

    fireEvent.click(screen.getByRole('button', { name: 'Add Subslice' }));
    const dialog = screen.getByRole('dialog', { name: 'Manage Subslices' });
    const selectedRow = within(dialog).getByText('Selected FABRIC').closest('tr');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow as HTMLTableRowElement).getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(api.updateFederatedProviderMembers).toHaveBeenCalledWith('fed-1', [
        { provider: 'chameleon', slice_id: 'chi-selected' },
      ]);
    });
  });

  it('opens a selected FABRIC subslice in the embedded editor and propagates updates', async () => {
    const onFabricSliceUpdated = vi.fn();
    const onCompositeGraphRefresh = vi.fn();
    renderPanel({ onFabricSliceUpdated, onCompositeGraphRefresh });
    await screen.findAllByText('Selected FABRIC');

    const selectedRow = screen.getAllByTestId('federated-member-row')
      .find(row => row.getAttribute('data-provider') === 'fabric');
    expect(selectedRow).toBeTruthy();
    fireEvent.click(within(selectedRow as HTMLElement).getByRole('button', { name: 'Edit' }));

    await waitFor(() => {
      expect(api.getSlice).toHaveBeenCalledWith('fab-selected');
    });
    const embeddedEditor = await screen.findByTestId('mock-fabric-editor');
    expect(embeddedEditor).toHaveAttribute('data-slice-name', 'Selected FABRIC');

    fireEvent.click(within(embeddedEditor).getByRole('button', { name: 'Emit FABRIC update' }));
    expect(onFabricSliceUpdated).toHaveBeenCalledWith(expect.objectContaining({
      id: 'fab-selected',
      name: 'Selected FABRIC Updated',
    }));
    expect(onCompositeGraphRefresh).toHaveBeenCalled();
  });

  it('opens a selected Chameleon subslice in the embedded editor and propagates updates', async () => {
    const onChameleonSliceUpdated = vi.fn();
    const onCompositeGraphRefresh = vi.fn();
    renderPanel({ onChameleonSliceUpdated, onCompositeGraphRefresh });
    await screen.findAllByText('Selected Chameleon');

    const selectedRow = screen.getAllByTestId('federated-member-row')
      .find(row => row.getAttribute('data-provider') === 'chameleon');
    expect(selectedRow).toBeTruthy();
    fireEvent.click(within(selectedRow as HTMLElement).getByRole('button', { name: 'Edit' }));

    const embeddedEditor = await screen.findByTestId('mock-chameleon-editor');
    expect(embeddedEditor).toHaveAttribute('data-draft-id', 'chi-selected');
    expect(embeddedEditor).toHaveAttribute('data-forms-only', 'true');

    fireEvent.click(within(embeddedEditor).getByRole('button', { name: 'Emit Chameleon update' }));
    expect(onChameleonSliceUpdated).toHaveBeenCalledWith(expect.objectContaining({
      id: 'chi-selected',
      name: 'Selected Chameleon Updated',
    }));
    expect(onCompositeGraphRefresh).toHaveBeenCalled();
  });

  it('adds a FABNetv4 connection between selected FABRIC and Chameleon members', async () => {
    const onMembersUpdated = vi.fn();
    const onCompositeGraphRefresh = vi.fn();
    renderPanel({ onMembersUpdated, onCompositeGraphRefresh });
    await screen.findAllByText('Selected FABRIC');

    await waitFor(() => {
      expect(screen.getByTestId('federated-connection-fabric-slice')).toHaveValue('fab-selected');
      expect(screen.getByTestId('federated-connection-chameleon-slice')).toHaveValue('chi-selected');
    });

    fireEvent.click(screen.getByTestId('federated-add-connection'));

    await waitFor(() => {
      expect(api.addFederatedConnection).toHaveBeenCalledWith('fed-1', expect.objectContaining({
        type: 'fabnetv4_l3',
        endpoint_a: expect.objectContaining({
          provider: 'fabric',
          slice_id: 'fab-selected',
          network: 'FABNetv4',
        }),
        endpoint_b: expect.objectContaining({
          provider: 'chameleon',
          slice_id: 'chi-selected',
          network: 'fabnetv4',
        }),
      }));
    });
    expect(onMembersUpdated).toHaveBeenCalled();
    expect(onCompositeGraphRefresh).toHaveBeenCalled();
  });

  it('adds a Facility Port L2 connection with endpoint nodes and VLAN', async () => {
    renderPanel();
    await screen.findAllByText('Selected FABRIC');

    await waitFor(() => {
      expect(screen.getByTestId('federated-connection-fabric-slice')).toHaveValue('fab-selected');
      expect(screen.getByTestId('federated-connection-chameleon-slice')).toHaveValue('chi-selected');
    });

    fireEvent.change(screen.getByTestId('federated-connection-type'), {
      target: { value: 'facility_port_l2' },
    });

    await waitFor(() => {
      expect(api.listChameleonFacilityPorts).toHaveBeenCalledWith('CHI@TACC');
    });
    await waitFor(() => {
      expect(screen.getByTestId('federated-connection-facility-port')).toHaveValue('Chameleon-TACC');
    });

    fireEvent.change(screen.getByTestId('federated-connection-fabric-node'), {
      target: { value: 'fabric-node-1' },
    });
    fireEvent.change(screen.getByTestId('federated-connection-chameleon-node'), {
      target: { value: 'chi-node-1' },
    });
    fireEvent.change(screen.getByTestId('federated-connection-vlan'), {
      target: { value: '3302' },
    });

    fireEvent.click(screen.getByTestId('federated-add-connection'));

    await waitFor(() => {
      expect(api.addFederatedConnection).toHaveBeenCalledWith('fed-1', expect.objectContaining({
        type: 'facility_port_l2',
        vlan: '3302',
        facility_port: 'Chameleon-TACC',
        endpoint_a: expect.objectContaining({
          provider: 'fabric',
          slice_id: 'fab-selected',
          node: 'fabric-node-1',
          site: 'TACC',
          facility_port: 'Chameleon-TACC',
          vlan: '3302',
        }),
        endpoint_b: expect.objectContaining({
          provider: 'chameleon',
          slice_id: 'chi-selected',
          node: 'chi-node-1',
          site: 'CHI@TACC',
          vlan: '3302',
        }),
      }));
    });
  });

  it('removes an existing cross-testbed connection', async () => {
    const onMembersUpdated = vi.fn();
    const onCompositeGraphRefresh = vi.fn();
    renderPanel({
      onMembersUpdated,
      onCompositeGraphRefresh,
      compositeSlice: {
        ...compositeSlice,
        cross_connections: [
          {
            id: 'conn-1',
            type: 'fabnetv4_l3',
            endpoint_a: { provider: 'fabric', slice_id: 'fab-selected' },
            endpoint_b: { provider: 'chameleon', slice_id: 'chi-selected' },
          },
        ],
      },
    });

    const connectionRow = await screen.findByTestId('federated-connection-row');
    fireEvent.click(within(connectionRow).getByRole('button', { name: 'Remove' }));

    await waitFor(() => {
      expect(api.removeFederatedConnection).toHaveBeenCalledWith('fed-1', 'conn-1');
    });
    expect(onMembersUpdated).toHaveBeenCalled();
    expect(onCompositeGraphRefresh).toHaveBeenCalled();
  });
});
