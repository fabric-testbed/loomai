'use client';
import React, { useState, useEffect, useCallback } from 'react';
import * as api from '../api/client';
import '../styles/chameleon-openstack.css';

type OsTab = 'instances' | 'networks' | 'leases' | 'images' | 'keypairs' | 'floating-ips' | 'security-groups';

const OS_TABS: { key: OsTab; label: string }[] = [
  { key: 'instances', label: 'Instances' },
  { key: 'networks', label: 'Networks' },
  { key: 'leases', label: 'Leases' },
  { key: 'images', label: 'Images' },
  { key: 'keypairs', label: 'Key Pairs' },
  { key: 'floating-ips', label: 'Floating IPs' },
  { key: 'security-groups', label: 'Security Groups' },
];

interface ChameleonOpenStackViewProps {
  onError?: (msg: string) => void;
  onOpenTerminal?: (instance: { id: string; name: string; site: string }) => void;
}

function formatDate(d: string): string {
  if (!d) return '';
  return d.replace('T', ' ').slice(0, 16);
}

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}

export default function ChameleonOpenStackView({ onError, onOpenTerminal }: ChameleonOpenStackViewProps) {
  const [activeTab, setActiveTab] = useState<OsTab>('instances');
  const [filter, setFilter] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  // --- Data state per tab ---
  const [instances, setInstances] = useState<any[]>([]);
  const [networks, setNetworks] = useState<any[]>([]);
  const [leases, setLeases] = useState<any[]>([]);
  const [images, setImages] = useState<any[]>([]);
  const [keypairs, setKeypairs] = useState<any[]>([]);
  const [floatingIps, setFloatingIps] = useState<any[]>([]);
  const [securityGroups, setSecurityGroups] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // --- Create network form ---
  const [showCreateNet, setShowCreateNet] = useState(false);
  const [newNetName, setNewNetName] = useState('');
  const [newNetSite, setNewNetSite] = useState('CHI@TACC');
  const [newNetCidr, setNewNetCidr] = useState('');

  // --- Key pair creation ---
  const [showCreateKp, setShowCreateKp] = useState(false);
  const [newKpName, setNewKpName] = useState('');
  const [newKpSite, setNewKpSite] = useState('CHI@TACC');
  const [newKpPublicKey, setNewKpPublicKey] = useState('');

  // --- Floating IP state ---
  const [showAllocateFip, setShowAllocateFip] = useState(false);
  const [allocFipSite, setAllocFipSite] = useState('CHI@TACC');

  // --- Security Group state ---
  const [showCreateSg, setShowCreateSg] = useState(false);
  const [newSgName, setNewSgName] = useState('');
  const [newSgSite, setNewSgSite] = useState('CHI@TACC');
  const [newSgDesc, setNewSgDesc] = useState('');
  const [expandedSgs, setExpandedSgs] = useState<Set<string>>(new Set());
  const [showAddRule, setShowAddRule] = useState<string | null>(null); // sg_id or null
  const [ruleDirection, setRuleDirection] = useState('ingress');
  const [ruleProtocol, setRuleProtocol] = useState('tcp');
  const [rulePortMin, setRulePortMin] = useState('');
  const [rulePortMax, setRulePortMax] = useState('');
  const [ruleRemoteIp, setRuleRemoteIp] = useState('0.0.0.0/0');

  // --- Image site selector ---
  const [imageSite, setImageSite] = useState('CHI@TACC');

  // --- Auto-refresh ---
  const [autoRefresh, setAutoRefresh] = useState(false);
  const AUTO_REFRESH_TABS: OsTab[] = ['instances', 'leases'];

  // --- Bulk selection ---
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  const load = useCallback((tab: OsTab) => {
    setLoading(true);
    let p: Promise<any>;
    switch (tab) {
      case 'instances':
        p = api.listChameleonInstances().then(setInstances);
        break;
      case 'networks':
        p = api.listChameleonNetworks().then(setNetworks);
        break;
      case 'leases':
        p = api.listChameleonLeases().then(setLeases);
        break;
      case 'images':
        p = api.getChameleonImages(imageSite).then(setImages);
        break;
      case 'keypairs':
        p = api.listChameleonKeypairs().then(setKeypairs);
        break;
      case 'floating-ips':
        p = api.listChameleonFloatingIps().then(setFloatingIps);
        break;
      case 'security-groups':
        p = api.listChameleonSecurityGroups().then(setSecurityGroups);
        break;
      default:
        p = Promise.resolve();
    }
    p.catch((e: any) => onError?.(String(e))).finally(() => setLoading(false));
  }, [imageSite, onError]);

  useEffect(() => { load(activeTab); }, [activeTab, load, refreshKey]);

  // Auto-refresh polling (30s) for instances and leases tabs
  useEffect(() => {
    if (!autoRefresh || !AUTO_REFRESH_TABS.includes(activeTab)) return;
    const interval = setInterval(() => {
      if (!document.hidden) load(activeTab);
    }, 30000);
    return () => clearInterval(interval);
  }, [autoRefresh, activeTab, load]);

  const handleTabChange = (tab: OsTab) => {
    setActiveTab(tab);
    setFilter('');
    setSelectedIds(new Set());
  };

  // Filter helper
  const applyFilter = (data: any[]) => {
    if (!filter) return data;
    const lf = filter.toLowerCase();
    return data.filter(item => JSON.stringify(item).toLowerCase().includes(lf));
  };

  // --- Key pair actions ---
  const handleCreateKeypair = async () => {
    if (!newKpName.trim()) return;
    try {
      await api.createChameleonKeypair({ site: newKpSite, name: newKpName.trim(), public_key: newKpPublicKey || undefined });
      setShowCreateKp(false);
      setNewKpName('');
      setNewKpPublicKey('');
      load('keypairs');
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleDeleteKeypair = async (name: string, site: string) => {
    if (!confirm(`Delete key pair "${name}" at ${site}?`)) return;
    try {
      await api.deleteChameleonKeypair(name, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Instance actions ---
  const handleRebootInstance = async (id: string, site: string) => {
    if (!confirm(`Reboot instance ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.rebootChameleonInstance(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleDeleteInstance = async (id: string, site: string) => {
    if (!confirm(`Delete instance ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.deleteChameleonInstance(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Network actions ---
  const handleDeleteNetwork = async (id: string, site: string) => {
    if (!confirm(`Delete network ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.deleteChameleonNetwork(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleCreateNetwork = async () => {
    if (!newNetName.trim()) return;
    try {
      await api.createChameleonNetwork({ site: newNetSite, name: newNetName.trim(), cidr: newNetCidr || undefined });
      setShowCreateNet(false);
      setNewNetName('');
      setNewNetCidr('');
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Lease actions ---
  const handleExtendLease = async (id: string, site: string) => {
    const hoursStr = prompt('Hours to extend:', '2');
    if (!hoursStr) return;
    const hours = parseInt(hoursStr, 10);
    if (isNaN(hours) || hours <= 0) return;
    try {
      await api.extendChameleonLease(id, site, hours);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleDeleteLease = async (id: string, site: string) => {
    if (!confirm(`Delete lease ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.deleteChameleonLease(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Security group actions ---
  const handleDeleteSecurityGroup = async (id: string, site: string) => {
    if (!confirm(`Delete security group ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.deleteChameleonSecurityGroup(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Floating IP actions ---
  const handleAllocateFloatingIp = async () => {
    try {
      await api.allocateChameleonFloatingIp(allocFipSite);
      setShowAllocateFip(false);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleReleaseFloatingIp = async (id: string, site: string) => {
    if (!confirm(`Release floating IP ${id.slice(0, 8)}... at ${site}?`)) return;
    try {
      await api.releaseChameleonFloatingIp(id, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleDisassociateFloatingIp = async (ipId: string, site: string) => {
    if (!confirm('Disassociate this floating IP from its port?')) return;
    try {
      await api.associateChameleonFloatingIp(ipId, site, '');
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  // --- Security group CRUD ---
  const handleCreateSecurityGroup = async () => {
    if (!newSgName.trim()) return;
    try {
      await api.createChameleonSecurityGroup({ site: newSgSite, name: newSgName.trim(), description: newSgDesc });
      setShowCreateSg(false);
      setNewSgName('');
      setNewSgDesc('');
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleAddSecurityGroupRule = async (sgId: string, site: string) => {
    try {
      const rule: any = { site, direction: ruleDirection, ethertype: 'IPv4' };
      if (ruleProtocol) rule.protocol = ruleProtocol;
      if (rulePortMin) rule.port_range_min = parseInt(rulePortMin, 10);
      if (rulePortMax) rule.port_range_max = parseInt(rulePortMax, 10);
      if (ruleRemoteIp) rule.remote_ip_prefix = ruleRemoteIp;
      await api.addChameleonSecurityGroupRule(sgId, rule);
      setShowAddRule(null);
      setRulePortMin('');
      setRulePortMax('');
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const handleDeleteSecurityGroupRule = async (sgId: string, ruleId: string, site: string) => {
    if (!confirm('Delete this security group rule?')) return;
    try {
      await api.deleteChameleonSecurityGroupRule(sgId, ruleId, site);
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      onError?.(String(e));
    }
  };

  const toggleSgExpand = (sgId: string) => {
    setExpandedSgs(prev => {
      const next = new Set(prev);
      if (next.has(sgId)) next.delete(sgId); else next.add(sgId);
      return next;
    });
  };

  // --- Bulk actions ---
  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`Delete ${selectedIds.size} selected item(s)?`)) return;
    setBulkLoading(true);
    const items = Array.from(selectedIds);
    for (const id of items) {
      try {
        if (activeTab === 'instances') {
          const inst = instances.find(i => i.id === id);
          if (inst) await api.deleteChameleonInstance(id, inst.site || inst._site || 'CHI@TACC');
        } else if (activeTab === 'leases') {
          const lease = leases.find(l => l.id === id);
          if (lease) await api.deleteChameleonLease(id, lease._site || 'CHI@TACC');
        } else if (activeTab === 'networks') {
          const net = networks.find(n => n.id === id);
          if (net) await api.deleteChameleonNetwork(id, net.site || net._site || 'CHI@TACC');
        } else if (activeTab === 'floating-ips') {
          const fip = floatingIps.find(f => f.id === id);
          if (fip) await api.releaseChameleonFloatingIp(id, fip._site || 'CHI@TACC');
        } else if (activeTab === 'keypairs') {
          const kp = keypairs.find(k => k.name === id);
          if (kp) await api.deleteChameleonKeypair(kp.name, kp._site || 'CHI@TACC');
        } else if (activeTab === 'security-groups') {
          const sg = securityGroups.find(s => s.id === id);
          if (sg) await api.deleteChameleonSecurityGroup(id, sg._site || 'CHI@TACC');
        }
      } catch (e: any) {
        onError?.(`Bulk delete failed for ${id.slice(0, 8)}: ${e}`);
      }
    }
    setSelectedIds(new Set());
    setBulkLoading(false);
    setRefreshKey(k => k + 1);
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = (ids: string[]) => {
    setSelectedIds(prev => {
      const allSelected = ids.every(id => prev.has(id));
      if (allSelected) return new Set();
      return new Set(ids);
    });
  };

  // --- Render helpers ---
  const renderTable = (headers: string[], rows: React.ReactNode[][], rowIds?: string[]) => (
    <div className="chi-os-table-wrap">
      <table className="chi-os-table">
        <thead>
          <tr>
            {rowIds && (
              <th style={{ width: 28 }}>
                <input type="checkbox" checked={rowIds.length > 0 && rowIds.every(id => selectedIds.has(id))} onChange={() => toggleSelectAll(rowIds)} />
              </th>
            )}
            {headers.map((h, i) => <th key={i}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={headers.length + (rowIds ? 1 : 0)} className="chi-os-empty">{loading ? 'Loading...' : 'No data'}</td></tr>
          ) : rows.map((cells, i) => (
            <tr key={i} className={rowIds && selectedIds.has(rowIds[i]) ? 'chi-os-row-selected' : ''}>
              {rowIds && <td style={{ width: 28 }}><input type="checkbox" checked={selectedIds.has(rowIds[i])} onChange={() => toggleSelect(rowIds[i])} /></td>}
              {cells.map((c, j) => <td key={j}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const handleAssignFloatingIp = async (instanceId: string, site: string) => {
    try {
      const result = await api.assignChameleonFloatingIp(instanceId, site);
      if (result.floating_ip) {
        setRefreshKey(k => k + 1);
      }
    } catch (e: any) {
      onError?.(`Floating IP assignment failed: ${e}`);
    }
  };

  const renderInstances = () => {
    const data = applyFilter(instances);
    return renderTable(
      ['Name', 'Site', 'Status', 'IPs', 'Floating IP', 'Actions'],
      data.map(s => {
        const site = s.site || s._site || 'CHI@TACC';
        const fip = s.floating_ip || '';
        const hasAnyIp = fip || (s.ip_addresses && s.ip_addresses.length > 0);
        return [
          s.name,
          site,
          <span className={`chi-os-badge chi-os-badge-${(s.status || '').toLowerCase()}`}>{s.status}</span>,
          (s.ip_addresses || []).join(', '),
          fip ? <span style={{ fontFamily: 'monospace', color: 'var(--fabric-teal, #008e7a)', fontWeight: 600 }}>{fip}</span> : <span style={{ color: 'var(--fabric-text-muted)' }}>—</span>,
          <span className="chi-os-row-actions">
            {hasAnyIp && onOpenTerminal && s.status === 'ACTIVE' && (
              <button className="chi-os-btn chi-os-btn-sm" style={{ color: '#39B54A' }} onClick={() => onOpenTerminal({ id: s.id, name: s.name, site })} title="Open SSH terminal">SSH</button>
            )}
            {!fip && s.status === 'ACTIVE' && (
              <button className="chi-os-btn chi-os-btn-sm" style={{ color: 'var(--fabric-teal, #008e7a)' }} onClick={() => handleAssignFloatingIp(s.id, site)} title="Allocate and assign a floating IP">+ FIP</button>
            )}
            <button className="chi-os-btn chi-os-btn-sm" onClick={() => handleRebootInstance(s.id, site)} title="Reboot">Reboot</button>
            <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleDeleteInstance(s.id, site)} title="Delete">Delete</button>
          </span>,
        ];
      }),
      data.map(s => s.id),
    );
  };

  const renderNetworks = () => {
    const data = applyFilter(networks);
    return renderTable(
      ['Name', 'Site', 'Status', 'Shared', 'Subnets', 'Actions'],
      data.map(n => [
        n.name,
        n.site || n._site || '',
        n.status || '',
        n.shared ? 'Yes' : 'No',
        (n.subnet_details || []).map((s: any) => s.cidr || s.name).join(', ') || String(n.subnets?.length || 0),
        n.shared ? '' : (
          <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleDeleteNetwork(n.id, n.site || n._site || 'CHI@TACC')} title="Delete">Delete</button>
        ),
      ]),
      data.map(n => n.id),
    );
  };

  const renderLeases = () => {
    const data = applyFilter(leases);
    return renderTable(
      ['Name', 'Site', 'Status', 'Start', 'End', 'Reservations', 'Actions'],
      data.map(l => [
        l.name,
        l._site || '',
        <span className={`chi-os-badge chi-os-badge-${(l.status || '').toLowerCase()}`}>{l.status}</span>,
        formatDate(l.start_date),
        formatDate(l.end_date),
        String((l.reservations || []).length),
        <span className="chi-os-row-actions">
          <button className="chi-os-btn chi-os-btn-sm" onClick={() => handleExtendLease(l.id, l._site || 'CHI@TACC')} title="Extend">Extend</button>
          <button className="chi-os-btn chi-os-btn-sm" style={{ color: 'var(--fabric-teal, #008e7a)' }} onClick={async () => {
            const sliceId = prompt('Enter slice ID to import instances into:');
            if (!sliceId) return;
            try {
              const result = await api.importChameleonReservation(sliceId, l._site || 'CHI@TACC', l.id);
              alert(`Imported ${result.imported} instance(s): ${result.instances?.join(', ') || 'none'}`);
            } catch (e: any) { onError?.(`Import failed: ${e}`); }
          }} title="Import instances from this lease into a slice">Import</button>
          <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleDeleteLease(l.id, l._site || 'CHI@TACC')} title="Delete">Delete</button>
        </span>,
      ]),
      data.map(l => l.id),
    );
  };

  const renderImages = () => {
    const data = applyFilter(images);
    return renderTable(
      ['Name', 'Status', 'Size'],
      data.map(img => [
        img.name,
        img.status || '',
        img.size_mb ? `${img.size_mb} MB` : (img.size ? formatSize(img.size) : ''),
      ]),
    );
  };

  const renderKeypairs = () => {
    const data = applyFilter(keypairs);
    return renderTable(
      ['Name', 'Site', 'Fingerprint', 'Type', 'Actions'],
      data.map(kp => [
        kp.name,
        kp._site || '',
        <span className="chi-os-mono">{kp.fingerprint || ''}</span>,
        kp.type || '',
        <button className="chi-os-btn chi-os-btn-danger" onClick={() => handleDeleteKeypair(kp.name, kp._site || 'CHI@TACC')}>Delete</button>,
      ]),
      data.map(kp => kp.name),
    );
  };

  const renderFloatingIps = () => {
    const data = applyFilter(floatingIps);
    return renderTable(
      ['IP', 'Site', 'Status', 'Port', 'Actions'],
      data.map(fip => [
        fip.floating_ip_address || '',
        fip._site || '',
        <span className={`chi-os-badge chi-os-badge-${(fip.status || '').toLowerCase()}`}>{fip.status}</span>,
        fip.port_id ? fip.port_id.slice(0, 8) + '...' : 'None',
        <span className="chi-os-row-actions">
          {fip.port_id && <button className="chi-os-btn chi-os-btn-sm" onClick={() => handleDisassociateFloatingIp(fip.id, fip._site || 'CHI@TACC')} title="Disassociate from port">Disassociate</button>}
          <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleReleaseFloatingIp(fip.id, fip._site || 'CHI@TACC')} title="Release IP">Release</button>
        </span>,
      ]),
      data.map(fip => fip.id),
    );
  };

  const renderSecurityGroups = () => {
    const data = applyFilter(securityGroups);
    return (
      <div className="chi-os-table-wrap">
        <table className="chi-os-table">
          <thead>
            <tr><th></th><th>Name</th><th>Site</th><th>Description</th><th>Rules</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {data.length === 0 ? (
              <tr><td colSpan={6} className="chi-os-empty">{loading ? 'Loading...' : 'No data'}</td></tr>
            ) : data.map(sg => {
              const isExpanded = expandedSgs.has(sg.id);
              const rules = sg.security_group_rules || [];
              const sgSite = sg._site || 'CHI@TACC';
              return (
                <React.Fragment key={sg.id}>
                  <tr>
                    <td style={{ width: 28, cursor: 'pointer', textAlign: 'center' }} onClick={() => toggleSgExpand(sg.id)}>
                      <span style={{ fontSize: 8 }}>{isExpanded ? '\u25BC' : '\u25B6'}</span>
                    </td>
                    <td>{sg.name}</td>
                    <td>{sgSite}</td>
                    <td>{(sg.description || '').slice(0, 60)}</td>
                    <td style={{ cursor: 'pointer' }} onClick={() => toggleSgExpand(sg.id)}>{rules.length}</td>
                    <td>
                      {sg.name !== 'default' && (
                        <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleDeleteSecurityGroup(sg.id, sgSite)}>Delete</button>
                      )}
                    </td>
                  </tr>
                  {isExpanded && (
                    <>
                      {rules.map((r: any) => (
                        <tr key={r.id} style={{ background: 'var(--fabric-bg-tint, #f8f9fa)', fontSize: 11 }}>
                          <td></td>
                          <td style={{ paddingLeft: 16 }}>{r.direction}</td>
                          <td>{r.protocol || 'any'}</td>
                          <td>{r.port_range_min != null ? `${r.port_range_min}-${r.port_range_max}` : 'all'}</td>
                          <td>{r.remote_ip_prefix || r.remote_group_id || 'any'}</td>
                          <td>
                            <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={() => handleDeleteSecurityGroupRule(sg.id, r.id, sgSite)}>Remove</button>
                          </td>
                        </tr>
                      ))}
                      {showAddRule === sg.id ? (
                        <tr style={{ background: 'var(--fabric-bg-tint, #f8f9fa)', fontSize: 11 }}>
                          <td></td>
                          <td>
                            <select value={ruleDirection} onChange={e => setRuleDirection(e.target.value)} style={{ fontSize: 11 }}>
                              <option value="ingress">ingress</option>
                              <option value="egress">egress</option>
                            </select>
                          </td>
                          <td>
                            <select value={ruleProtocol} onChange={e => setRuleProtocol(e.target.value)} style={{ fontSize: 11 }}>
                              <option value="tcp">tcp</option>
                              <option value="udp">udp</option>
                              <option value="icmp">icmp</option>
                              <option value="">any</option>
                            </select>
                          </td>
                          <td>
                            <input type="number" placeholder="min" value={rulePortMin} onChange={e => setRulePortMin(e.target.value)} style={{ width: 50, fontSize: 11 }} />
                            {' - '}
                            <input type="number" placeholder="max" value={rulePortMax} onChange={e => setRulePortMax(e.target.value)} style={{ width: 50, fontSize: 11 }} />
                          </td>
                          <td>
                            <input type="text" placeholder="0.0.0.0/0" value={ruleRemoteIp} onChange={e => setRuleRemoteIp(e.target.value)} style={{ width: 100, fontSize: 11 }} />
                          </td>
                          <td>
                            <button className="chi-os-btn chi-os-btn-sm chi-os-btn-primary" onClick={() => handleAddSecurityGroupRule(sg.id, sgSite)}>Add</button>
                            {' '}
                            <button className="chi-os-btn chi-os-btn-sm" onClick={() => setShowAddRule(null)}>Cancel</button>
                          </td>
                        </tr>
                      ) : (
                        <tr style={{ background: 'var(--fabric-bg-tint, #f8f9fa)' }}>
                          <td></td>
                          <td colSpan={5}>
                            <button className="chi-os-btn chi-os-btn-sm" onClick={() => setShowAddRule(sg.id)}>+ Add Rule</button>
                          </td>
                        </tr>
                      )}
                    </>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  const TAB_RENDERERS: Record<OsTab, () => React.ReactNode> = {
    instances: renderInstances,
    networks: renderNetworks,
    leases: renderLeases,
    images: renderImages,
    keypairs: renderKeypairs,
    'floating-ips': renderFloatingIps,
    'security-groups': renderSecurityGroups,
  };

  return (
    <div className="chi-os-view">
      {/* Sub-tab bar */}
      <div className="chi-os-tabs">
        {OS_TABS.map(t => (
          <button
            key={t.key}
            className={`chi-os-tab${activeTab === t.key ? ' active' : ''}`}
            onClick={() => handleTabChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Action bar */}
      <div className="chi-os-action-bar">
        <button
          className="chi-action-btn"
          style={{ fontSize: 10, padding: '2px 8px' }}
          onClick={() => { setRefreshKey(k => k + 1); load(activeTab); }}
          title="Refresh data"
        >{'\u21BB'} Refresh</button>
        <button
          className={`chi-action-btn${autoRefresh ? ' chi-action-btn-active' : ''}`}
          style={{ fontSize: 10, padding: '2px 8px' }}
          onClick={() => setAutoRefresh(v => !v)}
          title={autoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh (30s)'}
        >{autoRefresh ? '\u25CF Auto' : '\u25CB Auto'}</button>
        <input
          className="chi-os-filter"
          type="text"
          placeholder="Filter..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        {activeTab === 'images' && (
          <select className="chi-os-site-select" value={imageSite} onChange={e => { setImageSite(e.target.value); }}>
            <option value="CHI@TACC">CHI@TACC</option>
            <option value="CHI@UC">CHI@UC</option>
            <option value="CHI@NU">CHI@NU</option>
            <option value="CHI@EVL">CHI@EVL</option>
            <option value="KVM@TACC">KVM@TACC</option>
          </select>
        )}
        {activeTab === 'keypairs' && (
          <button className="chi-os-btn chi-os-btn-primary" onClick={() => setShowCreateKp(true)}>+ Create Key Pair</button>
        )}
        {activeTab === 'networks' && (
          <button className="chi-os-btn chi-os-btn-primary" onClick={() => setShowCreateNet(true)}>+ Create Network</button>
        )}
        {activeTab === 'floating-ips' && (
          <button className="chi-os-btn chi-os-btn-primary" onClick={() => setShowAllocateFip(true)}>+ Allocate IP</button>
        )}
        {activeTab === 'security-groups' && (
          <button className="chi-os-btn chi-os-btn-primary" onClick={() => setShowCreateSg(true)}>+ Create Security Group</button>
        )}
        <button className="chi-os-btn" onClick={() => setRefreshKey(k => k + 1)} disabled={loading} title="Refresh">
          {loading ? 'Loading...' : '\u21BB Refresh'}
        </button>
        {AUTO_REFRESH_TABS.includes(activeTab) && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer', marginLeft: 4 }}>
            <input type="checkbox" checked={autoRefresh} onChange={() => setAutoRefresh(v => !v)} />
            Auto
          </label>
        )}
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', background: 'var(--fabric-bg-tint)', borderBottom: '1px solid var(--fabric-border)', fontSize: 12, color: 'var(--fabric-text)' }}>
          <span style={{ fontWeight: 600 }}>{selectedIds.size} selected</span>
          <button className="chi-os-btn chi-os-btn-sm chi-os-btn-danger" onClick={handleBulkDelete} disabled={bulkLoading}>
            {bulkLoading ? 'Deleting...' : `Delete ${selectedIds.size}`}
          </button>
          <button className="chi-os-btn chi-os-btn-sm" onClick={() => setSelectedIds(new Set())} style={{ marginLeft: 'auto' }}>
            Clear selection
          </button>
        </div>
      )}

      {/* Create keypair dialog */}
      {showCreateKp && (
        <div className="chi-os-create-kp">
          <div className="chi-os-create-kp-row">
            <label>Name:</label>
            <input type="text" value={newKpName} onChange={e => setNewKpName(e.target.value)} placeholder="my-key" />
          </div>
          <div className="chi-os-create-kp-row">
            <label>Site:</label>
            <select value={newKpSite} onChange={e => setNewKpSite(e.target.value)}>
              <option value="CHI@TACC">CHI@TACC</option>
              <option value="CHI@UC">CHI@UC</option>
              <option value="CHI@NU">CHI@NU</option>
              <option value="CHI@EVL">CHI@EVL</option>
              <option value="KVM@TACC">KVM@TACC</option>
            </select>
          </div>
          <div className="chi-os-create-kp-row">
            <label>Public Key (optional):</label>
            <textarea value={newKpPublicKey} onChange={e => setNewKpPublicKey(e.target.value)} placeholder="ssh-rsa AAAA..." rows={3} />
          </div>
          <div className="chi-os-create-kp-actions">
            <button className="chi-os-btn chi-os-btn-primary" onClick={handleCreateKeypair} disabled={!newKpName.trim()}>Create</button>
            <button className="chi-os-btn" onClick={() => setShowCreateKp(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Create network dialog */}
      {showCreateNet && (
        <div className="chi-os-create-kp">
          <div className="chi-os-create-kp-row">
            <label>Name:</label>
            <input type="text" value={newNetName} onChange={e => setNewNetName(e.target.value)} placeholder="my-network" />
          </div>
          <div className="chi-os-create-kp-row">
            <label>Site:</label>
            <select value={newNetSite} onChange={e => setNewNetSite(e.target.value)}>
              <option value="CHI@TACC">CHI@TACC</option>
              <option value="CHI@UC">CHI@UC</option>
              <option value="CHI@NU">CHI@NU</option>
              <option value="CHI@EVL">CHI@EVL</option>
              <option value="KVM@TACC">KVM@TACC</option>
            </select>
          </div>
          <div className="chi-os-create-kp-row">
            <label>CIDR (optional):</label>
            <input type="text" value={newNetCidr} onChange={e => setNewNetCidr(e.target.value)} placeholder="192.168.1.0/24" />
          </div>
          <div className="chi-os-create-kp-actions">
            <button className="chi-os-btn chi-os-btn-primary" onClick={handleCreateNetwork} disabled={!newNetName.trim()}>Create</button>
            <button className="chi-os-btn" onClick={() => setShowCreateNet(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Allocate floating IP dialog */}
      {showAllocateFip && (
        <div className="chi-os-create-kp">
          <div className="chi-os-create-kp-row">
            <label>Site:</label>
            <select value={allocFipSite} onChange={e => setAllocFipSite(e.target.value)}>
              <option value="CHI@TACC">CHI@TACC</option>
              <option value="CHI@UC">CHI@UC</option>
              <option value="KVM@TACC">KVM@TACC</option>
            </select>
          </div>
          <div className="chi-os-create-kp-actions">
            <button className="chi-os-btn chi-os-btn-primary" onClick={handleAllocateFloatingIp}>Allocate</button>
            <button className="chi-os-btn" onClick={() => setShowAllocateFip(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Create security group dialog */}
      {showCreateSg && (
        <div className="chi-os-create-kp">
          <div className="chi-os-create-kp-row">
            <label>Name:</label>
            <input type="text" value={newSgName} onChange={e => setNewSgName(e.target.value)} placeholder="my-security-group" />
          </div>
          <div className="chi-os-create-kp-row">
            <label>Site:</label>
            <select value={newSgSite} onChange={e => setNewSgSite(e.target.value)}>
              <option value="CHI@TACC">CHI@TACC</option>
              <option value="CHI@UC">CHI@UC</option>
              <option value="KVM@TACC">KVM@TACC</option>
            </select>
          </div>
          <div className="chi-os-create-kp-row">
            <label>Description:</label>
            <input type="text" value={newSgDesc} onChange={e => setNewSgDesc(e.target.value)} placeholder="Optional description" />
          </div>
          <div className="chi-os-create-kp-actions">
            <button className="chi-os-btn chi-os-btn-primary" onClick={handleCreateSecurityGroup} disabled={!newSgName.trim()}>Create</button>
            <button className="chi-os-btn" onClick={() => setShowCreateSg(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="chi-os-content">
        {TAB_RENDERERS[activeTab]?.()}
      </div>
    </div>
  );
}
