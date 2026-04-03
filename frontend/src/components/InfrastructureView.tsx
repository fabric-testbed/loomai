'use client';
import React, { useMemo, useState } from 'react';
import TestbedViewShell, { FABRIC_THEME } from './TestbedViewShell';
import type { Tab } from './TestbedViewShell';
import GeoView from './GeoView';
import ResourceBrowser from './ResourceBrowser';
import FacilityPortsBrowser from './FacilityPortsBrowser';
import ResourceCalendar from './ResourceCalendar';
import '../styles/infrastructure-view.css';
import type { SiteInfo, LinkInfo, SiteMetrics, LinkMetrics, FacilityPortInfo, SliceSummary } from '../types/fabric';

type InfraSubView = 'editor' | 'map' | 'resources' | 'calendar';

// State colors for slice badges
function sliceStateClass(state: string): string {
  const s = state.toLowerCase();
  if (s === 'stableok' || s === 'active') return 'fab-state-active';
  if (s.includes('configuring') || s.includes('nascent') || s.includes('ticketed')) return 'fab-state-pending';
  if (s.includes('error')) return 'fab-state-error';
  if (s.includes('closing') || s.includes('dead')) return 'fab-state-terminated';
  return '';
}

interface InfrastructureViewProps {
  subView: InfraSubView;
  onSubViewChange: (sv: InfraSubView) => void;
  sites: SiteInfo[];
  links: LinkInfo[];
  facilityPorts: FacilityPortInfo[];
  linksLoading: boolean;
  siteMetricsCache: Record<string, SiteMetrics>;
  linkMetricsCache: Record<string, LinkMetrics>;
  metricsRefreshRate: number;
  onMetricsRefreshRateChange: (rate: number) => void;
  onRefreshMetrics: () => void;
  metricsLoading: boolean;
  selectedElement: Record<string, string> | null;
  onNodeClick: (data: Record<string, string>) => void;
  infraLoading: boolean;
  onRefreshInfrastructure: () => void;
  /** FABRIC slices for the Slices tab */
  slices?: SliceSummary[];
  onSliceSelect?: (id: string) => void;
  /** Whether a slice is currently selected (show Editor tab) */
  hasSelectedSlice?: boolean;
  selectedSliceName?: string;
  /** Editor content — passed from App.tsx (topology, table, map, storage, apps sub-views) */
  children?: React.ReactNode;
}

const SUB_VIEW_DEFS: Array<{ key: InfraSubView; label: string; requiresSlice?: boolean }> = [
  { key: 'editor', label: 'Editor', requiresSlice: true },
  { key: 'map', label: 'Map' },
  { key: 'resources', label: 'Resources' },
  { key: 'calendar', label: 'Calendar' },
];

export default function InfrastructureView({
  subView, onSubViewChange, sites, links, facilityPorts, linksLoading,
  siteMetricsCache, linkMetricsCache, metricsRefreshRate, onMetricsRefreshRateChange,
  onRefreshMetrics, metricsLoading, selectedElement, onNodeClick,
  infraLoading, onRefreshInfrastructure, slices, onSliceSelect,
  hasSelectedSlice, selectedSliceName, children,
}: InfrastructureViewProps) {
  // slices data available for sub-components if needed

  // Build tabs for the shell — filter out editor when no slice is selected
  const tabs: Tab[] = useMemo(() => {
    return SUB_VIEW_DEFS
      .filter(sv => !sv.requiresSlice || hasSelectedSlice)
      .map(sv => ({
        id: sv.key,
        label: sv.key === 'editor' && selectedSliceName
          ? `Editor \u2014 ${selectedSliceName}`
          : sv.label,
        badge: undefined,
      }));
  }, [hasSelectedSlice, selectedSliceName]);

  const toolbarContent = (
    <button
      className="infra-refresh-btn"
      onClick={onRefreshInfrastructure}
      disabled={infraLoading}
      title="Refresh sites, links, and metrics"
    >
      {infraLoading ? 'Updating...' : '\u21BB'}
    </button>
  );

  return (
    <TestbedViewShell
      theme={FABRIC_THEME}
      tabs={tabs}
      activeTab={subView}
      onTabChange={(id) => onSubViewChange(id as InfraSubView)}
      toolbarContent={toolbarContent}
    >
      {subView === 'editor' && hasSelectedSlice ? (
        // Full slice editor — content passed from App.tsx
        <>{children}</>
      ) : subView === 'map' ? (
        <GeoView
          sliceData={null}
          selectedElement={selectedElement}
          onNodeClick={onNodeClick}
          sites={sites}
          links={links}
          linksLoading={linksLoading}
          siteMetricsCache={siteMetricsCache}
          linkMetricsCache={linkMetricsCache}
          metricsRefreshRate={metricsRefreshRate}
          onMetricsRefreshRateChange={onMetricsRefreshRateChange}
          onRefreshMetrics={onRefreshMetrics}
          metricsLoading={metricsLoading}
          collapsibleDetail
          hideInfraToggles
        />
      ) : subView === 'calendar' ? (
        <ResourceCalendar sites={sites} slices={slices} />
      ) : subView === 'resources' ? (
        <ResourcesPanel sites={sites} facilityPorts={facilityPorts} infraLoading={infraLoading} />
      ) : null}
    </TestbedViewShell>
  );
}

function ResourcesPanel({ sites, facilityPorts, infraLoading }: { sites: SiteInfo[]; facilityPorts: FacilityPortInfo[]; infraLoading: boolean }) {
  const [category, setCategory] = useState<'sites' | 'facility-ports'>('sites');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div className="resource-category-bar">
        <button className={`resource-category-btn${category === 'sites' ? ' active' : ''}`} onClick={() => setCategory('sites')}>Sites &amp; Hosts</button>
        <button className={`resource-category-btn${category === 'facility-ports' ? ' active' : ''}`} onClick={() => setCategory('facility-ports')}>Facility Ports</button>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {category === 'sites' ? (
          <ResourceBrowser sites={sites} />
        ) : (
          <FacilityPortsBrowser facilityPorts={facilityPorts} loading={infraLoading} />
        )}
      </div>
    </div>
  );
}
