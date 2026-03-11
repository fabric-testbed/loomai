'use client';
import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import TitleBar from './components/TitleBar';
import Toolbar from './components/Toolbar';
import CytoscapeGraph from './components/CytoscapeGraph';
import type { ContextMenuAction } from './components/CytoscapeGraph';
import SliverView from './components/SliverView';
import AllSliversView from './components/AllSliversView';
import EditorPanel from './components/EditorPanel';
import LibrariesPanel from './components/LibrariesPanel';
import LibrariesView from './components/LibrariesView';
import GeoView from './components/GeoView';
import BottomPanel from './components/BottomPanel';
import type { TerminalTab, RecipeConsoleLine, BootConsoleLine } from './components/BottomPanel';
import SideConsolePanel from './components/SideConsolePanel';
import StatusBar from './components/StatusBar';
import ConfigureView from './components/ConfigureView';
import FileTransferView from './components/FileTransferView';
import HelpView from './components/HelpView';
import ClientView from './components/ClientView';
import JupyterLabView from './components/JupyterLabView';
import AICompanionView from './components/AICompanionView';
import AIChatPanel from './components/AIChatPanel';
import LandingView from './components/LandingView';
import ArtifactEditorView from './components/ArtifactEditorView';
import SlicesView from './components/SlicesView';
import InfrastructureView from './components/InfrastructureView';
import type { ClientTarget } from './components/ClientView';
import HelpContextMenu from './components/HelpContextMenu';
import GuidedTour from './components/GuidedTour';
import { tours } from './data/tourSteps';
import * as api from './api/client';
import type { SliceSummary, SliceData, SiteInfo, LinkInfo, ComponentModel, SiteMetrics, LinkMetrics, ValidationIssue, ProjectInfo, VMTemplateSummary, BootConfig, RecipeSummary, FacilityPortInfo } from './types/fabric';

