'use client';
import GeoView from './GeoView';
import ResourceBrowser from './ResourceBrowser';
import '../styles/infrastructure-view.css';
import type { SiteInfo, LinkInfo, SiteMetrics, LinkMetrics } from '../types/fabric';

type InfraSubView = 'map' | 'browse';

interface InfrastructureViewProps {
  subView: InfraSubView;
  onSubViewChange: (sv: InfraSubView) => void;
  sites: SiteInfo[];
  links: LinkInfo[];
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
}

const SUB_VIEWS: Array<{ key: InfraSubView; label: string }> = [
  { key: 'map', label: 'Map' },
  { key: 'browse', label: 'Browse' },
];

export default function InfrastructureView({ subView, onSubViewChange, sites, links, linksLoading, siteMetricsCache, linkMetricsCache, metricsRefreshRate, onMetricsRefreshRateChange, onRefreshMetrics, metricsLoading, selectedElement, onNodeClick, infraLoading, onRefreshInfrastructure }: InfrastructureViewProps) {
  return (
    <div className="infra-view">
      <div className="infra-subtabs">
        {SUB_VIEWS.map((sv) => (
          <button
            key={sv.key}
            className={`infra-subtab ${subView === sv.key ? 'active' : ''}`}
            onClick={() => onSubViewChange(sv.key)}
          >
            {sv.label}
          </button>
        ))}
        <button
          className="infra-refresh-btn"
          onClick={onRefreshInfrastructure}
          disabled={infraLoading}
          title="Refresh sites, links, and metrics"
        >
          {infraLoading ? 'Updating...' : 'Update Resources'}
        </button>
      </div>
      <div className="infra-content">
        {subView === 'map' ? (
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
        ) : (
          <ResourceBrowser sites={sites} />
        )}
      </div>
    </div>
  );
}
