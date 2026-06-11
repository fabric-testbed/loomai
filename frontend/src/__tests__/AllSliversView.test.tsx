import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AllSliversView from '../components/AllSliversView';
import * as api from '../api/client';
import type { SliceData } from '../types/fabric';

vi.mock('../api/client', () => ({
  getSlice: vi.fn(),
  removeNode: vi.fn(),
  removeNetwork: vi.fn(),
  removeFacilityPort: vi.fn(),
  removePortMirror: vi.fn(),
}));

const sliceData: SliceData = {
  name: 'fabric-member',
  id: 'slice-1',
  state: 'Draft',
  dirty: false,
  lease_start: '',
  lease_end: '',
  error_messages: [],
  nodes: [
    {
      name: 'node1',
      site: 'RENC',
      host: '',
      cores: 2,
      ram: 4,
      disk: 20,
      image: 'default_ubuntu_22',
      image_type: 'qcow2',
      management_ip: '',
      reservation_state: '',
      error_message: '',
      username: '',
      components: [],
      interfaces: [],
    },
  ],
  networks: [
    {
      name: 'net1',
      type: 'L2Bridge',
      layer: 'L2',
      subnet: '',
      gateway: '',
      interfaces: [],
    },
  ],
  facility_ports: [
    {
      name: 'fp1',
      site: 'RENC',
      vlan: '3300',
      bandwidth: '100',
      interfaces: [],
    },
  ],
  port_mirrors: [
    {
      name: 'mirror1',
      mirror_interface_name: 'node1-nic0',
      receive_interface_name: 'node1-nic1',
      mirror_direction: 'both',
    },
  ],
  graph: { nodes: [], edges: [] },
};

function renderView(onContextAction = vi.fn()) {
  return {
    onContextAction,
    ...render(
      <AllSliversView
        slices={[{ id: 'slice-1', name: 'fabric-member', state: 'Draft' }]}
        dark={false}
        selectedSliceId=""
        onSliceSelect={() => {}}
        onDeleteSlice={vi.fn()}
        onRefreshSlices={vi.fn()}
        onContextAction={onContextAction}
      />,
    ),
  };
}

describe('AllSliversView resource context menu', () => {
  beforeEach(() => {
    vi.mocked(api.getSlice).mockResolvedValue(sliceData);
  });

  it('right-click delete sends the resource slice name for network, facility port, and port mirror rows', async () => {
    const { onContextAction } = renderView();

    fireEvent.click(screen.getByTestId('fabric-slice-expand'));
    await waitFor(() => expect(api.getSlice).toHaveBeenCalledWith('fabric-member'));
    await screen.findAllByTestId('fabric-resource-row');

    for (const [resourceName, elementType] of [
      ['net1', 'network'],
      ['fp1', 'facility-port'],
      ['mirror1', 'port-mirror'],
    ] as const) {
      const row = screen.getByText(resourceName).closest('tr');
      expect(row).toBeTruthy();
      fireEvent.contextMenu(row!);
      fireEvent.click(within(screen.getByText(resourceName).ownerDocument.body).getByText('🗑 Delete'));
      expect(onContextAction).toHaveBeenLastCalledWith({
        type: 'delete',
        elements: [expect.objectContaining({
          element_type: elementType,
          name: resourceName,
          slice_name: 'fabric-member',
        })],
      });
    }
  });
});