export default function App() {
  const [slices, setSlices] = useState<SliceSummary[]>([]);
  const [selectedSliceId, setSelectedSliceId] = useState('');
  const [sliceData, setSliceData] = useState<SliceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [bootConfigErrors, setBootConfigErrors] = useState<Array<{ node: string; type: string; id: string; detail: string }>>([]);
  // Per-node activity status shown in Slivers view (key=nodeName, value=status message or empty for ready)
  const [nodeActivity, setNodeActivity] = useState<Record<string, string>>({});
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [recipeConsole, setRecipeConsole] = useState<RecipeConsoleLine[]>([]);
  const [recipeRunning, setRecipeRunning] = useState(false);
  const [executingRecipeName, setExecutingRecipeName] = useState<string | null>(null);
  const [sliceBootLogs, setSliceBootLogs] = useState<Record<string, BootConsoleLine[]>>({});
  const [sliceBootRunning, setSliceBootRunning] = useState<Record<string, boolean>>({});
  const [sliceBootNodeStatus, setSliceBootNodeStatus] = useState<Record<string, Record<string, 'pending' | 'running' | 'done' | 'error'>>>({});
  type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai';
  type SlicesSubView = 'topology' | 'table' | 'storage' | 'map' | 'apps';
  type InfraSubView = 'map' | 'browse' | 'facility-ports';
  const [currentView, setCurrentView] = useState<TopView>('landing');
  const [slicesSubView, setSlicesSubView] = useState<SlicesSubView>('topology');
  const [infraSubView, setInfraSubView] = useState<InfraSubView>('browse');
  const [editingArtifactDirName, setEditingArtifactDirName] = useState('');
  const [jupyterPath, setJupyterPath] = useState<string | undefined>(undefined);
  const [selectedAiTool, setSelectedAiTool] = useState<string | null>(null);
  const [enabledAiTools, setEnabledAiTools] = useState<Record<string, boolean>>({});
  const [clientTarget, setClientTarget] = useState<ClientTarget | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [configStatus, setConfigStatus] = useState<import('./types/fabric').ConfigStatus | null>(null);
  const [userUuid, setUserUuid] = useState<string>('');
  const [layout, setLayout] = useState('dagre');
  const [selectedElement, setSelectedElement] = useState<Record<string, string> | null>(null);
  const [listLoaded, setListLoaded] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark');
  // Derived display name from selected ID
  const selectedSliceName = useMemo(() => {
    if (!selectedSliceId) return '';
    const entry = slices.find(s => s.id === selectedSliceId);
    if (entry) return entry.name;
    // Fallback: check sliceData (covers the gap before slice list refreshes)
    if (sliceData?.name && sliceData?.id === selectedSliceId) return sliceData.name;
    return '';
  }, [slices, selectedSliceId, sliceData]);
  // --- Draggable panel layout ---
  type PanelId = 'editor' | 'template' | 'chat' | 'console';
  type PanelLayoutEntry = { side: 'left' | 'right'; collapsed: boolean; width: number; order: number };
  type PanelLayoutMap = Record<PanelId, PanelLayoutEntry>;

  const PANEL_ICONS: Record<PanelId, string> = { editor: '\u270E', template: '\u29C9', chat: '\u2728', console: '\u2756' };
  const PANEL_LABELS: Record<PanelId, string> = { editor: 'Editor', template: 'Artifacts', chat: 'LoomAI', console: 'Console' };
  const PANEL_IDS: PanelId[] = ['editor', 'template', 'chat', 'console'];
  const DEFAULT_PANEL_WIDTH = 280;
  const MIN_PANEL_WIDTH = 180;

  const defaultLayout: PanelLayoutMap = {
    editor: { side: 'left', collapsed: false, width: DEFAULT_PANEL_WIDTH, order: 0 },
    template: { side: 'right', collapsed: false, width: DEFAULT_PANEL_WIDTH, order: 0 },
    chat: { side: 'right', collapsed: true, width: 320, order: 1 },
    console: { side: 'right', collapsed: true, width: 380, order: 2 },
  };

  const [panelLayout, setPanelLayout] = useState<PanelLayoutMap>(() => {
    try {
      const saved = localStorage.getItem('fabric-panel-layout');
      if (saved) {
        const parsed = JSON.parse(saved);
        // Migrate old format (no width field)
        for (const id of PANEL_IDS) {
          if (parsed[id] && parsed[id].width === undefined) {
            parsed[id].width = DEFAULT_PANEL_WIDTH;
          }
        }
        // Clean up removed panels
        delete parsed['vm-template'];
        delete parsed.project;
        delete parsed.detail;
        // Ensure all current panels exist with defaults
        for (const id of PANEL_IDS) {
          if (!parsed[id]) {
            parsed[id] = { ...defaultLayout[id] };
          }
          if (parsed[id].width === undefined) parsed[id].width = DEFAULT_PANEL_WIDTH;
          if (parsed[id].order === undefined) parsed[id].order = defaultLayout[id].order;
        }
        return parsed;
      }
    } catch {}
    return defaultLayout;
  });

  const [draggingPanel, setDraggingPanel] = useState<PanelId | null>(null);

  // Resize state
  const resizeRef = useRef<{ panelId: PanelId; startX: number; startWidth: number; growRight: boolean } | null>(null);
  // Keep a ref to the latest panelLayout so the resize mousedown handler never reads stale state
  const panelLayoutRef = useRef(panelLayout);
  panelLayoutRef.current = panelLayout;

  useEffect(() => {
    localStorage.setItem('fabric-panel-layout', JSON.stringify(panelLayout));
  }, [panelLayout]);

  const toggleCollapse = useCallback((id: PanelId) => {
    setPanelLayout(prev => ({ ...prev, [id]: { ...prev[id], collapsed: !prev[id].collapsed } }));
  }, []);

  const movePanel = useCallback((id: PanelId, side: 'left' | 'right') => {
    setPanelLayout(prev => {
      // Place the moved panel at the end of the target side
      const maxOrder = Math.max(-1, ...PANEL_IDS.filter(p => p !== id && prev[p].side === side).map(p => prev[p].order));
      return { ...prev, [id]: { ...prev[id], side, collapsed: false, order: maxOrder + 1 } };
    });
  }, []);

  /** Move a panel to a specific position (before `beforeId`) on a side. */
  const movePanelToPosition = useCallback((id: PanelId, side: 'left' | 'right', beforeId: PanelId | null) => {
    setPanelLayout(prev => {
      const next = { ...prev };
      // Get panels on the target side sorted by order, excluding the dragged panel
      const sidePanels = PANEL_IDS
        .filter(p => p !== id && next[p].side === side)
        .sort((a, b) => next[a].order - next[b].order);

      // Insert the dragged panel at the right position
      const insertIdx = beforeId ? sidePanels.indexOf(beforeId) : sidePanels.length;
      const finalIdx = insertIdx === -1 ? sidePanels.length : insertIdx;
      sidePanels.splice(finalIdx, 0, id);

      // Reassign orders
      sidePanels.forEach((p, i) => {
        next[p] = { ...next[p], side, order: i, collapsed: p === id ? false : next[p].collapsed };
      });

      return next;
    });
  }, []);

  // Stable callback — reads width from ref, so no stale closure issues
  const startResize = useCallback((panelId: PanelId, growRight: boolean, e: React.MouseEvent) => {
    e.preventDefault();
    const currentWidth = panelLayoutRef.current[panelId].width;
    resizeRef.current = { panelId, startX: e.clientX, startWidth: currentWidth, growRight };
    const handle = e.currentTarget as HTMLElement;
    handle.classList.add('active');

    const onMouseMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      const { panelId: pid, startX, startWidth, growRight: gr } = resizeRef.current;
      const delta = gr ? ev.clientX - startX : startX - ev.clientX;
      const newWidth = Math.max(MIN_PANEL_WIDTH, startWidth + delta);
      setPanelLayout(prev => ({ ...prev, [pid]: { ...prev[pid], width: newWidth } }));
    };
    const onMouseUp = () => {
      resizeRef.current = null;
      handle.classList.remove('active');
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []); // stable — no deps needed
  const [terminalTabs, setTerminalTabs] = useState<TerminalTab[]>([]);
  const [terminalIdCounter, setTerminalIdCounter] = useState(0);
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [validationValid, setValidationValid] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [hiddenProjects, setHiddenProjects] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem('fabric-hidden-projects');
      if (saved) return new Set(JSON.parse(saved));
    } catch {}
    return new Set();
  });
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpSection, setHelpSection] = useState<string | undefined>(undefined);
  const [statusMessage, setStatusMessage] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(() => localStorage.getItem('auto-refresh') !== 'off');
  const autoRefreshRef = useRef(autoRefresh);
  autoRefreshRef.current = autoRefresh;
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [consoleFullWidth, setConsoleFullWidth] = useState(false);
  const [consoleExpanded, setConsoleExpanded] = useState(false);
  const [consoleHeight, setConsoleHeight] = useState(260);
  const [openBootLogSlices, setOpenBootLogSlices] = useState<string[]>([]);
  const [activeRuns, setActiveRuns] = useState<api.BackgroundRun[]>([]);
  // Side console panel state (tabs tracked here, layout managed by panel system)
  const [sideConsoleTabs, setSideConsoleTabs] = useState<string[]>([]);
  const [dropIndicator, setDropIndicator] = useState<{ panelId: PanelId; edge: 'left' | 'right' } | null>(null);

  // Persist hidden projects to localStorage
  useEffect(() => {
    localStorage.setItem('fabric-hidden-projects', JSON.stringify([...hiddenProjects]));
  }, [hiddenProjects]);

  // Visible projects = all projects minus hidden ones
  const visibleProjects = projects.filter(p => !hiddenProjects.has(p.uuid));

  // Track previous slice states for build log state-transition messages
  const prevSliceStatesRef = useRef<Record<string, string>>({});

  // Append a single line to a slice's build log
  const appendBuildLog = useCallback((sliceName: string, line: BootConsoleLine) => {
    setSliceBootLogs(prev => ({
      ...prev,
      [sliceName]: [...(prev[sliceName] || []), line],
    }));
  }, []);

  // --- Global cache: infrastructure ---
  const [infraSites, setInfraSites] = useState<SiteInfo[]>([]);
  const [infraLinks, setInfraLinks] = useState<LinkInfo[]>([]);
  const [infraFacilityPorts, setInfraFacilityPorts] = useState<FacilityPortInfo[]>([]);
  const [infraLoading, setInfraLoading] = useState(false);

  // --- Global cache: static data (fetched once on mount) ---
  const [images, setImages] = useState<string[]>([]);
  const [componentModels, setComponentModels] = useState<ComponentModel[]>([]);
  const [vmTemplates, setVmTemplates] = useState<VMTemplateSummary[]>([]);

  // --- Guided tour (multi-tour) ---
  const [activeTourId, setActiveTourId] = useState<string | null>(null);
  const [tourStep, setTourStep] = useState(0);

  // --- Global cache: metrics ---
  const [siteMetricsCache, setSiteMetricsCache] = useState<Record<string, SiteMetrics>>({});
  const [linkMetricsCache, setLinkMetricsCache] = useState<Record<string, LinkMetrics>>({});
  const [metricsRefreshRate, setMetricsRefreshRate] = useState(0); // 0 = manual
  const [metricsLoading, setMetricsLoading] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    // Sync JupyterLab theme whenever dark mode changes (fire-and-forget)
    api.setJupyterTheme(dark ? 'dark' : 'light').catch(() => {});
  }, [dark]);

  // Fetch static data once on mount (images + component models + VM templates)
  useEffect(() => {
    api.listImages().then(setImages).catch(() => {});
    api.listComponentModels().then(setComponentModels).catch(() => {});
    api.listVmTemplates().then(setVmTemplates).catch(() => {});
    api.getAiTools().then(setEnabledAiTools).catch(() => {});
  }, []);

  const refreshVmTemplates = useCallback(() => {
    api.listVmTemplates().then(setVmTemplates).catch(() => {});
  }, []);

  // Fetch recipes on mount
  useEffect(() => {
    api.listRecipes().then(setRecipes).catch(() => {});
  }, []);

  // Recipe execution handler (streams SSE to bottom panel console)
  const handleExecuteRecipe = useCallback(async (recipeDirName: string, nodeName: string) => {
    if (!selectedSliceId) return;
    setRecipeRunning(true);
    setExecutingRecipeName(recipeDirName);
    setRecipeConsole([{ type: 'step', message: `Starting recipe "${recipeDirName}" on ${nodeName}...` }]);
    try {
      await api.executeRecipeStream(recipeDirName, selectedSliceId, nodeName, (evt) => {
        if (evt.event === 'done') {
          setRecipeConsole(prev => [...prev, {
            type: evt.status === 'ok' ? 'step' : 'error',
            message: `Done — ${evt.status}`
          }]);
          setRecipeRunning(false);
          setExecutingRecipeName(null);
        } else {
          setRecipeConsole(prev => [...prev, { type: evt.event, message: evt.message || '' }]);
        }
      });
    } catch (e: any) {
      setRecipeConsole(prev => [...prev, { type: 'error', message: e.message }]);
      setRecipeRunning(false);
      setExecutingRecipeName(null);
    }
  }, [selectedSliceId]);

  // Boot config streaming handler — per-slice, supports concurrent runs across multiple slices
  // When calledFromBuildLog=true, doesn't reset logs or touch sliceBootRunning (caller manages lifecycle)
  const handleRunBootConfigStream = useCallback(async (sliceNameOverride?: string, calledFromBuildLog?: boolean) => {
    const target = sliceNameOverride || selectedSliceId;
    console.log(`[bootConfigStream] called with override=${sliceNameOverride} selected=${selectedSliceName} target=${target} fromBuild=${calledFromBuildLog}`);
    if (!target) return;

    if (!calledFromBuildLog) {
      // Standalone invocation — manage lifecycle ourselves
      setSliceBootRunning(prev => ({ ...prev, [target]: true }));
      setSliceBootLogs(prev => ({
        ...prev,
        [target]: [{ type: 'step', message: `Starting boot config for slice "${target}" (waiting for SSH)...` }],
      }));
    } else {
      // Called from build log — just append a separator
      appendBuildLog(target, { type: 'build', message: 'Running boot config (SSH, uploads, commands)...' });
    }

    const appendLine = (line: BootConsoleLine) => {
      setSliceBootLogs(prev => ({
        ...prev,
        [target]: [...(prev[target] || []), line],
      }));
    };

    try {
      await api.executeBootConfigStream(target, (evt) => {
        if (evt.event === 'done') {
          appendLine({ type: evt.status === 'ok' ? 'step' : 'error', message: evt.message || `Done — ${evt.status}` });
          if (!calledFromBuildLog) {
            setSliceBootRunning(prev => ({ ...prev, [target]: false }));
          }
          setSliceBootNodeStatus(prev => {
            const nodeStatus = { ...(prev[target] || {}) };
            for (const k of Object.keys(nodeStatus)) {
              if (nodeStatus[k] === 'running' || nodeStatus[k] === 'pending') nodeStatus[k] = 'done';
            }
            return { ...prev, [target]: nodeStatus };
          });
        } else if (evt.event === 'node' && evt.node) {
          if (evt.status === 'ok') {
            setSliceBootNodeStatus(prev => ({ ...prev, [target]: { ...(prev[target] || {}), [evt.node!]: 'done' } }));
          } else {
            setSliceBootNodeStatus(prev => ({ ...prev, [target]: { ...(prev[target] || {}), [evt.node!]: 'running' } }));
          }
          appendLine({ type: evt.event, message: evt.message || '' });
        } else if (evt.event === 'error' && evt.node) {
          setSliceBootNodeStatus(prev => ({ ...prev, [target]: { ...(prev[target] || {}), [evt.node!]: 'error' } }));
          appendLine({ type: evt.event, message: evt.message || '' });
        } else {
          appendLine({ type: evt.event, message: evt.message || '' });
        }
      });
    } catch (e: any) {
      appendLine({ type: 'error', message: e.message });
      if (!calledFromBuildLog) {
        setSliceBootRunning(prev => ({ ...prev, [target]: false }));
      }
    }
  }, [selectedSliceId, appendBuildLog]);

  // Check config status on mount
  useEffect(() => {
    api.getConfig().then((cfg) => {
      setIsConfigured(cfg.configured);
      setConfigStatus(cfg);
      if (cfg.token_info?.uuid) setUserUuid(cfg.token_info.uuid);
      // Set project ID from config as initial value
      if (cfg.project_id) {
        setProjectId(cfg.project_id);
        // Use JWT projects as initial fallback until Core API responds
        if (cfg.token_info?.projects) {
          setProjects(cfg.token_info.projects);
          const proj = cfg.token_info.projects.find((p) => p.uuid === cfg.project_id);
          if (proj) setProjectName(proj.name);
        }
      }
      // Check if token is valid and not expired
      const tokenExpired = cfg.token_info?.exp
        ? cfg.token_info.exp * 1000 < Date.now()
        : !cfg.has_token;
      if (!cfg.configured || tokenExpired) {
        if (tokenExpired && cfg.has_token) {
          setErrors(prev => [...prev, 'Your FABRIC token has expired. Please update it in Settings.']);
        }
      } else {
        // Token is good — auto-load slices and resources
        refreshSliceList();
        refreshInfrastructureAndMark();
        // Fetch full project list from Core API (replaces JWT subset)
        api.listUserProjects().then((resp) => {
          setProjects(resp.projects);
          // Only update project if we don't already have one set from getConfig,
          // or if the backend reports a different active project (explicit switch).
          if (resp.active_project_id) {
            setProjectId(prev => {
              if (prev && prev === resp.active_project_id) return prev; // no change
              return resp.active_project_id;
            });
            const proj = resp.projects.find((p) => p.uuid === resp.active_project_id);
            if (proj) setProjectName(proj.name);
          }
          // Reconcile all known slices with their projects in the background,
          // then refresh the slice list so filtering is accurate
          api.reconcileProjects().then(() => {
            refreshSliceList();
          }).catch(() => {});
        }).catch(() => {
          // Core API unavailable — keep JWT projects as fallback
        });
      }
    }).catch(() => {
      setIsConfigured(false);
    });

    // Handle OAuth callback
    const params = new URLSearchParams(window.location.search);
    if (params.get('configLogin') === 'success') {
      setSettingsOpen(true);
      window.history.replaceState({}, '', '/');
    }
  }, []);

  const activeTourSteps = activeTourId ? (tours[activeTourId]?.steps ?? []) : [];

  const dismissTour = useCallback(() => {
    // Only set localStorage dismiss for getting-started tour
    if (activeTourId === 'getting-started') {
      localStorage.setItem('fabric-tour-dismissed', 'true');
    }
    setActiveTourId(null);
    setTourStep(0);
  }, [activeTourId]);

  const closeTour = useCallback(() => {
    setActiveTourId(null);
    setTourStep(0);
  }, []);

  const startTour = useCallback((tourId: string) => {
    if (tourId === 'getting-started') {
      localStorage.removeItem('fabric-tour-dismissed');
    }
    setTourStep(0);
    setActiveTourId(tourId);
    setHelpOpen(false);
    setSettingsOpen(false);
  }, []);

  // Poll config status during tour steps that check config-based completions
  const CONFIG_CHECKS = new Set(['has_token', 'has_bastion_key', 'has_slice_key', 'configured']);
  useEffect(() => {
    if (!activeTourId) return;
    const tourDef = tours[activeTourId];
    if (!tourDef) return;
    const currentStep = tourDef.steps[tourStep];
    if (!currentStep?.completionCheck || !CONFIG_CHECKS.has(currentStep.completionCheck)) return;
    const interval = setInterval(async () => {
      try {
        const cfg = await api.getConfig();
        setConfigStatus(cfg);
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(interval);
  }, [activeTourId, tourStep]);

  // Compute tourContext from app state for interactive tour completion checks
  const tourContext = useMemo<Record<string, boolean>>(() => ({
    // Config (polled from backend)
    has_token: !!configStatus?.has_token,
    has_bastion_key: !!configStatus?.has_bastion_key,
    has_slice_key: !!configStatus?.has_slice_key,
    configured: !!configStatus?.configured,
    // Slices
    has_slices: slices.length > 0,
    slice_loaded: !!sliceData,
    has_nodes: (sliceData?.nodes?.length ?? 0) > 0,
    has_networks: (sliceData?.networks?.length ?? 0) > 0,
    has_components: !!(sliceData?.nodes?.some(n => n.components && n.components.length > 0)),
    node_selected: selectedElement?.element_type === 'node',
    // Resources
    resources_loaded: infraSites.length > 0,
    // AI
    ai_tool_selected: !!selectedAiTool,
  }), [configStatus, slices, sliceData, selectedElement, infraSites, selectedAiTool]);

  // --- Refresh infrastructure (sites + links) + metrics ---
  const refreshInfrastructure = useCallback(async () => {
    setInfraLoading(true);
    setStatusMessage('Loading sites and links...');
    const IGNORED = new Set(['AWS', 'AZURE', 'GCP', 'OCI', 'AL2S']);
    try {
      const [allSites, links, facilityPorts] = await Promise.all([api.listSites(), api.listLinks(), api.listFacilityPorts().catch(() => [] as FacilityPortInfo[])]);
      const filteredSites = allSites.filter((s) => !IGNORED.has(s.name) && s.lat !== 0 && s.lon !== 0);
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
  }, []);

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
  }, [selectedElement]);

  // Infrastructure loaded flag (no auto-fetch on startup)
  const [infraLoaded, setInfraLoaded] = useState(false);
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

  // Validate slice whenever sliceData changes
  const runValidation = useCallback(async (name: string) => {
    try {
      const result = await api.validateSlice(name);
      setValidationIssues(result.issues);
      setValidationValid(result.valid);
    } catch {
      // If validation fails, assume invalid
      setValidationIssues([]);
      setValidationValid(false);
    }
  }, []);

  // Helper: protect slices being deleted from having their state overwritten by
  // stale FABRIC data. Mutates the list in-place: if a slice is in the deleting
  // set and FABRIC still reports a non-terminal state, force it to "Closing".
  const protectDeletingSlices = useCallback((list: SliceSummary[]) => {
    const DELETING_TIMEOUT = 120_000;
    const now = Date.now();
    for (const [key, ts] of deletingSlicesRef.current.entries()) {
      if (now - ts > DELETING_TIMEOUT) {
        deletingSlicesRef.current.delete(key);
        continue;
      }
      const entry = list.find(s => s.id === key || s.name === key);
      if (entry) {
        if (entry.state === 'Dead' || entry.state === 'Closing') {
          deletingSlicesRef.current.delete(key);
        } else {
          entry.state = 'Closing';
        }
      }
    }
  }, []);

  // Helper: after receiving a fresh slice list from FABRIC, update sliceData.state
  // if the current slice's state in the list differs. Ensures the toolbar badge
  // stays current even when only the list is refreshed (not the full slice).
  const syncStateFromList = useCallback((list: SliceSummary[]) => {
    setSliceData(prev => {
      if (!prev?.name) return prev;
      const entry = list.find(s => s.name === prev.name);
      if (!entry || !entry.state || entry.state === prev.state) return prev;
      return { ...prev, state: entry.state };
    });
  }, []);

  // --- Auto-refresh polling — refreshes list until all slices are stable/terminal ---
  const POLL_STATES = new Set(['Configuring', 'Ticketed', 'Nascent', 'ModifyOK', 'ModifyError']);
  const STABLE_STATES = new Set(['StableOK', 'Active']);
  const TERMINAL_STATES_SET = new Set(['Dead', 'Closing', 'StableError']);
  const POLL_INTERVAL = 15000; // 15 seconds

  // Track which slices have already had boot configs auto-executed
  const bootConfigRanRef = useRef<Set<string>>(new Set());

  // Track slices being deleted — prevent polling from overwriting their state
  // back to StableOK before FABRIC orchestrator processes the delete.
  // Maps slice id/name → timestamp when delete was initiated.
  const deletingSlicesRef = useRef<Map<string, number>>(new Map());

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const selectedSliceRef = useRef(selectedSliceId);
  selectedSliceRef.current = selectedSliceId;

  const projectNameRef = useRef(projectName);
  projectNameRef.current = projectName;

  // Helper to add errors with project/slice context prefix
  const addError = useCallback((msg: string, sliceName?: string) => {
    const parts: string[] = [];
    if (projectNameRef.current) parts.push(projectNameRef.current);
    if (sliceName || selectedSliceRef.current) parts.push(sliceName || selectedSliceRef.current);
    const prefix = parts.length > 0 ? `[${parts.join(' / ')}] ` : '';
    setErrors(prev => [...prev, prefix + msg]);
  }, []);

  // Run boot configs per-node with activity tracking
  const runBootConfigsPerNode = useCallback(async (sliceName: string, nodeNames: string[]) => {
    if (nodeNames.length === 0) return;
    setNodeActivity(prev => {
      const next = { ...prev };
      for (const n of nodeNames) next[n] = 'Boot config pending...';
      return next;
    });
    const bootErrors: Array<{ node: string; type: string; id: string; detail: string }> = [];
    for (const nodeName of nodeNames) {
      setNodeActivity(prev => ({ ...prev, [nodeName]: 'Running boot config...' }));
      try {
        const results = await api.executeBootConfig(sliceName, nodeName);
        let hasError = false;
        for (const r of results) {
          if (r.status === 'error') {
            hasError = true;
            bootErrors.push({ node: nodeName, type: r.type, id: r.id, detail: r.detail || 'Unknown error' });
          }
        }
        setNodeActivity(prev => ({ ...prev, [nodeName]: hasError ? 'Boot config failed' : '' }));
      } catch (e: any) {
        setNodeActivity(prev => ({ ...prev, [nodeName]: 'Boot config failed' }));
        bootErrors.push({ node: nodeName, type: 'general', id: '', detail: e.message });
      }
    }
    if (bootErrors.length > 0) {
      setBootConfigErrors(bootErrors);
    }
    // Clear error statuses after a delay
    setTimeout(() => setNodeActivity(prev => {
      const next = { ...prev };
      for (const n of nodeNames) { if (next[n] === 'Boot config failed') delete next[n]; }
      return next;
    }), 8000);
    return bootErrors;
  }, []);

  const startPolling = useCallback(() => {
    console.log(`[startPolling] called, autoRefresh=${autoRefreshRef.current}`);
    stopPolling();
    if (!autoRefreshRef.current) return;

    pollingRef.current = setInterval(async () => {
      if (!autoRefreshRef.current) { stopPolling(); return; }

      try {
        // Refresh slice list
        const list = await api.listSlices();
        protectDeletingSlices(list);
        setSlices(list);
        setListLoaded(true);
        syncStateFromList(list);

        // Log state transitions for slices with active build logs
        for (const entry of list) {
          const prev = prevSliceStatesRef.current[entry.name];
          if (prev && prev !== entry.state) {
            // Only log transitions for slices that have an active build
            appendBuildLog(entry.name, { type: 'build', message: `State: ${prev} \u2192 ${entry.state}` });
          }
          prevSliceStatesRef.current[entry.name] = entry.state;
        }

        // Also refresh the currently selected slice if it's in a transitional state
        const currentName = selectedSliceRef.current;
        const currentEntry = currentName ? list.find(s => s.name === currentName) : null;
        if (currentName && currentEntry && POLL_STATES.has(currentEntry.state)) {
          try {
            const data = await api.refreshSlice(currentName);
            setSliceData(data);
          } catch { /* next poll will retry */ }
        }

        // Auto-run boot configs for slices that just reached StableOK
        // Runs for any slice the webui sees transition to stable for the first time
        for (const entry of list) {
          console.log(`[poll] Slice "${entry.name}" state=${entry.state} bootConfigRan=${bootConfigRanRef.current.has(entry.name)}`);
          if ((entry.state === 'StableOK' || entry.state === 'Active') && !bootConfigRanRef.current.has(entry.name)) {
            console.log(`[poll] Auto-running boot config for "${entry.name}"`);
            bootConfigRanRef.current.add(entry.name);
            appendBuildLog(entry.name, { type: 'build', message: `Slice is ready (${entry.state})` });
            // Refresh slice data if it's the currently selected slice — use
            // refreshSlice (POST) to pull fresh sliver states from FABRIC
            if (entry.name === currentName) {
              try {
                const data = await api.refreshSlice(currentName);
                setSliceData(data);
              } catch { /* ignore */ }
            }
            // Fire and forget — each slice configures independently in parallel
            const sliceName = entry.name;
            (async () => {
              // Get node names for per-node progress tracking
              let sliceNodeNames: string[] = [];
              try {
                const sd = await api.refreshSlice(sliceName);
                sliceNodeNames = sd.nodes.map((n: any) => n.name);
                if (sliceName === currentName) setSliceData(sd);
              } catch { /* fallback */ }

              // Run FABlib's native post_boot_config (assigns IPs/hostnames)
              appendBuildLog(sliceName, { type: 'build', message: 'Running FABlib post-boot config (networking, routes, hostnames)...' });
              try {
                await api.runPostBootConfig(sliceName);
                appendBuildLog(sliceName, { type: 'build', message: 'FABlib post-boot config complete' });
              } catch (e: any) {
                appendBuildLog(sliceName, { type: 'error', message: `FABlib post-boot config failed: ${e.message}` });
                addError(`FABlib post_boot_config failed for ${sliceName}: ${e.message}`);
              }

              // Run boot configs via streaming endpoint (includes deploy.sh + SSH readiness)
              await handleRunBootConfigStream(sliceName, true);

              // Mark build complete
              appendBuildLog(sliceName, { type: 'build', message: '\u2713 Build complete' });
              setSliceBootRunning(prev => ({ ...prev, [sliceName]: false }));
            })();
          }
        }

        // Check if ALL slices are in a stable or terminal state — if so, stop polling
        const allSettled = list.every(s => {
          const st = s.state || '';
          return st === 'Draft' || STABLE_STATES.has(st) || TERMINAL_STATES_SET.has(st);
        });
        if (allSettled) {
          console.log(`[poll] All slices settled, stopping polling`);
          stopPolling();
        }
      } catch {
        // Silently ignore polling errors — next poll will retry
      }
    }, POLL_INTERVAL);
  }, [stopPolling, syncStateFromList, handleRunBootConfigStream, appendBuildLog]);

  // Clean up polling on unmount
  useEffect(() => { return () => stopPolling(); }, [stopPolling]);

  // Refresh slice data when switching back to a slice-displaying view
  // so the user sees current data even if state changed while on another view.
  // Also restart polling if any slices are still transitional.
  useEffect(() => {
    if (currentView === 'slices') {
      if (selectedSliceId) {
        api.refreshSlice(selectedSliceId).then(data => {
          setSliceData(data);
        }).catch(() => {});
      }
      // Re-check slice list and restart polling if needed
      api.listSlices().then(list => {
        protectDeletingSlices(list);
        setSlices(list);
        syncStateFromList(list);
        const hasTransitional = list.some(s => POLL_STATES.has(s.state));
        if (hasTransitional && autoRefreshRef.current && !pollingRef.current) {
          startPolling();
        }
      }).catch(() => {});
    }
  }, [currentView, slicesSubView]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleAutoRefresh = useCallback(() => {
    setAutoRefresh(prev => {
      const next = !prev;
      localStorage.setItem('auto-refresh', next ? 'on' : 'off');
      if (!next) stopPolling();
      return next;
    });
  }, [stopPolling]);

  // Load slice list on first interaction or mount
  const refreshSliceList = useCallback(async () => {
    setLoading(true);
    setErrors([]);
    setStatusMessage('Refreshing slice list...');
    try {
      const list = await api.listSlices();
      protectDeletingSlices(list);
      setSlices(list);
      setListLoaded(true);

      // Pre-seed bootConfigRanRef with already-stable slices so we only
      // auto-run boot config for slices that *newly* transition to stable
      for (const s of list) {
        if (STABLE_STATES.has(s.state) || TERMINAL_STATES_SET.has(s.state)) {
          bootConfigRanRef.current.add(s.name);
        }
      }

      // If the currently selected slice changed state, reload it
      const currentName = selectedSliceRef.current;
      if (currentName) {
        const entry = list.find(s => s.name === currentName);
        if (entry) {
          syncStateFromList(list);
          // Reload slice data if it's not yet stable/terminal (state may have changed)
          if (POLL_STATES.has(entry.state)) {
            try {
              const data = await api.refreshSlice(currentName);
              setSliceData(data);
            } catch { /* ignore */ }
          }
        }
      } else {
        syncStateFromList(list);
      }

      // Start polling if any slices are in transitional states
      const hasTransitional = list.some(s => POLL_STATES.has(s.state));
      if (hasTransitional && autoRefreshRef.current) {
        startPolling();
      }
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [syncStateFromList, startPolling]);

  const handleProjectChange = useCallback(async (uuid: string) => {
    const proj = projects.find((p) => p.uuid === uuid);
    if (!proj) return;
    setStatusMessage('Switching project...');
    try {
      const result = await api.switchProject(uuid);
      setProjectId(uuid);
      setProjectName(proj.name);
      // Reset slice state and refresh
      setSliceData(null);
      setSelectedSliceId('');
      setSelectedElement(null);
      setSlices([]);
      setListLoaded(false);
      // If token couldn't be refreshed, open CM login in a new tab so the
      // user can get a project-scoped token with a refresh_token
      if (!result.token_refreshed && result.login_url) {
        window.open(result.login_url, '_blank');
        setErrors(prev => [...prev,
          'Your token needs to be updated for the new project. ' +
          'A login page has opened — copy the token and paste it in Settings.'
        ]);
        setSettingsOpen(true);
      }
      // Auto-load slices for the new project
      await refreshSliceList();
    } catch (e: any) {
      addError(e.message);
    } finally {
      setStatusMessage('');
    }
  }, [projects, refreshSliceList]);

  // No auto-load — user must click "Load Slices" first

  // When sliceData updates, push its state into the matching slices list entry
  // so the dropdown stays in sync with the loaded slice's current state.
  useEffect(() => {
    if (!sliceData?.name || !sliceData.state) return;
    const name = sliceData.name;
    const state = sliceData.state;
    const hasErrors = (sliceData.error_messages?.length ?? 0) > 0;
    setSlices(prev => {
      const idx = prev.findIndex(s => s.name === name);
      if (idx === -1) return prev;
      if (prev[idx].state === state && prev[idx].has_errors === hasErrors) return prev;
      const updated = [...prev];
      updated[idx] = { ...updated[idx], state, has_errors: hasErrors };
      return updated;
    });
  }, [sliceData?.name, sliceData?.state, sliceData?.error_messages]);

  // Helper: update slice data and re-validate
  const updateSliceAndValidate = useCallback((data: SliceData) => {
    setSliceData(data);
    if (data.name) {
      runValidation(data.name);
    }
  }, [runValidation]);


  // Submit handles both new slice creation and modifications to existing slices
  const handleSubmit = useCallback(async () => {
    if (!selectedSliceId) return;
    const sliceId = selectedSliceId;
    const name = selectedSliceName;
    setLoading(true);
    setStatusMessage('Submitting slice to FABRIC...');

    // Open build log tab with a fresh log
    setOpenBootLogSlices(prev => prev.includes(name) ? prev : [...prev, name]);
    setConsoleExpanded(true);
    setSliceBootRunning(prev => ({ ...prev, [name]: true }));
    setSliceBootLogs(prev => ({ ...prev, [name]: [] }));
    appendBuildLog(name, { type: 'build', message: 'Submitting slice to FABRIC...' });

    try {
      const data = await api.submitSlice(sliceId);
      if (data.id && data.id !== sliceId) setSelectedSliceId(data.id);
      setSliceData(data);
      setValidationIssues([]);
      setValidationValid(true);
      appendBuildLog(name, { type: 'build', message: `Slice submitted (state: ${data.state || 'unknown'})` });
      prevSliceStatesRef.current[name] = data.state || '';
      setStatusMessage('Submitted. Refreshing slice state...');
      let refreshedData = data;
      try {
        // Reload slice data to get updated state from FABRIC
        const refreshed = await api.refreshSlice(sliceId);
        refreshedData = refreshed;
        setSliceData(refreshed);
        runValidation(name);
        if (refreshed.state && refreshed.state !== data.state) {
          appendBuildLog(name, { type: 'build', message: `State: ${data.state || 'unknown'} \u2192 ${refreshed.state}` });
          prevSliceStatesRef.current[name] = refreshed.state;
        }
      } catch {}
      setStatusMessage('Refreshing slice list...');
      try {
        const list = await api.listSlices();
        setSlices(list);
        setListLoaded(true);
      } catch {}
      // If slice reached StableOK immediately, run boot configs now
      console.log(`[submit] refreshedData.state=${refreshedData.state}`);
      if (refreshedData.state === 'StableOK') {
        console.log(`[submit] StableOK immediate — running post-boot config`);
        bootConfigRanRef.current.add(name);
        appendBuildLog(name, { type: 'build', message: `Slice is ready (${refreshedData.state})` });
        // Run FABlib's native post_boot_config (L3 networking, hostnames, IPs, routes)
        setStatusMessage('Running FABlib post-boot config...');
        appendBuildLog(name, { type: 'build', message: 'Running FABlib post-boot config (networking, routes, hostnames)...' });
        try {
          await api.runPostBootConfig(sliceId);
          appendBuildLog(name, { type: 'build', message: 'FABlib post-boot config complete' });
        } catch (e: any) {
          appendBuildLog(name, { type: 'error', message: `FABlib post-boot config failed: ${e.message}` });
          addError(`FABlib post_boot_config failed: ${e.message}`);
        }
        setStatusMessage('Running post-boot configuration (waiting for SSH)...');
        await handleRunBootConfigStream(name, true);
        appendBuildLog(name, { type: 'build', message: '\u2713 Build complete' });
        setSliceBootRunning(prev => ({ ...prev, [name]: false }));
      } else if (POLL_STATES.has(refreshedData.state || '')) {
        // Slice is still provisioning — start auto-refresh polling
        appendBuildLog(name, { type: 'build', message: 'Waiting for slice to become ready...' });
        startPolling();
      } else {
        // Not a poll state and not StableOK — mark build done
        setSliceBootRunning(prev => ({ ...prev, [name]: false }));
      }
    } catch (e: any) {
      appendBuildLog(name, { type: 'error', message: `Submit failed: ${e.message}` });
      addError(e.message);
      setSliceBootRunning(prev => ({ ...prev, [name]: false }));
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [selectedSliceId, runValidation, startPolling, handleRunBootConfigStream, appendBuildLog]);

  const handleRefreshSlices = useCallback(async () => {
    setLoading(true);
    setStatusMessage('Refreshing slices...');
    try {
      // Refresh the slice list
      const list = await api.listSlices();
      protectDeletingSlices(list);
      setSlices(list);
      setListLoaded(true);
      syncStateFromList(list);

      // Also refresh the currently loaded slice if any
      const currentName = selectedSliceRef.current;
      if (currentName) {
        try {
          const data = await api.refreshSlice(currentName);
          setSliceData(data);
          runValidation(currentName);
        } catch { /* slice may no longer exist */ }
      }
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [runValidation, syncStateFromList]);

  const handleDeleteElements = useCallback(async (elements: Record<string, string>[]) => {
    if (!sliceData || elements.length === 0) return;
    setLoading(true);
    try {
      let data: SliceData = sliceData;
      for (const el of elements) {
        if (el.element_type === 'node') {
          data = await api.removeNode(selectedSliceId, el.name);
        } else if (el.element_type === 'network') {
          data = await api.removeNetwork(selectedSliceId, el.name);
        } else if (el.element_type === 'facility-port') {
          data = await api.removeFacilityPort(selectedSliceId, el.name);
        } else if (el.element_type === 'port-mirror') {
          data = await api.removePortMirror(selectedSliceId, el.name);
        }
      }
      updateSliceAndValidate(data);
      setSelectedElement(null);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
    }
  }, [sliceData, selectedSliceId, updateSliceAndValidate]);

  const handleDeleteSlice = useCallback(async () => {
    if (!selectedSliceId) return;
    const deletedId = selectedSliceId;
    const deletedName = selectedSliceName;
    const wasDraft = sliceData?.state === 'Draft';
    setLoading(true);
    setStatusMessage('Deleting slice...');
    try {
      // Register as deleting so polling won't overwrite state back to StableOK
      if (!wasDraft) {
        deletingSlicesRef.current.set(deletedId, Date.now());
        if (deletedName) deletingSlicesRef.current.set(deletedName, Date.now());
      }
      await api.deleteSlice(deletedId);
      setSliceData(null);
      setSelectedSliceId('');
      setSelectedElement(null);
      setValidationIssues([]);
      setValidationValid(false);
      if (wasDraft) {
        // Drafts are fully removed — take them out of the list immediately
        setSlices(prev => prev.filter(s => s.id !== deletedId));
      } else {
        // Submitted slices become "Dead" — mark locally for instant feedback
        setSlices(prev => prev.map(s => s.id === deletedId ? { ...s, state: 'Dead' } : s));
      }
      // Refresh the list to confirm the backend state
      setStatusMessage('Confirming deletion...');
      const MAX_RETRIES = 4;
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        try {
          const list = await api.listSlices();
          protectDeletingSlices(list);
          if (wasDraft) {
            setSlices(list);
            setListLoaded(true);
            if (!list.some(s => s.id === deletedId)) break;
          } else {
            // Ensure the deleted slice stays in the list as Dead until archived
            const entry = list.find(s => s.id === deletedId);
            if (!entry) {
              // Backend didn't return it yet — inject it as Dead
              list.push({ name: deletedName, id: deletedId, state: 'Dead', has_errors: false });
            }
            setSlices(list);
            setListLoaded(true);
            const finalEntry = list.find(s => s.id === deletedId);
            if (finalEntry && (finalEntry.state === 'Dead' || finalEntry.state === 'Closing')) break;
          }
        } catch {
          // Ignore and retry
        }
        if (attempt < MAX_RETRIES - 1) {
          await new Promise(r => setTimeout(r, 3000));
        }
      }
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [selectedSliceId, sliceData?.state]);

  // Delete a slice by name (used by AllSliversView)
  const handleDeleteSliceByName = useCallback(async (name: string) => {
    const slice = slices.find(s => s.name === name);
    const wasDraft = slice?.state === 'Draft';
    // Register as deleting so polling won't overwrite state back to StableOK
    if (!wasDraft) {
      deletingSlicesRef.current.set(name, Date.now());
      if (slice?.id) deletingSlicesRef.current.set(slice.id, Date.now());
    }
    await api.deleteSlice(name);
    // If deleting the currently-selected slice, clear selection
    if (name === selectedSliceName) {
      setSliceData(null);
      setSelectedSliceId('');
      setSelectedElement(null);
      setValidationIssues([]);
      setValidationValid(false);
    }
    if (wasDraft) {
      setSlices(prev => prev.filter(s => s.name !== name));
    } else {
      setSlices(prev => prev.map(s => s.name === name ? { ...s, state: 'Dead' } : s));
    }
  }, [slices, selectedSliceId]);


  const handleArchiveSlice = useCallback(async () => {
    if (!selectedSliceId) return;
    setLoading(true);
    setStatusMessage('Archiving slice...');
    try {
      await api.archiveSlice(selectedSliceId);
      setSliceData(null);
      setSelectedSliceId('');
      setSelectedElement(null);
      setValidationIssues([]);
      setValidationValid(false);
      try {
        const list = await api.listSlices();
        setSlices(list);
        setListLoaded(true);
      } catch {}
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [selectedSliceId]);

  const handleArchiveAllTerminal = useCallback(async () => {
    setLoading(true);
    setStatusMessage('Archiving terminal slices...');
    try {
      await api.archiveAllTerminal();
      // If current slice was archived, clear it
      const list = await api.listSlices();
      setSlices(list);
      setListLoaded(true);
      if (selectedSliceId && !list.find(s => s.id === selectedSliceId)) {
        setSliceData(null);
        setSelectedSliceId('');
        setSelectedElement(null);
        setValidationIssues([]);
        setValidationValid(false);
      }
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [selectedSliceId]);

  const handleNodeClick = useCallback((data: Record<string, string>) => {
    setSelectedElement(data);
  }, []);

  const handleEdgeClick = useCallback((data: Record<string, string>) => {
    setSelectedElement(data);
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setSelectedElement(null);
  }, []);

  const handleCreateSlice = useCallback(async (name: string) => {
    setLoading(true);
    setErrors([]);
    setStatusMessage('Creating slice...');
    try {
      const data = await api.createSlice(name);
      setSliceData(data);
      const newId = data.id || '';
      setSelectedSliceId(newId);
      setSlices((prev) => {
        if (prev.some((s) => s.id === newId)) return prev;
        return [...prev, { name, id: newId, state: 'Draft' }];
      });
      setCurrentView('slices'); setSlicesSubView('topology');
      runValidation(newId || name);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [runValidation]);

  const handleOpenTerminals = useCallback((elements: Record<string, string>[]) => {
    let counter = terminalIdCounter;
    const newTabs: TerminalTab[] = [];
    for (const el of elements) {
      if (el.element_type === 'node' && el.management_ip) {
        const id = `term-${counter}`;
        counter++;
        newTabs.push({
          id,
          label: el.name,
          sliceName: selectedSliceName,
          nodeName: el.name,
          managementIp: el.management_ip,
        });
      }
    }
    if (newTabs.length > 0) {
      setTerminalIdCounter(counter);
      setTerminalTabs((prev) => [...prev, ...newTabs]);
    }
  }, [selectedSliceId, terminalIdCounter]);

  const handleDeleteComponent = useCallback(async (nodeName: string, componentName: string) => {
    if (!selectedSliceId) return;
    setLoading(true);
    try {
      const data = await api.removeComponent(selectedSliceId, nodeName, componentName);
      updateSliceAndValidate(data);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedSliceId, updateSliceAndValidate]);

  const handleDeleteFacilityPort = useCallback(async (fpName: string) => {
    if (!selectedSliceId) return;
    setLoading(true);
    try {
      const data = await api.removeFacilityPort(selectedSliceId, fpName);
      updateSliceAndValidate(data);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedSliceId, updateSliceAndValidate]);

  // --- Save-template modal state ---
  const [saveTemplateModal, setSaveTemplateModal] = useState<{ type: 'slice' | 'vm'; nodeName?: string } | null>(null);
  const [saveTemplateName, setSaveTemplateName] = useState('');
  const [saveTemplateDesc, setSaveTemplateDesc] = useState('');
  const [saveTemplateBusy, setSaveTemplateBusy] = useState(false);

  const handleSaveSliceTemplate = useCallback(() => {
    setSaveTemplateName(selectedSliceName || '');
    setSaveTemplateDesc('');
    setSaveTemplateModal({ type: 'slice' });
  }, [selectedSliceId]);

  const handleSaveVmTemplate = useCallback((nodeName: string) => {
    setSaveTemplateName('');
    setSaveTemplateDesc('');
    setSaveTemplateModal({ type: 'vm', nodeName });
  }, []);

  const handleSaveTemplateConfirm = useCallback(async () => {
    if (!saveTemplateName.trim() || !saveTemplateModal) return;
    setSaveTemplateBusy(true);
    setStatusMessage('Saving template...');
    try {
      if (saveTemplateModal.type === 'slice') {
        await api.saveTemplate({
          name: saveTemplateName.trim(),
          description: saveTemplateDesc.trim(),
          slice_name: selectedSliceId,
        });
      } else if (saveTemplateModal.type === 'vm' && saveTemplateModal.nodeName) {
        let bootConfig: BootConfig = { uploads: [], commands: [], network: [] };
        try {
          bootConfig = await api.getBootConfig(selectedSliceId, saveTemplateModal.nodeName);
        } catch { /* no boot config yet */ }
        const node = sliceData?.nodes.find((n) => n.name === saveTemplateModal.nodeName);
        const vmData: Parameters<typeof api.saveVmTemplate>[0] = {
          name: saveTemplateName.trim(),
          description: saveTemplateDesc.trim(),
          image: node?.image || 'default_ubuntu_22',
          boot_config: bootConfig,
        };
        if (node) {
          if (node.cores) vmData.cores = node.cores;
          if (node.ram) vmData.ram = node.ram;
          if (node.disk) vmData.disk = node.disk;
          if (node.site && node.site !== 'auto') vmData.site = node.site;
          if (node.host) vmData.host = node.host;
          if (node.image_type && node.image_type !== 'qcow2') vmData.image_type = node.image_type;
          if (node.username) vmData.username = node.username;
          if (node.components?.length) {
            vmData.components = node.components.map(c => ({
              name: c.name.replace(`${node.name}-`, ''),
              model: c.model,
            }));
          }
        }
        await api.saveVmTemplate(vmData);
        refreshVmTemplates();
      }
      setSaveTemplateModal(null);
      setSaveTemplateName('');
      setSaveTemplateDesc('');
    } catch (e: any) {
      addError(e.message);
    } finally {
      setSaveTemplateBusy(false);
      setStatusMessage('');
    }
  }, [saveTemplateModal, saveTemplateName, saveTemplateDesc, selectedSliceId, sliceData, refreshVmTemplates]);

  const handleContextAction = useCallback((action: ContextMenuAction) => {
    if (action.type === 'terminal') {
      handleOpenTerminals(action.elements);
    } else if (action.type === 'delete') {
      handleDeleteElements(action.elements);
    } else if (action.type === 'delete-slice' && action.sliceNames) {
      (async () => {
        for (const name of action.sliceNames!) {
          try { await handleDeleteSliceByName(name); } catch (e: any) { addError(e.message); }
        }
        handleRefreshSlices();
      })();
    } else if (action.type === 'delete-component' && action.nodeName && action.componentName) {
      handleDeleteComponent(action.nodeName, action.componentName);
    } else if (action.type === 'delete-facility-port' && action.fpName) {
      handleDeleteFacilityPort(action.fpName);
    } else if (action.type === 'save-vm-template' && action.nodeName) {
      handleSaveVmTemplate(action.nodeName);
    } else if (action.type === 'apply-recipe' && action.recipeName && action.nodeName) {
      handleExecuteRecipe(action.recipeName, action.nodeName);
    } else if (action.type === 'open-client' && action.elements.length > 0) {
      const el = action.elements[0];
      setClientTarget({ sliceName: selectedSliceName, nodeName: el.name, port: action.port || 80 });
      setCurrentView('slices'); setSlicesSubView('apps');
    } else if (action.type === 'open-boot-log' && action.sliceNames && action.sliceNames.length > 0) {
      const sn = action.sliceNames[0];
      setOpenBootLogSlices(prev => prev.includes(sn) ? prev : [...prev, sn]);
      setConsoleExpanded(true);
    }
  }, [handleOpenTerminals, handleDeleteElements, handleDeleteSliceByName, handleRefreshSlices, handleDeleteComponent, handleDeleteFacilityPort, handleSaveVmTemplate, handleExecuteRecipe, selectedSliceId]);

  const handleCloseTerminal = useCallback((id: string) => {
    setTerminalTabs((prev) => prev.filter((t) => t.id !== id));
    setSideConsoleTabs(prev => prev.filter(t => t !== id));
  }, []);

  // --- Cross-panel tab coordination ---
  const handleBottomReceiveTab = useCallback((tabId: string, _fromPanel: string) => {
    // Tab moved from side panel to bottom panel
    setSideConsoleTabs(prev => prev.filter(id => id !== tabId));
  }, []);

  const handleSideReceiveTab = useCallback((tabId: string, _fromPanel: string) => {
    // Tab moved from bottom panel to side panel
    setSideConsoleTabs(prev => prev.includes(tabId) ? prev : [...prev, tabId]);
    // Expand the console panel if it's collapsed
    setPanelLayout(prev => prev.console.collapsed ? { ...prev, console: { ...prev.console, collapsed: false } } : prev);
  }, []);

  const handleSideTabMovedOut = useCallback((tabId: string) => {
    // Tab removed from side panel (close button sends it back to bottom)
    setSideConsoleTabs(prev => prev.filter(id => id !== tabId));
  }, []);

  const handleSliceUpdated = useCallback((data: SliceData) => {
    updateSliceAndValidate(data);
  }, [updateSliceAndValidate]);

  const handleOpenHelp = useCallback((section?: string) => {
    if (!section && helpOpen) {
      // Toggle off when clicking the help button again with no specific section
      setHelpOpen(false);
      setHelpSection(undefined);
    } else {
      setHelpSection(section);
      setHelpOpen(true);
    }
  }, [helpOpen]);

  const handleCloneSlice = useCallback(async (newName: string) => {
    if (!selectedSliceId) return;
    setLoading(true);
    setStatusMessage('Cloning slice...');
    try {
      const data = await api.cloneSlice(selectedSliceId, newName);
      setSliceData(data);
      const cloneId = data.id || '';
      setSelectedSliceId(cloneId);
      // Refresh the full slice list from backend to include the new draft
      try {
        const list = await api.listSlices();
        setSlices(list);
        setListLoaded(true);
      } catch {
        // Fallback: add locally if list refresh fails
        setSlices((prev) => {
          if (prev.some((s) => s.id === cloneId)) return prev;
          return [...prev, { name: data.name, id: cloneId, state: 'Draft' }];
        });
      }
      setCurrentView('slices'); setSlicesSubView('topology');
      runValidation(cloneId || data.name);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [selectedSliceId, runValidation]);

  const handleSliceImported = useCallback((data: SliceData) => {
    setSliceData(data);
    const importId = data.id || '';
    setSelectedSliceId(importId);
    setSlices((prev) => {
      if (importId && prev.some((s) => s.id === importId)) return prev;
      return [...prev, { name: data.name, id: importId, state: 'Draft' }];
    });
    runValidation(importId || data.name);
    setCurrentView('slices'); setSlicesSubView('topology');
  }, [runValidation]);

  // Deploy weave: load template → submit → poll → boot config (all automatic)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleDeployWeave = useCallback(async (templateDirName: string, sliceNameForDeploy: string, _args: Record<string, string> = {}) => {
    setLoading(true);
    setStatusMessage('Loading weave template...');

    // Open build log
    setOpenBootLogSlices(prev => prev.includes(sliceNameForDeploy) ? prev : [...prev, sliceNameForDeploy]);
    setConsoleExpanded(true);
    setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: true }));
    setSliceBootLogs(prev => ({ ...prev, [sliceNameForDeploy]: [] }));
    appendBuildLog(sliceNameForDeploy, { type: 'build', message: `Loading weave "${templateDirName}"...` });

    try {
      // Step 1: Load the template as a draft slice
      const data = await api.loadTemplate(templateDirName, sliceNameForDeploy);
      const sliceId = data.id || '';
      setSliceData(data);
      setSelectedSliceId(sliceId);
      setCurrentView('slices'); setSlicesSubView('topology');
      setSlices((prev) => {
        if (sliceId && prev.some((s) => s.id === sliceId)) return prev;
        return [...prev, { name: data.name, id: sliceId, state: 'Draft' }];
      });
      appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Weave loaded as draft slice' });

      // Step 2: Submit the slice
      setStatusMessage('Submitting slice to FABRIC...');
      appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Submitting slice to FABRIC...' });
      const submitted = await api.submitSlice(sliceId);
      if (submitted.id && submitted.id !== sliceId) setSelectedSliceId(submitted.id);
      setSliceData(submitted);
      appendBuildLog(sliceNameForDeploy, { type: 'build', message: `Slice submitted (state: ${submitted.state || 'unknown'})` });
      prevSliceStatesRef.current[sliceNameForDeploy] = submitted.state || '';

      // Refresh state
      setStatusMessage('Refreshing slice state...');
      let refreshedData = submitted;
      try {
        const refreshed = await api.refreshSlice(submitted.id || sliceId);
        refreshedData = refreshed;
        setSliceData(refreshed);
        if (refreshed.state && refreshed.state !== submitted.state) {
          appendBuildLog(sliceNameForDeploy, { type: 'build', message: `State: ${submitted.state || 'unknown'} \u2192 ${refreshed.state}` });
          prevSliceStatesRef.current[sliceNameForDeploy] = refreshed.state;
        }
      } catch {}

      // Refresh slice list
      try {
        const list = await api.listSlices();
        setSlices(list);
        setListLoaded(true);
      } catch {}

      // Handle immediate StableOK or start polling
      if (refreshedData.state === 'StableOK') {
        bootConfigRanRef.current.add(sliceNameForDeploy);
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: `Slice is ready (${refreshedData.state})` });
        setStatusMessage('Running FABlib post-boot config...');
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Running FABlib post-boot config (networking, routes, hostnames)...' });
        try {
          await api.runPostBootConfig(refreshedData.id || sliceId);
          appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'FABlib post-boot config complete' });
        } catch (e: any) {
          appendBuildLog(sliceNameForDeploy, { type: 'error', message: `FABlib post-boot config failed: ${e.message}` });
          addError(`FABlib post_boot_config failed: ${e.message}`);
        }
        setStatusMessage('Running post-boot configuration (waiting for SSH)...');
        await handleRunBootConfigStream(sliceNameForDeploy, true);
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: '\u2713 Deploy complete' });
        setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: false }));
      } else if (POLL_STATES.has(refreshedData.state || '')) {
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Waiting for slice to become ready...' });
        startPolling();
      } else {
        setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: false }));
      }
    } catch (e: any) {
      appendBuildLog(sliceNameForDeploy, { type: 'error', message: `Deploy failed: ${e.message}` });
      addError(e.message);
      setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: false }));
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [appendBuildLog, startPolling, handleRunBootConfigStream]);

  // Run weave script: execute run.sh as a background run (survives browser disconnect)
  const runPollTimers = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());

  const pollBackgroundRun = useCallback((runId: string, logKey: string) => {
    let offset = 0;

    const poll = async () => {
      try {
        const resp = await api.getBackgroundRunOutput(runId, offset);
        if (resp.output) {
          // Split into lines and append each
          const lines = resp.output.split('\n');
          for (const line of lines) {
            if (!line) continue;
            if (line.startsWith('### PROGRESS:')) {
              appendBuildLog(logKey, { type: 'build', message: `\u25B6 ${line.slice(13).trim()}` });
            } else {
              appendBuildLog(logKey, { type: 'output', message: line });
            }
          }
          offset = resp.offset;
        }
        if (resp.status !== 'running') {
          // Run finished — stop polling
          const timer = runPollTimers.current.get(runId);
          if (timer) {
            clearInterval(timer);
            runPollTimers.current.delete(runId);
          }
          if (resp.status === 'done') {
            appendBuildLog(logKey, { type: 'build', message: '\u2713 run.sh complete' });
          } else {
            appendBuildLog(logKey, { type: 'error', message: `run.sh exited (status: ${resp.status})` });
          }
          setSliceBootRunning(prev => ({ ...prev, [logKey]: false }));
          // Refresh active runs list so LibrariesPanel updates the badge
          api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
        }
      } catch {
        // Network error — keep polling, we might reconnect
      }
    };

    // Poll immediately, then every 2 seconds
    poll();
    const timer = setInterval(poll, 2000);
    runPollTimers.current.set(runId, timer);
  }, [appendBuildLog]);

  const handleRunWeaveScript = useCallback((templateDirName: string, weaveName: string, args: Record<string, string>) => {
    const logKey = `run:${weaveName}`;

    // Open build log tab for this run
    setOpenBootLogSlices(prev => prev.includes(logKey) ? prev : [...prev, logKey]);
    setConsoleExpanded(true);
    setSliceBootRunning(prev => ({ ...prev, [logKey]: true }));
    setSliceBootLogs(prev => ({ ...prev, [logKey]: [] }));
    appendBuildLog(logKey, { type: 'build', message: `Executing run.sh from "${weaveName}" (background)...` });

    // Start as background run
    api.startBackgroundRun(templateDirName, 'run.sh', args).then((resp) => {
      appendBuildLog(logKey, { type: 'build', message: `Run started: ${resp.run_id}` });
      pollBackgroundRun(resp.run_id, logKey);
      // Refresh active runs list so LibrariesPanel shows the running badge
      api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
    }).catch((err) => {
      appendBuildLog(logKey, { type: 'error', message: `Failed to start: ${err.message}` });
      setSliceBootRunning(prev => ({ ...prev, [logKey]: false }));
    });
  }, [appendBuildLog, pollBackgroundRun]);

  // Orchestrated run: deploy first (if deploy.sh exists), wait, then run run.sh
  // Stores pending run-after-deploy info keyed by slice name
  const pendingRunAfterDeploy = useRef<Map<string, { templateDirName: string; weaveName: string; args: Record<string, string> }>>(new Map());

  const handleRunExperiment = useCallback((templateDirName: string, weaveName: string, args: Record<string, string>) => {
    const sliceName = args.SLICE_NAME || weaveName || templateDirName;
    // Stash the run info — will trigger after deploy completes
    pendingRunAfterDeploy.current.set(sliceName, { templateDirName, weaveName, args });
    // Start deploy
    handleDeployWeave(templateDirName, sliceName, args);
  }, [handleDeployWeave]);

  // Watch for deploy completion and auto-trigger pending run.sh
  useEffect(() => {
    for (const [sliceName, runInfo] of pendingRunAfterDeploy.current.entries()) {
      const stillRunning = sliceBootRunning[sliceName];
      if (stillRunning === false) {
        // Deploy finished — check if it was successful (has log entries, last one is success)
        const logs = sliceBootLogs[sliceName] || [];
        const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;
        const deploySucceeded = lastLog?.message?.includes('Deploy complete') || lastLog?.message?.includes('Build complete');
        pendingRunAfterDeploy.current.delete(sliceName);
        if (deploySucceeded) {
          appendBuildLog(sliceName, { type: 'build', message: 'Deploy succeeded — starting run.sh...' });
          handleRunWeaveScript(runInfo.templateDirName, runInfo.weaveName, runInfo.args);
        } else {
          appendBuildLog(sliceName, { type: 'error', message: 'Deploy did not complete successfully — skipping run.sh' });
        }
      }
    }
  }, [sliceBootRunning, sliceBootLogs, handleRunWeaveScript, appendBuildLog]);

  // On mount, check for active background runs and resume polling
  useEffect(() => {
    api.listBackgroundRuns().then((runs) => {
      setActiveRuns(runs);
      for (const run of runs) {
        if (run.status === 'running') {
          const logKey = `run:${run.weave_name}`;
          setOpenBootLogSlices(prev => prev.includes(logKey) ? prev : [...prev, logKey]);
          setSliceBootRunning(prev => ({ ...prev, [logKey]: true }));
          appendBuildLog(logKey, { type: 'build', message: `Reconnected to background run: ${run.run_id}` });
          pollBackgroundRun(run.run_id, logKey);
        }
      }
    }).catch(() => {});

    // Periodically refresh active runs list (for badge updates in LibrariesPanel)
    const runsInterval = setInterval(() => {
      api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
    }, 10_000);

    return () => {
      clearInterval(runsInterval);
      // Cleanup poll timers on unmount
      for (const timer of runPollTimers.current.values()) clearInterval(timer);
      runPollTimers.current.clear();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // View output of a running or completed weave run — opens the build log tab
  const handleViewRunOutput = useCallback((weaveName: string) => {
    const logKey = `run:${weaveName}`;
    setOpenBootLogSlices(prev => prev.includes(logKey) ? prev : [...prev, logKey]);
    setConsoleExpanded(true);
  }, []);

  // Stop a background run
  const handleStopRun = useCallback(async (runId: string) => {
    try {
      await api.stopBackgroundRun(runId);
      // Refresh active runs list
      api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
    } catch (err: any) {
      setErrors(prev => [...prev, `Failed to stop run: ${err.message}`]);
    }
  }, []);

  // Reset/revert a published artifact to its original version
  const handleResetArtifact = useCallback(async (dirName: string) => {
    try {
      await api.revertArtifact(dirName);
    } catch (err: any) {
      setErrors(prev => [...prev, `Failed to reset artifact: ${err.message}`]);
    }
  }, []);

  const handleLaunchNotebook = useCallback((path: string) => {
    setJupyterPath(path);
    setCurrentView('jupyter');
  }, []);

  const handleEditArtifact = useCallback((dirName: string) => {
    setEditingArtifactDirName(dirName);
    setCurrentView('artifacts');
  }, []);

  const handleArtifactEditorBack = useCallback(() => {
    setEditingArtifactDirName('');
  }, []);

  const [publishNotebookName, setPublishNotebookName] = useState<string | undefined>(undefined);
  const handlePublishNotebook = useCallback((dirName: string) => {
    setPublishNotebookName(dirName);
    setCurrentView('artifacts');
  }, []);

  const [publishArtifactIntent, setPublishArtifactIntent] = useState<{ dirName: string; category: string } | undefined>(undefined);
  const handlePublishArtifact = useCallback((dirName: string, category: string) => {
    setPublishArtifactIntent({ dirName, category });
    setCurrentView('artifacts');
  }, []);

  const [marketplaceCategory, setMarketplaceCategory] = useState<'weave' | 'vm-template' | 'recipe' | 'notebook' | undefined>(undefined);
  const handleNavigateToMarketplace = useCallback((category: 'weave' | 'vm-template' | 'recipe' | 'notebook') => {
    setMarketplaceCategory(category);
    setCurrentView('artifacts');
  }, []);

  // --- Panel rendering helpers (shared between left/right panel groups) ---
  const showSidePanels = currentView === 'slices' || currentView === 'artifacts';
  // In artifacts view, only show chat and console panels (not editor/template)
  const visiblePanelIds: PanelId[] = currentView === 'artifacts'
    ? PANEL_IDS.filter(id => id === 'chat' || id === 'console')
    : PANEL_IDS;

  const makeDragProps = (id: PanelId) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      e.dataTransfer.setData('text/plain', id);
      setDraggingPanel(id);
    },
    onDragEnd: () => setDraggingPanel(null),
  });

  const renderPanel = (id: PanelId) => {
    const dragProps = makeDragProps(id);
    const icon = PANEL_ICONS[id];
    switch (id) {
      case 'editor':
        return (
          <EditorPanel
            key="editor"
            sliceData={sliceData}
            sliceName={selectedSliceName}
            onSliceUpdated={handleSliceUpdated}
            onCollapse={() => toggleCollapse('editor')}
            sites={infraSites}
            images={images}
            componentModels={componentModels}
            selectedElement={selectedElement}
            dragHandleProps={dragProps}
            panelIcon={icon}
            vmTemplates={vmTemplates}
            onSaveVmTemplate={handleSaveVmTemplate}
            onBootConfigErrors={setBootConfigErrors}
            onRunBootConfig={handleRunBootConfigStream}
            bootRunning={!!sliceBootRunning[selectedSliceName]}
            facilityPorts={infraFacilityPorts}
          />
        );
      case 'template':
        return (
          <LibrariesPanel
            key="template"
            onSliceImported={handleSliceImported}
            onDeployWeave={handleDeployWeave}
            onRunWeaveScript={handleRunWeaveScript}
            onRunExperiment={handleRunExperiment}
            activeRuns={activeRuns}
            onViewRunOutput={handleViewRunOutput}
            onStopRun={handleStopRun}
            onResetArtifact={handleResetArtifact}
            onCollapse={() => toggleCollapse('template')}
            dragHandleProps={dragProps}
            panelIcon={icon}
            onVmTemplatesChanged={refreshVmTemplates}
            sliceName={selectedSliceName}
            sliceData={sliceData}
            onNodeAdded={updateSliceAndValidate}
            onExecuteRecipe={handleExecuteRecipe}
            executingRecipe={executingRecipeName}
            onRecipesChanged={() => api.listRecipes().then(setRecipes).catch(() => {})}
            onLaunchNotebook={handleLaunchNotebook}
            onPublishNotebook={handlePublishNotebook}
            onPublishArtifact={handlePublishArtifact}
            onNavigateToMarketplace={handleNavigateToMarketplace}
            onEditArtifact={handleEditArtifact}
          />
        );
      case 'chat':
        return (
          <AIChatPanel
            key="chat"
            onCollapse={() => toggleCollapse('chat')}
            dragHandleProps={dragProps}
            panelIcon={icon}
            sliceContext={sliceData ? JSON.stringify(sliceData, null, 2) : undefined}
            onSliceChanged={refreshSliceList}
            persistId="loomai-sidebar"
          />
        );
      case 'console':
        return (
          <SideConsolePanel
            key="console"
            tabIds={sideConsoleTabs}
            terminals={terminalTabs}
            onCloseTerminal={handleCloseTerminal}
            validationIssues={validationIssues}
            validationValid={validationValid}
            sliceState={sliceData?.state ?? ''}
            dirty={sliceData?.dirty ?? false}
            errors={errors}
            onClearErrors={() => { setErrors([]); setValidationIssues([]); setValidationValid(false); }}
            sliceErrors={sliceData?.error_messages ?? []}
            bootConfigErrors={bootConfigErrors}
            onClearBootConfigErrors={() => setBootConfigErrors([])}
            recipeConsole={recipeConsole}
            recipeRunning={recipeRunning}
            onClearRecipeConsole={() => setRecipeConsole([])}
            sliceBootLogs={sliceBootLogs}
            sliceBootRunning={sliceBootRunning}
            onClearSliceBootLog={(sn) => setSliceBootLogs(prev => { const next = { ...prev }; delete next[sn]; return next; })}
            containerTermActive={true}
            onReceiveExternalTab={handleSideReceiveTab}
            onTabMovedOut={handleSideTabMovedOut}
            onCollapse={() => toggleCollapse('console')}
            dragHandleProps={dragProps}
            panelIcon={icon}
          />
        );
    }
  };

  const sortByOrder = (ids: PanelId[]) => [...ids].sort((a, b) => panelLayout[a].order - panelLayout[b].order);

  const renderPanelGroup = (panels: PanelId[], side: 'left' | 'right') => {
    const findTargetPanel = (groupEl: HTMLElement, clientX: number, ps: PanelId[]): { panelId: PanelId; edge: 'left' | 'right' } | null => {
      const wrappers = groupEl.querySelectorAll<HTMLElement>('.panel-wrapper');
      for (let i = 0; i < wrappers.length; i++) {
        const rect = wrappers[i].getBoundingClientRect();
        if (clientX >= rect.left && clientX <= rect.right) {
          const panelId = ps[i];
          if (!panelId || panelId === draggingPanel) return null;
          const midX = rect.left + rect.width / 2;
          return { panelId, edge: clientX < midX ? 'left' : 'right' };
        }
      }
      return null;
    };
    return (
      <div
        className={`panel-group ${side}`}
        onDragOver={(e) => {
          if (!draggingPanel) return;
          e.preventDefault();
          setDropIndicator(findTargetPanel(e.currentTarget as HTMLElement, e.clientX, panels));
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) {
            setDropIndicator(null);
          }
        }}
        onDrop={(e) => {
          if (!draggingPanel) return;
          e.preventDefault();
          const target = findTargetPanel(e.currentTarget as HTMLElement, e.clientX, panels);
          if (target) {
            const targetIdx = panels.indexOf(target.panelId);
            const beforeId = target.edge === 'left' ? target.panelId : (targetIdx + 1 < panels.length ? panels[targetIdx + 1] : null);
            movePanelToPosition(draggingPanel, side, beforeId);
          }
          setDraggingPanel(null);
          setDropIndicator(null);
        }}
      >
        {side === 'right' && (
          <div
            className="panel-resize-handle"
            onMouseDown={(e) => startResize(panels[0], false, e)}
          />
        )}
        {panels.map((id, i) => {
          const isDragging = draggingPanel === id;
          const showLeftIndicator = dropIndicator?.panelId === id && dropIndicator?.edge === 'left';
          const showRightIndicator = dropIndicator?.panelId === id && dropIndicator?.edge === 'right';
          return (
            <React.Fragment key={id}>
              {i > 0 && !draggingPanel && (
                <div
                  className="panel-resize-handle"
                  onMouseDown={(e) => startResize(
                    side === 'left' ? panels[i - 1] : panels[i],
                    side === 'left',
                    e
                  )}
                />
              )}
              <div
                className={`panel-wrapper${isDragging ? ' dragging' : ''}${showLeftIndicator ? ' drop-left' : ''}${showRightIndicator ? ' drop-right' : ''}`}
                style={{ width: panelLayout[id].width }}
              >
                {renderPanel(id)}
              </div>
            </React.Fragment>
          );
        })}
        {side === 'left' && (
          <div
            className="panel-resize-handle"
            onMouseDown={(e) => startResize(panels[panels.length - 1], true, e)}
          />
        )}
      </div>
    );
  };

  const leftExpanded = sortByOrder(visiblePanelIds.filter(id => panelLayout[id].side === 'left' && !panelLayout[id].collapsed));
  const rightExpanded = sortByOrder(visiblePanelIds.filter(id => panelLayout[id].side === 'right' && !panelLayout[id].collapsed));
  const leftCollapsed = sortByOrder(visiblePanelIds.filter(id => panelLayout[id].side === 'left' && panelLayout[id].collapsed));
  const rightCollapsed = sortByOrder(visiblePanelIds.filter(id => panelLayout[id].side === 'right' && panelLayout[id].collapsed));

  const AI_TOOL_INFO = [
    { id: 'loomai', name: 'LoomAI', icon: '\u2728' },
    { id: 'aider', name: 'Aider', icon: 'Ai' },
    { id: 'opencode', name: 'OpenCode', icon: 'OC' },
    { id: 'crush', name: 'Crush', icon: 'Cr' },
    { id: 'claude', name: 'Claude Code', icon: 'CC' },
  ];
  // LoomAI is always visible; other tools filtered by settings
  const visibleAiTools = AI_TOOL_INFO.filter((t) => t.id === 'loomai' || enabledAiTools[t.id] !== false);

  return (
    <>
      <TitleBar
        dark={dark}
        currentView={currentView}
        onToggleDark={() => setDark((d) => !d)}
        onViewChange={(v) => { if (v !== 'jupyter') setJupyterPath(undefined); setCurrentView(v); }}
        onOpenSettings={() => setSettingsOpen((prev) => !prev)}
        onOpenHelp={() => handleOpenHelp()}
        onGoHome={() => setCurrentView('landing')}
        projectName={projectName}
        projects={visibleProjects}
        onProjectChange={handleProjectChange}
        aiTools={visibleAiTools}
        selectedAiTool={selectedAiTool}
        onLaunchAiTool={(toolId) => { setSelectedAiTool(toolId); setCurrentView('ai'); }}
      />

      {currentView === 'slices' && <Toolbar
        slices={slices}
        selectedSlice={selectedSliceId}
        sliceState={sliceData?.state ?? ''}
        dirty={sliceData?.dirty ?? false}
        sliceValid={validationValid}
        loading={loading}
        onSelectSlice={(id) => {
          setSelectedSliceId(id);
          setSliceData(null);
          setSelectedElement(null);
          setValidationIssues([]);
          setValidationValid(false);
          // Auto-load the slice data
          if (id) {
            setLoading(true);
            setStatusMessage('Loading slice...');
            api.getSlice(id).then(data => {
              setSliceData(data);
              // Update to real ID if backend returned a different one (e.g. after submit)
              if (data.id && data.id !== id) setSelectedSliceId(data.id);
              // Update the slice list entry if the state changed
              if (data.state) {
                setSlices(prev => prev.map(s =>
                  s.id === id && s.state !== data.state
                    ? { ...s, state: data.state, id: data.id || s.id }
                    : s
                ));
              }
              runValidation(id);
            }).catch(e => {
              addError(e.message);
            }).finally(() => {
              setLoading(false);
              setStatusMessage('');
            });
          }
        }}
        onCreateSlice={handleCreateSlice}
        onSubmit={handleSubmit}
        onRefreshSlices={handleRefreshSlices}
        onDeleteSlice={handleDeleteSlice}
        onRefreshTopology={refreshInfrastructureAndMark}
        infraLoading={infraLoading}
        onCloneSlice={handleCloneSlice}
        listLoaded={listLoaded}
        onLoadSlices={refreshSliceList}
        infraLoaded={infraLoaded}
        statusMessage={statusMessage}
        onSaveSliceTemplate={handleSaveSliceTemplate}
        onArchiveSlice={handleArchiveSlice}
        onArchiveAllTerminal={handleArchiveAllTerminal}
        hasErrors={sliceData?.error_messages != null && sliceData.error_messages.length > 0}
        autoRefresh={autoRefresh}
        onToggleAutoRefresh={toggleAutoRefresh}
      />}

      <HelpContextMenu onOpenHelp={handleOpenHelp} />

      {/* Help overlay */}
      {helpOpen && (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <HelpView
            scrollToSection={helpSection}
            onClose={() => { setHelpOpen(false); setHelpSection(undefined); }}
            onStartTour={(tourId: string) => startTour(tourId)}
          />
        </div>
      )}

      {/* Settings overlay */}
      {settingsOpen && !helpOpen && (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <ConfigureView
            hiddenProjects={hiddenProjects}
            onHiddenProjectsChange={setHiddenProjects}
            allProjects={projects}
            onConfigured={() => {
              setIsConfigured(true);
              setSettingsOpen(false);
              setListLoaded(false);
              refreshInfrastructureAndMark();
              // Check if user changed — clear all account-specific state
              api.getConfig().then((cfg) => {
                setConfigStatus(cfg);
                const newUuid = cfg.token_info?.uuid || '';
                if (newUuid && newUuid !== userUuid) {
                  setUserUuid(newUuid);
                  // User switched accounts — clear previous account data
                  setSlices([]);
                  setSelectedSliceId('');
                  setSliceData(null);
                }
                if (cfg.token_info?.projects) {
                  setProjects(cfg.token_info.projects);
                }
                if (cfg.project_id) {
                  setProjectId(cfg.project_id);
                  const proj = cfg.token_info?.projects?.find((p: any) => p.uuid === cfg.project_id);
                  if (proj) setProjectName(proj.name);
                }
              }).catch(() => {});
              // Refresh slices for the (possibly new) account
              refreshSliceList();
              // Refresh project list from Core API (with config fallback)
              api.listUserProjects().then((resp) => {
                setProjects(resp.projects);
                if (resp.active_project_id) {
                  setProjectId(resp.active_project_id);
                  const proj = resp.projects.find((p) => p.uuid === resp.active_project_id);
                  if (proj) setProjectName(proj.name);
                }
                // Reconcile slice→project mappings in background
                api.reconcileProjects().catch(() => {});
              }).catch(() => {});
            }}
            onClose={() => {
              setSettingsOpen(false);
              setListLoaded(false);
              refreshInfrastructureAndMark();
            }}
          />
        </div>
      )}

      <div style={{
        flex: 1,
        display: (settingsOpen || helpOpen) ? 'none' : 'grid',
        overflow: 'hidden',
        gridTemplateColumns: showSidePanels ? 'auto 1fr auto' : '1fr',
        gridTemplateRows: '1fr auto',
      }}>
        {/* Left side panels (topology/sliver views only) */}
        {showSidePanels && (
          <div style={{
            gridColumn: 1,
            gridRow: consoleFullWidth ? '1' : '1 / -1',
            display: 'flex',
            overflow: 'hidden',
          }}>
            {leftExpanded.length > 0 && renderPanelGroup(leftExpanded, 'left')}
          </div>
        )}

        {/* Center column: view content */}
        <div style={{ gridColumn: showSidePanels ? 2 : 1, gridRow: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden', position: 'relative' }}>
          {/* Collapsed panel icon tabs (topology/sliver views only) */}
          {showSidePanels && (
            <>
              {leftCollapsed.map((id, i) => (
                <button
                  key={id}
                  className="panel-icon-tab left"
                  style={{ top: 40 + i * 36 }}
                  onClick={() => toggleCollapse(id)}
                  title={`Show ${PANEL_LABELS[id]}`}
                >
                  {PANEL_ICONS[id]}
                </button>
              ))}
              {rightCollapsed.map((id, i) => (
                <button
                  key={id}
                  className="panel-icon-tab right"
                  style={{ top: 40 + i * 36 }}
                  onClick={() => toggleCollapse(id)}
                  title={`Show ${PANEL_LABELS[id]}`}
                >
                  {PANEL_ICONS[id]}
                </button>
              ))}
              {draggingPanel && (
                <>
                  <div
                    className="panel-drop-zone left active"
                    onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('hover'); }}
                    onDragLeave={(e) => e.currentTarget.classList.remove('hover')}
                    onDrop={(e) => { e.preventDefault(); movePanel(draggingPanel, 'left'); setDraggingPanel(null); }}
                  />
                  <div
                    className="panel-drop-zone right active"
                    onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('hover'); }}
                    onDragLeave={(e) => e.currentTarget.classList.remove('hover')}
                    onDrop={(e) => { e.preventDefault(); movePanel(draggingPanel, 'right'); setDraggingPanel(null); }}
                  />
                </>
              )}
            </>
          )}

          {/* AI Companion — always mounted for chat persistence, hidden when not active */}
          <div style={{
            display: currentView === 'ai' ? 'flex' : 'none',
            flexDirection: 'column',
            flex: 1,
            minHeight: 0,
            overflow: 'hidden',
          }}>
            <AICompanionView selectedTool={selectedAiTool} onToolChange={setSelectedAiTool} visible={currentView === 'ai'} />
          </div>

          {/* View content */}
          {currentView === 'ai' ? null : currentView === 'landing' ? (
            <LandingView
              onNavigate={(view) => setCurrentView(view)}
              onOpenSettings={() => setSettingsOpen(true)}
              listLoaded={listLoaded}
              onLoadSlices={refreshSliceList}
              onStartTour={() => startTour('getting-started')}
            />
          ) : currentView === 'jupyter' ? (
            <JupyterLabView initialPath={jupyterPath} dark={dark} />
          ) : currentView === 'artifacts' ? (
            editingArtifactDirName ? (
              <ArtifactEditorView
                dirName={editingArtifactDirName}
                onBack={handleArtifactEditorBack}
                onLaunchJupyter={handleLaunchNotebook}
                sites={infraSites}
                images={images}
                componentModels={componentModels}
                dark={dark}
              />
            ) : (
              <LibrariesView
                onLoadSlice={(data) => { setSliceData(data); setSelectedSliceId(data.id || ''); refreshSliceList(); setCurrentView('slices'); setSlicesSubView('topology'); }}
                onLaunchNotebook={handleLaunchNotebook}
                onEditArtifact={handleEditArtifact}
                initialPublishNotebook={publishNotebookName}
                onClearPublishNotebook={() => setPublishNotebookName(undefined)}
                initialPublishArtifact={publishArtifactIntent}
                onClearPublishArtifact={() => setPublishArtifactIntent(undefined)}
                initialMarketplaceCategory={marketplaceCategory}
                onClearMarketplaceCategory={() => setMarketplaceCategory(undefined)}
                onNavigateToSlicesView={(dirName) => {
                  setCurrentView('slices');
                  // Ensure side panel shows Weaves tab by uncollapsing the template panel
                  setPanelLayout(prev => ({ ...prev, template: { ...prev.template, collapsed: false } }));
                }}
              />
            )
          ) : currentView === 'infrastructure' ? (
            <InfrastructureView
              subView={infraSubView}
              onSubViewChange={setInfraSubView}
              sites={infraSites}
              links={infraLinks}
              facilityPorts={infraFacilityPorts}
              linksLoading={infraLoading}
              siteMetricsCache={siteMetricsCache}
              linkMetricsCache={linkMetricsCache}
              metricsRefreshRate={metricsRefreshRate}
              onMetricsRefreshRateChange={setMetricsRefreshRate}
              onRefreshMetrics={refreshMetrics}
              metricsLoading={metricsLoading}
              selectedElement={selectedElement}
              onNodeClick={handleNodeClick}
              infraLoading={infraLoading}
              onRefreshInfrastructure={refreshInfrastructureAndMark}
            />
          ) : currentView === 'slices' ? (
            <SlicesView subView={slicesSubView} onSubViewChange={setSlicesSubView}>
              {slicesSubView === 'topology' ? (
                <CytoscapeGraph
                  graph={sliceData?.graph ?? null}
                  layout={layout}
                  dark={dark}
                  sliceData={sliceData}
                  recipes={recipes}
                  bootNodeStatus={sliceBootNodeStatus[selectedSliceName] ?? {}}
                  onLayoutChange={setLayout}
                  onNodeClick={handleNodeClick}
                  onEdgeClick={handleEdgeClick}
                  onBackgroundClick={handleBackgroundClick}
                  onContextAction={handleContextAction}
                />
              ) : slicesSubView === 'table' ? (
                <AllSliversView
                  slices={slices}
                  dark={dark}
                  onSliceSelect={(id) => {
                    setSelectedSliceId(id);
                    setSlicesSubView('topology');
                  }}
                  onDeleteSlice={handleDeleteSliceByName}
                  onRefreshSlices={handleRefreshSlices}
                  onContextAction={handleContextAction}
                  nodeActivity={nodeActivity}
                  recipes={recipes}
                />
              ) : slicesSubView === 'storage' ? (
                <FileTransferView
                  sliceName={selectedSliceName}
                  sliceData={sliceData}
                />
              ) : slicesSubView === 'map' ? (
                <GeoView
                  sliceData={sliceData}
                  selectedElement={selectedElement}
                  onNodeClick={handleNodeClick}
                  sites={infraSites}
                  links={infraLinks}
                  linksLoading={infraLoading}
                  siteMetricsCache={siteMetricsCache}
                  linkMetricsCache={linkMetricsCache}
                  metricsRefreshRate={metricsRefreshRate}
                  onMetricsRefreshRateChange={setMetricsRefreshRate}
                  onRefreshMetrics={refreshMetrics}
                  metricsLoading={metricsLoading}
                  defaultShowInfra={false}
                  hideDetail
                />
              ) : (
                <ClientView
                  slices={slices}
                  selectedSliceName={selectedSliceName}
                  sliceData={sliceData}
                  clientTarget={clientTarget}
                  onTargetChange={setClientTarget}
                />
              )}
            </SlicesView>
          ) : null}

        </div>

        {/* Right side panels (topology/sliver views only) */}
        {showSidePanels && (
          <div style={{
            gridColumn: 3,
            gridRow: consoleFullWidth ? '1' : '1 / -1',
            display: 'flex',
            overflow: 'hidden',
          }}>
            {rightExpanded.length > 0 && renderPanelGroup(rightExpanded, 'right')}
          </div>
        )}

        {/* BottomPanel — grid row 2, spans all columns when fullWidth, center column only when narrow */}
        <div style={{
          gridColumn: showSidePanels ? ((consoleFullWidth) ? '1 / -1' : '2') : '1',
          gridRow: 2,
          minHeight: 0,
          overflow: 'hidden',
        }}>
          <BottomPanel
            terminals={terminalTabs}
            onCloseTerminal={handleCloseTerminal}
            validationIssues={validationIssues}
            validationValid={validationValid}
            sliceState={sliceData?.state ?? ''}
            dirty={sliceData?.dirty ?? false}
            errors={errors}
            onClearErrors={() => { setErrors([]); setValidationIssues([]); setValidationValid(false); }}
            sliceErrors={sliceData?.error_messages ?? []}
            bootConfigErrors={bootConfigErrors}
            onClearBootConfigErrors={() => setBootConfigErrors([])}
            fullWidth={consoleFullWidth || !showSidePanels}
            onToggleFullWidth={() => setConsoleFullWidth(fw => !fw)}
            showWidthToggle={showSidePanels}
            expanded={consoleExpanded}
            onExpandedChange={setConsoleExpanded}
            panelHeight={consoleHeight}
            onPanelHeightChange={setConsoleHeight}
            recipeConsole={recipeConsole}
            recipeRunning={recipeRunning}
            onClearRecipeConsole={() => setRecipeConsole([])}
            sliceBootLogs={sliceBootLogs}
            sliceBootRunning={sliceBootRunning}
            onClearSliceBootLog={(sn) => setSliceBootLogs(prev => { const next = { ...prev }; delete next[sn]; return next; })}
            openBootLogSlices={openBootLogSlices}
            onOpenBootLog={(sn) => setOpenBootLogSlices(prev => prev.includes(sn) ? prev : [...prev, sn])}
            onCloseBootLog={(sn) => setOpenBootLogSlices(prev => prev.filter(s => s !== sn))}
            excludeTabIds={sideConsoleTabs}
            onReceiveExternalTab={handleBottomReceiveTab}
          />
        </div>
      </div>

      {/* StatusBar — always visible, full width */}
      <StatusBar
        statusMessage={statusMessage}
        loading={loading}
        sliceState={sliceData?.state ?? ''}
        errorCount={errors.length + (sliceData?.error_messages?.length ?? 0)}
        validationErrorCount={validationIssues.filter(i => i.severity === 'error').length}
        warnCount={validationIssues.filter(i => i.severity === 'warning').length}
        terminalCount={terminalTabs.length}
        recipeRunning={recipeRunning}
        bootRunning={Object.values(sliceBootRunning).some(Boolean)}
      />

      {/* Save Template Modal (slice or VM) */}
      {saveTemplateModal && (
        <div className="toolbar-modal-overlay" onClick={() => setSaveTemplateModal(null)}>
          <div className="toolbar-modal" onClick={(e) => e.stopPropagation()}>
            <h4>{saveTemplateModal.type === 'slice' ? 'Save as Artifact' : 'Save VM Template'}</h4>
            <p>
              {saveTemplateModal.type === 'slice'
                ? <>Save <strong>{selectedSliceName}</strong> as a reusable artifact.</>
                : <>Save node <strong>{saveTemplateModal.nodeName}</strong> config as a VM template.</>
              }
            </p>
            <input
              type="text"
              className="toolbar-modal-input"
              placeholder="Template name..."
              value={saveTemplateName}
              onChange={(e) => setSaveTemplateName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSaveTemplateConfirm()}
              autoFocus
            />
            <textarea
              className="toolbar-modal-input"
              placeholder="Description (optional)..."
              value={saveTemplateDesc}
              onChange={(e) => setSaveTemplateDesc(e.target.value)}
              rows={2}
              style={{ resize: 'vertical', marginTop: 8 }}
            />
            <div className="toolbar-modal-actions">
              <button onClick={() => setSaveTemplateModal(null)}>Cancel</button>
              <button
                className="success"
                onClick={handleSaveTemplateConfirm}
                disabled={!saveTemplateName.trim() || saveTemplateBusy}
              >
                {saveTemplateBusy ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Guided Tour */}
      <GuidedTour
        active={activeTourId !== null}
        steps={activeTourSteps}
        step={tourStep}
        onStepChange={setTourStep}
        onDismiss={dismissTour}
        onClose={closeTour}
        onOpenSettings={() => setSettingsOpen(true)}
        onCloseSettings={() => setSettingsOpen(false)}
        settingsOpen={settingsOpen}
        onSwitchView={setCurrentView}
        currentView={currentView}
        tourContext={tourContext}
      />
    </>
  );
}
