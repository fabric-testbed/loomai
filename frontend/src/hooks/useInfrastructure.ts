import { useState, useCallback, useEffect, useRef } from 'react';
import * as api from '../api/client';
import type { SiteInfo, LinkInfo, FacilityPortInfo, SiteMetrics, LinkMetrics } from '../types/fabric';

/** Sites ignored from infrastructure views (cloud providers + AL2S). */
const IGNORED_SITES = new Set(['AWS', 'AZURE', 'GCP', 'OCI', 'AL2S']);

export interface UseInfrastructureOpts {
  addError: (msg: string) => void;
  setStatusMessage: (msg: string) => void;
  /** Currently selected graph element — used by refreshMetrics and auto-refresh interval. */
  selectedElement: Record<string, string> | null;
}

export interface UseInfrastructureReturn {
  infraSites: SiteInfo[];
  infraLinks: LinkInfo[];
  infraFacilityPorts: FacilityPortInfo[];
  infraLoading: boolean;
  infraLoaded: boolean;
  siteMetricsCache: Record<string, SiteMetrics>;
  linkMetricsCache: Record<string, LinkMetrics>;
  metricsRefreshRate: number;
  setMetricsRefreshRate: React.Dispatch<React.SetStateAction<number>>;
  metricsLoading: boolean;
  refreshInfrastructure: () => Promise<void>;
  refreshMetrics: () => Promise<void>;
  refreshInfrastructureAndMark: () => Promise<void>;
}

export function useInfrastructure(opts: UseInfrastructureOpts): UseInfrastructureReturn {
  const { addError, setStatusMessage, selectedElement } = opts;

  // --- State ---
  const [infraSites, setInfraSites] = useState<SiteInfo[]>([]);
  const [infraLinks, setInfraLinks] = useState<LinkInfo[]>([]);
  const [infraFacilityPorts, setInfraFacilityPorts] = useState<FacilityPortInfo[]>([]);
  const [infraLoading, setInfraLoading] = useState(false);
  const [infraLoaded, setInfraLoaded] = useState(false);
  const [siteMetricsCache, setSiteMetricsCache] = useState<Record<string, SiteMetrics>>({});
  const [linkMetricsCache, setLinkMetricsCache] = useState<Record<string, LinkMetrics>>({});
  const [metricsRefreshRate, setMetricsRefreshRate] = useState(0); // 0 = manual
  const [metricsLoading, setMetricsLoading] = useState(false);

  // --- Callbacks ---

  const refreshInfrastructure = useCallback(async () => {
    setInfraLoading(true);
    setStatusMessage('Loading sites and links...');
    try {
      const [allSites, links, facilityPorts] = await Promise.all([api.listSites(), api.listLinks(), api.listFacilityPorts().catch(() => [] as FacilityPortInfo[])]);
      const filteredSites = allSites.filter((s) => !IGNORED_SITES.has(s.name) && s.lat !== 0 && s.lon !== 0);
      setInfraSites(filteredSites);
      setInfraLinks(links);
      setInfraFacilityPorts(facilityPorts);

      setStatusMessage('Loading metrics...');
      // Refresh all site metrics in parallel
      await Promise.allSettled(filteredSites.map((s) => api.getSiteMetrics(s.name)))
        .then((results) => {
          const cache: Record<string, SiteMetrics> = {};
          results.forEach((r, i) => {
            if (r.status === 'fulfilled') {
              cache[filteredSites[i].name] = r.value;
            }
          });
          setSiteMetricsCache((prev) => ({ ...prev, ...cache }));
        });

      // Refresh all link metrics in parallel
      await Promise.allSettled(links.map((l) => api.getLinkMetrics(l.site_a, l.site_b)))
        .then((results) => {
          const cache: Record<string, any> = {};
          results.forEach((r, i) => {
            if (r.status === 'fulfilled') {
              const key = `${links[i].site_a}-${links[i].site_b}`;
              cache[key] = r.value;
            }
          });
          setLinkMetricsCache((prev) => ({ ...prev, ...cache }));
        });
    } catch (e: any) {
      addError(e.message);
    } finally {
      setInfraLoading(false);
      setStatusMessage('');
    }
  }, [addError, setStatusMessage]);

  // --- Refresh metrics for currently selected element ---
  const refreshMetrics = useCallback(async () => {
    if (!selectedElement) return;
    const type = selectedElement.element_type;
    if (type === 'site') {
      const siteName = selectedElement.name;
      setMetricsLoading(true);
      setStatusMessage(`Refreshing metrics for ${siteName}...`);
      try {
        const m = await api.getSiteMetrics(siteName);
        setSiteMetricsCache((prev) => ({ ...prev, [siteName]: m }));
      } catch (e: any) {
        addError(e.message);
      } finally {
        setMetricsLoading(false);
        setStatusMessage('');
      }
    } else if (type === 'infra_link') {
      const key = `${selectedElement.site_a}-${selectedElement.site_b}`;
      setMetricsLoading(true);
      setStatusMessage('Refreshing link metrics...');
      try {
        const m = await api.getLinkMetrics(selectedElement.site_a, selectedElement.site_b);
        setLinkMetricsCache((prev) => ({ ...prev, [key]: m }));
      } catch (e: any) {
        addError(e.message);
      } finally {
        setMetricsLoading(false);
        setStatusMessage('');
      }
    }
  }, [selectedElement, addError, setStatusMessage]);

  const refreshInfrastructureAndMark = useCallback(async () => {
    await refreshInfrastructure();
    setInfraLoaded(true);
  }, [refreshInfrastructure]);

  // --- Auto-refresh interval for metrics ---
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (metricsRefreshRate > 0 && selectedElement) {
      const type = selectedElement.element_type;
      if (type === 'site' || type === 'infra_link') {
        intervalRef.current = setInterval(refreshMetrics, metricsRefreshRate * 1000);
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [metricsRefreshRate, selectedElement, refreshMetrics]);

  return {
    infraSites,
    infraLinks,
    infraFacilityPorts,
    infraLoading,
    infraLoaded,
    siteMetricsCache,
    linkMetricsCache,
    metricsRefreshRate,
    setMetricsRefreshRate,
    metricsLoading,
    refreshInfrastructure,
    refreshMetrics,
    refreshInfrastructureAndMark,
  };
}
