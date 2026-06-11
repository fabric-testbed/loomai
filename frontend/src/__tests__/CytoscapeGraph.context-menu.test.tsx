import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import CytoscapeGraph from '../components/CytoscapeGraph';

type MockNode = {
  isEdge: () => boolean;
  hasClass: (className: string) => boolean;
  data: (key?: string) => any;
  id: () => string;
  selected: () => boolean;
  select: () => MockNode;
};

const cytoscapeState = vi.hoisted(() => ({
  rightClickTarget: null as MockNode | null,
  selectedNodes: [] as MockNode[],
}));

function makeMockNode(data: Record<string, any>, classes: string[] = []): MockNode {
  let selected = false;
  const node: MockNode = {
    isEdge: () => false,
    hasClass: (className: string) => classes.includes(className),
    data: (key?: string) => (key ? data[key] : data),
    id: () => String(data.id || ''),
    selected: () => selected,
    select: () => {
      selected = true;
      if (!cytoscapeState.selectedNodes.includes(node)) {
        cytoscapeState.selectedNodes.push(node);
      }
      return node;
    },
  };
  return node;
}

vi.mock('cytoscape', () => {
  const makeCollection = (items: MockNode[] = []) => {
    const collection = [...items] as any;
    collection.unselect = vi.fn(() => {
      cytoscapeState.selectedNodes = [];
      return collection;
    });
    collection.remove = vi.fn(() => collection);
    collection.addClass = vi.fn(() => collection);
    collection.removeClass = vi.fn(() => collection);
    collection.not = vi.fn(() => collection);
    collection.empty = vi.fn(() => collection.length === 0);
    collection.layout = vi.fn(() => ({ on: vi.fn(), run: vi.fn() }));
    collection.filter = (predicate: (node: MockNode) => boolean) => makeCollection(items.filter(predicate));
    return collection;
  };

  const cytoscape = vi.fn(() => ({
    _private: {
      renderer: {
        projectIntoViewport: vi.fn(() => [0, 0]),
        findNearestElement: vi.fn(() => cytoscapeState.rightClickTarget),
      },
    },
    on: vi.fn(),
    off: vi.fn(),
    destroy: vi.fn(),
    resize: vi.fn(),
    style: vi.fn(),
    startBatch: vi.fn(),
    endBatch: vi.fn(),
    batch: vi.fn((callback: () => void) => callback()),
    fit: vi.fn(),
    add: vi.fn(),
    elements: vi.fn(() => makeCollection(cytoscapeState.selectedNodes)),
    nodes: vi.fn((selector?: string) => (
      selector === ':selected'
        ? makeCollection(cytoscapeState.selectedNodes)
        : makeCollection([])
    )),
    edges: vi.fn(() => makeCollection([])),
    getElementById: vi.fn(() => makeCollection([])),
  }));
  (cytoscape as any).use = vi.fn();
  return { __esModule: true, default: cytoscape };
});

vi.mock('cytoscape-dagre', () => ({ __esModule: true, default: {} }));
vi.mock('cytoscape-cola', () => ({ __esModule: true, default: {} }));

function renderGraph(onContextAction = vi.fn(), sliceData: any = null) {
  render(
    <CytoscapeGraph
      graph={null}
      layout="dagre"
      dark={false}
      sliceData={sliceData}
      onLayoutChange={vi.fn()}
      onNodeClick={vi.fn()}
      onEdgeClick={vi.fn()}
      onBackgroundClick={vi.fn()}
      onContextAction={onContextAction}
    />,
  );
  return { onContextAction };
}

