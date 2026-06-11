import { graphElementIdSnapshot, graphElementIdsChanged, isTopologyElementDeletable, sanitizeGraphElements } from '../components/CytoscapeGraph';

describe('sanitizeGraphElements', () => {
  it('drops edges whose endpoints are not present in the node set', () => {
    const graph = sanitizeGraphElements(
      [
        { data: { id: 'node-a', label: 'Node A' }, classes: 'vm' },
        { data: { id: 'net-a', label: 'Network A' }, classes: 'network-l2' },
      ],
      [
        { data: { id: 'valid-edge', source: 'node-a', target: 'net-a' }, classes: 'edge-l2' },
        { data: { id: 'bad-edge', source: 'missing-node', target: 'net-a' }, classes: 'edge-l2' },
      ],
    );

    expect(graph.nodes.map((node) => node.data.id)).toEqual(['node-a', 'net-a']);
    expect(graph.edges.map((edge) => edge.data.id)).toEqual(['valid-edge']);
    expect(graph.droppedEdges).toEqual([
      {
        id: 'bad-edge',
        source: 'missing-node',
        target: 'net-a',
        reason: 'endpoint node not found',
      },
    ]);
  });

  it('normalizes compound nodes with missing parents into top-level nodes', () => {
    const graph = sanitizeGraphElements(
      [{ data: { id: 'child-node', parent: 'missing-parent' }, classes: 'vm' }],
      [],
    );

    expect(graph.nodes).toHaveLength(1);
    expect(graph.nodes[0].data).not.toHaveProperty('parent');
  });
});

describe('graphElementIdsChanged', () => {
  it('detects topology additions that require a layout refresh', () => {
    const previous = graphElementIdSnapshot(
      [{ data: { id: 'node-a' }, classes: 'vm' }],
      [],
    );
    const next = graphElementIdSnapshot(
      [
        { data: { id: 'node-a' }, classes: 'vm' },
        { data: { id: 'fp:slice-1:Chameleon-TACC' }, classes: 'facility-port' },
      ],
      [],
    );

    expect(graphElementIdsChanged(previous, next)).toBe(true);
  });

  it('ignores state-only graph data updates so layout can be preserved', () => {
    const previous = graphElementIdSnapshot(
      [{ data: { id: 'node-a', state: 'Ticketed' }, classes: 'vm' }],
      [{ data: { id: 'edge-1', source: 'node-a', target: 'net-a' }, classes: 'edge-l2' }],
    );
    const next = graphElementIdSnapshot(
      [{ data: { id: 'node-a', state: 'StableOK' }, classes: 'vm' }],
      [{ data: { id: 'edge-1', source: 'node-a', target: 'net-a' }, classes: 'edge-l2' }],
    );

    expect(graphElementIdsChanged(previous, next)).toBe(false);
  });
});

describe('isTopologyElementDeletable', () => {
  it('allows provider-owned FABRIC resources and draft Chameleon nodes', () => {
    expect(isTopologyElementDeletable({ element_type: 'node', testbed: 'FABRIC' })).toBe(true);
    expect(isTopologyElementDeletable({ element_type: 'facility-port', testbed: 'FABRIC', deletable: 'true' })).toBe(true);
    expect(isTopologyElementDeletable({ element_type: 'facility-port', testbed: 'FABRIC', deletable: 'false' })).toBe(true);
    expect(isTopologyElementDeletable({ element_type: 'facility-port', deletable: 'false' })).toBe(true);
    expect(isTopologyElementDeletable({ element_type: 'port-mirror', testbed: 'FABRIC' })).toBe(true);
    expect(isTopologyElementDeletable({
      element_type: 'chameleon_instance',
      testbed: 'Chameleon',
      status: 'DRAFT',
      node_id: 'node-1',
    })).toBe(true);
    expect(isTopologyElementDeletable({
      element_type: 'network',
      testbed: 'Chameleon',
      network_id: 'net-1',
      deletable: 'true',
    })).toBe(true);
    expect(isTopologyElementDeletable({
      element_type: 'network',
      testbed: 'Chameleon',
      name: 'chameleon-fabric-fabnet-stitch',
      resource_id: 'res-net-1',
    })).toBe(true);
  });

  it('blocks shared/external topology objects and non-draft Chameleon instances', () => {
    expect(isTopologyElementDeletable({ element_type: 'facility-port', testbed: 'SHARED' })).toBe(false);
    expect(isTopologyElementDeletable({ element_type: 'fabnet-internet', testbed: 'SHARED' })).toBe(false);
    expect(isTopologyElementDeletable({ element_type: 'network', testbed: 'Chameleon', name: 'fabnetv4' })).toBe(false);
    expect(isTopologyElementDeletable({
      element_type: 'chameleon_instance',
      testbed: 'Chameleon',
      status: 'ACTIVE',
      instance_id: 'inst-1',
    })).toBe(false);
  });
});
