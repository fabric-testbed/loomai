import { render, screen, fireEvent } from '@testing-library/react';
import SliverComboBox from '../components/editor/SliverComboBox';
import type { SliceData } from '../types/fabric';

const mockSliceData: SliceData = {
  name: 'test',
  id: 'test-id',
  state: 'Draft',
  dirty: false,
  lease_start: '',
  lease_end: '',
  error_messages: [],
  nodes: [
    {
      name: 'node1',
      site: 'RENC',
      cores: 4,
      ram: 16,
      disk: 50,
      image: 'default_ubuntu_22',
      image_type: 'qcow2',
      host: '',
      reservation_state: '',
      error_message: '',
      management_ip: '',
      username: 'ubuntu',
      components: [],
      interfaces: [],
    },
  ],
  networks: [
    {
      name: 'net1',
      type: 'L2Bridge',
      layer: 'L2',
      interfaces: [],
      subnet: '',
      gateway: '',
    },
  ],
  facility_ports: [
    { name: 'fp1', site: 'STAR', vlan: '100', bandwidth: '10', interfaces: [] },
  ],
  port_mirrors: [],
  chameleon_nodes: [
    { name: 'chi1', site: 'CHI@TACC', node_type: 'compute_skylake' },
  ],
  graph: { nodes: [], edges: [] },
};

describe('SliverComboBox', () => {
  it('shows all groups when no tabFilter', () => {
    render(
      <SliverComboBox sliceData={mockSliceData} selectedSliverKey="" onSelect={() => {}} />,
    );
    fireEvent.click(screen.getByText('Select sliver...'));
    expect(screen.getByText('Nodes (VMs)')).toBeInTheDocument();
    expect(screen.getByText('Networks')).toBeInTheDocument();
    expect(screen.getByText('Facility Ports')).toBeInTheDocument();
    expect(screen.getByText('Chameleon Nodes')).toBeInTheDocument();
  });

  it('filters to fabric tab (nodes and non-chameleon networks)', () => {
    render(
      <SliverComboBox
        sliceData={mockSliceData}
        selectedSliverKey=""
        onSelect={() => {}}
        tabFilter="fabric"
      />,
    );
    fireEvent.click(screen.getByText('Select sliver...'));
    expect(screen.getByText('Nodes (VMs)')).toBeInTheDocument();
    expect(screen.getByText('Networks')).toBeInTheDocument();
    expect(screen.queryByText('Chameleon Nodes')).not.toBeInTheDocument();
    expect(screen.queryByText('Facility Ports')).not.toBeInTheDocument();
  });

  it('filters to chameleon only', () => {
    render(
      <SliverComboBox
        sliceData={mockSliceData}
        selectedSliverKey=""
        onSelect={() => {}}
        tabFilter="chameleon"
      />,
    );
    fireEvent.click(screen.getByText('Select sliver...'));
    expect(screen.getByText('Chameleon Nodes')).toBeInTheDocument();
    expect(screen.queryByText('Nodes (VMs)')).not.toBeInTheDocument();
    expect(screen.queryByText('Networks')).not.toBeInTheDocument();
  });

  it('filters to experiment tab', () => {
    render(
      <SliverComboBox
        sliceData={mockSliceData}
        selectedSliverKey=""
        onSelect={() => {}}
        tabFilter="experiment"
      />,
    );
    fireEvent.click(screen.getByText('Select sliver...'));
    expect(screen.getByText('Facility Ports')).toBeInTheDocument();
    expect(screen.queryByText('Nodes (VMs)')).not.toBeInTheDocument();
    expect(screen.queryByText('Chameleon Nodes')).not.toBeInTheDocument();
  });

  it('calls onSelect when option clicked', () => {
    const onSelect = vi.fn();
    render(
      <SliverComboBox sliceData={mockSliceData} selectedSliverKey="" onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByText('Select sliver...'));
    fireEvent.click(screen.getByText('node1'));
    expect(onSelect).toHaveBeenCalledWith('node:node1');
  });

  it('shows selected option name when key matches', () => {
    render(
      <SliverComboBox
        sliceData={mockSliceData}
        selectedSliverKey="node:node1"
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText('node1')).toBeInTheDocument();
  });

  it('shows placeholder when sliceData is null', () => {
    render(
      <SliverComboBox sliceData={null} selectedSliverKey="" onSelect={() => {}} />,
    );
    expect(screen.getByText('Select sliver...')).toBeInTheDocument();
  });
});
