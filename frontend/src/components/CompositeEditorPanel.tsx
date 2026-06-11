'use client';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import * as api from '../api/client';
import type { SliceData, SiteInfo, ComponentModel, FederatedConnection, VMTemplateSummary, FacilityPortInfo } from '../types/fabric';
import type { ChameleonDraft, ChameleonFacilityPortList } from '../types/chameleon';
import EditorPanel from './EditorPanel';
import ChameleonEditor from './ChameleonEditor';
import '../styles/template-panel.css';

/**
 * CompositeEditorPanel — three-tab editor for federated slices.
 *
 * Tab 1: Federated — member picker (add/remove FABRIC/Chameleon slices), status summary
 * Tab 2: FABRIC — embedded EditorPanel for a selected FABRIC member slice
 * Tab 3: Chameleon — embedded ChameleonEditor (formsOnly) for a selected Chameleon member slice
 */

interface CompositeEditorPanelProps {
  compositeSliceId: string;
  compositeSlice: any;
  fabricSlices: any[];
  chameleonSlices: any[];
  chameleonEnabled: boolean;
  chameleonSites?: any[];
  onMembersUpdated: (updated: any) => void;
  onCompositeGraphRefresh: () => void;
  onError: (msg: string) => void;
  onSwitchToSlice?: (testbed: 'fabric' | 'chameleon', sliceId: string) => void;
  onCreateSlice?: (testbed: 'fabric' | 'chameleon') => void;
  /** Callback when a FABRIC member slice is edited inline — passes updated SliceData */
  onFabricSliceUpdated?: (data: SliceData) => void;
  /** Current FABRIC sites, images, component models for the embedded editor */
  sites?: SiteInfo[];
  images?: string[];
  componentModels?: ComponentModel[];
  selectedElement?: Record<string, string> | null;
  vmTemplates?: VMTemplateSummary[];
  onSaveVmTemplate?: (sliceId: string, nodeName: string, sliceData: SliceData) => void;
  onBootConfigErrors?: (errors: Array<{ node: string; type: string; id: string; detail: string }>) => void;
  onRunFabricBootConfig?: (sliceId: string) => void;
  sliceBootRunning?: Record<string, boolean>;
  facilityPorts?: FacilityPortInfo[];
  chameleonAutoRefresh?: boolean;
  onOpenChameleonTerminal?: (instance: { id: string; name: string; site: string }) => void;
  onChameleonSliceUpdated?: (draft: ChameleonDraft) => void;
  dark: boolean;
}

type CompositeTab = 'composite' | 'fabric' | 'chameleon';
type MemberProvider = 'fabric' | 'chameleon';
type MemberProviderFilter = 'all' | MemberProvider;

interface SubsliceCandidate {
  provider: MemberProvider;
  id: string;
  name: string;
  state?: string;
  site?: string;
  nodeCount?: number;
  selected: boolean;
  searchText: string;
}