describe('CytoscapeGraph topology context menu', () => {
  beforeAll(() => {
    class ResizeObserverMock {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (globalThis as any).ResizeObserver = ResizeObserverMock;
  });

  afterEach(() => {
    cleanup();
    cytoscapeState.rightClickTarget = null;
    cytoscapeState.selectedNodes = [];
  });

  it('offers Open Terminal from the slice-level menu when the slice has a management IP', () => {
    const { onContextAction } = renderGraph(vi.fn(), {
      name: 'slice-a',
      nodes: [{
        name: 'node1',
        site: 'TACC',
        management_ip: '192.0.2.10',
        username: 'ubuntu',
        reservation_state: 'StableOK',
        image: 'default_ubuntu_22',
        components: [],
      }],
    });
    cytoscapeState.rightClickTarget = makeMockNode({
      id: 'slice-a',
      name: 'slice-a',
      label: 'slice-a',
    }, ['slice']);

    fireEvent.mouseUp(screen.getByTestId('topology-graph'), { button: 2, clientX: 40, clientY: 50 });

    const terminalItem = screen.getByTestId('topology-context-open-terminal');
    expect(terminalItem).toBeVisible();

    fireEvent.click(terminalItem);

    expect(onContextAction).toHaveBeenCalledWith({
      type: 'terminal',
      elements: [expect.objectContaining({
        element_type: 'node',
        name: 'node1',
        management_ip: '192.0.2.10',
      })],
    });
  });

  it('uses refreshed slice node management IPs when graph node data is stale', () => {
    const { onContextAction } = renderGraph(vi.fn(), {
      name: 'slice-a',
      nodes: [{
        name: 'node1',
        site: 'TACC',
        management_ip: '192.0.2.25',
        username: 'ubuntu',
        reservation_state: 'StableOK',
        image: 'default_ubuntu_22',
        components: [],
      }],
    });
    cytoscapeState.rightClickTarget = makeMockNode({
      id: 'node:slice-a:node1',
      element_type: 'node',
      name: 'node1',
      label: 'node1',
      site: 'TACC',
      management_ip: '',
    }, ['vm']);

    fireEvent.mouseUp(screen.getByTestId('topology-graph'), { button: 2, clientX: 40, clientY: 50 });

    fireEvent.click(screen.getByTestId('topology-context-open-terminal'));

    expect(onContextAction).toHaveBeenCalledWith({
      type: 'terminal',
      elements: [expect.objectContaining({
        element_type: 'node',
        name: 'node1',
        management_ip: '192.0.2.25',
      })],
    });
  });

  it('shows Delete for FABRIC facility ports even when graph metadata says not deletable', () => {
    const { onContextAction } = renderGraph();
    cytoscapeState.rightClickTarget = makeMockNode({
      id: 'fp:slice-1:Chameleon-TACC',
      element_type: 'facility-port',
      testbed: 'FABRIC',
      name: 'Chameleon-TACC',
      slice_id: 'slice-1',
      deletable: 'false',
    }, ['facility-port']);

    fireEvent.mouseUp(screen.getByTestId('topology-graph'), { button: 2, clientX: 40, clientY: 50 });

    const deleteItem = screen.getByTestId('topology-context-delete');
    expect(deleteItem).toBeVisible();

    fireEvent.click(deleteItem);

    expect(onContextAction).toHaveBeenCalledWith({
      type: 'delete',
      elements: [expect.objectContaining({
        element_type: 'facility-port',
        name: 'Chameleon-TACC',
        slice_id: 'slice-1',
        deletable: 'false',
      })],
    });
  });

  it('does not show Delete for shared facility-port connector nodes', () => {
    renderGraph();
    cytoscapeState.rightClickTarget = makeMockNode({
      id: 'shared:facility-port-l2:Chameleon-TACC:vlan-3300',
      element_type: 'facility-port',
      testbed: 'SHARED',
      name: 'Chameleon-TACC',
    }, ['facility-port', 'composite-shared-network']);

    fireEvent.mouseUp(screen.getByTestId('topology-graph'), { button: 2, clientX: 40, clientY: 50 });

    expect(screen.getByTestId('topology-context-menu')).toBeVisible();
    expect(screen.queryByTestId('topology-context-delete')).not.toBeInTheDocument();
  });
});
