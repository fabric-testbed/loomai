'use client';
import { useState, useEffect } from 'react';
import type { SliceData, SliceNode, SliceNetwork, SliceErrorMessage, SiteDetail, SiteMetrics, LinkMetrics } from '../types/fabric';
import { getSiteDetail } from '../api/client';
import '../styles/editor.css';

interface DragHandleProps {
  draggable: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
}

interface DetailPanelProps {
  sliceData: SliceData | null;
  selectedElement: Record<string, string> | null;
  onCollapse?: () => void;
  siteMetricsCache: Record<string, SiteMetrics>;
  linkMetricsCache: Record<string, LinkMetrics>;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
  dragHandleProps?: DragHandleProps;
  panelIcon?: string;
}

export default function DetailPanel({
  sliceData, selectedElement, onCollapse,
  siteMetricsCache, linkMetricsCache,
  metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
  dragHandleProps, panelIcon,
}: DetailPanelProps) {
  if (!selectedElement) {
    return (
      <div className="detail-panel">
        <div className="detail-header" {...(dragHandleProps || {})}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="panel-drag-handle">{'\u283F'}</span>
            Details
          </span>
          {onCollapse && <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">{'\u2715'}</button>}
        </div>
        <div className="detail-body">
          <div className="detail-empty">Click an element to view details</div>
        </div>
      </div>
    );
  }

  const elementType = selectedElement.element_type;

  const typeLabels: Record<string, string> = {
    node: 'Node',
    network: 'Network',
    interface: 'Interface',
    slice: 'Slice',
    site: 'Site',
    infra_link: 'Link',
    'port-mirror': 'Port Mirror',
  };

  const hasTabs = elementType === 'site' || elementType === 'infra_link';

  return (
    <div className="detail-panel">
      <div className="detail-header" {...(dragHandleProps || {})}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="panel-drag-handle">{'\u283F'}</span>
          {typeLabels[elementType] ?? elementType}
          {' — '}
          {selectedElement.name || selectedElement.label}
        </span>
        {onCollapse && <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">{'\u2715'}</button>}
      </div>
      <div className="detail-body">
        {elementType === 'node' && sliceData && <NodeDetail node={findNode(sliceData, selectedElement.name)} data={selectedElement} />}
        {elementType === 'network' && sliceData && <NetworkDetail network={findNetwork(sliceData, selectedElement.name)} data={selectedElement} />}
        {elementType === 'interface' && <InterfaceDetail data={selectedElement} />}
        {elementType === 'port-mirror' && <PortMirrorDetail data={selectedElement} />}
        {elementType === 'slice' && sliceData && <SliceDetailView data={selectedElement} sliceData={sliceData} />}
        {elementType === 'site' && (
          <SiteTabbedDetail
            data={selectedElement}
            metrics={siteMetricsCache[selectedElement.name] ?? null}
            metricsRefreshRate={metricsRefreshRate}
            onMetricsRefreshRateChange={onMetricsRefreshRateChange}
            onRefreshMetrics={onRefreshMetrics}
            metricsLoading={metricsLoading}
          />
        )}
        {elementType === 'infra_link' && (
          <LinkTabbedDetail
            data={selectedElement}
            metrics={linkMetricsCache[`${selectedElement.site_a}-${selectedElement.site_b}`] ?? null}
            metricsRefreshRate={metricsRefreshRate}
            onMetricsRefreshRateChange={onMetricsRefreshRateChange}
            onRefreshMetrics={onRefreshMetrics}
            metricsLoading={metricsLoading}
          />
        )}
      </div>
    </div>
  );
}

function PropTable({ rows }: { rows: [string, string | number | undefined][] }) {
  return (
    <table>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <td className="label-cell">{label}</td>
            <td>{value ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NodeDetail({ node, data }: { node: SliceNode | null; data: Record<string, string> }) {
  const errorMessage = node?.error_message || '';
  return (
    <>
      <PropTable rows={[
        ['Name', data.name],
        ['Site', data.site],
        ['Host', data.host || '—'],
        ['State', data.state],
        ['Cores', data.cores],
        ['RAM', `${data.ram} GB`],
        ['Disk', `${data.disk} GB`],
        ['Image', data.image || '—'],
        ['Mgmt IP', data.management_ip || '—'],
        ['Username', data.username || '—'],
      ]} />

      {errorMessage && <NodeErrorBadge message={errorMessage} />}

      {node?.components && node.components.length > 0 && (
        <>
          <div className="section-title">Components</div>
          <table>
            <thead>
              <tr><th>Name</th><th>Model</th></tr>
            </thead>
            <tbody>
              {node.components.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td>{c.model}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {node?.interfaces && node.interfaces.length > 0 && (
        <>
          <div className="section-title">Interfaces</div>
          <table>
            <thead>
              <tr><th>Name</th><th>Network</th><th>VLAN</th></tr>
            </thead>
            <tbody>
              {node.interfaces.map((i) => (
                <tr key={i.name}>
                  <td>{i.name}</td>
                  <td>{i.network_name || '—'}</td>
                  <td>{i.vlan || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

function NetworkDetail({ network, data }: { network: SliceNetwork | null; data: Record<string, string> }) {
  return (
    <>
      <PropTable rows={[
        ['Name', data.name],
        ['Type', data.type],
        ['Layer', data.layer],
        ['Subnet', data.subnet || '—'],
        ['Gateway', data.gateway || '—'],
      ]} />

      {network?.interfaces && network.interfaces.length > 0 && (
        <>
          <div className="section-title">Connected Interfaces</div>
          <table>
            <thead>
              <tr><th>Interface</th><th>Node</th><th>IP</th></tr>
            </thead>
            <tbody>
              {network.interfaces.map((i) => (
                <tr key={i.name}>
                  <td>{i.name}</td>
                  <td>{i.node_name}</td>
                  <td>{i.ip_addr || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

function InterfaceDetail({ data }: { data: Record<string, string> }) {
  return (
    <PropTable rows={[
      ['Interface', data.interface_name],
      ['Node', data.node_name],
      ['Network', data.network_name],
      ['VLAN', data.vlan || '—'],
      ['MAC', data.mac || '—'],
      ['IP', data.ip_addr || '—'],
      ['Bandwidth', data.bandwidth || '—'],
    ]} />
  );
}

function PortMirrorDetail({ data }: { data: Record<string, string> }) {
  return (
    <PropTable rows={[
      ['Name', data.name],
      ['Mirror Interface', data.mirror_interface_name || '—'],
      ['Receive Interface', data.receive_interface_name || '—'],
      ['Direction', data.mirror_direction || 'both'],
    ]} />
  );
}

const TERMINAL_STATES = new Set(['Dead', 'Closing', 'StableError']);

interface ErrorDiagnosis {
  category: string;
  summary: string;
  remedy: string;
}

function diagnoseError(message: string): ErrorDiagnosis {
  const msg = message.toLowerCase();
  if (msg.includes('could not find image') || msg.includes('image not found')) {
    const match = message.match(/image\s+([\w_]+)/i);
    const imageName = match?.[1] || 'the requested image';
    return {
      category: 'Image Not Found',
      summary: `The image "${imageName}" is not available on the target site.`,
      remedy: 'Change the node image to one available on the target site (e.g. default_ubuntu_22, default_centos_9), or try a different site.',
    };
  }
  if (msg.includes('insufficient resources') || msg.includes('no hosts available')) {
    return {
      category: 'Insufficient Resources',
      summary: 'The target site does not have enough resources to provision this node.',
      remedy: 'Try a different site with more available resources, reduce the node size (cores/RAM/disk), or remove specialized components (GPUs, SmartNICs) that may have limited availability.',
    };
  }
  if (msg.includes('closing reservation due to failure in slice')) {
    return {
      category: 'Cascade Failure',
      summary: 'This resource was closed because another resource in the slice failed.',
      remedy: 'Fix the root-cause failure on the other node/network first, then resubmit.',
    };
  }
  if (msg.includes('predecessor reservation') && msg.includes('terminal state')) {
    return {
      category: 'Dependency Failure',
      summary: 'A network or dependent resource failed because its parent node failed first.',
      remedy: 'Fix the root-cause failure on the parent node, then resubmit.',
    };
  }
  if (msg.includes('expired') || msg.includes('lease')) {
    return {
      category: 'Lease Expired',
      summary: 'The slice lease expired and the resources were reclaimed.',
      remedy: 'Create a new slice. Use a longer lease period or renew the lease before it expires.',
    };
  }
  return {
    category: 'Error',
    summary: message.length > 200 ? message.slice(0, 200) + '...' : message,
    remedy: 'Review the error message for details. You may need to adjust the slice configuration and resubmit.',
  };
}

function SliceErrorPanel({ errors }: { errors: SliceErrorMessage[] }) {
  if (!errors || errors.length === 0) return null;

  // Deduplicate and diagnose
  const seen = new Set<string>();
  const diagnosed: Array<{ sliver: string; diagnosis: ErrorDiagnosis; raw: string }> = [];
  for (const err of errors) {
    const key = err.message;
    if (seen.has(key)) continue;
    seen.add(key);
    diagnosed.push({ sliver: err.sliver, diagnosis: diagnoseError(err.message), raw: err.message });
  }

  return (
    <div className="slice-error-panel">
      <div className="slice-error-header">Slice Failed</div>
      {diagnosed.map((d, i) => (
        <div key={i} className="slice-error-entry">
          <div className="slice-error-category">
            {d.diagnosis.category}
            {d.sliver && <span className="slice-error-sliver"> — {d.sliver}</span>}
          </div>
          <div className="slice-error-summary">{d.diagnosis.summary}</div>
          <div className="slice-error-remedy">
            <strong>Suggested fix:</strong> {d.diagnosis.remedy}
          </div>
        </div>
      ))}
    </div>
  );
}

function NodeErrorBadge({ message }: { message: string }) {
  if (!message) return null;
  const diagnosis = diagnoseError(message);
  return (
    <div className="node-error-badge">
      <div className="node-error-category">{diagnosis.category}</div>
      <div className="node-error-summary">{diagnosis.summary}</div>
      <div className="node-error-remedy"><strong>Fix:</strong> {diagnosis.remedy}</div>
    </div>
  );
}

function SliceDetailView({ data, sliceData }: { data: Record<string, string>; sliceData: SliceData }) {
  const isTerminal = TERMINAL_STATES.has(sliceData.state);
  const hasErrors = sliceData.error_messages && sliceData.error_messages.length > 0;

  return (
    <>
      <PropTable rows={[
        ['Name', sliceData.name],
        ['ID', sliceData.id],
        ['State', sliceData.state],
        ['Lease End', sliceData.lease_end || '—'],
        ['Nodes', String(sliceData.nodes.length)],
        ['Networks', String(sliceData.networks.length)],
      ]} />

      {isTerminal && !hasErrors && (
        <div className="slice-terminal-notice">
          This slice is <strong>{sliceData.state}</strong> — it has been shut down and resources have been released. No errors were reported.
        </div>
      )}

      {isTerminal && hasErrors && (
        <div className="slice-terminal-notice" style={{ borderLeftColor: '#e25241', color: '#e25241' }}>
          This slice has failed — see <strong>Slice Errors</strong> tab in the console for details.
        </div>
      )}
    </>
  );
}

/* ============ Metrics Refresh Controls ============ */

function MetricsControls({
  metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
}: {
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
}) {
  return (
    <div className="metrics-controls">
      <button onClick={onRefreshMetrics} disabled={metricsLoading} title="Refresh metrics now">
        {metricsLoading ? '↻...' : '↻'}
      </button>
      <select
        value={metricsRefreshRate}
        onChange={(e) => onMetricsRefreshRateChange(Number(e.target.value))}
        title="How often to refresh site and link metrics (seconds)"
      >
        <option value={0}>Manual</option>
        <option value={5}>5s</option>
        <option value={10}>10s</option>
        <option value={30}>30s</option>
        <option value={60}>1 min</option>
        <option value={300}>5 min</option>
        <option value={600}>10 min</option>
      </select>
    </div>
  );
}

/* ============ Site Tabbed Detail ============ */

function SiteTabbedDetail({
  data, metrics, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
}: {
  data: Record<string, string>;
  metrics: SiteMetrics | null;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
}) {
  const [tab, setTab] = useState<'resources' | 'metrics'>('resources');
  const elementKey = data.name;

  // Reset tab when site changes
  useEffect(() => { setTab('resources'); }, [elementKey]);

  return (
    <>
      <div className="detail-tabs">
        <button className={tab === 'resources' ? 'active' : ''} onClick={() => setTab('resources')}>Resources</button>
        <button className={tab === 'metrics' ? 'active' : ''} onClick={() => setTab('metrics')}>Metrics</button>
      </div>
      {tab === 'resources' && <SiteResourcesTab data={data} />}
      {tab === 'metrics' && (
        <SiteMetricsTab
          metrics={metrics}
          metricsRefreshRate={metricsRefreshRate}
          onMetricsRefreshRateChange={onMetricsRefreshRateChange}
          onRefreshMetrics={onRefreshMetrics}
          metricsLoading={metricsLoading}
        />
      )}
    </>
  );
}

function SiteResourcesTab({ data }: { data: Record<string, string> }) {
  const [siteDetail, setSiteDetail] = useState<SiteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSiteDetail(data.name)
      .then((d) => { if (!cancelled) setSiteDetail(d); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [data.name]);

  return (
    <>
      <PropTable rows={[
        ['Name', data.name],
        ['State', data.state || '—'],
        ['Hosts', data.hosts || '—'],
        ['Location', `${data.lat}, ${data.lon}`],
      ]} />
      <div className="section-title">Compute Resources</div>
      <PropTable rows={[
        ['Cores', `${data.cores_available} / ${data.cores_capacity} available`],
        ['RAM', `${data.ram_available} / ${data.ram_capacity} GB available`],
        ['Disk', `${data.disk_available} / ${data.disk_capacity} GB available`],
      ]} />

      {loading && <div className="detail-loading">Loading component details...</div>}
      {error && <div className="metrics-error">Failed to load components</div>}
      {siteDetail && Object.keys(siteDetail.components).length > 0 && (
        <>
          <div className="section-title">Components</div>
          <table>
            <thead>
              <tr><th>Type</th><th>Avail</th><th>Alloc</th><th>Total</th></tr>
            </thead>
            <tbody>
              {Object.entries(siteDetail.components).map(([name, res]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{res.available}</td>
                  <td>{res.allocated}</td>
                  <td>{res.capacity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {siteDetail && Object.keys(siteDetail.components).length === 0 && (
        <div className="detail-loading">No specialized components at this site</div>
      )}
    </>
  );
}

function SiteMetricsTab({
  metrics, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
}: {
  metrics: SiteMetrics | null;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
}) {
  if (!metrics) {
    return (
      <>
        <MetricsControls
          metricsRefreshRate={metricsRefreshRate}
          onMetricsRefreshRateChange={onMetricsRefreshRateChange}
          onRefreshMetrics={onRefreshMetrics}
          metricsLoading={metricsLoading}
        />
        <div className="detail-loading">Click ↻ to load metrics</div>
      </>
    );
  }

  // Build CPU load table: group by worker instance
  const workers = new Map<string, { load1?: string; load5?: string; load15?: string }>();
  for (const r of metrics.node_load1) {
    const instance = r.metric.instance || r.metric.job || 'unknown';
    if (!workers.has(instance)) workers.set(instance, {});
    workers.get(instance)!.load1 = parseFloat(r.value[1]).toFixed(2);
  }
  for (const r of metrics.node_load5) {
    const instance = r.metric.instance || r.metric.job || 'unknown';
    if (!workers.has(instance)) workers.set(instance, {});
    workers.get(instance)!.load5 = parseFloat(r.value[1]).toFixed(2);
  }
  for (const r of metrics.node_load15) {
    const instance = r.metric.instance || r.metric.job || 'unknown';
    if (!workers.has(instance)) workers.set(instance, {});
    workers.get(instance)!.load15 = parseFloat(r.value[1]).toFixed(2);
  }

  // Build network traffic table
  const destMap = new Map<string, { inBits?: string; outBits?: string }>();
  for (const r of metrics.dataplaneInBits) {
    const dest = r.metric.dst_rack || r.metric.destination || 'unknown';
    if (!destMap.has(dest)) destMap.set(dest, {});
    destMap.get(dest)!.inBits = formatBits(r.value[1]);
  }
  for (const r of metrics.dataplaneOutBits) {
    const dest = r.metric.dst_rack || r.metric.destination || 'unknown';
    if (!destMap.has(dest)) destMap.set(dest, {});
    destMap.get(dest)!.outBits = formatBits(r.value[1]);
  }
  const traffic: { destination: string; inBits: string; outBits: string }[] = [];
  for (const [dest, vals] of destMap) {
    traffic.push({ destination: dest.toUpperCase(), inBits: vals.inBits || '—', outBits: vals.outBits || '—' });
  }

  return (
    <>
      <MetricsControls
        metricsRefreshRate={metricsRefreshRate}
        onMetricsRefreshRateChange={onMetricsRefreshRateChange}
        onRefreshMetrics={onRefreshMetrics}
        metricsLoading={metricsLoading}
      />

      {workers.size > 0 && (
        <>
          <div className="section-title">CPU Load</div>
          <table>
            <thead>
              <tr><th>Worker</th><th>1m</th><th>5m</th><th>15m</th></tr>
            </thead>
            <tbody>
              {[...workers.entries()].map(([instance, loads]) => (
                <tr key={instance}>
                  <td>{shortenInstance(instance)}</td>
                  <td>{loads.load1 ?? '—'}</td>
                  <td>{loads.load5 ?? '—'}</td>
                  <td>{loads.load15 ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {traffic.length > 0 && (
        <>
          <div className="section-title">Network Traffic</div>
          <table>
            <thead>
              <tr><th>Destination</th><th>In</th><th>Out</th></tr>
            </thead>
            <tbody>
              {traffic.map((t) => (
                <tr key={t.destination}>
                  <td>{t.destination}</td>
                  <td>{t.inBits}</td>
                  <td>{t.outBits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {workers.size === 0 && traffic.length === 0 && (
        <div className="detail-loading">No metrics available for this site</div>
      )}
    </>
  );
}

/* ============ Link Tabbed Detail ============ */

function LinkTabbedDetail({
  data, metrics, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
}: {
  data: Record<string, string>;
  metrics: LinkMetrics | null;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
}) {
  const [tab, setTab] = useState<'resources' | 'metrics'>('resources');
  const elementKey = `${data.site_a}-${data.site_b}`;

  useEffect(() => { setTab('resources'); }, [elementKey]);

  return (
    <>
      <div className="detail-tabs">
        <button className={tab === 'resources' ? 'active' : ''} onClick={() => setTab('resources')}>Info</button>
        <button className={tab === 'metrics' ? 'active' : ''} onClick={() => setTab('metrics')}>Metrics</button>
      </div>
      {tab === 'resources' && <LinkResourcesTab data={data} />}
      {tab === 'metrics' && (
        <LinkMetricsTab
          siteA={data.site_a}
          siteB={data.site_b}
          metrics={metrics}
          metricsRefreshRate={metricsRefreshRate}
          onMetricsRefreshRateChange={onMetricsRefreshRateChange}
          onRefreshMetrics={onRefreshMetrics}
          metricsLoading={metricsLoading}
        />
      )}
    </>
  );
}

function LinkResourcesTab({ data }: { data: Record<string, string> }) {
  return (
    <PropTable rows={[
      ['Name', data.name],
      ['From', data.site_a],
      ['To', data.site_b],
    ]} />
  );
}

function LinkMetricsTab({
  siteA, siteB, metrics, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading,
}: {
  siteA: string;
  siteB: string;
  metrics: LinkMetrics | null;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
}) {
  if (!metrics) {
    return (
      <>
        <MetricsControls
          metricsRefreshRate={metricsRefreshRate}
          onMetricsRefreshRateChange={onMetricsRefreshRateChange}
          onRefreshMetrics={onRefreshMetrics}
          metricsLoading={metricsLoading}
        />
        <div className="detail-loading">Click ↻ to load metrics</div>
      </>
    );
  }

  const hasData = metrics.a_to_b_in.length > 0 || metrics.a_to_b_out.length > 0 ||
                  metrics.b_to_a_in.length > 0 || metrics.b_to_a_out.length > 0;

  return (
    <>
      <MetricsControls
        metricsRefreshRate={metricsRefreshRate}
        onMetricsRefreshRateChange={onMetricsRefreshRateChange}
        onRefreshMetrics={onRefreshMetrics}
        metricsLoading={metricsLoading}
      />

      {!hasData ? (
        <div className="detail-loading">No traffic metrics available for this link</div>
      ) : (
        <>
          <div className="section-title">{siteA} → {siteB}</div>
          <PropTable rows={[
            ['In', metrics.a_to_b_in.length > 0 ? formatBits(metrics.a_to_b_in[0].value[1]) : '—'],
            ['Out', metrics.a_to_b_out.length > 0 ? formatBits(metrics.a_to_b_out[0].value[1]) : '—'],
          ]} />

          <div className="section-title">{siteB} → {siteA}</div>
          <PropTable rows={[
            ['In', metrics.b_to_a_in.length > 0 ? formatBits(metrics.b_to_a_in[0].value[1]) : '—'],
            ['Out', metrics.b_to_a_out.length > 0 ? formatBits(metrics.b_to_a_out[0].value[1]) : '—'],
          ]} />
        </>
      )}
    </>
  );
}

/* ============ Helpers ============ */

function formatBits(value: string): string {
  const bits = parseFloat(value);
  if (isNaN(bits)) return '—';
  if (bits >= 1e9) return `${(bits / 1e9).toFixed(2)} Gbps`;
  if (bits >= 1e6) return `${(bits / 1e6).toFixed(2)} Mbps`;
  if (bits >= 1e3) return `${(bits / 1e3).toFixed(2)} Kbps`;
  return `${bits.toFixed(0)} bps`;
}

function shortenInstance(instance: string): string {
  // Extract hostname from "host:port" format
  const host = instance.split(':')[0];
  // Further shorten if it's a FQDN
  const short = host.split('.')[0];
  return short || instance;
}

function findNode(slice: SliceData, name: string): SliceNode | null {
  return slice.nodes.find((n) => n.name === name) ?? null;
}

function findNetwork(slice: SliceData, name: string): SliceNetwork | null {
  return slice.networks.find((n) => n.name === name) ?? null;
}