export default React.memo(function CompositeEditorPanel({
  compositeSliceId,
  compositeSlice,
  fabricSlices,
  chameleonSlices,
  chameleonEnabled,
  onMembersUpdated,
  onCompositeGraphRefresh,
  onError,
  onSwitchToSlice,
  onCreateSlice,
  onFabricSliceUpdated,
  sites,
  images,
  componentModels,
  selectedElement,
  vmTemplates,
  onSaveVmTemplate,
  onBootConfigErrors,
  onRunFabricBootConfig,
  sliceBootRunning,
  facilityPorts,
  chameleonAutoRefresh,
  onOpenChameleonTerminal,
  onChameleonSliceUpdated,
  chameleonSites,
  dark,
}: CompositeEditorPanelProps) {
  const [tab, setTab] = useState<CompositeTab>('composite');
  const [saving, setSaving] = useState(false);

  // Selected member slice for inline editing
  const [selectedFabricMemberId, setSelectedFabricMemberId] = useState('');
  const [selectedChameleonMemberId, setSelectedChameleonMemberId] = useState('');
  const [fabricMemberData, setFabricMemberData] = useState<SliceData | null>(null);
  const [loadingMember, setLoadingMember] = useState(false);

  // Local member state for the picker
  const [localFabricMembers, setLocalFabricMembers] = useState<string[]>([]);
  const [localChameleonMembers, setLocalChameleonMembers] = useState<string[]>([]);
  const [localOtherMembers, setLocalOtherMembers] = useState<Array<{ provider: string; slice_id: string; name?: string }>>([]);
  const [addMemberDialogOpen, setAddMemberDialogOpen] = useState(false);
  const [memberCandidateFilter, setMemberCandidateFilter] = useState('');
  const [memberProviderFilter, setMemberProviderFilter] = useState<MemberProviderFilter>('all');
  const [connectionType, setConnectionType] = useState<'fabnetv4_l3' | 'facility_port_l2'>('fabnetv4_l3');
  const [connectionFabricSliceId, setConnectionFabricSliceId] = useState('');
  const [connectionChameleonSliceId, setConnectionChameleonSliceId] = useState('');
  const [connectionVlan, setConnectionVlan] = useState('');
  const [connectionFabricNode, setConnectionFabricNode] = useState('');
  const [connectionChameleonNode, setConnectionChameleonNode] = useState('');
  const [connectionFacilityPort, setConnectionFacilityPort] = useState('');
  const [connectionChameleonSite, setConnectionChameleonSite] = useState('');
  const [connectionFabricSite, setConnectionFabricSite] = useState('');
  const [connectionFabricData, setConnectionFabricData] = useState<SliceData | null>(null);
  const [connectionChameleonData, setConnectionChameleonData] = useState<ChameleonDraft | null>(null);
  const [connectionFacilityPorts, setConnectionFacilityPorts] = useState<ChameleonFacilityPortList | null>(null);
  const [connectionPortsLoading, setConnectionPortsLoading] = useState(false);

  // Sync from compositeSlice prop
  useEffect(() => {
    if (compositeSlice) {
      setLocalFabricMembers(compositeSlice.fabric_slices || []);
      setLocalChameleonMembers(compositeSlice.chameleon_slices || []);
      setLocalOtherMembers((compositeSlice.members || []).filter((m: any) => !['fabric', 'chameleon'].includes(m.provider)));
    }
  }, [compositeSlice]);

  useEffect(() => {
    setConnectionFabricSliceId(current => current && localFabricMembers.includes(current) ? current : (localFabricMembers[0] || ''));
    setConnectionChameleonSliceId(current => current && localChameleonMembers.includes(current) ? current : (localChameleonMembers[0] || ''));
  }, [localFabricMembers, localChameleonMembers]);

  useEffect(() => {
    setConnectionFabricNode('');
    setConnectionFabricData(null);
    if (!connectionFabricSliceId) return;
    let cancelled = false;
    api.getSlice(connectionFabricSliceId)
      .then(data => { if (!cancelled) setConnectionFabricData(data); })
      .catch(() => { if (!cancelled) setConnectionFabricData(null); });
    return () => { cancelled = true; };
  }, [connectionFabricSliceId]);

  useEffect(() => {
    setConnectionChameleonNode('');
    setConnectionChameleonSite('');
    setConnectionFacilityPorts(null);
    setConnectionFacilityPort('');
    setConnectionChameleonData(null);
    if (!connectionChameleonSliceId) return;
    let cancelled = false;
    api.getChameleonDraft(connectionChameleonSliceId)
      .then(data => {
        if (cancelled) return;
        setConnectionChameleonData(data);
        const sitesFromNodes = (data.nodes || []).map(n => n.site).filter(Boolean);
        const sites = sitesFromNodes.length > 0 ? Array.from(new Set(sitesFromNodes)) : (data.sites || (data.site ? [data.site] : []));
        setConnectionChameleonSite(sites[0] || '');
      })
      .catch(() => { if (!cancelled) setConnectionChameleonData(null); });
    return () => { cancelled = true; };
  }, [connectionChameleonSliceId]);

  useEffect(() => {
    if (connectionType !== 'facility_port_l2' || !connectionChameleonSite) {
      setConnectionFacilityPorts(null);
      return;
    }
    let cancelled = false;
    setConnectionPortsLoading(true);
    api.listChameleonFacilityPorts(connectionChameleonSite)
      .then(data => {
        if (cancelled) return;
        setConnectionFacilityPorts(data);
        setConnectionFabricSite(data.fabric_site || '');
        setConnectionFacilityPort(current => current || data.facility_ports[0]?.name || '');
        setConnectionVlan(current => current || (data.suggested_vlan ? String(data.suggested_vlan) : ''));
      })
      .catch(() => {
        if (!cancelled) {
          setConnectionFacilityPorts(null);
          setConnectionFabricSite('');
        }
      })
      .finally(() => { if (!cancelled) setConnectionPortsLoading(false); });
    return () => { cancelled = true; };
  }, [connectionType, connectionChameleonSite]);

  // Fetch FABRIC member slice data when selected for inline editing
  useEffect(() => {
    if (!selectedFabricMemberId) { setFabricMemberData(null); return; }
    setLoadingMember(true);
    api.getSlice(selectedFabricMemberId).then(data => {
      setFabricMemberData(data);
    }).catch(() => setFabricMemberData(null)).finally(() => setLoadingMember(false));
  }, [selectedFabricMemberId]);

  const saveMembership = useCallback(async (fabSlices: string[], chiSlices: string[]) => {
    if (!compositeSliceId) return;
    setSaving(true);
    try {
      const members = [
        ...fabSlices.map(slice_id => ({ provider: 'fabric', slice_id })),
        ...chiSlices.map(slice_id => ({ provider: 'chameleon', slice_id })),
        ...localOtherMembers,
      ];
      const updated = await api.updateFederatedProviderMembers(compositeSliceId, members);
      onMembersUpdated(updated);
      onCompositeGraphRefresh();
    } catch (e: any) {
      onError(e.message || 'Failed to update members');
    } finally {
      setSaving(false);
    }
  }, [compositeSliceId, localOtherMembers, onMembersUpdated, onCompositeGraphRefresh, onError]);

  const openAddMemberDialog = useCallback((provider: MemberProviderFilter = 'all') => {
    setMemberProviderFilter(provider);
    setMemberCandidateFilter('');
    setAddMemberDialogOpen(true);
  }, []);

  const addMember = useCallback((provider: MemberProvider, sliceId: string) => {
    if (provider === 'fabric') {
      if (localFabricMembers.includes(sliceId)) return;
      const next = [...localFabricMembers, sliceId];
      setLocalFabricMembers(next);
      setSelectedFabricMemberId(current => current || sliceId);
      saveMembership(next, localChameleonMembers);
      return;
    }
    if (localChameleonMembers.includes(sliceId)) return;
    const next = [...localChameleonMembers, sliceId];
    setLocalChameleonMembers(next);
    setSelectedChameleonMemberId(current => current || sliceId);
    saveMembership(localFabricMembers, next);
  }, [localFabricMembers, localChameleonMembers, saveMembership]);

  const removeFabricMember = useCallback((sliceId: string) => {
    const next = localFabricMembers.filter(id => id !== sliceId);
    setLocalFabricMembers(next);
    if (selectedFabricMemberId === sliceId) {
      setSelectedFabricMemberId('');
      setFabricMemberData(null);
    }
    saveMembership(next, localChameleonMembers);
  }, [localFabricMembers, localChameleonMembers, saveMembership, selectedFabricMemberId]);

  const removeChameleonMember = useCallback((sliceId: string) => {
    const next = localChameleonMembers.filter(id => id !== sliceId);
    setLocalChameleonMembers(next);
    if (selectedChameleonMemberId === sliceId) {
      setSelectedChameleonMemberId('');
    }
    saveMembership(localFabricMembers, next);
  }, [localFabricMembers, localChameleonMembers, saveMembership, selectedChameleonMemberId]);

  const memberFabricSummaries = compositeSlice?.fabric_member_summaries || [];
  const memberChameleonSummaries = compositeSlice?.chameleon_member_summaries || [];
  const fabricMemberOptions = localFabricMembers.map(sliceId => {
    const summary = memberFabricSummaries.find((m: any) => m.id === sliceId);
    const known = fabricSlices.find((s: any) => s.id === sliceId || s.name === sliceId);
    return { id: sliceId, name: summary?.name || known?.name || sliceId, state: summary?.state || known?.state };
  });
  const chameleonMemberOptions = localChameleonMembers.map(sliceId => {
    const summary = memberChameleonSummaries.find((m: any) => m.id === sliceId);
    const known = chameleonSlices.find((s: any) => s.id === sliceId);
    return { id: sliceId, name: summary?.name || known?.name || sliceId, state: summary?.state || known?.state, site: summary?.site || known?.site };
  });
  const selectedSubsliceOptions = useMemo<SubsliceCandidate[]>(() => ([
    ...fabricMemberOptions.map(member => ({
      provider: 'fabric' as const,
      id: member.id,
      name: member.name,
      state: member.state,
      selected: true,
      searchText: ['fabric', member.id, member.name, member.state, 'selected'].filter(Boolean).join(' ').toLowerCase(),
    })),
    ...chameleonMemberOptions.map(member => ({
      provider: 'chameleon' as const,
      id: member.id,
      name: member.name,
      state: member.state,
      site: member.site,
      selected: true,
      searchText: ['chameleon', member.id, member.name, member.state, member.site, 'selected'].filter(Boolean).join(' ').toLowerCase(),
    })),
  ].sort((a, b) => a.name.localeCompare(b.name))), [fabricMemberOptions, chameleonMemberOptions]);

  const allSubsliceCandidates = useMemo<SubsliceCandidate[]>(() => {
    const fabricSelected = new Set(localFabricMembers);
    const chameleonSelected = new Set(localChameleonMembers);
    const fabricCandidates = fabricSlices
      .flatMap((slice: any): SubsliceCandidate[] => {
        const id = String(slice.id || slice.name || '');
        const name = String(slice.name || id);
        if (!id) return [];
        const state = slice.state ? String(slice.state) : undefined;
        const nodeCount = Array.isArray(slice.nodes) ? slice.nodes.length : slice.node_count;
        const selected = fabricSelected.has(id) || fabricSelected.has(name);
        return [{
          provider: 'fabric' as const,
          id,
          name,
          state,
          nodeCount: Number.isFinite(Number(nodeCount)) ? Number(nodeCount) : undefined,
          selected,
          searchText: ['fabric', id, name, state, selected ? 'selected' : 'available'].filter(Boolean).join(' ').toLowerCase(),
        }];
      });
    const fabricCandidateIds = new Set(fabricCandidates.map(candidate => candidate.id));
    const missingFabricSelections = fabricMemberOptions
      .filter(member => !fabricCandidateIds.has(member.id))
      .map(member => ({
        provider: 'fabric' as const,
        id: member.id,
        name: member.name,
        state: member.state,
        selected: true,
        searchText: ['fabric', member.id, member.name, member.state, 'selected'].filter(Boolean).join(' ').toLowerCase(),
      }));
    const chameleonCandidates = (chameleonEnabled ? chameleonSlices : [])
      .flatMap((slice: any): SubsliceCandidate[] => {
        const id = String(slice.id || '');
        const name = String(slice.name || id);
        if (!id) return [];
        const state = slice.state ? String(slice.state) : undefined;
        const site = slice.site || (Array.isArray(slice.sites) ? slice.sites.join(', ') : undefined);
        const selected = chameleonSelected.has(id) || chameleonSelected.has(name);
        return [{
          provider: 'chameleon' as const,
          id,
          name,
          state,
          site: site ? String(site) : undefined,
          selected,
          searchText: ['chameleon', id, name, state, site, selected ? 'selected' : 'available'].filter(Boolean).join(' ').toLowerCase(),
        }];
      });
    const chameleonCandidateIds = new Set(chameleonCandidates.map(candidate => candidate.id));
    const missingChameleonSelections = chameleonMemberOptions
      .filter(member => !chameleonCandidateIds.has(member.id))
      .map(member => ({
        provider: 'chameleon' as const,
        id: member.id,
        name: member.name,
        state: member.state,
        site: member.site,
        selected: true,
        searchText: ['chameleon', member.id, member.name, member.state, member.site, 'selected'].filter(Boolean).join(' ').toLowerCase(),
      }));
    return [...fabricCandidates, ...missingFabricSelections, ...chameleonCandidates, ...missingChameleonSelections].sort((a, b) => {
      if (a.provider !== b.provider) return a.provider.localeCompare(b.provider);
      return a.name.localeCompare(b.name);
    });
  }, [fabricSlices, chameleonSlices, chameleonEnabled, localFabricMembers, localChameleonMembers, fabricMemberOptions, chameleonMemberOptions]);
  const filteredSubsliceCandidates = useMemo(() => {
    const query = memberCandidateFilter.trim().toLowerCase();
    return allSubsliceCandidates.filter(candidate => (
      (memberProviderFilter === 'all' || candidate.provider === memberProviderFilter)
      && (!query || candidate.searchText.includes(query))
    ));
  }, [allSubsliceCandidates, memberCandidateFilter, memberProviderFilter]);
  const stateLooksHealthy = (state?: string) => ['stableok', 'active', 'ready'].includes(String(state || '').toLowerCase());
  const connectionFabricNodeOptions = (connectionFabricData?.nodes || []).map(node => ({
    name: node.name,
    site: node.site,
  }));
  const connectionChameleonSites = Array.from(new Set([
    ...((connectionChameleonData?.nodes || []).map(node => node.site).filter(Boolean)),
    ...(connectionChameleonData?.sites || []),
    ...(connectionChameleonData?.site ? [connectionChameleonData.site] : []),
  ]));
  const connectionChameleonNodeOptions = (connectionChameleonData?.nodes || [])
    .filter(node => !connectionChameleonSite || node.site === connectionChameleonSite)
    .map(node => ({ id: node.id, name: node.name, site: node.site }));
  const selectedFacilityPort = connectionFacilityPorts?.facility_ports.find(fp => fp.name === connectionFacilityPort);
  const selectedFacilityPortVlans = Array.from(new Set(
    (selectedFacilityPort?.interfaces || [])
      .flatMap(iface => iface.vlan_range || [])
      .flatMap(value => {
        const text = String(value);
        if (!text.includes('-')) return [text];
        const [start, end] = text.split('-').map(v => Number(v.trim()));
        if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return [];
        return Array.from({ length: Math.min(end - start + 1, 200) }, (_, idx) => String(start + idx));
      })
  ));
  const connectionLabel = (conn: any, provider: 'fabric' | 'chameleon') => {
    const endpoint = [conn.endpoint_a, conn.endpoint_b, conn.source, conn.target]
      .find((e: any) => e?.provider === provider);
    const sliceId = endpoint?.slice_id || (provider === 'fabric' ? conn.fabric_slice : conn.chameleon_slice) || '';
    const node = endpoint?.node || (provider === 'fabric' ? conn.fabric_node : conn.chameleon_node);
    const options = provider === 'fabric' ? fabricMemberOptions : chameleonMemberOptions;
    const name = options.find((o: any) => o.id === sliceId)?.name || sliceId || provider;
    return node ? `${name} / ${node}` : name;
  };
  const displayConnectionType = (type: string) => {
    if (type === 'facility_port_l2' || type === 'l2_stitch') return 'Facility Port L2';
    return 'FABNetv4 L3';
  };
  const canonicalConnectionType = (type?: string) => {
    if (type === 'facility_port_l2' || type === 'l2_stitch') return 'facility_port_l2';
    return 'fabnetv4_l3';
  };
  const connectionEndpointSliceId = (conn: any, provider: 'fabric' | 'chameleon') => {
    const endpoint = [conn.endpoint_a, conn.endpoint_b, conn.source, conn.target]
      .find((e: any) => e?.provider === provider);
    return endpoint?.slice_id || (provider === 'fabric' ? conn.fabric_slice : conn.chameleon_slice) || '';
  };
  const selectedConnectionExists = (compositeSlice?.cross_connections || []).some((conn: any) => (
    canonicalConnectionType(conn.type) === canonicalConnectionType(connectionType)
    && connectionEndpointSliceId(conn, 'fabric') === connectionFabricSliceId
    && connectionEndpointSliceId(conn, 'chameleon') === connectionChameleonSliceId
    && (canonicalConnectionType(connectionType) !== 'facility_port_l2' || String(conn.vlan || '') === connectionVlan.trim())
    && (canonicalConnectionType(connectionType) !== 'facility_port_l2' || String(conn.facility_port || conn.endpoint_a?.facility_port || '') === connectionFacilityPort)
    && (canonicalConnectionType(connectionType) !== 'facility_port_l2' || String(conn.endpoint_a?.node || conn.fabric_node || '') === connectionFabricNode)
    && (canonicalConnectionType(connectionType) !== 'facility_port_l2' || String(conn.endpoint_b?.node || conn.chameleon_node || '') === connectionChameleonNode)
  ));
  const connectionValidationMessage = !connectionFabricSliceId || !connectionChameleonSliceId
    ? 'Select one FABRIC and one Chameleon member.'
    : connectionType === 'facility_port_l2' && !connectionVlan.trim()
      ? 'Enter a VLAN for Facility Port L2.'
      : connectionType === 'facility_port_l2' && !connectionFacilityPort
        ? 'Select a Facility Port for L2.'
        : connectionType === 'facility_port_l2' && !connectionFabricNode
          ? 'Select a FABRIC endpoint node.'
          : connectionType === 'facility_port_l2' && !connectionChameleonNode
            ? 'Select a Chameleon endpoint node.'
            : selectedConnectionExists
              ? 'That connection already exists.'
              : '';

  const addConnection = useCallback(async () => {
    if (!compositeSliceId) return;
    if (connectionValidationMessage) {
      onError(connectionValidationMessage);
      return;
    }
    setSaving(true);
    try {
      const fabricSummary = memberFabricSummaries.find((m: any) => m.id === connectionFabricSliceId);
      const chameleonSummary = memberChameleonSummaries.find((m: any) => m.id === connectionChameleonSliceId);
      const fabricNode = connectionFabricNodeOptions.find(node => node.name === connectionFabricNode);
      const chameleonNode = connectionChameleonNodeOptions.find(node => node.name === connectionChameleonNode || node.id === connectionChameleonNode);
      const l2FabricSite = connectionType === 'facility_port_l2'
        ? (connectionFabricSite || selectedFacilityPort?.fabric_site || selectedFacilityPort?.site || fabricNode?.site || '')
        : fabricSummary?.site;
      const l2ChameleonSite = connectionType === 'facility_port_l2'
        ? (connectionChameleonSite || chameleonNode?.site || chameleonSummary?.site || '')
        : chameleonSummary?.site;
      const connection: FederatedConnection = {
        type: connectionType,
        endpoint_a: {
          provider: 'fabric',
          slice_id: connectionFabricSliceId,
          site: l2FabricSite,
          node: connectionType === 'facility_port_l2' ? connectionFabricNode : undefined,
          network: connectionType === 'fabnetv4_l3' ? 'FABNetv4' : undefined,
          facility_port: connectionType === 'facility_port_l2' ? connectionFacilityPort : undefined,
          vlan: connectionType === 'facility_port_l2' ? connectionVlan.trim() : undefined,
        },
        endpoint_b: {
          provider: 'chameleon',
          slice_id: connectionChameleonSliceId,
          site: l2ChameleonSite,
          node: connectionType === 'facility_port_l2' ? connectionChameleonNode : undefined,
          network: connectionType === 'fabnetv4_l3' ? 'fabnetv4' : undefined,
          vlan: connectionType === 'facility_port_l2' ? connectionVlan.trim() : undefined,
        },
        fabric_slice: connectionFabricSliceId,
        chameleon_slice: connectionChameleonSliceId,
        fabric_node: connectionType === 'facility_port_l2' ? connectionFabricNode : undefined,
        chameleon_node: connectionType === 'facility_port_l2' ? connectionChameleonNode : undefined,
        fabric_site: l2FabricSite,
        chameleon_site: l2ChameleonSite,
        state: 'Draft',
      };
      if (connectionType === 'facility_port_l2' && connectionVlan.trim()) {
        connection.vlan = connectionVlan.trim();
        connection.facility_port = connectionFacilityPort;
      }
      const updated = await api.addFederatedConnection(compositeSliceId, connection);
      onMembersUpdated(updated);
      onCompositeGraphRefresh();
    } catch (e: any) {
      onError(e.message || 'Failed to add connection');
    } finally {
      setSaving(false);
    }
  }, [
    compositeSliceId,
    connectionFabricSliceId,
    connectionChameleonSliceId,
    connectionType,
    connectionVlan,
    connectionFabricNode,
    connectionChameleonNode,
    connectionFacilityPort,
    connectionFabricSite,
    connectionChameleonSite,
    connectionValidationMessage,
    connectionFabricNodeOptions,
    connectionChameleonNodeOptions,
    selectedFacilityPort,
    memberFabricSummaries,
    memberChameleonSummaries,
    onMembersUpdated,
    onCompositeGraphRefresh,
    onError,
  ]);

  if (!compositeSliceId || !compositeSlice) {
    return (
      <div style={{ padding: 16, textAlign: 'center', color: 'var(--fabric-text-muted)', fontSize: 12 }}>
        Select a federated slice to edit.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }} data-testid="federated-editor-panel" data-federated-slice-id={compositeSliceId}>
      {/* Tab bar */}
      <div className="editor-top-tabs" data-testid="federated-editor-tabs">
        <button className={tab === 'composite' ? 'active' : ''} onClick={() => setTab('composite')} data-testid="federated-editor-tab" data-federated-tab="composite">
          Federated
        </button>
        <button className={tab === 'fabric' ? 'active' : ''} onClick={() => setTab('fabric')} data-testid="federated-editor-tab" data-federated-tab="fabric">
          FABRIC
        </button>
        {chameleonEnabled && (
          <button
            className={`${tab === 'chameleon' ? 'active chameleon-tab-active' : ''}`}
            onClick={() => setTab('chameleon')}
            data-testid="federated-editor-tab"
            data-federated-tab="chameleon"
          >
            Chameleon
          </button>
        )}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {tab === 'composite' && (
          <div>
            {/* Federated metadata */}
            <div style={{ marginBottom: 12, padding: '8px 4px', borderBottom: '1px solid var(--fabric-border)' }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{compositeSlice.name}</div>
              <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>
                State: <span style={{ fontWeight: 600, color: '#27aae1' }}>{compositeSlice.state || 'Draft'}</span>
                {' · '}{localFabricMembers.length} FABRIC + {localChameleonMembers.length} Chameleon
              </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#27aae1' }}>
                  Subslices
                </div>
                <button
                  style={{ fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #27aae1', background: 'rgba(39,170,225,0.1)', color: '#27aae1', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
                  disabled={saving || allSubsliceCandidates.length === 0}
                  onClick={() => openAddMemberDialog('all')}
                  data-testid="federated-add-subslice"
                >
                  Add Subslice
                </button>
              </div>

              {selectedSubsliceOptions.length === 0 ? (
                <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', padding: '5px 2px' }}>No subslices selected.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {selectedSubsliceOptions.map(member => (
                    <div
                      key={`${member.provider}:${member.id}`}
                      style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto auto auto auto', gap: 6, alignItems: 'center', padding: '5px 6px', border: '1px solid var(--fabric-border)', borderRadius: 4, fontSize: 11, opacity: saving ? 0.65 : 1 }}
                      data-testid="federated-member-row"
                      data-provider={member.provider}
                      data-subslice-id={member.id}
                      data-subslice-name={member.name}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{member.name}</div>
                        <div style={{ color: 'var(--fabric-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{member.site ? `${member.site} · ` : ''}{member.id}</div>
                      </div>
                      <span className={`federated-candidate-provider federated-candidate-provider-${member.provider}`}>
                        {member.provider === 'fabric' ? 'FABRIC' : 'CHI'}
                      </span>
                      <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', padding: '1px 4px', borderRadius: 3, background: stateLooksHealthy(member.state) ? 'rgba(0, 142, 122, 0.15)' : 'rgba(87, 152, 188, 0.15)', color: stateLooksHealthy(member.state) ? '#008e7a' : (member.provider === 'fabric' ? '#5798bc' : '#39B54A'), whiteSpace: 'nowrap' }}>
                        {member.state || 'Draft'}
                      </span>
                      <button
                        style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', cursor: 'pointer', whiteSpace: 'nowrap' }}
                        data-testid="federated-member-edit"
                        onClick={() => {
                          if (member.provider === 'fabric') {
                            setSelectedFabricMemberId(member.id);
                            setTab('fabric');
                          } else {
                            setSelectedChameleonMemberId(member.id);
                            setTab('chameleon');
                          }
                        }}
                      >
                        Edit
                      </button>
                      <button
                        style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text-muted)', cursor: 'pointer', whiteSpace: 'nowrap' }}
                        disabled={saving}
                        data-testid="federated-member-remove"
                        onClick={() => {
                          if (member.provider === 'fabric') removeFabricMember(member.id);
                          else removeChameleonMember(member.id);
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Cross-testbed connections */}
            <div style={{ marginTop: 8, padding: '8px 4px', borderTop: '1px solid var(--fabric-border)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#27aae1', marginBottom: 6 }}>
                Connections
              </div>
              {(compositeSlice.cross_connections || []).length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                  {(compositeSlice.cross_connections || []).map((conn: any, i: number) => (
                    <div
                      key={conn.id || i}
                      style={{ fontSize: 11, padding: '5px 6px', border: '1px solid var(--fabric-border)', borderRadius: 4, display: 'grid', gridTemplateColumns: '1fr auto 1fr auto auto', gap: 6, alignItems: 'center' }}
                      data-testid="federated-connection-row"
                      data-connection-id={conn.id || i}
                      data-connection-type={conn.type || ''}
                    >
                      <span style={{ color: '#5798bc', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{connectionLabel(conn, 'fabric')}</span>
                      <span style={{ color: 'var(--fabric-text-muted)' }}>{'\u2194'}</span>
                      <span style={{ color: '#39B54A', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{connectionLabel(conn, 'chameleon')}</span>
                      <span style={{ fontSize: 9, color: '#27aae1', background: 'rgba(39,170,225,0.1)', padding: '1px 4px', borderRadius: 3, whiteSpace: 'nowrap' }}>
                        {displayConnectionType(conn.type)}
                        {conn.facility_port ? ` ${conn.facility_port}` : ''}
                        {conn.vlan ? ` VLAN ${conn.vlan}` : ''}
                      </span>
                      <button
                        style={{ background: 'none', border: '1px solid var(--fabric-border)', borderRadius: 3, color: 'var(--fabric-text-muted)', cursor: 'pointer', fontSize: 10, padding: '1px 6px' }}
                        disabled={saving}
                        data-testid="federated-connection-remove"
                        onClick={async () => {
                          try {
                            if (conn.id) {
                              const updated = await api.removeFederatedConnection(compositeSliceId, conn.id);
                              onMembersUpdated(updated);
                            } else {
                              const updated = (compositeSlice.cross_connections || []).filter((_: any, j: number) => j !== i);
                              await api.updateFederatedConnections(compositeSliceId, updated);
                              onMembersUpdated({ ...compositeSlice, cross_connections: updated });
                            }
                            onCompositeGraphRefresh();
                          } catch (e: any) { onError(e.message); }
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, alignItems: 'center' }}>
                <select
                  value={connectionType}
                  onChange={(e) => {
                    setConnectionType(e.target.value as 'fabnetv4_l3' | 'facility_port_l2');
                    setConnectionVlan('');
                    setConnectionFacilityPort('');
                    setConnectionFabricNode('');
                    setConnectionChameleonNode('');
                  }}
                  style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                  data-testid="federated-connection-type"
                >
                  <option value="fabnetv4_l3">FABNetv4 L3</option>
                  <option value="facility_port_l2">Facility Port L2</option>
                </select>
                <select
                  value={connectionFabricSliceId}
                  onChange={(e) => setConnectionFabricSliceId(e.target.value)}
                  style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                  data-testid="federated-connection-fabric-slice"
                >
                  <option value="">FABRIC member</option>
                  {fabricMemberOptions.map(member => (
                    <option key={member.id} value={member.id}>{member.name}{member.state ? ` (${member.state})` : ''}</option>
                  ))}
                </select>
                <select
                  value={connectionChameleonSliceId}
                  onChange={(e) => setConnectionChameleonSliceId(e.target.value)}
                  style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                  data-testid="federated-connection-chameleon-slice"
                >
                  <option value="">Chameleon member</option>
                  {chameleonMemberOptions.map(member => (
                    <option key={member.id} value={member.id}>{member.name}{member.site ? ` @ ${member.site}` : ''}</option>
                  ))}
                </select>
              </div>
              {connectionType === 'facility_port_l2' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, alignItems: 'center', marginTop: 4 }}>
                  <select
                    value={connectionChameleonSite}
                    onChange={(e) => {
                      setConnectionChameleonSite(e.target.value);
                      setConnectionChameleonNode('');
                      setConnectionFacilityPort('');
                      setConnectionVlan('');
                    }}
                    style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                    data-testid="federated-connection-chameleon-site"
                  >
                    <option value="">Chameleon site</option>
                    {connectionChameleonSites.map(site => (
                      <option key={site} value={site}>{site}</option>
                    ))}
                  </select>
                  <select
                    value={connectionFacilityPort}
                    onChange={(e) => {
                      const name = e.target.value;
                      const fp = connectionFacilityPorts?.facility_ports.find(port => port.name === name);
                      setConnectionFacilityPort(name);
                      setConnectionFabricSite(fp?.fabric_site || fp?.site || '');
                      setConnectionVlan(connectionFacilityPorts?.suggested_vlan ? String(connectionFacilityPorts.suggested_vlan) : '');
                    }}
                    disabled={connectionPortsLoading || !connectionFacilityPorts}
                    style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0, opacity: connectionPortsLoading || !connectionFacilityPorts ? 0.55 : 1 }}
                    data-testid="federated-connection-facility-port"
                  >
                    <option value="">{connectionPortsLoading ? 'Loading facility ports...' : 'Facility port'}</option>
                    {(connectionFacilityPorts?.facility_ports || []).map(fp => (
                      <option key={fp.name} value={fp.name}>{fp.name} @ {fp.fabric_site || fp.site}</option>
                    ))}
                  </select>
                  <select
                    value={connectionFabricNode}
                    onChange={(e) => {
                      const nodeName = e.target.value;
                      const node = connectionFabricNodeOptions.find(n => n.name === nodeName);
                      setConnectionFabricNode(nodeName);
                      if (node?.site && !connectionFabricSite) setConnectionFabricSite(node.site);
                    }}
                    style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                    data-testid="federated-connection-fabric-node"
                  >
                    <option value="">FABRIC endpoint node</option>
                    {connectionFabricNodeOptions.map(node => (
                      <option key={node.name} value={node.name}>{node.name}{node.site ? ` @ ${node.site}` : ''}</option>
                    ))}
                  </select>
                  <select
                    value={connectionChameleonNode}
                    onChange={(e) => setConnectionChameleonNode(e.target.value)}
                    style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                    data-testid="federated-connection-chameleon-node"
                  >
                    <option value="">Chameleon endpoint node</option>
                    {connectionChameleonNodeOptions.map(node => (
                      <option key={node.id || node.name} value={node.name}>{node.name}{node.site ? ` @ ${node.site}` : ''}</option>
                    ))}
                  </select>
                  {selectedFacilityPortVlans.length > 0 ? (
                    <select
                      value={connectionVlan}
                      onChange={(e) => setConnectionVlan(e.target.value)}
                      style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                      data-testid="federated-connection-vlan"
                    >
                      <option value="">VLAN</option>
                      {selectedFacilityPortVlans.map(vlan => (
                        <option key={vlan} value={vlan}>{vlan}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={connectionVlan}
                      onChange={(e) => setConnectionVlan(e.target.value)}
                      placeholder="VLAN"
                      style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                      data-testid="federated-connection-vlan"
                    />
                  )}
                  <input
                    value={connectionFabricSite}
                    onChange={(e) => setConnectionFabricSite(e.target.value)}
                    placeholder="FABRIC site"
                    style={{ fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)', minWidth: 0 }}
                    data-testid="federated-connection-fabric-site"
                  />
                </div>
              )}
              <button
                style={{ marginTop: 6, fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #27aae1', background: 'rgba(39,170,225,0.1)', color: '#27aae1', cursor: 'pointer', fontWeight: 600 }}
                disabled={saving || Boolean(connectionValidationMessage)}
                onClick={addConnection}
                data-testid="federated-add-connection"
              >
                Add Connection
              </button>
              {connectionValidationMessage && (
                <div style={{ marginTop: 4, fontSize: 10, color: 'var(--fabric-text-muted)' }}>
                  {connectionValidationMessage}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'fabric' && (
          <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Slice selector */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8, alignItems: 'center' }}>
              <select
                style={{ flex: 1, fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)' }}
                value={selectedFabricMemberId}
                onChange={(e) => setSelectedFabricMemberId(e.target.value)}
                data-testid="federated-fabric-member-select"
              >
                <option value="">-- Select FABRIC slice --</option>
                {memberFabricSummaries.map((m: any) => (
                  <option key={m.id} value={m.id}>{m.name} ({m.state})</option>
                ))}
              </select>
              {onCreateSlice && (
                <button
                  style={{ fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #5798bc', background: 'rgba(87,152,188,0.1)', color: '#5798bc', cursor: 'pointer', whiteSpace: 'nowrap' }}
                  onClick={() => onCreateSlice('fabric')}
                  data-testid="federated-create-fabric-slice"
                >+ New</button>
              )}
            </div>
            {/* Embedded editor or placeholder */}
            {selectedFabricMemberId && fabricMemberData ? (
              <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--fabric-border)', borderRadius: 4 }}>
                <EditorPanel
                  sliceData={fabricMemberData}
                  sliceName={fabricMemberData.name || selectedFabricMemberId}
                  onSliceUpdated={(data) => {
                    setFabricMemberData(data);
                    onFabricSliceUpdated?.(data);
                    onCompositeGraphRefresh();
                  }}
                  onCollapse={() => setSelectedFabricMemberId('')}
                  sites={sites || []}
                  images={images || []}
                  componentModels={componentModels || []}
                  selectedElement={selectedElement}
                  vmTemplates={vmTemplates || []}
                  onSaveVmTemplate={onSaveVmTemplate ? (nodeName) => onSaveVmTemplate(fabricMemberData.id || selectedFabricMemberId, nodeName, fabricMemberData) : undefined}
                  onBootConfigErrors={onBootConfigErrors}
                  onRunBootConfig={onRunFabricBootConfig ? () => onRunFabricBootConfig(fabricMemberData.id || selectedFabricMemberId) : undefined}
                  bootRunning={!!sliceBootRunning?.[fabricMemberData.id || selectedFabricMemberId] || !!sliceBootRunning?.[fabricMemberData.name || '']}
                  facilityPorts={facilityPorts || []}
                  viewContext="fabric"
                />
              </div>
            ) : selectedFabricMemberId && loadingMember ? (
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--fabric-text-muted)' }}>Loading slice...</div>
            ) : localFabricMembers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p>No FABRIC slices in this federated slice.</p>
                <p style={{ fontSize: 11 }}>Add existing slices in the Federated tab or create a new one above.</p>
              </div>
            ) : !selectedFabricMemberId ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p style={{ fontSize: 11 }}>Select a FABRIC slice above to edit it.</p>
              </div>
            ) : null}
          </div>
        )}

        {tab === 'chameleon' && chameleonEnabled && (
          <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Slice selector */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8, alignItems: 'center' }}>
              <select
                style={{ flex: 1, fontSize: 11, padding: '3px 6px', borderRadius: 3, border: '1px solid var(--fabric-border)', background: 'var(--fabric-bg)', color: 'var(--fabric-text)' }}
                value={selectedChameleonMemberId}
                onChange={(e) => setSelectedChameleonMemberId(e.target.value)}
                data-testid="federated-chameleon-member-select"
              >
                <option value="">-- Select Chameleon slice --</option>
                {memberChameleonSummaries.map((m: any) => (
                  <option key={m.id} value={m.id}>{m.name} ({m.state})</option>
                ))}
              </select>
              {onCreateSlice && (
                <button
                  style={{ fontSize: 10, padding: '3px 8px', borderRadius: 3, border: '1px solid #39B54A', background: 'rgba(57,181,74,0.1)', color: '#39B54A', cursor: 'pointer', whiteSpace: 'nowrap' }}
                  onClick={() => onCreateSlice('chameleon')}
                  data-testid="federated-create-chameleon-slice"
                >+ New</button>
              )}
            </div>
            {/* Embedded Chameleon editor or placeholder */}
            {selectedChameleonMemberId ? (
              <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--fabric-border)', borderRadius: 4 }}>
                <ChameleonEditor
                  sites={chameleonSites || []}
                  onError={onError}
                  formsOnly
                  draftId={selectedChameleonMemberId}
                  onDraftUpdated={(draft) => {
                    onChameleonSliceUpdated?.(draft);
                    onCompositeGraphRefresh();
                  }}
                  autoRefresh={chameleonAutoRefresh}
                  onOpenTerminal={onOpenChameleonTerminal}
                />
              </div>
            ) : localChameleonMembers.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p>No Chameleon slices in this federated slice.</p>
                <p style={{ fontSize: 11 }}>Add existing slices in the Federated tab or create a new one above.</p>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--fabric-text-muted)' }}>
                <p style={{ fontSize: 11 }}>Select a Chameleon slice above to edit it.</p>
              </div>
            )}
          </div>
        )}
      </div>

      {addMemberDialogOpen && typeof document !== 'undefined' && createPortal(
        <div
          className="template-modal-overlay"
          style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }}
          onClick={() => setAddMemberDialogOpen(false)}
          data-testid="federated-subslice-modal-overlay"
        >
          <div
            className="template-modal federated-subslice-modal"
            style={{ maxHeight: '80vh', overflowY: 'auto' }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="federated-subslice-modal-title"
            data-testid="federated-subslice-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 id="federated-subslice-modal-title">Manage Subslices</h4>
            <div className="federated-subslice-controls">
              <div className="federated-subslice-filter">
                <label htmlFor="federated-subslice-filter">Filter</label>
                <input
                  id="federated-subslice-filter"
                  className="template-input"
                  value={memberCandidateFilter}
                  onChange={(e) => setMemberCandidateFilter(e.target.value)}
                  placeholder="Name, state, site, or id"
                  autoFocus
                  data-testid="federated-subslice-filter"
                />
              </div>
              <div className="federated-subslice-filter" style={{ flex: '0 0 180px', minWidth: 160 }}>
                <label htmlFor="federated-subslice-provider">Provider</label>
                <select
                  id="federated-subslice-provider"
                  className="template-input"
                  value={memberProviderFilter}
                  onChange={(e) => setMemberProviderFilter(e.target.value as MemberProviderFilter)}
                  data-testid="federated-subslice-provider-filter"
                >
                  <option value="all">All providers</option>
                  <option value="fabric">FABRIC</option>
                  {chameleonEnabled && <option value="chameleon">Chameleon</option>}
                </select>
              </div>
              <span>{filteredSubsliceCandidates.length} of {allSubsliceCandidates.length} subslices</span>
            </div>
            <div className="federated-candidate-table-wrap">
              <table className="federated-candidate-table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Name</th>
                    <th>State</th>
                    <th>Details</th>
                    <th>ID</th>
                    <th className="federated-candidate-action-column"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSubsliceCandidates.map(candidate => (
                    <tr
                      key={`${candidate.provider}:${candidate.id}`}
                      data-testid="federated-subslice-candidate"
                      data-provider={candidate.provider}
                      data-subslice-id={candidate.id}
                      data-subslice-name={candidate.name}
                      data-selected={candidate.selected ? 'true' : 'false'}
                    >
                      <td>
                        <span className={`federated-candidate-provider federated-candidate-provider-${candidate.provider}`}>
                          {candidate.provider === 'fabric' ? 'FABRIC' : 'CHI'}
                        </span>
                      </td>
                      <td className="federated-candidate-name">{candidate.name}</td>
                      <td className={stateLooksHealthy(candidate.state) ? 'federated-candidate-state-ok' : 'federated-candidate-state-muted'}>
                        {candidate.state || 'Draft'}
                      </td>
                      <td className="federated-candidate-muted">
                        {candidate.provider === 'fabric'
                          ? (candidate.nodeCount !== undefined ? `${candidate.nodeCount} node${candidate.nodeCount === 1 ? '' : 's'}` : '-')
                          : (candidate.site || '-')}
                      </td>
                      <td className="federated-candidate-id" title={candidate.id}>{candidate.id}</td>
                      <td className="federated-candidate-actions">
                        <button
                          disabled={saving}
                          data-testid="federated-subslice-toggle"
                          onClick={() => {
                            if (candidate.selected) {
                              if (candidate.provider === 'fabric') removeFabricMember(candidate.id);
                              else removeChameleonMember(candidate.id);
                            } else {
                              addMember(candidate.provider, candidate.id);
                            }
                          }}
                        >
                          {candidate.selected ? 'Remove' : 'Add'}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredSubsliceCandidates.length === 0 && (
                    <tr>
                      <td colSpan={6} className="federated-candidate-empty">
                        No subslices match the current filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="template-modal-actions">
              <button onClick={() => setAddMemberDialogOpen(false)} data-testid="federated-subslice-close">Close</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
});
