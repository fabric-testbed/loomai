import type { SliceData, SliceFacilityPort } from '../types/fabric';

export type FabricFacilityPortSliver = SliceFacilityPort & {
  derived_from_graph?: boolean;
};

/**
 * Some FABRIC facility-port stitches are exposed by FABlib as network
 * interfaces with a non-VM node_name, not as entries in get_facility_ports().
 * The graph builder renders those as facility-port nodes; this helper keeps
 * editor/list views consistent with that graph representation.
 */
export function getFacilityPortSlivers(sliceData: SliceData | null): FabricFacilityPortSliver[] {
  if (!sliceData) return [];
  const ports: FabricFacilityPortSliver[] = [...(sliceData.facility_ports ?? [])];
  const seen = new Set(ports.map((fp) => fp.name));
  const graphNodes = sliceData.graph?.nodes ?? [];
  const graphEdges = sliceData.graph?.edges ?? [];

  for (const node of graphNodes) {
    const data = node.data ?? {};
    if (data.element_type !== 'facility-port') continue;
    const name = String(data.name || '');
    if (!name || seen.has(name)) continue;

    const nodeId = String(data.id || '');
    const interfaces = graphEdges
      .filter((edge) => {
        const edgeData = edge.data ?? {};
        return edgeData.element_type === 'interface'
          && (String(edgeData.source || '') === nodeId || String(edgeData.target || '') === nodeId);
      })
      .map((edge) => {
        const edgeData = edge.data ?? {};
        return {
          name: String(edgeData.interface_name || ''),
          node_name: String(edgeData.node_name || name),
          network_name: String(edgeData.network_name || ''),
          vlan: String(edgeData.vlan || data.vlan || ''),
          mac: String(edgeData.mac || ''),
          ip_addr: String(edgeData.ip_addr || ''),
          bandwidth: String(edgeData.bandwidth ?? data.bandwidth ?? ''),
          mode: String(edgeData.mode || ''),
        };
      });

    ports.push({
      name,
      site: String(data.site || name),
      vlan: String(data.vlan || ''),
      bandwidth: String(data.bandwidth || ''),
      interfaces,
      derived_from_graph: true,
    });
    seen.add(name);
  }

  return ports;
}
