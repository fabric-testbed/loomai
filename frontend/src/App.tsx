'use client';
import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import dynamic from 'next/dynamic';
import TitleBar from './components/TitleBar';
import CytoscapeGraph from './components/CytoscapeGraph';
import type { ContextMenuAction } from './components/CytoscapeGraph';
import SliverView from './components/SliverView';
import AllSliversView from './components/AllSliversView';
import EditorPanel from './components/EditorPanel';
import LibrariesPanel from './components/LibrariesPanel';
import LibrariesView from './components/LibrariesView';
import './styles/infrastructure-view.css';
import GeoView from './components/GeoView';
import DetailPanel from './components/DetailPanel';
import BottomPanel from './components/BottomPanel';
import type { TerminalTab, RecipeConsoleLine, BootConsoleLine } from './components/BottomPanel';
import SideConsolePanel from './components/SideConsolePanel';
import StatusBar from './components/StatusBar';
const ConfigureView = dynamic(() => import('./components/ConfigureView'), { ssr: false });
const FileTransferView = dynamic(() => import('./components/FileTransferView'), { ssr: false });
const HelpView = dynamic(() => import('./components/HelpView'), { ssr: false });
import ClientView from './components/ClientView';
const JupyterLabView = dynamic(() => import('./components/JupyterLabView'), { ssr: false });
const AICompanionView = dynamic(() => import('./components/AICompanionView'), { ssr: false });
import AIChatPanel from './components/AIChatPanel';
import { assetUrl } from './utils/assetUrl';
import LoginPage from './components/LoginPage';
const LandingView = dynamic(() => import('./components/LandingView'), { ssr: false });
const ArtifactEditorView = dynamic(() => import('./components/ArtifactEditorView'), { ssr: false });
import type { CompositeSubView } from './components/CompositeView';
const InfrastructureView = dynamic(() => import('./components/InfrastructureView'), { ssr: false });
const ResourceBrowser = dynamic(() => import('./components/ResourceBrowser'), { ssr: false });
const FacilityPortsBrowser = dynamic(() => import('./components/FacilityPortsBrowser'), { ssr: false });
const ResourceCalendar = dynamic(() => import('./components/ResourceCalendar'), { ssr: false });
const ChameleonView = dynamic(() => import('./components/ChameleonView'), { ssr: false });
const ChameleonSlicesView = dynamic(() => import('./components/ChameleonSlicesView'), { ssr: false });
const ChameleonEditor = dynamic(() => import('./components/ChameleonEditor'), { ssr: false });
const ChameleonOpenStackView = dynamic(() => import('./components/ChameleonOpenStackView'), { ssr: false });
const CompositeEditorPanel = dynamic(() => import('./components/CompositeEditorPanel'), { ssr: false });
import type { ClientTarget } from './components/ClientView';
import HelpContextMenu from './components/HelpContextMenu';
import GuidedTour from './components/GuidedTour';
import { tours } from './data/tourSteps';
import * as api from './api/client';
import type { SliceSummary, SliceData, ComponentModel, ValidationIssue, ProjectInfo, VMTemplateSummary, BootConfig, RecipeSummary, ExperimentVariable } from './types/fabric';
import type { ChameleonSite, ChameleonInstance, ChameleonDraft, ChameleonSlice } from './types/chameleon';
import { useInfrastructure } from './hooks/useInfrastructure';

const AUTH_BASE = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH)
  ? `${window.__LOOMAI_BASE_PATH}/api`
  : '/api';

export default function App() {
  // --- Auth gating state ---
  const [authChecked, setAuthChecked] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);

  // Check auth status on mount
  useEffect(() => {
    fetch(`${AUTH_BASE}/auth/status`)
      .then(r => r.json())
      .then(data => {
        if (!data.auth_enabled) {
          // Auth not enabled — proceed directly
          setAuthChecked(true);
          setNeedsLogin(false);
          return;
        }
        // Auth enabled — test if we have a valid session cookie
        return fetch(`${AUTH_BASE}/health`).then(r => {
          if (r.status === 401) {
            setNeedsLogin(true);
          }
          setAuthChecked(true);
        });
      })
      .catch(() => {
        // Backend unreachable — show app anyway (will fail on API calls)
        setAuthChecked(true);
      });
  }, []);

  // Listen for 401 events from the API client
  useEffect(() => {
    const handler = () => setNeedsLogin(true);
    window.addEventListener('loomai-auth-required', handler);
    return () => window.removeEventListener('loomai-auth-required', handler);
  }, []);

  // --- Original app state ---
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
  type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai' | 'chameleon';
  type SlicesSubView = CompositeSubView;
  type InfraSubView = 'topology' | 'table' | 'storage' | 'map' | 'apps' | 'resources' | 'calendar';
  type ChameleonSubView = 'topology' | 'slices' | 'map' | 'calendar' | 'openstack';
  const [currentView, setCurrentView] = useState<TopView>('landing');
  const [slicesSubView, setSlicesSubView] = useState<SlicesSubView>('topology');
  const [infraSubView, setInfraSubView] = useState<InfraSubView>('table');
  const [chameleonSubView, setChameleonSubView] = useState<ChameleonSubView>('slices');
  const [chameleonSlices, setChameleonSlices] = useState<ChameleonSlice[]>([]);
  const [selectedChameleonSliceId, setSelectedChameleonSliceId] = useState('');
  const [chameleonSliceData, setChameleonSliceData] = useState<ChameleonSlice | null>(null);
  // Composite slice state — independent from FABRIC and Chameleon
  const [compositeSlices, setCompositeSlices] = useState<any[]>([]);
  const [selectedCompositeSliceId, setSelectedCompositeSliceId] = useState('');
  const [compositeGraph, setCompositeGraph] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [compositeEnabled, setCompositeEnabled] = useState(false);
  const [checkedCompositeIds, setCheckedCompositeIds] = useState<Set<string>>(new Set());
  const [chameleonAutoRefresh, setChameleonAutoRefresh] = useState(true);
  const [showChameleonLeaseDialog, setShowChameleonLeaseDialog] = useState(false);
  const [chiLeaseStartNow, setChiLeaseStartNow] = useState(true);
  const [chiLeaseStartDate, setChiLeaseStartDate] = useState('');
  const [chiLeaseDuration, setChiLeaseDuration] = useState(24);
  const [chiLeaseDeploying, setChiLeaseDeploying] = useState(false);
  const [chiAvailability, setChiAvailability] = useState<Record<string, {earliest_start: string | null; available_now: number; total: number; error: string; approximate?: boolean; warning?: string}>>({});
  const [chiAvailLoading, setChiAvailLoading] = useState(false);
  const [checkingAvailability, setCheckingAvailability] = useState(false);
  const [availabilityResult, setAvailabilityResult] = useState<import('./api/client').SliceAvailabilityResult | null>(null);
  const [chiDeployMode, setChiDeployMode] = useState<'lease-only' | 'auto-deploy' | 'existing-lease'>('auto-deploy');
  const [chiExistingLeaseId, setChiExistingLeaseId] = useState('');
  const [chiDeployStatus, setChiDeployStatus] = useState('');
  const [showChameleonDeleteDialog, setShowChameleonDeleteDialog] = useState(false);
  const [chiDeleteMode, setChiDeleteMode] = useState<'release' | 'delete-all'>('release');
  const [chiDeleting, setChiDeleting] = useState(false);
  const [chiActiveLeases, setChiActiveLeases] = useState<any[]>([]);
  const deployChiRef = useRef<(() => void) | null>(null);
  const [chiDeployNetworks, setChiDeployNetworks] = useState<Array<{id: string; name: string; shared?: boolean}>>([]);
  const [chiSelectedNetworkId, setChiSelectedNetworkId] = useState('');
  const [chiDraftVersion, setChiDraftVersion] = useState(0);
  const [chameleonLeases, setChameleonLeases] = useState<any[]>([]);
  const [resourceCategory, setResourceCategory] = useState<'sites' | 'facility-ports'>('sites');
  const [editingArtifactDirName, setEditingArtifactDirName] = useState('');
  const [jupyterPath, setJupyterPath] = useState<string | undefined>(undefined);
  const [jupyterMounted, setJupyterMounted] = useState(false);
  const [selectedAiTool, setSelectedAiTool] = useState<string | null>(null);
  const [enabledAiTools, setEnabledAiTools] = useState<Record<string, boolean>>({});
  const [clientTarget, setClientTarget] = useState<ClientTarget | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [configStatus, setConfigStatus] = useState<import('./types/fabric').ConfigStatus | null>(null);
  const [chameleonEnabled, setChameleonEnabled] = useState(false);
  const [chameleonSites, setChameleonSites] = useState<ChameleonSite[]>([]);
  const [chameleonInstances, setChameleonInstances] = useState<ChameleonInstance[]>([]);
  const [userUuid, setUserUuid] = useState<string>('');
  const [layout, setLayout] = useState('dagre');
  const [selectedElement, setSelectedElement] = useState<Record<string, string> | null>(null);
  const [selectedResourceKey, setSelectedResourceKey] = useState<string>('');
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
  type PanelId = 'editor' | 'template' | 'chat' | 'console' | 'details';
  type PanelLayoutEntry = { side: 'left' | 'right'; collapsed: boolean; width: number; order: number };
  type PanelLayoutMap = Record<PanelId, PanelLayoutEntry>;

  const PANEL_ICONS: Record<PanelId, string> = { editor: '\u270E', template: '__marketplace_icon__', chat: '__loomai_icon__', console: '\u2756', details: '\u2139' };
  const PANEL_LABELS: Record<PanelId, string> = { editor: 'Editor', template: 'Artifacts', chat: 'LoomAI', console: 'Console', details: 'Details' };
  const ICON_MAP: Record<string, string> = { '__loomai_icon__': '/loomai-icon-transparent.svg', '__marketplace_icon__': '/marketplace-icon-transparent.svg', '__composite_icon__': '/composite-slice-icon-transparent.svg' };
  const renderPanelIcon = (iconKey: string, size = 14) => ICON_MAP[iconKey] ? <img src={assetUrl(ICON_MAP[iconKey])} alt="" style={{ height: size }} /> : <>{iconKey}</>;
  const PANEL_IDS: PanelId[] = ['editor', 'template', 'chat', 'console', 'details'];
  const DEFAULT_PANEL_WIDTH = 280;
  const MIN_PANEL_WIDTH = 180;

  const defaultLayout: PanelLayoutMap = {
    editor: { side: 'left', collapsed: false, width: DEFAULT_PANEL_WIDTH, order: 0 },
    template: { side: 'right', collapsed: true, width: DEFAULT_PANEL_WIDTH, order: 0 },
    chat: { side: 'right', collapsed: true, width: 320, order: 1 },
    console: { side: 'right', collapsed: true, width: 380, order: 2 },
    details: { side: 'right', collapsed: true, width: 300, order: 3 },
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
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const infraRequestedRef = useRef(false);
  const sitesRequestedRef = useRef(false);
  const currentViewRef = useRef(currentView);
  currentViewRef.current = currentView;
  const [consoleFullWidth, setConsoleFullWidth] = useState(false);
  const [consoleExpanded, setConsoleExpanded] = useState(false);
  const [consoleHeight, setConsoleHeight] = useState(260);
  const [openBootLogSlices, setOpenBootLogSlices] = useState<string[]>([]);
  const [activeRuns, setActiveRuns] = useState<api.BackgroundRun[]>([]);
  // Track which weave dir_names have a deploy in progress (for button state in LibrariesPanel)
  const [deployingWeaves, setDeployingWeaves] = useState<Set<string>>(new Set());
  // Side console panel state (tabs tracked here, layout managed by panel system)
  const [sideConsoleTabs, setSideConsoleTabs] = useState<string[]>([]);
  const [dropIndicator, setDropIndicator] = useState<{ panelId: PanelId; edge: 'left' | 'right' } | null>(null);

  // Persist hidden projects to localStorage
  useEffect(() => {
    localStorage.setItem('fabric-hidden-projects', JSON.stringify([...hiddenProjects]));
  }, [hiddenProjects]);

  // Visible projects = non-service projects minus hidden ones
  const isServiceProject = (p: ProjectInfo) => /^SERVICE\s*[-–—]/i.test(p.name);
  const visibleProjects = projects.filter(p => !hiddenProjects.has(p.uuid) && !isServiceProject(p));

  // Track previous slice states for build log state-transition messages
  const prevSliceStatesRef = useRef<Record<string, string>>({});

  // Append a single line to a slice's build log
  const appendBuildLog = useCallback((sliceName: string, line: BootConsoleLine) => {
    setSliceBootLogs(prev => ({
      ...prev,
      [sliceName]: [...(prev[sliceName] || []), line],
    }));
  }, []);

  // Refs for addError context (moved up so infrastructure hook can use addError)
  const selectedSliceRef = useRef(selectedSliceId);
  selectedSliceRef.current = selectedSliceId;
  const sliceDataRef = useRef(sliceData);
  sliceDataRef.current = sliceData;
  const slicesRef = useRef(slices);
  slicesRef.current = slices;
  const [sliceRefreshKey, setSliceRefreshKey] = useState(0);

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

  // --- Infrastructure hook (sites, links, facility ports, metrics) ---
  const {
    infraSites, infraLinks, infraFacilityPorts, infraLoading, infraLoaded,
    siteMetricsCache, linkMetricsCache,
    metricsRefreshRate, setMetricsRefreshRate, metricsLoading,
    refreshSites, refreshInfrastructure, refreshMetrics, refreshInfrastructureAndMark,
  } = useInfrastructure({ addError, setStatusMessage, selectedElement });

  // --- Global cache: static data (fetched once on mount) ---
  const [images, setImages] = useState<string[]>([]);
  const [componentModels, setComponentModels] = useState<ComponentModel[]>([]);
  const [vmTemplates, setVmTemplates] = useState<VMTemplateSummary[]>([]);

  // --- Guided tour (multi-tour) ---
  const [activeTourId, setActiveTourId] = useState<string | null>(null);
  const [tourStep, setTourStep] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    // Sync JupyterLab theme whenever dark mode changes (fire-and-forget)
    api.setJupyterTheme(dark ? 'dark' : 'light').catch(() => {});
  }, [dark]);

  // Fetch static data once on mount (images, component models, VM templates, AI tools, recipes).
  // Each fetch is independent so a failure in one doesn't block the others.
  useEffect(() => {
    api.listImages().then(setImages).catch(() => {});
    api.listComponentModels().then(setComponentModels).catch(() => {});
    api.listVmTemplates().then(setVmTemplates).catch(() => {});
    api.getAiTools().then(setEnabledAiTools).catch(() => {});
    api.listRecipes().then(setRecipes).catch(() => {});
  }, []);

  const refreshVmTemplates = useCallback(() => {
    api.listVmTemplates().then(setVmTemplates).catch(() => {});
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

  // Full boot config pipeline: post_boot_config → auto_configure_networks → execute
  const handleRunFullBootConfigPipeline = useCallback(async (sliceNameOverride?: string) => {
    const target = sliceNameOverride || selectedSliceId;
    if (!target) return;
    setSliceBootRunning(prev => ({ ...prev, [target]: true }));
    setSliceBootLogs(prev => ({
      ...prev,
      [target]: [{ type: 'step', message: `Running full boot config pipeline for "${target}"...` }],
    }));
    setConsoleExpanded(true);

    const appendLine = (line: BootConsoleLine) => {
      setSliceBootLogs(prev => ({
        ...prev,
        [target]: [...(prev[target] || []), line],
      }));
    };

    // Step 1: FABlib post_boot_config (assigns IPs, hostnames, routes)
    appendLine({ type: 'step', message: 'Running FABlib post-boot config (networking, routes, hostnames)...' });
    try {
      await api.runPostBootConfig(target);
      appendLine({ type: 'step', message: 'FABlib post-boot config complete' });
    } catch (e: any) {
      appendLine({ type: 'error', message: `FABlib post-boot config failed: ${e.message}` });
    }

    // Step 2: Execute boot config scripts (uploads, commands)
    await handleRunBootConfigStream(target, true);
    appendLine({ type: 'step', message: '\u2713 Boot config pipeline complete' });
    setSliceBootRunning(prev => ({ ...prev, [target]: false }));
  }, [selectedSliceId, handleRunBootConfigStream]);

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
        // Token is good — navigate to FABRIC view and load slices
        setCurrentView('infrastructure');
        refreshSliceList();
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
          // Refresh slice list after project info loads
          refreshSliceList();
        }).catch(() => {
          // Core API unavailable — keep JWT projects as fallback
        });
      }
    }).catch(() => {
      setIsConfigured(false);
    });

    // Check Chameleon status
    api.getChameleonStatus().then(status => {
      setChameleonEnabled(status.enabled);
      if (status.enabled) {
        api.getChameleonSites().then(setChameleonSites).catch(() => {});
        api.listChameleonInstances().then(setChameleonInstances).catch(() => {});
        api.listAllChameleonSlices().then(setChameleonSlices).catch(() => {});
        api.listChameleonLeases().then(setChameleonLeases).catch(() => {});
      }
    }).catch(() => {});

    // Check view status and load composite slices
    api.getViewsStatus().then(status => {
      setCompositeEnabled(status.composite_enabled);
      if (status.composite_enabled) {
        api.listCompositeSlices().then(setCompositeSlices).catch(() => {});
      }
    }).catch(() => {});

    // Load draft data when selection changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // end of mount effect — Chameleon draft/polling effects below

  // Load selected Chameleon slice data
  useEffect(() => {
    if (!selectedChameleonSliceId) { setChameleonSliceData(null); return; }
    api.getChameleonDraft(selectedChameleonSliceId).then(setChameleonSliceData).catch(() => setChameleonSliceData(null));
  }, [selectedChameleonSliceId]);

  // Chameleon auto-refresh polling
  useEffect(() => {
    if (!chameleonAutoRefresh || currentView !== 'chameleon') return;
    const interval = setInterval(() => {
      api.listAllChameleonSlices().then(setChameleonSlices).catch(() => {});
      if (selectedChameleonSliceId) {
        api.getChameleonDraft(selectedChameleonSliceId).then(newData => {
          setChameleonSliceData(prev => {
            if (!prev || !newData) return newData;
            const prevStatuses = (prev.resources || []).map(r => `${r.id}:${r.status || ''}:${r.floating_ip || ''}`).join(',');
            const newStatuses = (newData.resources || []).map(r => `${r.id}:${r.status || ''}:${r.floating_ip || ''}`).join(',');
            if (prevStatuses !== newStatuses) {
              setChiDraftVersion(v => v + 1);
            }
            return newData;
          });
        }).catch(() => {});
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [chameleonAutoRefresh, currentView, selectedChameleonSliceId]);

  // --- Post-login project picker state ---
  const [showPostLoginProjectPicker, setShowPostLoginProjectPicker] = useState(false);
  const [postLoginProjects, setPostLoginProjects] = useState<Array<{ uuid: string; name: string }>>([]);
  const [postLoginBusy, setPostLoginBusy] = useState(false);

  const loginPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const loginTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loginStartExpRef = useRef<number | undefined>(undefined);

  const handleLoginSuccess = useCallback(async (cfg: import('./types/fabric').ConfigStatus) => {
    setConfigStatus(cfg);
    // Run post-login setup
    try {
      const projResp = await api.getProjects();
      const allProjs = projResp.projects || [];
      // Filter out service projects — they can't provision slices
      const provisionable = allProjs.filter(p => !/^SERVICE\s*[-–—]/i.test(p.name));
      if (provisionable.length === 1) {
        await runAutoSetup(provisionable[0].uuid);
      } else if (provisionable.length > 1) {
        setPostLoginProjects(provisionable);
        setShowPostLoginProjectPicker(true);
      } else {
        setErrors(prev => [...prev, 'No FABRIC projects found. Visit the FABRIC Portal to join a project.']);
        setSettingsOpen(true);
      }
    } catch (err: any) {
      setErrors(prev => [...prev, `Post-login setup failed: ${err.message}. Please configure manually in Settings.`]);
      setSettingsOpen(true);
    }
  }, []);

  const handleLogin = useCallback(async () => {
    try {
      const { login_url } = await api.getLoginUrl();
      // Snapshot the current config so we can detect when a new token arrives.
      // We compare both `exp` and `email` to catch re-logins with the same lifetime.
      const startExp = configStatus?.token_info?.exp;
      const startEmail = configStatus?.token_info?.email || '';
      const startHasToken = configStatus?.has_token || false;
      console.log('[login] starting, has_token=%s exp=%s email=%s', startHasToken, startExp, startEmail);

      const popup = window.open(login_url, 'fabric-login', 'width=600,height=700');
      if (!popup) {
        console.warn('[login] popup blocked — opening in new tab');
        window.open(login_url, '_blank');
      }
      let popupClosedChecks = 0;
      let loginHandled = false;

      const handleTokenDetected = async (cfg: import('./types/fabric').ConfigStatus) => {
        if (loginHandled) return;
        loginHandled = true;
        if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null; }
        if (loginTimeoutRef.current) { clearTimeout(loginTimeoutRef.current); loginTimeoutRef.current = null; }
        try { popup?.close(); } catch {}
        console.log('[login] token detected — running post-login setup');
        await handleLoginSuccess(cfg);
      };

      if (loginPollRef.current) clearInterval(loginPollRef.current);
      if (loginTimeoutRef.current) { clearTimeout(loginTimeoutRef.current); loginTimeoutRef.current = null; }
      loginPollRef.current = setInterval(async () => {
        if (loginHandled) return;
        try {
          const cfg = await api.getConfig();
          const newExp = cfg.token_info?.exp;
          const newEmail = cfg.token_info?.email || '';

          // Detect token change: new token appeared, exp changed, or email changed
          const tokenChanged = cfg.has_token && (
            !startHasToken ||                    // first token
            newExp !== startExp ||               // expiry changed
            newEmail !== startEmail              // different user
          );
          console.log('[login poll] has_token=%s exp=%s→%s email=%s→%s changed=%s',
            cfg.has_token, startExp, newExp, startEmail, newEmail, tokenChanged);

          if (tokenChanged) {
            await handleTokenDetected(cfg);
            return;
          }

          // Detect popup closure — give extra polls for token delivery
          let popupClosed = false;
          try { popupClosed = popup ? popup.closed : true; } catch { popupClosed = true; }
          if (popupClosed) {
            popupClosedChecks++;
            console.log('[login] popup closed, check #%d', popupClosedChecks);
            if (popupClosedChecks >= 5) {
              // Final check: accept any valid token even if exp didn't change
              // (handles re-login with same lifetime, or CM not delivering via callback)
              if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null; }
              if (loginTimeoutRef.current) { clearTimeout(loginTimeoutRef.current); loginTimeoutRef.current = null; }
              const finalCfg = await api.getConfig();
              if (finalCfg.has_token && finalCfg.configured) {
                console.log('[login] final check: valid token found — running post-login setup');
                await handleTokenDetected(finalCfg);
              } else if (finalCfg.has_token) {
                // Token exists but not fully configured — still run setup
                console.log('[login] final check: token found (not configured) — running setup');
                await handleTokenDetected(finalCfg);
              } else {
                setErrors(prev => [...prev,
                  'Login popup closed but token was not received. ' +
                  'Please try again, or copy your token from https://cm.fabric-testbed.net and paste it in Settings.'
                ]);
                setSettingsOpen(true);
              }
            }
          }
        } catch (err) { console.warn('[login poll] error:', err); }
      }, 2000);
      // Stop polling after 5 minutes
      loginTimeoutRef.current = setTimeout(() => {
        if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null; }
        loginTimeoutRef.current = null;
      }, 300000);
    } catch (err: any) {
      setErrors(prev => [...prev, `Login failed: ${err.message}`]);
    }
  }, [configStatus?.token_info?.exp, configStatus?.token_info?.email, configStatus?.has_token, handleLoginSuccess]);

  const runAutoSetup = useCallback(async (chosenProjectId: string) => {
    setPostLoginBusy(true);
    try {
      const result = await api.autoSetup(chosenProjectId);
      // Refresh config status
      const cfg = await api.getConfig();
      setConfigStatus(cfg);
      setIsConfigured(cfg.configured);
      if (result.uuid) setUserUuid(result.uuid);
      if (result.project_id) {
        setProjectId(result.project_id);
      }
      // Notify if bastion key creation failed
      if (!result.bastion_key_generated && result.bastion_key_error) {
        addError(`Bastion SSH key could not be created: ${result.bastion_key_error}. Upload your bastion key manually in Settings > SSH Keys.`);
      }
      // Notify if LLM key creation failed
      if (!result.llm_key_created && result.llm_key_error) {
        addError('FABRIC LLM API key could not be created automatically. Create one at https://cm.fabric-testbed.net and paste it in Settings > LLMs.');
      }
      if (cfg.token_info?.projects) {
        setProjects(cfg.token_info.projects);
        const proj = cfg.token_info.projects.find((p: any) => p.uuid === result.project_id);
        if (proj) setProjectName(proj.name);
      }
      setShowPostLoginProjectPicker(false);
      setSettingsOpen(false);
      // Navigate to FABRIC view and load slices
      setCurrentView('infrastructure');
      refreshSliceList();
      infraRequestedRef.current = false; sitesRequestedRef.current = false;
      // Also refresh from Core API
      api.listUserProjects().then((resp) => {
        setProjects(resp.projects);
        if (resp.active_project_id) {
          const proj = resp.projects.find((p) => p.uuid === resp.active_project_id);
          if (proj) setProjectName(proj.name);
        }
      }).catch(() => {});
    } catch (err: any) {
      setErrors(prev => [...prev, `Auto-setup failed: ${err.message}. Please configure manually in Settings.`]);
      setSettingsOpen(true);
    } finally {
      setPostLoginBusy(false);
    }
  }, []);

  const handleLogout = useCallback(async () => {
    // In K8s mode, redirect to hub logout which stops the pod and clears the session
    const basePath = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH) || '';
    if (basePath) {
      window.location.href = '/hub/logout';
      return;
    }
    // Clean up any active login polling/timeouts first
    if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null; }
    if (loginTimeoutRef.current) { clearTimeout(loginTimeoutRef.current); loginTimeoutRef.current = null; }
    loginStartExpRef.current = undefined;
    try {
      await api.logout();
    } catch (err: any) {
      // Best-effort — clear local state regardless
      console.warn('Logout API call failed:', err.message);
    }
    // Clear password auth session cookie (standalone mode)
    try {
      await fetch(`${AUTH_BASE}/auth/logout`, { method: 'POST' });
    } catch {
      // Best-effort
    }
    // Clear local state
    setConfigStatus(null);
    setIsConfigured(false);
    setSlices([]);
    setSliceData(null);
    setSelectedSliceId('');
    setProjects([]);
    setProjectId('');
    setProjectName('');
    setUserUuid('');
    setCurrentView('landing');
    // Show login page again if auth is enabled
    setNeedsLogin(true);
  }, []);

  // --- (continued from mount effect) ---
  useEffect(() => {
    // Handle OAuth callback redirect (runs in the popup window after CM redirect)
    const params = new URLSearchParams(window.location.search);
    if (params.get('configLogin') === 'success') {
      window.history.replaceState({}, '', '/');
      // Signal the main window that the token arrived
      try {
        localStorage.setItem('fabric-login-success', Date.now().toString());
      } catch {}
      // If this is a popup, try to close it — the main window handles setup
      if (window.opener) {
        try { window.close(); } catch {}
        // window.close() may fail silently — fall through to run setup here too
      }
      // Run setup (works in both popup and main window)
      (async () => {
        try {
          // The backend callback already did key generation; just refresh config
          const cfg = await api.getConfig();
          setConfigStatus(cfg);
          setIsConfigured(cfg.configured);
          if (cfg.configured) {
            setCurrentView('infrastructure');
            refreshSliceList();
          }
          // If not fully configured (multi-project), show project picker
          if (!cfg.project_id) {
            const projResp = await api.getProjects();
            const projectsList = projResp.projects || [];
            if (projectsList.length === 1) {
              await runAutoSetup(projectsList[0].uuid);
            } else if (projectsList.length > 1) {
              setPostLoginProjects(projectsList);
              setShowPostLoginProjectPicker(true);
            }
          }
        } catch {
          setSettingsOpen(true);
        }
      })();
    }

    // Listen for login success from popup window (cross-window via localStorage)
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'fabric-login-success' && e.newValue) {
        console.log('[login] detected token via localStorage event');
        localStorage.removeItem('fabric-login-success');
        // Stop any active polling
        if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null; }
        if (loginTimeoutRef.current) { clearTimeout(loginTimeoutRef.current); loginTimeoutRef.current = null; }
        // Fetch fresh config and run post-login setup
        api.getConfig().then(cfg => {
          if (cfg.has_token) {
            handleLoginSuccess(cfg);
          }
        }).catch(() => {});
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const activeTourSteps = activeTourId ? (tours[activeTourId]?.steps ?? []) : [];

  const dismissTour = useCallback(() => {
    setActiveTourId(null);
    setTourStep(0);
  }, []);

  const closeTour = useCallback(() => {
    setActiveTourId(null);
    setTourStep(0);
  }, []);

  const startTour = useCallback((tourId: string) => {
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
    has_ai_api_key: !!configStatus?.ai_api_key_set,
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

  // --- Auto-refresh polling — adaptive freshness based on slice/sliver states ---
  const POLL_STATES = new Set(['Configuring', 'Ticketed', 'Nascent', 'ModifyOK', 'ModifyError']);
  const STABLE_STATES = new Set(['StableOK', 'Active']);
  const TERMINAL_STATES_SET = new Set(['Dead', 'Closing', 'StableError']);
  const [pollInterval, setPollInterval] = useState(() => parseInt(localStorage.getItem('poll-interval') || '300000', 10));
  const pollIntervalRef = useRef(pollInterval);
  pollIntervalRef.current = pollInterval;

  // Adaptive polling: poll interval controls API call frequency (60s active, user-configured steady).
  // Each poll always fetches fresh data (max_age=0) so FABRIC state changes are detected immediately.
  const ACTIVE_POLL_INTERVAL = 60_000; // 60s when slices are provisioning
  const MUTATION_COOLDOWN = 120_000; // 2 minutes — stay ACTIVE after a mutation

  // Track last mutation time for the 3-minute cooldown
  const lastMutationRef = useRef<number>(0);

  // Track which slices have already had boot configs auto-executed
  const bootConfigRanRef = useRef<Set<string>>(new Set());
  // Track slices submitted through the GUI in this session — only these get auto-boot-config
  const guiSubmittedRef = useRef<Set<string>>(new Set());

  // Track slices being deleted — prevent polling from overwriting their state
  // back to StableOK before FABRIC orchestrator processes the delete.
  // Maps slice id/name → timestamp when delete was initiated.
  const deletingSlicesRef = useRef<Map<string, number>>(new Map());

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
  }, []);

  // (selectedSliceRef and projectNameRef moved up, next to infrastructure hook)

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

  // forceActive: when true, polls at ACTIVE_POLL_INTERVAL even if user chose "Never"
  // (used after slice submit/deploy to track provisioning progress)
  const forceActiveRef = useRef(false);

  const startPolling = useCallback((forceActive = false) => {
    forceActiveRef.current = forceActive;
    const enabled = pollIntervalRef.current > 0 || forceActive;
    console.log(`[startPolling] called, polling=${enabled ? (pollIntervalRef.current || 'forced-active') + 'ms' : 'off'}`);
    stopPolling();
    if (!enabled) return;

    const scheduleTick = (delay: number) => {
      pollingRef.current = setTimeout(pollTick, delay);
    };

    const pollTick = async () => {
      if (pollIntervalRef.current <= 0 && !forceActiveRef.current) { stopPolling(); return; }

      // Abort any previous in-flight poll request before starting a new one
      if (pollAbortRef.current) pollAbortRef.current.abort();
      const controller = new AbortController();
      pollAbortRef.current = controller;

      let nextDelay = pollIntervalRef.current; // default: user-chosen interval

      try {
        // Determine ACTIVE vs STEADY mode for adaptive freshness
        const now = Date.now();
        const withinCooldown = (now - lastMutationRef.current) < MUTATION_COOLDOWN;
        // Pre-check: use previous slice list to decide if transitional
        const hadTransitional = slices.some(s => POLL_STATES.has(s.state));
        const isActive = hadTransitional || withinCooldown;

        // Always fetch fresh data — poll interval controls API call frequency
        const list = await api.listSlices(0);
        protectDeletingSlices(list);
        // Guard: don't overwrite non-empty slices with an empty poll result
        // (backend may return empty during FABlib re-init or API hiccup)
        if (list.length === 0 && slicesRef.current.length > 0) {
          console.warn('[poll] API returned empty slice list but we had %d slices — skipping update', slicesRef.current.length);
        } else {
          setSlices(list);
        }
        setListLoaded(true);
        syncStateFromList(list);

        // Log state transitions and detect external changes
        let externalChangeDetected = false;
        const prevStates = prevSliceStatesRef.current;
        const prevIds = new Set(Object.keys(prevStates));
        for (const entry of list) {
          const prev = prevStates[entry.name];
          if (prev && prev !== entry.state) {
            appendBuildLog(entry.name, { type: 'build', message: `State: ${prev} \u2192 ${entry.state}` });
            // State changed — if we didn't initiate it, it's external
            if (!withinCooldown) externalChangeDetected = true;
          }
          if (!prevIds.has(entry.name) && entry.state !== 'Draft') {
            // New slice appeared that we didn't create — external change
            if (!withinCooldown) externalChangeDetected = true;
          }
          prevSliceStatesRef.current[entry.name] = entry.state;
        }

        // External change detected — switch to ACTIVE mode
        if (externalChangeDetected) {
          console.log('[poll] External slice change detected, switching to ACTIVE mode');
          lastMutationRef.current = Date.now();
        }

        // For the currently selected slice:
        // Always poll sliver states to keep node colors/states up to date.
        // Merge state changes into existing sliceData WITHOUT replacing the graph
        // (so CytoscapeGraph's preserveLayout can diff in-place without re-layout).
        const currentId = selectedSliceRef.current;
        const currentEntry = currentId ? list.find(s => s.id === currentId) : null;
        if (currentId && currentEntry && !TERMINAL_STATES_SET.has(currentEntry.state)) {
          // Poll sliver states — lightweight check for state changes
          try {
            const sliverData = await api.getSliverStates(currentId, 0);
            // Check if any state changed (slice-level or node-level)
            const prevData = sliceDataRef.current;
            const newSliceState = sliverData.slice_state || currentEntry.state;
            const sliceStateChanged = prevData && prevData.state !== newSliceState;
            const nodeStateChanged = prevData && sliverData.nodes.some((fresh: any) => {
              const prev = prevData.nodes.find(n => n.name === fresh.name);
              return prev && prev.reservation_state !== fresh.reservation_state;
            });

            if (sliceStateChanged || nodeStateChanged) {
              // State changed — re-fetch full slice to get updated graph with correct state colors.
              // CytoscapeGraph's preserveLayout will diff in-place (update colors, keep positions).
              try {
                const data = await api.getSlice(currentId);
                setSliceData(data);
              } catch { /* fallback: merge states manually */ }
            } else {
              // No state change — just merge management IPs and error messages
              setSliceData(prev => {
                if (!prev || !sliverData.nodes.length) return prev;
                const updatedNodes = prev.nodes.map(node => {
                  const fresh = sliverData.nodes.find((s: any) => s.name === node.name);
                  if (!fresh) return node;
                  if (node.management_ip === (fresh.management_ip || '') && node.error_message === (fresh.error_message || '')) return node;
                  return { ...node, management_ip: fresh.management_ip || node.management_ip, error_message: fresh.error_message || node.error_message };
                });
                return { ...prev, nodes: updatedNodes };
              });
            }
          } catch { /* next poll will retry */ }
        } else if (currentId && currentEntry && TERMINAL_STATES_SET.has(currentEntry.state)) {
          // Slice reached terminal state — update sliver states to match
          setSliceData(prev => {
            if (!prev) return prev;
            const terminalState = currentEntry.state;
            const updatedNodes = prev.nodes.map(node => ({
              ...node,
              reservation_state: terminalState,
            }));
            return { ...prev, state: terminalState, nodes: updatedNodes };
          });
        }

        // Auto-run boot configs for GUI-submitted slices that just reached StableOK
        for (const entry of list) {
          if ((entry.state === 'StableOK' || entry.state === 'Active')
              && !bootConfigRanRef.current.has(entry.name)
              && guiSubmittedRef.current.has(entry.name)) {
            bootConfigRanRef.current.add(entry.name);
            appendBuildLog(entry.name, { type: 'build', message: `Slice is ready (${entry.state})` });
            const sliceName = entry.name;
            (async () => {
              try {
                const sd = await api.refreshSlice(sliceName);
                if (entry.id === currentId) setSliceData(sd);
              } catch { /* fallback */ }

              appendBuildLog(sliceName, { type: 'build', message: 'Running FABlib post-boot config (networking, routes, hostnames)...' });
              try {
                await api.runPostBootConfig(sliceName);
                appendBuildLog(sliceName, { type: 'build', message: 'FABlib post-boot config complete' });
              } catch (e: any) {
                appendBuildLog(sliceName, { type: 'error', message: `FABlib post-boot config failed: ${e.message}` });
                addError(`FABlib post_boot_config failed for ${sliceName}: ${e.message}`);
              }

              await handleRunBootConfigStream(sliceName, true);
              appendBuildLog(sliceName, { type: 'build', message: '\u2713 Build complete' });
              setSliceBootRunning(prev => ({ ...prev, [sliceName]: false }));
            })();
          }
        }

        // Adaptive poll interval: 20s when slices are provisioning, user-chosen otherwise
        const hasTransitional = list.some(s => POLL_STATES.has(s.state));
        if (hasTransitional || withinCooldown) {
          nextDelay = ACTIVE_POLL_INTERVAL;
        }
        if (!hasTransitional && !withinCooldown && isActive) {
          console.log(`[poll] All slices settled, switching to STEADY mode (interval=${pollIntervalRef.current}ms)`);
          // If force-active polling was on (user chose "Never" but slice was provisioning),
          // stop polling now that all slices have settled
          if (forceActiveRef.current) {
            forceActiveRef.current = false;
            if (pollIntervalRef.current <= 0) {
              console.log('[poll] Force-active complete, stopping polling (user interval=Never)');
              stopPolling();
              return;
            }
          }
        }
      } catch {
        // Silently ignore polling errors — next poll will retry
      }

      // Schedule next tick
      const shouldContinue = pollIntervalRef.current > 0 || forceActiveRef.current;
      if (shouldContinue) scheduleTick(nextDelay);
    };

    // First tick after the user-chosen delay (or ACTIVE if transitional)
    const hasTransitional = slices.some(s => POLL_STATES.has(s.state));
    const initialDelay = hasTransitional || forceActive || (Date.now() - lastMutationRef.current) < MUTATION_COOLDOWN
      ? ACTIVE_POLL_INTERVAL : (pollIntervalRef.current || ACTIVE_POLL_INTERVAL);
    scheduleTick(initialDelay);
  }, [stopPolling, syncStateFromList, handleRunBootConfigStream, appendBuildLog]);

  // Clean up polling on unmount
  useEffect(() => { return () => stopPolling(); }, [stopPolling]);

  // Pause all polling when the browser tab is hidden, resume on return
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stopPolling();
      } else if (document.visibilityState === 'visible') {
        const view = currentViewRef.current;
        if (view !== 'slices' && view !== 'infrastructure') return;
        // On return, refresh slice list (force fresh) and restart polling if needed
        api.listSlices(0).then(list => {
          protectDeletingSlices(list);
          if (list.length === 0 && slicesRef.current.length > 0) {
            console.warn('[visibility] API returned empty slice list but we had %d slices — skipping update', slicesRef.current.length);
          } else {
            setSlices(list);
          }
          syncStateFromList(list);
          if (pollIntervalRef.current > 0 && !pollingRef.current) {
            startPolling();
          }
        }).catch(() => {});
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [stopPolling, startPolling, syncStateFromList]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch lightweight sites list when first entering infrastructure view (for editor dropdowns)
  useEffect(() => {
    if (currentView === 'infrastructure' && !sitesRequestedRef.current && infraSites.length === 0) {
      sitesRequestedRef.current = true;
      refreshSites();
    }
  }, [currentView, infraSites.length, refreshSites]);

  // Lazy-load full infrastructure data (sites + links + metrics) on first visit to sub-views that need it
  useEffect(() => {
    const infraNeedsData = currentView === 'infrastructure' &&
      (infraSubView === 'map' || infraSubView === 'resources' || infraSubView === 'calendar');
    const slicesNeedsData = currentView === 'slices' && slicesSubView === 'map';
    if ((infraNeedsData || slicesNeedsData) && !infraRequestedRef.current) {
      infraRequestedRef.current = true;
      refreshInfrastructureAndMark();
    }
  }, [currentView, slicesSubView, infraSubView, refreshInfrastructureAndMark]);

  // Fetch slice data whenever selectedSliceId changes (e.g. dropdown pick)
  useEffect(() => {
    if (!selectedSliceId) return;
    const view = currentViewRef.current;
    if (view !== 'slices' && view !== 'infrastructure') return;
    api.getSlice(selectedSliceId).then(data => {
      setSliceData(data);
    }).catch(() => {});
  }, [selectedSliceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Start/stop slice polling based on active view; refresh selected slice on view switch
  useEffect(() => {
    if (currentView === 'slices' || currentView === 'infrastructure') {
      // Refresh selected slice to show current state
      if (selectedSliceId) {
        api.refreshSlice(selectedSliceId).then(data => {
          setSliceData(data);
        }).catch(() => {});
      }
      // Restart polling (first tick fetches fresh data)
      if (pollIntervalRef.current > 0 && !pollingRef.current) {
        startPolling();
      }
    } else {
      // Stop polling when leaving slice-related views
      stopPolling();
    }
  }, [currentView]); // eslint-disable-line react-hooks/exhaustive-deps

  // Restart or stop polling when poll interval changes
  useEffect(() => {
    if (pollInterval === 0) {
      stopPolling();
    } else if (pollingRef.current) {
      // Interval changed while polling — restart with new timing
      stopPolling();
      startPolling();
    } else if (currentViewRef.current === 'slices' || currentViewRef.current === 'infrastructure') {
      // Switched from Never to an interval while on a slice view — start
      startPolling();
    }
  }, [pollInterval]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load slice list on first interaction or mount
  const refreshSliceList = useCallback(async () => {
    setLoading(true);
    setErrors([]);
    setStatusMessage('Refreshing slice list...');
    try {
      const list = await api.listSlices();
      protectDeletingSlices(list);
      // Guard: don't overwrite non-empty slices with empty result (API hiccup)
      if (list.length === 0 && slicesRef.current.length > 0) {
        console.warn('[refreshSliceList] API returned empty but we had %d slices — keeping existing', slicesRef.current.length);
      } else {
        setSlices(list);
      }
      setListLoaded(true);

      // Pre-seed bootConfigRanRef with already-stable slices so we only
      // auto-run boot config for slices that *newly* transition to stable
      for (const s of list) {
        if (STABLE_STATES.has(s.state) || TERMINAL_STATES_SET.has(s.state)) {
          bootConfigRanRef.current.add(s.name);
        }
      }

      // If the currently selected slice changed state, reload it
      const currentId = selectedSliceRef.current;
      if (currentId) {
        const entry = list.find(s => s.id === currentId);
        if (entry) {
          syncStateFromList(list);
          // Reload slice data if it's not yet stable/terminal (state may have changed)
          if (POLL_STATES.has(entry.state)) {
            try {
              const data = await api.refreshSlice(currentId);
              setSliceData(data);
            } catch { /* ignore */ }
          }
        }
      } else {
        syncStateFromList(list);
      }

      // Always start polling (STEADY mode is near-free with high max_age)
      if (pollIntervalRef.current > 0) {
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
      // Reset slice state
      setSliceData(null);
      setSelectedSliceId('');
      setSelectedElement(null);
      setSlices([]);
      setListLoaded(false);
      infraRequestedRef.current = false; sitesRequestedRef.current = false; // re-fetch infra on next tab visit
      // If token couldn't be refreshed, trigger OAuth re-login scoped to the new project
      if (result.needs_relogin) {
        addError('Token needs to be refreshed for the new project. Please re-login.');
        handleLogin();
      } else {
        // Token refreshed successfully — load slices for the new project
        await refreshSliceList();
      }
    } catch (e: any) {
      addError(e.message);
    } finally {
      setStatusMessage('');
    }
  }, [projects, refreshSliceList, handleLogin]);

  // Debug: log when slices state changes from populated to empty
  const prevSliceCountRef = useRef(0);
  useEffect(() => {
    if (slices.length === 0 && prevSliceCountRef.current > 0) {
      console.warn('[slices] slices became empty! Previous count was %d. Stack:', prevSliceCountRef.current, new Error().stack);
    }
    prevSliceCountRef.current = slices.length;
  }, [slices]);

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


  const handleCheckAvailability = useCallback(async () => {
    if (!selectedSliceId) return;
    setCheckingAvailability(true);
    try {
      const result = await api.checkSliceAvailability(selectedSliceId);
      setAvailabilityResult(result);
    } catch (e: any) {
      setErrors(prev => [...prev, `Availability check failed: ${e.message}`]);
    } finally {
      setCheckingAvailability(false);
    }
  }, [selectedSliceId]);

  // Submit handles both new slice creation and modifications to existing slices
  // Uses composite submit when Chameleon nodes are present
  const handleSubmit = useCallback(async () => {
    if (!selectedSliceId) return;
    const sliceId = selectedSliceId;
    const name = selectedSliceName;
    const hasChameleon = (sliceData?.chameleon_nodes || []).length > 0;
    lastMutationRef.current = Date.now(); // Switch to ACTIVE polling mode
    setLoading(true);
    setStatusMessage(hasChameleon ? 'Submitting composite slice (FABRIC + Chameleon)...' : 'Submitting slice to FABRIC...');

    // Open build log tab with a fresh log
    setOpenBootLogSlices(prev => prev.includes(name) ? prev : [...prev, name]);
    setConsoleExpanded(true);
    setSliceBootRunning(prev => ({ ...prev, [name]: true }));
    setSliceBootLogs(prev => ({ ...prev, [name]: [] }));
    appendBuildLog(name, { type: 'build', message: hasChameleon ? 'Submitting composite slice (FABRIC + Chameleon)...' : 'Submitting slice to FABRIC...' });

    try {
      let data: SliceData;
      if (hasChameleon) {
        const compositeResult = await api.submitCompositeSlice(sliceId);
        appendBuildLog(name, { type: 'build', message: `Composite submit: FABRIC=${compositeResult.fabric_status}, Chameleon=${compositeResult.chameleon_status || 'N/A'}` });
        if (compositeResult.chameleon_error) {
          appendBuildLog(name, { type: 'error', message: `Chameleon error: ${compositeResult.chameleon_error}` });
        }
        if (compositeResult.fabric_error) {
          appendBuildLog(name, { type: 'error', message: `FABRIC error: ${compositeResult.fabric_error}` });
        }
        // Use the embedded fabric_slice data, or re-fetch if not included
        data = compositeResult.fabric_slice || await api.getSlice(sliceId);
      } else {
        data = await api.submitSlice(sliceId);
      }
      if (data.id && data.id !== sliceId) setSelectedSliceId(data.id);
      setSliceData(data);
      setValidationIssues([]);
      setValidationValid(true);
      // Mark this slice as GUI-submitted so polling auto-runs boot config for it
      guiSubmittedRef.current.add(name);
      appendBuildLog(name, { type: 'build', message: `Slice submitted (state: ${data.state || 'unknown'})` });
      prevSliceStatesRef.current[name] = data.state || '';
      // Use submit response directly — no redundant refreshSlice() call.
      // Just update the slice list (lightweight, uses backend cache).
      let refreshedData = data;
      setStatusMessage('Refreshing slice list...');
      try {
        const list = await api.listSlices();
        setSlices(list);
        setListLoaded(true);
        // Check if the list shows a newer state than the submit response
        const updated = list.find(s => s.id === (data.id || sliceId));
        if (updated && updated.state && updated.state !== data.state) {
          appendBuildLog(name, { type: 'build', message: `State: ${data.state || 'unknown'} \u2192 ${updated.state}` });
          prevSliceStatesRef.current[name] = updated.state;
          refreshedData = { ...data, state: updated.state };
        }
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
        // Slice is still provisioning — force-start polling even if user chose "Never"
        appendBuildLog(name, { type: 'build', message: 'Waiting for slice to become ready...' });
        startPolling(true);
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
      // Manual refresh — force fresh data (max_age=0)
      const list = await api.listSlices(0);
      protectDeletingSlices(list);
      setSlices(list);
      setListLoaded(true);
      syncStateFromList(list);
      setSliceRefreshKey(k => k + 1);

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

  // --- Chameleon callbacks (mirror FABRIC pattern) ---
  const handleRefreshChameleonSlices = useCallback(async () => {
    try { setChameleonSlices(await api.listAllChameleonSlices()); } catch { /* ignore */ }
  }, []);

  const handleCreateChameleonDraft = useCallback(async () => {
    const name = prompt('Draft name:');
    if (!name) return;
    const site = (chameleonSites || [])[0]?.name || 'CHI@TACC';
    try {
      const draft = await api.createChameleonDraft({ name, site });
      setChameleonSlices(prev => [...prev, draft]);
      setSelectedChameleonSliceId(draft.id);
      setChameleonSliceData(draft);
      setChameleonSubView('topology');
    } catch (e: any) { setErrors(prev => [...prev, e.message]); }
  }, [chameleonSites]);

  // --- Composite auto-refresh: poll member states every 30s ---
  const compositeStatesRef = useRef<string>('');
  useEffect(() => {
    if (!selectedCompositeSliceId || pollInterval === 0 || currentView !== 'slices') return;
    // Immediate refresh on (re-)activation so the user sees fresh state
    // without waiting 30s after switching back to the composite view.
    const refreshComposite = async () => {
      try {
        const data = await api.getCompositeSlice(selectedCompositeSliceId);
        const stateKey = JSON.stringify(data.fabric_member_summaries?.map((m: any) => m.state) || []) +
                         JSON.stringify(data.chameleon_member_summaries?.map((m: any) => m.state) || []);
        if (stateKey !== compositeStatesRef.current) {
          compositeStatesRef.current = stateKey;
          setCompositeSlices(prev => prev.map(s => s.id === data.id ? data : s));
          api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
        }
      } catch { /* ignore polling errors */ }
    };
    refreshComposite();
    const interval = setInterval(refreshComposite, 30000);
    return () => clearInterval(interval);
  }, [selectedCompositeSliceId, pollInterval, currentView]);

  // Refresh composite graph when switching to topology tab
  useEffect(() => {
    if (currentView === 'slices' && slicesSubView === 'topology' && selectedCompositeSliceId) {
      api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
    }
  }, [slicesSubView, currentView, selectedCompositeSliceId]);

  // Refresh Chameleon graph when switching to topology tab
  useEffect(() => {
    if (currentView === 'chameleon' && chameleonSubView === 'topology' && selectedChameleonSliceId) {
      setChiDraftVersion(v => v + 1);
    }
  }, [chameleonSubView, currentView, selectedChameleonSliceId]);

  const handleSubmitChameleonDraft = useCallback(async () => {
    if (!selectedChameleonSliceId || !chameleonSliceData) return;
    // One-click submit: deploy directly using config from editor Leases tab
    // Trigger the deploy flow (defined below, called via setTimeout to avoid stale closure)
    setTimeout(() => deployChiRef.current?.(), 0);
  }, [selectedChameleonSliceId, chameleonSliceData]);

  // Derive sites from slice nodes
  const chiDraftSites = useMemo(() => {
    if (!chameleonSliceData) return [] as string[];
    const fromNodes = (chameleonSliceData.nodes || []).map(n => n.site).filter(Boolean);
    if (fromNodes.length > 0) return [...new Set(fromNodes)].sort();
    return chameleonSliceData.site ? [chameleonSliceData.site] : [];
  }, [chameleonSliceData]);

  useEffect(() => {
    if (!showChameleonLeaseDialog) return;
    api.listChameleonLeases().then(leases => {
      setChiActiveLeases(leases.filter((l: any) => l.status === 'ACTIVE'));
    }).catch(() => {});
    // Fetch available networks for each site in draft
    for (const site of chiDraftSites) {
      api.listChameleonNetworks(site).then(nets => {
        setChiDeployNetworks(prev => {
          // Merge: replace networks for this site, keep others
          const others = (prev || []).filter((n: any) => n.site !== site);
          return [...others, ...nets];
        });
        // Prefer sharednet1 (provider network with external routing) over fabnetv4
        const sharednet1 = nets.find((n: any) => n.shared && /sharednet/i.test(n.name));
        const anyShared = nets.find((n: any) => n.shared && !/fabnet/i.test(n.name));
        const fallback = nets.find((n: any) => n.shared);
        const preferred = sharednet1 || anyShared || fallback;
        if (preferred && !chiSelectedNetworkId) setChiSelectedNetworkId(preferred.id);
      }).catch(() => {});
    }
  }, [showChameleonLeaseDialog]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCheckChiAvailability = useCallback(async () => {
    if (!chameleonSliceData) return;
    setChiAvailLoading(true);
    const results: typeof chiAvailability = {};
    // Group nodes by site + type
    const siteTypeMap: Record<string, { site: string; count: number }> = {};
    for (const n of chameleonSliceData.nodes) {
      const key = `${n.site}::${n.node_type}`;
      if (!siteTypeMap[key]) siteTypeMap[key] = { site: n.site, count: 0 };
      siteTypeMap[key].count += n.count || 1;
    }
    for (const [key, { site, count }] of Object.entries(siteTypeMap)) {
      const nodeType = key.split('::')[1];
      try {
        const r = await api.findChameleonAvailability({
          site,
          node_type: nodeType,
          node_count: count,
          duration_hours: chiLeaseDuration,
        });
        results[key] = r;
      } catch (e: any) {
        results[key] = { earliest_start: null, available_now: 0, total: 0, error: e.message };
      }
    }
    setChiAvailability(results);
    setChiAvailLoading(false);
  }, [chameleonSliceData, chiLeaseDuration]);

  const handleDeployChameleonLease = useCallback(async () => {
    if (!selectedChameleonSliceId || !chameleonSliceData) return;
    setChiLeaseDeploying(true);
    setChiDeployStatus('');

    // Open deploy log in Console panel
    const deployLogId = `chi:${chameleonSliceData.name || selectedChameleonSliceId}`;
    setOpenBootLogSlices(prev => prev.includes(deployLogId) ? prev : [...prev, deployLogId]);
    setConsoleExpanded(true);
    setSliceBootLogs(prev => ({ ...prev, [deployLogId]: [] }));
    setSliceBootRunning(prev => ({ ...prev, [deployLogId]: true }));
    const log = (type: string, message: string) => appendBuildLog(deployLogId, { type, message });
    log('deploy', `Starting Chameleon deployment for "${chameleonSliceData.name}"...`);
    log('build', `Sites: ${chiDraftSites.join(', ')} | Nodes: ${chameleonSliceData.nodes.length} | Mode: ${chiDeployMode}`);

    try {
      // Build site→leaseId map
      const leaseMap: Record<string, string> = {};

      if (chiDeployMode === 'existing-lease') {
        if (!chiExistingLeaseId) { setErrors(prev => [...prev, 'Select an existing lease']); setChiLeaseDeploying(false); return; }
        for (const s of chiDraftSites) leaseMap[s] = chiExistingLeaseId;
        setChiDeployStatus('Using existing lease...');
        log('step', `Using existing lease ${chiExistingLeaseId}`);
      } else {
        // Create leases from draft (one per site)
        setChiDeployStatus(`Creating lease${chiDraftSites.length > 1 ? 's' : ''}...`);
        log('build', `Creating lease${chiDraftSites.length > 1 ? 's' : ''} (${chiDraftSites.join(', ')})...`);
        const result = await api.deployChameleonDraft(selectedChameleonSliceId, {
          duration_hours: chiLeaseDuration,
          ...(chiLeaseStartNow ? {} : { start_date: chiLeaseStartDate }),
        });

        for (const l of result.leases) {
          leaseMap[l.site] = l.lease_id;
          log('step', `Lease created at ${l.site}: ${l.lease_name || l.lease_id} (${l.status})`);
        }
        if (result.errors?.length) {
          for (const err of result.errors) log('error', `Lease error: ${err}`);
        }

        if (chiDeployMode === 'lease-only') {
          setChiDeployStatus(`${result.leases.length} lease${result.leases.length !== 1 ? 's' : ''} created.`);
          log('progress', `\u2713 ${result.leases.length} lease${result.leases.length !== 1 ? 's' : ''} created (lease-only mode)`);
          setSliceBootRunning(prev => ({ ...prev, [deployLogId]: false }));
          setShowChameleonLeaseDialog(false);
          handleRefreshChameleonSlices();
          setChiLeaseDeploying(false);
          return;
        }

        // Auto-deploy: wait for ALL leases to become ACTIVE
        setChiDeployStatus('Waiting for leases to become ACTIVE...');
        log('build', 'Waiting for leases to become ACTIVE...');
        let allActive = false;
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 5000));
          const statuses: Record<string, string> = {};
          for (const [site, leaseId] of Object.entries(leaseMap)) {
            try {
              const lease = await api.getChameleonLease(leaseId, site);
              statuses[site] = lease.status;
              if (lease.status === 'ERROR') throw new Error(`Lease at ${site} entered ERROR state`);
            } catch (e: any) {
              if (e.message.includes('ERROR')) throw e;
              statuses[site] = 'UNKNOWN';
            }
          }
          const statusStr = Object.entries(statuses).map(([s, st]) => `${s}: ${st}`).join(', ');
          setChiDeployStatus(`Waiting for ACTIVE... (${statusStr}, ${i * 5}s)`);
          if (i % 6 === 0) log('step', `Lease status: ${statusStr} (${i * 5}s)`);
          if (Object.values(statuses).every(s => s === 'ACTIVE')) { allActive = true; break; }
        }
        if (!allActive) throw new Error('Leases did not all become ACTIVE within 5 minutes');
        log('step', '\u2713 All leases ACTIVE');
      }

      // Get reservation IDs per site
      setChiDeployStatus('Getting reservation details...');
      log('step', 'Getting reservation details...');
      const reservationMap: Record<string, string> = {};
      for (const [site, leaseId] of Object.entries(leaseMap)) {
        try {
          const leaseDetails = await api.getChameleonLease(leaseId, site);
          const hostRes = (leaseDetails.reservations || []).find(
            (r: any) => r.resource_type === 'physical:host' || (!r.resource_type && r.id)
          );
          if (hostRes) {
            reservationMap[site] = hostRes.id;
            log('step', `Reservation at ${site}: ${hostRes.id.slice(0, 12)}...`);
          }
        } catch { /* proceed without */ }
      }

      // Ensure SSH keypair exists at each site AND we have the private key
      log('step', 'Ensuring SSH keypair at each site...');
      const keypairName = 'loomai-key';
      for (const site of Object.keys(leaseMap)) {
        try {
          const result = await api.ensureChameleonKeypair(site);
          log('step', `SSH keypair "${keypairName}" at ${site}: ${result.status}`);
        } catch (e: any) {
          log('error', `SSH keypair at ${site}: ${e.message}`);
        }
      }

      // Ensure routable networks for floating IPs
      const hasFips = (chameleonSliceData.floating_ips || []).length > 0;
      const siteNetworkMap: Record<string, string> = {};
      if (hasFips) {
        log('step', 'Ensuring routable networks for floating IP access...');
        for (const site of Object.keys(leaseMap)) {
          try {
            const netResult = await api.ensureChameleonNetwork(site);
            siteNetworkMap[site] = netResult.network_id;
            log('step', `Network at ${site}: ${netResult.network_name} (${netResult.type})`);
          } catch (e: any) {
            log('error', `Network setup at ${site}: ${e.message}`);
          }
        }
      }

      // Deploy instances — each node uses its own site's lease/reservation
      setChiDeployStatus('Launching instances...');
      log('build', `Launching ${chameleonSliceData.nodes.length} instance${chameleonSliceData.nodes.length !== 1 ? 's' : ''}...`);
      let launched = 0;
      for (const node of chameleonSliceData.nodes) {
        const nodeSite = node.site;
        const nodeLeaseId = leaseMap[nodeSite];
        if (!nodeLeaseId) {
          log('error', `No lease for ${node.name} at ${nodeSite}`);
          setErrors(prev => [...prev, `No lease for ${node.name} at ${nodeSite}`]);
          continue;
        }
        // Collect network IDs from per-node interfaces (multi-NIC) or fallback
        const ifaces = (node as any).interfaces;
        const networkIds: string[] = [];
        if (ifaces && Array.isArray(ifaces)) {
          for (const ifc of ifaces) {
            if (ifc.network?.id) networkIds.push(ifc.network.id);
          }
        }
        if (networkIds.length === 0) {
          // Legacy fallback: single network field or site-level
          const fallback = (node as any).network?.id || siteNetworkMap[nodeSite] || chiSelectedNetworkId;
          if (fallback) networkIds.push(fallback);
        }
        const networkId = networkIds.length === 1 ? networkIds[0] : undefined;
        try {
          log('node', `Launching ${node.name} at ${nodeSite}...`);
          const instance = await api.createChameleonInstance({
            site: nodeSite,
            name: node.name,
            lease_id: nodeLeaseId,
            image_id: node.image || 'CC-Ubuntu22.04',
            key_name: keypairName,
            ...(reservationMap[nodeSite] ? { reservation_id: reservationMap[nodeSite] } : {}),
            ...(networkIds.length > 1 ? { network_ids: networkIds } : networkId ? { network_id: networkId } : {}),
          });
          launched++;
          log('step', `\u2713 ${node.name} launched (${instance.id?.slice(0, 12) || '?'}...)`);
          // Track instance in slice resources (best-effort)
          try {
            await api.addChameleonSliceResource(selectedChameleonSliceId, {
              type: 'instance',
              id: instance.id || '',
              name: node.name,
              site: nodeSite,
              image: node.image || 'CC-Ubuntu22.04',
              lease_id: nodeLeaseId,
            });
          } catch { /* best-effort tracking */ }
          setChiDeployStatus(`Launching instances... (${launched}/${chameleonSliceData.nodes.length})`);
        } catch (e: any) {
          log('error', `Failed to launch ${node.name}: ${e.message}`);
          setErrors(prev => [...prev, `Failed to launch ${node.name}: ${e.message}`]);
        }
      }

      setChiDeployStatus(`Deployed (${launched} instance${launched !== 1 ? 's' : ''} launched)`);

      // Auto-bastion: if any nodes don't have floating IP, create a bastion for SSH access
      const fipNodeIds = new Set(chameleonSliceData.floating_ips || []);
      const nodesWithoutFip = chameleonSliceData.nodes.filter(n => !fipNodeIds.has(n.id));
      if (nodesWithoutFip.length > 0 && launched > 0) {
        for (const site of Object.keys(leaseMap)) {
          log('step', `Ensuring bastion at ${site} for SSH access to private nodes...`);
          try {
            const bastionResult = await api.ensureChameleonBastion(selectedChameleonSliceId, {
              site,
              experiment_net_id: siteNetworkMap[site] || chiSelectedNetworkId || '',
              reservation_id: reservationMap[site] || '',
            });
            if (bastionResult.floating_ip) {
              log('step', `\u2713 Bastion at ${site}: ${bastionResult.floating_ip} (${bastionResult.status})`);
            }
          } catch (e: any) {
            log('error', `Bastion at ${site}: ${e.message}`);
          }
        }
      }

      // Auto-setup networking (security groups + floating IPs)
      // This waits for instances to become ACTIVE, which can take 10+ min for bare-metal.
      // Run it but don't block the entire deploy on it — the user can also assign FIPs manually.
      if ((chameleonSliceData.floating_ips || []).length > 0 || launched > 0) {
        log('build', 'Setting up network access (security groups + floating IPs)...');
        log('step', 'Waiting for instances to become ACTIVE (this may take several minutes for bare-metal)...');
        try {
          const netSetup = await api.autoNetworkSetup(selectedChameleonSliceId);
          for (const entry of netSetup.results) {
            if (entry.error) {
              log('error', `${entry.name}: ${entry.error}`);
            } else if (entry.floating_ip) {
              log('step', `\u2713 ${entry.name} (${entry.site}): floating IP ${entry.floating_ip}`);
            } else {
              log('step', `\u2713 ${entry.name} (${entry.site}): security group applied`);
            }
          }
        } catch (e: any) {
          log('error', `Network setup failed: ${e.message}`);
          log('step', 'You can manually assign floating IPs from the OpenStack tab → Instances → "+ FIP" button');
        }
      }

      // Poll SSH readiness (max 2 min, every 10s)
      if (launched > 0) {
        log('build', 'Waiting for SSH readiness...');
        let allReady = false;
        for (let attempt = 0; attempt < 12; attempt++) {
          await new Promise(r => setTimeout(r, 10000));
          try {
            const readiness = await api.checkSliceReadiness(selectedChameleonSliceId);
            const ready = readiness.results.filter(r => r.ssh_ready);
            const total = readiness.results.filter(r => r.ip).length;
            if (total > 0) {
              log('step', `SSH readiness: ${ready.length}/${total} nodes reachable`);
            }
            // Refresh slice data + graph to show updated state
            api.getChameleonDraft(selectedChameleonSliceId).then(setChameleonSliceData).catch(() => {});
            setChiDraftVersion(v => v + 1);
            if (ready.length > 0 && ready.length >= total) {
              allReady = true;
              break;
            }
          } catch { /* check-readiness not critical */ }
        }
        if (allReady) {
          log('progress', '\u2713 All nodes SSH-ready');
        } else {
          log('build', 'Some nodes not yet SSH-ready (will become available shortly)');
        }

        // Refresh slice data to show updated IPs in topology (Z3)
        try {
          const refreshed = await api.getChameleonDraft(selectedChameleonSliceId);
          setChameleonSliceData(refreshed);
          setChiDraftVersion(v => v + 1);
        } catch {}

        // Auto-run boot config on nodes that have it defined (Z2)
        for (const node of chameleonSliceData.nodes) {
          try {
            const bc = await api.getChameleonBootConfig(selectedChameleonSliceId, node.name);
            if (bc && (bc.commands?.length > 0 || bc.uploads?.length > 0)) {
              log('step', `Running boot config on ${node.name}...`);
              const result = await api.executeChameleonBootConfig(selectedChameleonSliceId, node.name);
              const ok = (result as any).results?.filter((r: any) => r.status === 'ok').length || 0;
              const err = (result as any).results?.filter((r: any) => r.status === 'error').length || 0;
              log('step', `\u2713 Boot config on ${node.name}: ${ok} ok, ${err} errors`);
            }
          } catch (e: any) {
            log('error', `Boot config on ${node.name}: ${e.message}`);
          }
        }
      }

      log('build', `Setting slice state to ${launched > 0 ? 'Active' : 'Error'}...`);

      // Transition slice to Active (or Error if nothing launched)
      try {
        await api.setChameleonSliceState(selectedChameleonSliceId, launched > 0 ? 'Active' : 'Error');
      } catch { /* best-effort */ }

      log('progress', `\u2713 Deployed (${launched} instance${launched !== 1 ? 's' : ''} launched)`);
      setSliceBootRunning(prev => ({ ...prev, [deployLogId]: false }));

      // Trigger immediate graph refresh to show deployed state
      setChiDraftVersion(v => v + 1);

      setTimeout(() => {
        setShowChameleonLeaseDialog(false);
        setChiDeployStatus('');
        handleRefreshChameleonSlices();
      }, 2000);
    } catch (e: any) {
      setChiDeployStatus(`Error: ${e.message}`);
      log('error', `Deployment failed: ${e.message}`);
      setSliceBootRunning(prev => ({ ...prev, [deployLogId]: false }));
      setErrors(prev => [...prev, e.message]);
    }
    setChiLeaseDeploying(false);
  }, [selectedChameleonSliceId, chameleonSliceData, chiDeployMode, chiExistingLeaseId, chiLeaseDuration, chiLeaseStartNow, chiLeaseStartDate, chiDraftSites, chiSelectedNetworkId, handleRefreshChameleonSlices, appendBuildLog]);

  // Expose deploy function via ref so handleSubmitChameleonDraft (defined earlier) can call it
  deployChiRef.current = handleDeployChameleonLease;

  const handleDeleteChameleonDraft = useCallback(async () => {
    if (!selectedChameleonSliceId) return;
    const d = chameleonSlices.find(x => x.id === selectedChameleonSliceId);
    // Draft slices with no deployed resources: simple confirm
    if (d?.state === 'Draft' && (!d.resources || d.resources.length === 0)) {
      if (!window.confirm(`Delete draft "${d?.name}"?`)) return;
      try {
        await api.deleteChameleonDraft(selectedChameleonSliceId);
        setSelectedChameleonSliceId('');
        setChameleonSliceData(null);
        setChameleonSlices(prev => prev.filter(x => x.id !== selectedChameleonSliceId));
      } catch (e: any) { setErrors(prev => [...prev, e.message]); }
    } else {
      // Slice has resources — open the delete dialog
      setChiDeleteMode('release');
      setShowChameleonDeleteDialog(true);
    }
  }, [selectedChameleonSliceId, chameleonSlices]);

  const handleConfirmDeleteChameleon = useCallback(async () => {
    if (!selectedChameleonSliceId) return;
    setChiDeleting(true);
    try {
      const result = await api.deleteChameleonDraft(selectedChameleonSliceId, chiDeleteMode === 'delete-all');
      if (result.cleanup_errors && result.cleanup_errors.length > 0) {
        setErrors(prev => [...prev, ...result.cleanup_errors!.map(e => `Cleanup: ${e}`)]);
      }
      setSelectedChameleonSliceId('');
      setChameleonSliceData(null);
      setChameleonSlices(prev => prev.filter(x => x.id !== selectedChameleonSliceId));
      setShowChameleonDeleteDialog(false);
    } catch (e: any) {
      setErrors(prev => [...prev, e.message]);
    }
    setChiDeleting(false);
  }, [selectedChameleonSliceId, chiDeleteMode]);

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
    lastMutationRef.current = Date.now(); // Switch to ACTIVE polling mode
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
    // Sync resource key for the Details panel
    if (data.element_type === 'site') setSelectedResourceKey(`site:${data.name}`);
    else if (data.element_type === 'infra_link' && data.site_a && data.site_b) {
      setSelectedResourceKey(`link:${data.site_a} \u2194 ${data.site_b}`);
    }
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

  const handleOpenTerminals = useCallback((elements: Record<string, string>[], sliceName?: string) => {
    let counter = terminalIdCounter;
    const newTabs: TerminalTab[] = [];
    const resolvedSlice = sliceName || selectedSliceName;
    for (const el of elements) {
      if (el.element_type === 'node' && el.management_ip) {
        const id = `term-${counter}`;
        counter++;
        newTabs.push({
          id,
          label: el.name,
          sliceName: resolvedSlice,
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

  // Open SSH terminal for a Chameleon instance (bottom panel tab)
  const handleOpenChameleonTerminal = useCallback((instance: { id: string; name: string; site: string }) => {
    const newId = `chi-term-${Date.now()}`;
    setTerminalTabs(prev => [...prev, {
      id: newId,
      label: `${instance.name} (${instance.site})`,
      sliceName: '',
      nodeName: '',
      managementIp: '',
      chameleonInstanceId: instance.id,
      chameleonSite: instance.site,
    }]);
    setConsoleExpanded(true);
  }, []);

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

  // --- Save-weave / save-VM-template modal state ---
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
    setStatusMessage('Saving...');
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

  // --- Save-experiment-template modal state ---
  const [saveExperimentModal, setSaveExperimentModal] = useState(false);
  const [saveExpName, setSaveExpName] = useState('');
  const [saveExpDesc, setSaveExpDesc] = useState('');
  const [saveExpVariables, setSaveExpVariables] = useState<ExperimentVariable[]>([]);
  const [saveExpBusy, setSaveExpBusy] = useState(false);

  const hasFabricNodes = (sliceData?.nodes || []).length > 0;
  const hasChameleonNodes = (sliceData?.chameleon_nodes || []).length > 0;
  const canSaveExperiment = hasFabricNodes && hasChameleonNodes;

  const handleOpenSaveExperiment = useCallback(() => {
    const name = selectedSliceName || '';
    setSaveExpName(name);
    setSaveExpDesc('');
    // Auto-detect variables from the topology
    const vars: ExperimentVariable[] = [
      { name: 'SLICE_NAME', label: 'Slice Name', type: 'string', default: name, required: true },
    ];
    // Detect unique site names from FABRIC nodes
    const fabricSites = new Set<string>();
    for (const n of sliceData?.nodes || []) {
      if (n.site && n.site !== 'auto') fabricSites.add(n.site);
    }
    if (fabricSites.size > 0) {
      vars.push({ name: 'FABRIC_SITE', label: 'FABRIC Site', type: 'site', default: [...fabricSites][0], required: false });
    }
    // Detect unique Chameleon site names
    const chamSites = new Set<string>();
    for (const n of sliceData?.chameleon_nodes || []) {
      if (n.site) chamSites.add(n.site);
    }
    if (chamSites.size > 0) {
      vars.push({ name: 'CHAMELEON_SITE', label: 'Chameleon Site', type: 'chameleon_site', default: [...chamSites][0], required: false });
    }
    // Node counts
    const fabricCount = (sliceData?.nodes || []).length;
    const chamCount = (sliceData?.chameleon_nodes || []).length;
    if (fabricCount > 1) {
      vars.push({ name: 'FABRIC_NODE_COUNT', label: 'FABRIC Nodes', type: 'number', default: fabricCount, required: false });
    }
    if (chamCount > 1) {
      vars.push({ name: 'CHAMELEON_NODE_COUNT', label: 'Chameleon Nodes', type: 'number', default: chamCount, required: false });
    }
    setSaveExpVariables(vars);
    setSaveExperimentModal(true);
  }, [selectedSliceName, sliceData]);

  const handleSaveExperimentConfirm = useCallback(async () => {
    if (!saveExpName.trim()) return;
    setSaveExpBusy(true);
    setStatusMessage('Saving experiment template...');
    try {
      await api.saveExperiment({
        name: saveExpName.trim(),
        description: saveExpDesc.trim(),
        slice_name: selectedSliceId,
        variables: saveExpVariables.filter(v => v.name.trim()),
      });
      setSaveExperimentModal(false);
      setSaveExpName('');
      setSaveExpDesc('');
      setSaveExpVariables([]);
    } catch (e: any) {
      addError(e.message);
    } finally {
      setSaveExpBusy(false);
      setStatusMessage('');
    }
  }, [saveExpName, saveExpDesc, selectedSliceId, saveExpVariables]);

  const handleExpVarChange = useCallback((index: number, field: keyof ExperimentVariable, value: any) => {
    setSaveExpVariables(prev => prev.map((v, i) => i === index ? { ...v, [field]: value } : v));
  }, []);

  const handleAddExpVar = useCallback(() => {
    setSaveExpVariables(prev => [...prev, { name: '', label: '', type: 'string', default: '', required: false }]);
  }, []);

  const handleRemoveExpVar = useCallback((index: number) => {
    setSaveExpVariables(prev => prev.filter((_, i) => i !== index));
  }, []);

  // --- Experiment variable substitution popup (for loading experiment templates) ---
  const [experimentVarsPopup, setExperimentVarsPopup] = useState<{
    templateName: string;
    dirName: string;
    variables: ExperimentVariable[];
  } | null>(null);
  const [experimentVarValues, setExperimentVarValues] = useState<Record<string, string>>({});

  const handleLoadExperiment = useCallback(async (name: string, dirName: string) => {
    try {
      const template = await api.getExperimentTemplate(dirName);
      if (template.variables && template.variables.length > 0) {
        const defaults: Record<string, string> = {};
        for (const v of template.variables) {
          defaults[v.name] = String(v.default ?? '');
        }
        setExperimentVarValues(defaults);
        setExperimentVarsPopup({ templateName: name, dirName, variables: template.variables });
      } else {
        // No variables, load directly
        setLoading(true);
        setStatusMessage('Loading experiment template...');
        const result = await api.loadExperiment(dirName);
        updateSliceAndValidate(result);
        setSlices((prev) => {
          if (result.id && prev.some((s) => s.id === result.id)) return prev;
          return [...prev, { name: result.name, id: result.id, state: 'Draft' }];
        });
        setSelectedSliceId(result.id);
        setLoading(false);
        setStatusMessage('');
      }
    } catch (e: any) {
      addError(e.message);
      setLoading(false);
      setStatusMessage('');
    }
  }, [updateSliceAndValidate]);

  const handleExperimentVarsSubmit = useCallback(async () => {
    if (!experimentVarsPopup) return;
    setLoading(true);
    setStatusMessage('Loading experiment with variables...');
    try {
      const sliceName = experimentVarValues['SLICE_NAME'] || experimentVarsPopup.templateName;
      const result = await api.loadExperiment(experimentVarsPopup.dirName, sliceName, experimentVarValues);
      updateSliceAndValidate(result);
      setSlices((prev) => {
        if (result.id && prev.some((s) => s.id === result.id)) return prev;
        return [...prev, { name: result.name, id: result.id, state: 'Draft' }];
      });
      setSelectedSliceId(result.id);
      setExperimentVarsPopup(null);
      setExperimentVarValues({});
    } catch (e: any) {
      addError(e.message);
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [experimentVarsPopup, experimentVarValues, updateSliceAndValidate]);

  const handleContextAction = useCallback((action: ContextMenuAction) => {
    if (action.type === 'terminal') {
      handleOpenTerminals(action.elements, action.sliceNames?.[0]);
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
    } else if (action.type === 'chi-ssh' && action.instanceId && action.instanceSite) {
      handleOpenChameleonTerminal({ id: action.instanceId, name: action.instanceName || '', site: action.instanceSite });
    } else if (action.type === 'chi-reboot' && action.instanceId && action.instanceSite) {
      api.rebootChameleonInstance(action.instanceId, action.instanceSite).catch((e: any) => setErrors(prev => [...prev, `Reboot failed: ${e.message}`]));
    } else if (action.type === 'chi-stop' && action.instanceId && action.instanceSite) {
      api.stopChameleonInstance(action.instanceId, action.instanceSite).catch((e: any) => setErrors(prev => [...prev, `Stop failed: ${e.message}`]));
    } else if (action.type === 'chi-start' && action.instanceId && action.instanceSite) {
      api.startChameleonInstance(action.instanceId, action.instanceSite).catch((e: any) => setErrors(prev => [...prev, `Start failed: ${e.message}`]));
    } else if (action.type === 'chi-delete' && action.instanceId && action.instanceSite) {
      api.deleteChameleonInstance(action.instanceId, action.instanceSite).catch((e: any) => setErrors(prev => [...prev, `Delete failed: ${e.message}`]));
    } else if (action.type === 'chi-assign-fip' && action.instanceId && action.instanceSite) {
      api.assignChameleonFloatingIp(action.instanceId, action.instanceSite)
        .then(() => { setChiDraftVersion(v => v + 1); })
        .catch((e: any) => setErrors(prev => [...prev, `Floating IP failed: ${e.message}`]));
    } else if (action.type === 'chi-open-web' && action.instanceId && action.instanceSite) {
      // Find the instance's floating IP and open in browser
      const inst = chameleonInstances.find(i => i.id === action.instanceId);
      if (inst?.floating_ip) {
        window.open(`http://${inst.floating_ip}`, '_blank');
      }
    } else if (action.type === 'chi-apply-recipe' && action.recipeName && action.instanceId && action.instanceSite) {
      // Execute recipe on Chameleon instance via SSH
      const instName = action.instanceName || action.instanceId;
      setConsoleExpanded(true);
      appendBuildLog(instName, { type: 'build', message: `Running recipe "${action.recipeName}" on ${instName}...` });
      api.executeChameleonRecipe(action.instanceId, action.instanceSite, action.recipeName)
        .then((result: any) => {
          appendBuildLog(instName, { type: 'build', message: `Recipe complete: ${result.status || 'done'}` });
        })
        .catch((e: any) => {
          appendBuildLog(instName, { type: 'error', message: `Recipe failed: ${e.message}` });
          setErrors(prev => [...prev, `Recipe failed: ${e.message}`]);
        });
    } else if (action.type === 'chi-run-boot-config' && action.instanceId && action.instanceSite) {
      const instName = action.instanceName || action.instanceId;
      setConsoleExpanded(true);
      appendBuildLog(instName, { type: 'build', message: `Running boot config on ${instName}...` });
      api.executeChameleonBootConfig(selectedChameleonSliceId, instName)
        .then(() => appendBuildLog(instName, { type: 'build', message: `Boot config complete for ${instName}` }))
        .catch((e: any) => {
          appendBuildLog(instName, { type: 'error', message: `Boot config failed: ${e.message}` });
          setErrors(prev => [...prev, `Boot config failed: ${e.message}`]);
        });
    } else if (action.type === 'chi-save-template' && action.instanceName) {
      // Reuse the FABRIC save-template modal for Chameleon nodes
      handleSaveVmTemplate(action.instanceName);
    } else if (action.type === 'run-boot-config' && action.sliceNames && action.sliceNames.length > 0) {
      handleRunFullBootConfigPipeline(action.sliceNames[0]);
    } else if (action.type === 'run-boot-config-node' && action.nodeName && selectedSliceName) {
      setConsoleExpanded(true);
      appendBuildLog(selectedSliceName, { type: 'build', message: `Running boot config on ${action.nodeName}...` });
      api.executeBootConfig(selectedSliceName, action.nodeName)
        .then(() => appendBuildLog(selectedSliceName, { type: 'build', message: `\u2713 Boot config complete for ${action.nodeName}` }))
        .catch((e: any) => {
          appendBuildLog(selectedSliceName, { type: 'error', message: `Boot config failed for ${action.nodeName}: ${e.message}` });
          setErrors(prev => [...prev, `Boot config failed for ${action.nodeName}: ${e.message}`]);
        });
    }
  }, [handleOpenTerminals, handleDeleteElements, handleDeleteSliceByName, handleRefreshSlices, handleDeleteComponent, handleDeleteFacilityPort, handleSaveVmTemplate, handleExecuteRecipe, selectedSliceId, handleOpenChameleonTerminal, handleRunFullBootConfigPipeline, selectedSliceName, appendBuildLog]);

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

  // Separate handler for composite view — refreshes composite graph after edits
  const handleCompositeSliceUpdated = useCallback((data: SliceData) => {
    setSliceData(data);
    if (selectedCompositeSliceId) {
      api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
    }
  }, [selectedCompositeSliceId]);

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
    // Clear errors from previous operations
    setErrors([]);
    setLoading(true);
    setStatusMessage('Loading weave template...');
    lastMutationRef.current = Date.now(); // Switch to ACTIVE polling mode

    // Schedule a forced-fresh refresh after 10s (gives weave time to create slices)
    setTimeout(() => { lastMutationRef.current = Date.now(); }, 10000);

    // Mark this weave as deploying (for LibrariesPanel button state)
    setDeployingWeaves(prev => new Set(prev).add(templateDirName));
    // Mark as GUI-submitted so polling auto-runs boot config
    guiSubmittedRef.current.add(sliceNameForDeploy);

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
      // Don't switch view tab — let the user stay on their current view.
      // Build log output appears in the console panel (bottom) regardless.
      setSlices((prev) => {
        if (sliceId && prev.some((s) => s.id === sliceId)) return prev;
        return [...prev, { name: data.name, id: sliceId, state: 'Draft' }];
      });
      appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Weave loaded as draft slice' });

      // Step 2: Submit the slice (composite if Chameleon nodes present)
      const weaveChameleon = (data.chameleon_nodes || []).length > 0;
      setStatusMessage(weaveChameleon ? 'Submitting composite slice (FABRIC + Chameleon)...' : 'Submitting slice to FABRIC...');
      appendBuildLog(sliceNameForDeploy, { type: 'build', message: weaveChameleon ? 'Submitting composite slice (FABRIC + Chameleon)...' : 'Submitting slice to FABRIC...' });
      let submitted: SliceData;
      if (weaveChameleon) {
        const compositeResult = await api.submitCompositeSlice(sliceId);
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: `Composite: FABRIC=${compositeResult.fabric_status}, Chameleon=${compositeResult.chameleon_status || 'N/A'}` });
        if (compositeResult.chameleon_error) appendBuildLog(sliceNameForDeploy, { type: 'error', message: `Chameleon: ${compositeResult.chameleon_error}` });
        if (compositeResult.fabric_error) appendBuildLog(sliceNameForDeploy, { type: 'error', message: `FABRIC: ${compositeResult.fabric_error}` });
        submitted = compositeResult.fabric_slice || await api.getSlice(sliceId);
      } else {
        submitted = await api.submitSlice(sliceId);
      }
      if (submitted.id && submitted.id !== sliceId) {
        setSelectedSliceId(submitted.id);
        // Update composite slices that reference the old draft ID
        api.replaceCompositeFabricMember(sliceId, submitted.id).catch(() => {});
      }
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
        setDeployingWeaves(prev => { const next = new Set(prev); next.delete(templateDirName); return next; });
      } else if (POLL_STATES.has(refreshedData.state || '')) {
        appendBuildLog(sliceNameForDeploy, { type: 'build', message: 'Waiting for slice to become ready...' });
        startPolling(true);
        // deployingWeaves stays set — will be cleared when polling detects completion
      } else {
        setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: false }));
        setDeployingWeaves(prev => { const next = new Set(prev); next.delete(templateDirName); return next; });
      }
    } catch (e: any) {
      appendBuildLog(sliceNameForDeploy, { type: 'error', message: `Deploy failed: ${e.message}` });
      addError(e.message);
      setSliceBootRunning(prev => ({ ...prev, [sliceNameForDeploy]: false }));
      setDeployingWeaves(prev => { const next = new Set(prev); next.delete(templateDirName); return next; });
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  }, [appendBuildLog, startPolling, handleRunBootConfigStream]);

  // Run weave script: execute weave.sh as a background run (survives browser disconnect)
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
            appendBuildLog(logKey, { type: 'build', message: '\u2713 weave script complete' });
          } else {
            appendBuildLog(logKey, { type: 'error', message: `weave script exited (status: ${resp.status})` });
          }
          setSliceBootRunning(prev => ({ ...prev, [logKey]: false }));
          // Refresh active runs list so LibrariesPanel updates the badge
          api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
        }
      } catch {
        // Network error — keep polling, we might reconnect
      }
    };

    // Poll immediately, then every 5 seconds
    poll();
    const timer = setInterval(poll, 5000);
    runPollTimers.current.set(runId, timer);
  }, [appendBuildLog]);

  const handleRunWeaveScript = useCallback((templateDirName: string, weaveName: string, args: Record<string, string>) => {
    const logKey = `run:${weaveName}`;

    // Clear errors from previous runs
    setErrors([]);
    lastMutationRef.current = Date.now(); // Switch to ACTIVE polling mode

    // Schedule a forced-fresh refresh after 10s (gives weave time to create slices)
    setTimeout(() => { lastMutationRef.current = Date.now(); }, 10000);

    // Open build log tab for this run
    setOpenBootLogSlices(prev => prev.includes(logKey) ? prev : [...prev, logKey]);
    setConsoleExpanded(true);
    setSliceBootRunning(prev => ({ ...prev, [logKey]: true }));
    setSliceBootLogs(prev => ({ ...prev, [logKey]: [] }));
    appendBuildLog(logKey, { type: 'build', message: `Executing weave script from "${weaveName}" (background)...` });

    // Start as background run — "auto" resolves script from weave.json
    api.startBackgroundRun(templateDirName, 'auto', args).then((resp) => {
      appendBuildLog(logKey, { type: 'build', message: `Run started: ${resp.run_id}` });
      pollBackgroundRun(resp.run_id, logKey);
      // Refresh active runs list so LibrariesPanel shows the running badge
      api.listBackgroundRuns().then(setActiveRuns).catch(() => {});
    }).catch((err) => {
      appendBuildLog(logKey, { type: 'error', message: `Failed to start: ${err.message}` });
      setSliceBootRunning(prev => ({ ...prev, [logKey]: false }));
    });
  }, [appendBuildLog, pollBackgroundRun]);

  // Orchestrated run: deploy first (if weave has a topology), wait, then run weave.sh
  // Stores pending run-after-deploy info keyed by slice name
  const pendingRunAfterDeploy = useRef<Map<string, { templateDirName: string; weaveName: string; args: Record<string, string> }>>(new Map());

  const handleRunExperiment = useCallback((templateDirName: string, weaveName: string, args: Record<string, string>) => {
    const sliceName = args.SLICE_NAME || weaveName || templateDirName;
    // Clear errors from previous runs
    setErrors([]);
    // Stash the run info — will trigger after deploy completes
    pendingRunAfterDeploy.current.set(sliceName, { templateDirName, weaveName, args });
    // Start deploy
    handleDeployWeave(templateDirName, sliceName, args);
  }, [handleDeployWeave]);

  // Watch for deploy completion and auto-trigger pending weave.sh
  useEffect(() => {
    for (const [sliceName, runInfo] of pendingRunAfterDeploy.current.entries()) {
      const stillRunning = sliceBootRunning[sliceName];
      if (stillRunning === false) {
        // Deploy finished — check if it was successful (has log entries, last one is success)
        const logs = sliceBootLogs[sliceName] || [];
        const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;
        const deploySucceeded = lastLog?.message?.includes('Deploy complete') || lastLog?.message?.includes('Build complete');
        pendingRunAfterDeploy.current.delete(sliceName);
        // Clear deploying state for this weave
        setDeployingWeaves(prev => { const next = new Set(prev); next.delete(runInfo.templateDirName); return next; });
        if (deploySucceeded) {
          appendBuildLog(sliceName, { type: 'build', message: 'Deploy succeeded — starting weave script...' });
          handleRunWeaveScript(runInfo.templateDirName, runInfo.weaveName, runInfo.args);
        } else {
          appendBuildLog(sliceName, { type: 'error', message: 'Deploy did not complete successfully — skipping weave script' });
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
    // Only polls when tab is visible and there are running jobs
    const runsInterval = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      api.listBackgroundRuns().then(runs => {
        setActiveRuns(runs);
        // No need to keep polling if nothing is running — the next
        // user action (start run, view runs) will refresh the list
      }).catch(() => {});
    }, 30_000);

    return () => {
      clearInterval(runsInterval);
      // Cleanup poll timers on unmount
      for (const timer of runPollTimers.current.values()) clearInterval(timer);
      runPollTimers.current.clear();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // View output of a running or completed weave run — fetches full log from weave dir
  const handleViewRunOutput = useCallback((dirName: string, weaveName: string) => {
    const logKey = `run:${weaveName}`;
    setOpenBootLogSlices(prev => prev.includes(logKey) ? prev : [...prev, logKey]);
    setConsoleExpanded(true);
    // Fetch full log from offset 0 via weave-log endpoint
    setSliceBootLogs(prev => ({ ...prev, [logKey]: [] }));
    api.getWeaveLog(dirName, 0).then((resp) => {
      if (resp.output) {
        const lines = resp.output.split('\n');
        const logLines = lines
          .filter(line => line)
          .map(line => line.startsWith('### PROGRESS:')
            ? { type: 'build' as const, message: `\u25B6 ${line.slice(13).trim()}` }
            : { type: 'output' as const, message: line });
        setSliceBootLogs(prev => ({ ...prev, [logKey]: logLines }));
      }
    }).catch(() => {});
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
    setJupyterMounted(true);
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

  // --- Memoized values and stable callbacks for panel props ---
  const sliceContextJson = useMemo(
    () => sliceData ? JSON.stringify(sliceData, null, 2) : undefined,
    [sliceData]
  );

  const handleViewChange = useCallback((v: TopView) => {
    if (v === 'jupyter') setJupyterMounted(true);
    setCurrentView(v);
  }, []);

  const handleRecipesChanged = useCallback(() => {
    api.listRecipes().then(setRecipes).catch(() => {});
  }, []);

  const handleClearErrors = useCallback(() => {
    setErrors([]);
    setValidationIssues([]);
    setValidationValid(false);
  }, []);

  const handleClearBootConfigErrors = useCallback(() => setBootConfigErrors([]), []);

  const handleClearRecipeConsole = useCallback(() => setRecipeConsole([]), []);

  const handleClearSliceBootLog = useCallback((sn: string) => {
    setSliceBootLogs(prev => { const next = { ...prev }; delete next[sn]; return next; });
  }, []);

  const handleCollapseEditor = useCallback(() => toggleCollapse('editor'), [toggleCollapse]);
  const handleCollapseTemplate = useCallback(() => toggleCollapse('template'), [toggleCollapse]);
  const handleCollapseChat = useCallback(() => toggleCollapse('chat'), [toggleCollapse]);
  const handleCollapseConsole = useCallback(() => toggleCollapse('console'), [toggleCollapse]);
  const handleCollapseDetails = useCallback(() => toggleCollapse('details'), [toggleCollapse]);

  const handleToggleDark = useCallback(() => setDark((d) => !d), []);
  const handleToggleSettings = useCallback(() => setSettingsOpen((prev) => !prev), []);
  const handleGoHome = useCallback(() => setCurrentView('landing'), []);
  const handleOpenHelpCb = useCallback(() => handleOpenHelp(), [handleOpenHelp]);
  const handleLaunchAiTool = useCallback((toolId: string) => {
    setSelectedAiTool(toolId);
    setCurrentView('ai');
  }, []);

  // --- Panel rendering helpers (shared between left/right panel groups) ---
  const showSidePanels = currentView === 'slices' || currentView === 'artifacts' || currentView === 'infrastructure' || currentView === 'chameleon' || currentView === 'jupyter';
  // In artifacts view, only show chat and console panels (not editor/template)
  // In chameleon view, show all panels (editor panel shows Chameleon infrastructure editing)
  // Details panel only visible in infrastructure view
  const visiblePanelIds: PanelId[] = currentView === 'artifacts'
    ? PANEL_IDS.filter(id => id === 'chat' || id === 'console')
    : PANEL_IDS.filter(id => id !== 'details' || currentView === 'infrastructure');

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
        // Composite view: show CompositeEditorPanel with member management
        if (currentView === 'slices') {
          return (
            <div key="composite-editor" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <div {...dragProps} className="panel-header" style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, cursor: 'grab', background: 'var(--fabric-bg-tint)', borderBottom: '1px solid var(--fabric-border)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>{icon}</span> Composite Editor
                <button onClick={handleCollapseEditor} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, color: 'var(--fabric-text-muted)' }}>×</button>
              </div>
              <div style={{ flex: 1, overflow: 'auto' }}>
                <CompositeEditorPanel
                  compositeSliceId={selectedCompositeSliceId}
                  compositeSlice={compositeSlices.find(s => s.id === selectedCompositeSliceId) || null}
                  fabricSlices={slices.map(s => ({ id: s.id || s.name, name: s.name, state: s.state }))}
                  chameleonSlices={chameleonSlices}
                  chameleonEnabled={chameleonEnabled}
                  chameleonSites={chameleonSites}
                  sites={infraSites}
                  images={images}
                  componentModels={componentModels}
                  onFabricSliceUpdated={(data) => { setSliceData(data); handleSliceUpdated(data); }}
                  onMembersUpdated={(updated) => {
                    setCompositeSlices(prev => prev.map(s => s.id === updated.id ? updated : s));
                    // Immediately refresh graph when members change
                    if (selectedCompositeSliceId) {
                      api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
                    }
                  }}
                  onCompositeGraphRefresh={() => {
                    if (selectedCompositeSliceId) {
                      api.getCompositeSlice(selectedCompositeSliceId).then(data => {
                        setCompositeSlices(prev => prev.map(s => s.id === data.id ? data : s));
                      }).catch(() => {});
                      api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
                    }
                  }}
                  onError={(msg) => addError(msg)}
                  onSwitchToSlice={(testbed, sliceId) => {
                    if (testbed === 'fabric') {
                      setSelectedSliceId(sliceId);
                      setCurrentView('infrastructure');
                    } else {
                      setSelectedChameleonSliceId(sliceId);
                      setCurrentView('chameleon');
                    }
                  }}
                  onCreateSlice={async (testbed) => {
                    const name = prompt(`New ${testbed === 'fabric' ? 'FABRIC' : 'Chameleon'} slice name:`);
                    if (!name) return;
                    try {
                      if (testbed === 'fabric') {
                        const data = await api.createSlice(name);
                        // Refresh FABRIC slice list so the new slice appears in FABRIC view
                        handleRefreshSlices();
                        // Auto-add to composite
                        const sliceId = data.id || name;
                        const newFab = [...(compositeSlices.find(s => s.id === selectedCompositeSliceId)?.fabric_slices || []), sliceId];
                        await api.updateCompositeMembers(selectedCompositeSliceId, newFab, compositeSlices.find(s => s.id === selectedCompositeSliceId)?.chameleon_slices || []);
                        api.getCompositeSlice(selectedCompositeSliceId).then(d => setCompositeSlices(prev => prev.map(s => s.id === d.id ? d : s))).catch(() => {});
                        api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
                      } else {
                        const data = await api.createChameleonSlice({ name, site: chameleonSites?.[0]?.name || 'CHI@TACC' });
                        setChameleonSlices(prev => [...prev, data]);
                        // Auto-add to composite
                        const newChi = [...(compositeSlices.find(s => s.id === selectedCompositeSliceId)?.chameleon_slices || []), data.id];
                        await api.updateCompositeMembers(selectedCompositeSliceId, compositeSlices.find(s => s.id === selectedCompositeSliceId)?.fabric_slices || [], newChi);
                        api.getCompositeSlice(selectedCompositeSliceId).then(d => setCompositeSlices(prev => prev.map(s => s.id === d.id ? d : s))).catch(() => {});
                        api.getCompositeGraph(selectedCompositeSliceId).then(setCompositeGraph).catch(() => {});
                      }
                    } catch (e: any) { addError(e.message); }
                  }}
                  dark={dark}
                />
              </div>
            </div>
          );
        }
        if (currentView === 'chameleon') {
          return (
            <div key="chi-editor-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <div {...dragProps} className="panel-header" style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, cursor: 'grab', background: 'var(--fabric-bg-tint)', borderBottom: '1px solid var(--fabric-border)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>{icon}</span> Chameleon Editor
              </div>
              <div style={{ flex: 1, overflow: 'auto' }}>
                <ChameleonEditor
                  sites={chameleonSites || []}
                  onError={(msg: string) => setErrors(prev => [...prev, msg])}
                  formsOnly
                  draftId={selectedChameleonSliceId}
                  onDraftUpdated={(d: ChameleonDraft) => { setChameleonSliceData(d); setChiDraftVersion(v => v + 1); }}
                  autoRefresh={chameleonAutoRefresh}
                />
              </div>
            </div>
          );
        }
        return (
          <EditorPanel
            key="editor"
            sliceData={sliceData}
            sliceName={selectedSliceName}
            onSliceUpdated={handleSliceUpdated}
            onCollapse={handleCollapseEditor}
            sites={infraSites}
            images={images}
            componentModels={componentModels}
            selectedElement={selectedElement}
            dragHandleProps={dragProps}
            panelIcon={icon}
            vmTemplates={vmTemplates}
            onSaveVmTemplate={handleSaveVmTemplate}
            onBootConfigErrors={setBootConfigErrors}
            onRunBootConfig={handleRunFullBootConfigPipeline}
            bootRunning={!!sliceBootRunning[selectedSliceName]}
            facilityPorts={infraFacilityPorts}
            viewContext="fabric"
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
            deployingWeaves={deployingWeaves}
            onViewRunOutput={handleViewRunOutput}
            onStopRun={handleStopRun}
            onResetArtifact={handleResetArtifact}
            onCollapse={handleCollapseTemplate}
            dragHandleProps={dragProps}
            panelIcon={icon}
            onVmTemplatesChanged={refreshVmTemplates}
            sliceName={selectedSliceName}
            sliceData={sliceData}
            onNodeAdded={updateSliceAndValidate}
            onExecuteRecipe={handleExecuteRecipe}
            executingRecipe={executingRecipeName}
            onRecipesChanged={handleRecipesChanged}
            onLaunchNotebook={handleLaunchNotebook}
            onPublishNotebook={handlePublishNotebook}
            onPublishArtifact={handlePublishArtifact}
            onNavigateToMarketplace={handleNavigateToMarketplace}
            onEditArtifact={handleEditArtifact}
            onLoadExperiment={handleLoadExperiment}
          />
        );
      case 'chat':
        return (
          <AIChatPanel
            key="chat"
            onCollapse={handleCollapseChat}
            dragHandleProps={dragProps}
            panelIcon={icon}
            sliceContext={sliceContextJson}
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
            onClearErrors={handleClearErrors}
            sliceErrors={sliceData?.error_messages ?? []}
            bootConfigErrors={bootConfigErrors}
            onClearBootConfigErrors={handleClearBootConfigErrors}
            recipeConsole={recipeConsole}
            recipeRunning={recipeRunning}
            onClearRecipeConsole={handleClearRecipeConsole}
            sliceBootLogs={sliceBootLogs}
            sliceBootRunning={sliceBootRunning}
            onClearSliceBootLog={handleClearSliceBootLog}
            containerTermActive={true}
            onReceiveExternalTab={handleSideReceiveTab}
            onTabMovedOut={handleSideTabMovedOut}
            onCollapse={handleCollapseConsole}
            dragHandleProps={dragProps}
            panelIcon={icon}
          />
        );
      case 'details':
        return (
          <div key="details-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            <div {...dragProps} className="panel-header" style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, cursor: 'grab', background: 'var(--fabric-bg-tint)', borderBottom: '1px solid var(--fabric-border)', display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span>{icon}</span> Details
              </span>
              <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); handleCollapseDetails(); }} title="Close panel">{'\u2715'}</button>
            </div>
            {/* Searchable resource selector */}
            <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--fabric-border)' }}>
              <select
                className="details-resource-select"
                value={selectedResourceKey}
                onChange={(e) => {
                  const key = e.target.value;
                  setSelectedResourceKey(key);
                  if (!key) { setSelectedElement(null); return; }
                  const [type, ...rest] = key.split(':');
                  const name = rest.join(':');
                  if (type === 'site') {
                    const site = infraSites.find(s => s.name === name);
                    if (site) {
                      setSelectedElement({
                        element_type: 'site', name: site.name, state: site.state,
                        hosts: String(site.hosts), lat: String(site.lat), lon: String(site.lon),
                        cores_available: String(site.cores_available ?? 0),
                        cores_capacity: String(site.cores_capacity ?? 0),
                        ram_available: String(site.ram_available ?? 0),
                        ram_capacity: String(site.ram_capacity ?? 0),
                        disk_available: String(site.disk_available ?? 0),
                        disk_capacity: String(site.disk_capacity ?? 0),
                      });
                    }
                  } else if (type === 'link') {
                    const link = infraLinks.find((l) => `${l.site_a} \u2194 ${l.site_b}` === name);
                    if (link) {
                      setSelectedElement({
                        element_type: 'infra_link',
                        name: `${link.site_a} \u2014 ${link.site_b}`,
                        site_a: link.site_a, site_b: link.site_b,
                      });
                    }
                  }
                }}
                style={{ width: '100%', fontSize: 11, padding: '4px 6px' }}
              >
                <option value="">-- Select Resource --</option>
                <optgroup label="Sites">
                  {infraSites.map(s => <option key={`site:${s.name}`} value={`site:${s.name}`}>{s.name}</option>)}
                </optgroup>
                <optgroup label="Links">
                  {infraLinks.map((l, i) => {
                    const linkLabel = `${l.site_a} \u2194 ${l.site_b}`;
                    return <option key={`link:${linkLabel}`} value={`link:${linkLabel}`}>{linkLabel}</option>;
                  })}
                </optgroup>
              </select>
            </div>
            {/* Detail content */}
            <div style={{ flex: 1, overflow: 'auto' }}>
              <DetailPanel
                sliceData={sliceData}
                selectedElement={selectedElement}
                siteMetricsCache={siteMetricsCache}
                linkMetricsCache={linkMetricsCache}
                metricsRefreshRate={metricsRefreshRate}
                onMetricsRefreshRateChange={setMetricsRefreshRate}
                onRefreshMetrics={refreshMetrics}
                metricsLoading={metricsLoading}
              />
            </div>
          </div>
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
    { id: 'loomai', name: 'LoomAI', icon: '__loomai_icon__' },
    { id: 'aider', name: 'Aider', icon: 'Ai' },
    { id: 'opencode', name: 'OpenCode', icon: 'OC' },
    { id: 'crush', name: 'Crush', icon: 'Cr' },
    { id: 'deepagents', name: 'Deep Agents', icon: 'DA' },
    { id: 'claude', name: 'Claude Code', icon: 'CC' },
  ];
  // LoomAI is always visible; other tools filtered by settings
  const visibleAiTools = AI_TOOL_INFO.filter((t) => t.id === 'loomai' || enabledAiTools[t.id] !== false);

  // Auth gate — show login page before anything else
  if (!authChecked) return null;
  if (needsLogin) {
    return <LoginPage onSuccess={() => setNeedsLogin(false)} />;
  }

  return (
    <>
      <TitleBar
        dark={dark}
        currentView={currentView}
        onToggleDark={handleToggleDark}
        onViewChange={handleViewChange}
        onOpenSettings={handleToggleSettings}
        onOpenHelp={handleOpenHelpCb}
        onGoHome={handleGoHome}
        aiTools={visibleAiTools}
        selectedAiTool={selectedAiTool}
        onLaunchAiTool={handleLaunchAiTool}
        chameleonEnabled={chameleonEnabled}
        compositeEnabled={compositeEnabled}
        hasToken={configStatus?.has_token ?? undefined}
        tokenExpired={configStatus?.has_token && configStatus?.token_info?.exp ? configStatus.token_info.exp * 1000 < Date.now() : false}
        userEmail={configStatus?.token_info?.email}
        userName={configStatus?.token_info?.name}
        onLogout={handleLogout}
      />

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
              setListLoaded(false);
              infraRequestedRef.current = false; sitesRequestedRef.current = false; // re-fetch infra on next tab visit
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
                // Slice list already refreshed above for the new project
              }).catch(() => {});
            }}
            onClose={() => {
              setSettingsOpen(false);
              setListLoaded(false);
              infraRequestedRef.current = false; sitesRequestedRef.current = false; // re-fetch infra on next tab visit
            }}
          />
        </div>
      )}

      {/* FABRIC title bar with tabs — sits above the content grid */}
      {currentView === 'infrastructure' && !(settingsOpen || helpOpen) && (
        <div className="fabric-bar">
          <img src={assetUrl('/fabric_wave_dark.png')} alt="" className="fabric-bar-logo fabric-wave-light-mode" />
          <img src={assetUrl('/fabric_wave_light.png')} alt="" className="fabric-bar-logo fabric-wave-dark-mode" />
          <span className="fabric-bar-title">FABRIC</span>
          {projectName && (
            <span
              className="fabric-bar-project"
              onClick={handleToggleSettings}
              title="Active project — open Settings > Projects to switch"
            >
              {projectName}
            </span>
          )}
          <div className="fabric-bar-tabs">
            {([
              { key: 'table' as InfraSubView, label: 'Slices', needsSlice: false },
              { key: 'topology' as InfraSubView, label: 'Topology', needsSlice: true },
              { key: 'storage' as InfraSubView, label: 'Storage', needsSlice: true },
              { key: 'map' as InfraSubView, label: 'Map', needsSlice: false },
              { key: 'apps' as InfraSubView, label: 'Apps', needsSlice: true },
              { key: 'resources' as InfraSubView, label: 'Resources', needsSlice: false },
              { key: 'calendar' as InfraSubView, label: 'Calendar', needsSlice: false },
            ]).map(t => (
              <button
                key={t.key}
                className={`fabric-bar-tab${infraSubView === t.key ? ' active' : ''}`}
                onClick={() => setInfraSubView(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          {(infraSubView === 'table' || infraSubView === 'topology' || infraSubView === 'map') && (<>
            <select
              className="fabric-bar-slice-select"
              value={selectedSliceId}
              onChange={(e) => {
                const id = e.target.value;
                setSelectedSliceId(id);
              }}
            >
              <option value="">-- Select Slice --</option>
              {slices.filter(s => !['Dead', 'Closing'].includes(s.state)).map(s => (
                <option key={s.id} value={s.id}>{s.name} ({s.state})</option>
              ))}
              {slices.filter(s => ['Dead', 'Closing'].includes(s.state)).length > 0 && (
                <option disabled>── Past ──</option>
              )}
              {slices.filter(s => ['Dead', 'Closing'].includes(s.state)).slice(0, 10).map(s => (
                <option key={s.id} value={s.id}>{s.name} ({s.state})</option>
              ))}
            </select>
            <button className="fabric-bar-action-btn" onClick={async () => {
              const name = prompt('Slice name:');
              if (!name) return;
              try {
                const data = await api.createSlice(name);
                handleSliceUpdated(data);
                setSelectedSliceId(data.id || '');
                setInfraSubView('topology');
                setSlices(prev => {
                  const newId = data.id || '';
                  if (prev.some(s => s.id === newId)) return prev;
                  return [...prev, { name, id: newId, state: 'Draft' }];
                });
              } catch (e: any) { setErrors(prev => [...prev, e.message]); }
            }} title="Create new slice">+ New</button>
            <button className="fabric-bar-action-btn" onClick={async () => {
              if (!selectedSliceId) return;
              handleSubmit();
            }} disabled={!selectedSliceId} title="Submit selected slice">Submit</button>
            <button className="fabric-bar-action-btn" onClick={handleCheckAvailability}
              disabled={!selectedSliceId || checkingAvailability} title="Check if resources are available for this slice">
              {checkingAvailability ? '\u23F3 Checking...' : '\uD83D\uDD0D Availability'}</button>
            <button className="fabric-bar-action-btn fabric-bar-action-danger" onClick={async () => {
              if (!selectedSliceId || !selectedSliceName) return;
              if (!window.confirm(`Delete slice "${selectedSliceName}"?`)) return;
              handleDeleteSlice();
            }} disabled={!selectedSliceId} title="Delete selected slice">Delete</button>
            <button className="fabric-bar-action-btn" onClick={handleRefreshSlices} title="Refresh slices">&#x21BB; Slices</button>
            <select
              className="fabric-bar-action-btn"
              value={pollInterval}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                setPollInterval(val);
                localStorage.setItem('poll-interval', String(val));
              }}
              title="Auto-refresh interval for slice polling"
              style={{ minWidth: 60, cursor: 'pointer' }}
            >
              <option value={0}>Never</option>
              <option value={15000}>15s</option>
              <option value={30000}>30s</option>
              <option value={60000}>1m</option>
              <option value={120000}>2m</option>
              <option value={300000}>5m</option>
            </select>
          </>)}
          {(infraSubView === 'map' || infraSubView === 'resources' || infraSubView === 'calendar') && (
            <button className="fabric-bar-action-btn" onClick={() => refreshInfrastructure(0)} title="Refresh resources">&#x21BB; Resources</button>
          )}
        </div>
      )}

      {/* Chameleon title bar — mirrors FABRIC bar with extracted callbacks */}
      {currentView === 'chameleon' && !(settingsOpen || helpOpen) && chameleonEnabled && (
        <div className="chameleon-bar">
          <img src={assetUrl('/chameleon-icon.png')} alt="" className="chameleon-bar-logo" />
          <span className="chameleon-bar-title">Chameleon</span>
          <div className="chameleon-bar-tabs">
            {([
              { key: 'slices' as ChameleonSubView, label: 'Slices' },
              { key: 'topology' as ChameleonSubView, label: 'Topology' },
              { key: 'map' as ChameleonSubView, label: 'Map' },
              { key: 'calendar' as ChameleonSubView, label: 'Calendar' },
              { key: 'openstack' as ChameleonSubView, label: 'OpenStack' },
            ]).map(t => (
              <button key={t.key} className={`chameleon-bar-tab${chameleonSubView === t.key ? ' active' : ''}`}
                onClick={() => setChameleonSubView(t.key)}>{t.label}</button>
            ))}
          </div>
          <select className="chameleon-bar-select" value={selectedChameleonSliceId}
            onChange={(e) => { setSelectedChameleonSliceId(e.target.value); if (e.target.value) setChameleonSubView('topology'); }}>
            <option value="">-- Select Slice --</option>
            {chameleonSlices.filter(s => !['Terminated', 'Error'].includes(s.state || '') || s.id === selectedChameleonSliceId).map(s => {
              const sites = [...new Set((s.nodes || []).map(n => n.site).filter(Boolean))];
              const siteLabel = sites.length > 0 ? sites.join(', ') : 'no nodes';
              return <option key={s.id} value={s.id}>{s.name} [{s.state}] ({siteLabel})</option>;
            })}
          </select>
          <button className="chameleon-bar-btn" onClick={handleCreateChameleonDraft} title="Create new draft">+ New</button>
          <button className="chameleon-bar-btn" disabled={!selectedChameleonSliceId} onClick={handleSubmitChameleonDraft} title="Deploy as lease">Submit</button>
          <button className="chameleon-bar-btn chameleon-bar-btn-danger" disabled={!selectedChameleonSliceId} onClick={handleDeleteChameleonDraft} title="Delete draft">Delete</button>
          <button className="chameleon-bar-btn chameleon-bar-btn-danger" disabled={chameleonSlices.length === 0} onClick={async () => {
            const drafts = chameleonSlices.filter(s => s.state === 'Draft');
            const all = chameleonSlices;
            const target = drafts.length > 0 && drafts.length < all.length ? drafts : all;
            const label = target.length === drafts.length && drafts.length < all.length ? 'drafts' : 'slices';
            if (!window.confirm(`Delete all ${target.length} ${label}?`)) return;
            for (const s of target) {
              try { await api.deleteChameleonDraft(s.id); } catch {}
            }
            setSelectedChameleonSliceId('');
            setChameleonSliceData(null);
            handleRefreshChameleonSlices();
          }} title="Delete all drafts">Delete All</button>
          <button className="chameleon-bar-btn" onClick={handleRefreshChameleonSlices} title="Refresh slices">&#x21BB; Slices</button>
          <button className={`chameleon-bar-btn ${chameleonAutoRefresh ? 'chi-action-active' : ''}`}
            onClick={() => setChameleonAutoRefresh(prev => !prev)}
            title={chameleonAutoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh'}>
            {chameleonAutoRefresh ? '\u25CF Auto: ON' : '\u25CB Auto: OFF'}
          </button>
        </div>
      )}

      {/* Composite Slice bar — mirrors FABRIC/Chameleon bar with LoomAI indigo */}
      {currentView === 'slices' && !(settingsOpen || helpOpen) && (
        <div className="composite-bar">
          <img src={assetUrl('/composite-slice-icon-transparent.svg')} alt="" className="composite-bar-logo" />
          <span className="composite-bar-title">Composite Slices</span>
          <div className="composite-bar-tabs">
            {([
              { key: 'slices' as SlicesSubView, label: 'Slices' },
              { key: 'topology' as SlicesSubView, label: 'Topology' },
              { key: 'storage' as SlicesSubView, label: 'Storage' },
              { key: 'map' as SlicesSubView, label: 'Map' },
              { key: 'apps' as SlicesSubView, label: 'Apps' },
              { key: 'calendar' as SlicesSubView, label: 'Calendar' },
            ]).map(t => (
              <button
                key={t.key}
                className={`composite-bar-tab${slicesSubView === t.key ? ' active' : ''}`}
                onClick={() => setSlicesSubView(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          {(slicesSubView === 'slices' || slicesSubView === 'topology' || slicesSubView === 'map') && (<>
            <select
              className="composite-bar-select"
              value={selectedCompositeSliceId}
              onChange={async (e) => {
                const id = e.target.value;
                setSelectedCompositeSliceId(id);
                setCompositeGraph(null);
                if (id) {
                  api.getCompositeSlice(id).then(data => {
                    setCompositeSlices(prev => prev.map(s => s.id === data.id ? data : s));
                  }).catch(() => {});
                  api.getCompositeGraph(id).then(setCompositeGraph).catch(err => addError(err.message));
                }
              }}
            >
              <option value="">-- Select Composite Slice --</option>
              {compositeSlices.map(s => (
                <option key={s.id} value={s.id}>{s.name} ({s.state})</option>
              ))}
            </select>
            <button className="composite-bar-btn" onClick={async () => {
              const name = prompt('Composite slice name:');
              if (!name) return;
              try {
                const data = await api.createCompositeSlice(name);
                setCompositeSlices(prev => [...prev, data]);
                setSelectedCompositeSliceId(data.id);
                setSlicesSubView('slices');
              } catch (e: any) { addError(e.message); }
            }} title="Create new composite slice">+ New</button>
            <button className="composite-bar-btn" onClick={async () => {
              if (!selectedCompositeSliceId) return;
              setLoading(true);
              try {
                const result = await api.submitCompositeSliceById(selectedCompositeSliceId);
                if (result.fabric_results) for (const r of result.fabric_results) { if (r.status === 'error') addError(`FABRIC: ${r.error}`); }
                if (result.chameleon_results) for (const r of result.chameleon_results) { if (r.status === 'error') addError(`Chameleon: ${r.error}`); }
                const compId = selectedCompositeSliceId;
                api.getCompositeGraph(compId).then(setCompositeGraph).catch(() => {});
                setTimeout(() => { api.getCompositeGraph(compId).then(setCompositeGraph).catch(() => {}); }, 5000);
                setCompositeSlices(prev => prev.map(s => s.id === compId ? { ...s, state: 'Provisioning' } : s));
              } catch (e: any) { addError(e.message); }
              finally { setLoading(false); }
            }} disabled={!selectedCompositeSliceId || loading} title="Submit composite slice">Submit</button>
            <button className="composite-bar-btn composite-bar-btn-danger" onClick={() => {
              if (!selectedCompositeSliceId) return;
              const name = compositeSlices.find(s => s.id === selectedCompositeSliceId)?.name || '';
              if (!window.confirm(`Delete composite slice "${name}"?`)) return;
              api.deleteCompositeSlice(selectedCompositeSliceId).then(() => {
                setCompositeSlices(prev => prev.filter(s => s.id !== selectedCompositeSliceId));
                setSelectedCompositeSliceId('');
                setCompositeGraph(null);
              }).catch((e: any) => addError(e.message));
            }} disabled={!selectedCompositeSliceId} title="Delete composite slice">Delete</button>
            <button className="composite-bar-btn" onClick={handleRefreshSlices} title="Refresh slices">{'\u21BB'} Slices</button>
            <select
              className="composite-bar-btn"
              value={pollInterval}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                setPollInterval(val);
                localStorage.setItem('poll-interval', String(val));
              }}
              title="Auto-refresh interval for slice polling"
              style={{ minWidth: 60, cursor: 'pointer' }}
            >
              <option value={0}>Never</option>
              <option value={15000}>15s</option>
              <option value={30000}>30s</option>
              <option value={60000}>1m</option>
              <option value={120000}>2m</option>
              <option value={300000}>5m</option>
            </select>
          </>)}
          {(slicesSubView === 'map' || slicesSubView === 'calendar') && (
            <button className="composite-bar-btn" onClick={() => refreshInfrastructure(0)} title="Refresh resources">{'\u21BB'} Resources</button>
          )}
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
            {leftCollapsed.length > 0 && (
              <div className="collapsed-tab-rail">
                {leftCollapsed.map((id) => (
                  <button key={id} className="panel-icon-tab left" onClick={() => toggleCollapse(id)} title={`Show ${PANEL_LABELS[id]}`}>
                    {renderPanelIcon(PANEL_ICONS[id])}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Center column: view content */}
        <div style={{ gridColumn: showSidePanels ? 2 : 1, gridRow: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden', position: 'relative' }}>
          {/* Drop zones for panel drag-and-drop (topology/sliver views only) */}
          {showSidePanels && (
            <>
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

          {/* JupyterLab — mounted once visited, hidden via visibility (not display:none)
              to preserve iframe state and WebSocket connections across view switches */}
          {jupyterMounted && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              ...(currentView === 'jupyter' ? {
                flex: 1,
                minHeight: 0,
              } : {
                position: 'absolute' as const,
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                visibility: 'hidden' as const,
                pointerEvents: 'none' as const,
                zIndex: -1,
              }),
            }}>
              <JupyterLabView initialPath={jupyterPath} dark={dark} />
            </div>
          )}

          {/* View content */}
          {currentView === 'ai' ? null : currentView === 'landing' ? (
            <LandingView
              onNavigate={(view) => setCurrentView(view)}
              onOpenSettings={() => setSettingsOpen(true)}
              listLoaded={listLoaded}
              onLoadSlices={refreshSliceList}
              onStartTour={(id: string) => startTour(id)}
              hasToken={configStatus?.has_token ?? undefined}
              tokenExpired={configStatus?.has_token && configStatus?.token_info?.exp ? configStatus.token_info.exp * 1000 < Date.now() : false}
            />
          ) : currentView === 'jupyter' ? (
            null /* JupyterLabView rendered persistently below */
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
                chameleonEnabled={chameleonEnabled}
                onNavigateToSlicesView={(dirName) => {
                  setCurrentView('slices');
                  // Ensure side panel shows Weaves tab by uncollapsing the template panel
                  setPanelLayout(prev => ({ ...prev, template: { ...prev.template, collapsed: false } }));
                }}
              />
            )
          ) : currentView === 'infrastructure' ? (
            /* FABRIC view — content rendered directly, header is above the grid */
            infraSubView === 'topology' ? (
              <CytoscapeGraph
                graph={sliceData?.graph ?? null}
                layout={layout}
                dark={dark}
                sliceData={sliceData}
                recipes={recipes}
                bootNodeStatus={sliceBootNodeStatus[selectedSliceName] ?? {}}
                preserveLayout
                onLayoutChange={setLayout}
                onNodeClick={handleNodeClick}
                onEdgeClick={handleEdgeClick}
                onBackgroundClick={handleBackgroundClick}
                onContextAction={handleContextAction}
              />
            ) : infraSubView === 'table' ? (
              <AllSliversView
                slices={slices}
                dark={dark}
                selectedSliceId={selectedSliceId}
                onSliceSelect={(id) => {
                  setSelectedSliceId(id);
                  setInfraSubView('topology');
                }}
                onDeleteSlice={handleDeleteSliceByName}
                onRefreshSlices={handleRefreshSlices}
                onArchiveSlice={async (name) => {
                  await api.archiveSlice(name);
                  handleRefreshSlices();
                }}
                onArchiveAllTerminal={async () => {
                  await api.archiveAllTerminal();
                  handleRefreshSlices();
                }}
                onContextAction={handleContextAction}
                nodeActivity={nodeActivity}
                recipes={recipes}
                refreshKey={sliceRefreshKey}
              />
            ) : infraSubView === 'storage' ? (
              <FileTransferView
                sliceName={selectedSliceName}
                sliceData={sliceData}
              />
            ) : infraSubView === 'map' ? (
              <GeoView
                sliceData={selectedSliceId ? sliceData : null}
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
                hideDetail
                chameleonSites={chameleonEnabled ? chameleonSites : undefined}
                chameleonInstances={chameleonEnabled ? chameleonInstances : undefined}
              />
            ) : infraSubView === 'apps' ? (
              <ClientView
                slices={slices}
                selectedSliceName={selectedSliceName}
                sliceData={sliceData}
                clientTarget={clientTarget}
                onTargetChange={setClientTarget}
              />
            ) : infraSubView === 'calendar' ? (
              <ResourceCalendar sites={infraSites} slices={slices} />
            ) : infraSubView === 'resources' ? (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                <div className="resource-category-bar">
                  <button className={`resource-category-btn${resourceCategory === 'sites' ? ' active' : ''}`} onClick={() => setResourceCategory('sites')}>Sites &amp; Hosts</button>
                  <button className={`resource-category-btn${resourceCategory === 'facility-ports' ? ' active' : ''}`} onClick={() => setResourceCategory('facility-ports')}>Facility Ports</button>
                </div>
                <div style={{ flex: 1, overflow: 'auto' }}>
                  {resourceCategory === 'sites' ? (
                    <ResourceBrowser sites={infraSites} />
                  ) : (
                    <FacilityPortsBrowser facilityPorts={infraFacilityPorts} loading={infraLoading} />
                  )}
                </div>
              </div>
            ) : null
          ) : currentView === 'chameleon' ? (
            chameleonSubView === 'topology' ? (
              <ChameleonEditor
                sites={chameleonSites || []}
                onError={(msg: string) => setErrors(prev => [...prev, msg])}
                graphOnly
                draftId={selectedChameleonSliceId}
                draftData={chameleonSliceData}
                draftVersion={chiDraftVersion}
                onContextAction={handleContextAction}
                recipes={recipes}
                autoRefresh={chameleonAutoRefresh}
              />
            ) : chameleonSubView === 'slices' ? (
              <ChameleonSlicesView
                drafts={chameleonSlices}
                leases={chameleonLeases}
                instances={chameleonInstances}
                selectedDraftId={selectedChameleonSliceId}
                onDraftSelect={(id) => { setSelectedChameleonSliceId(id); setChameleonSubView('topology'); }}
                onDeleteDrafts={async (ids) => {
                  for (const id of ids) {
                    try { await api.deleteChameleonDraft(id); } catch {}
                  }
                  if (ids.includes(selectedChameleonSliceId)) {
                    setSelectedChameleonSliceId('');
                    setChameleonSliceData(null);
                  }
                  handleRefreshChameleonSlices();
                }}
                onOpenTerminal={handleOpenChameleonTerminal}
                onRefresh={() => { handleRefreshChameleonSlices(); api.listChameleonLeases().then(setChameleonLeases).catch(() => {}); }}
                loading={false}
              />
            ) : chameleonSubView === 'openstack' ? (
              <ChameleonOpenStackView onError={(msg) => setErrors(prev => [...prev, msg])} onOpenTerminal={handleOpenChameleonTerminal} />
            ) : (
              <ChameleonView
                onError={(msg) => setErrors(prev => [...prev, msg])}
                forcedTab={chameleonSubView}
                hideBar
                onOpenTerminal={handleOpenChameleonTerminal}
              />
            )
          ) : currentView === 'slices' ? (
            slicesSubView === 'topology' ? (
              compositeGraph && (compositeGraph.nodes.length > 0 || compositeGraph.edges.length > 0) ? (
                <CytoscapeGraph
                  graph={compositeGraph}
                  layout={layout}
                  dark={dark}
                  sliceData={null}
                  recipes={recipes}
                  bootNodeStatus={{}}
                  onLayoutChange={setLayout}
                  onNodeClick={handleNodeClick}
                  onEdgeClick={handleEdgeClick}
                  onBackgroundClick={handleBackgroundClick}
                  onContextAction={handleContextAction}
                />
              ) : (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--fabric-text-muted)', fontSize: 13, textAlign: 'center', padding: 40 }}>
                  {selectedCompositeSliceId
                    ? <div><p style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No resources attached</p><p>Attach FABRIC or Chameleon slices to this composite slice to see the unified topology.</p></div>
                    : <div><p style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No composite slice selected</p><p>Select or create a composite slice from the dropdown above.</p></div>
                  }
                </div>
              )
            ) : slicesSubView === 'slices' ? (
              <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
                {compositeSlices.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 40, color: 'var(--fabric-text-muted)', fontSize: 13 }}>
                    <p style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>No composite slices</p>
                    <p>Click "+ New" in the toolbar to create a composite slice.</p>
                  </div>
                ) : (
                  <>
                  {/* Bulk action bar */}
                  {checkedCompositeIds.size > 0 && (
                    <div style={{ padding: '6px 12px', background: 'rgba(39, 170, 225, 0.1)', borderRadius: 6, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ fontWeight: 600 }}>{checkedCompositeIds.size} selected</span>
                      <button
                        style={{ fontSize: 11, padding: '3px 10px', borderRadius: 4, border: '1px solid #e25241', background: 'rgba(226,82,65,0.1)', color: '#e25241', cursor: 'pointer', fontWeight: 600 }}
                        onClick={async () => {
                          if (!window.confirm(`Delete ${checkedCompositeIds.size} composite slice${checkedCompositeIds.size !== 1 ? 's' : ''}? Member slices will NOT be affected.`)) return;
                          for (const id of checkedCompositeIds) {
                            try { await api.deleteCompositeSlice(id); } catch {}
                          }
                          setCompositeSlices(prev => prev.filter(s => !checkedCompositeIds.has(s.id)));
                          setCheckedCompositeIds(new Set());
                          if (checkedCompositeIds.has(selectedCompositeSliceId)) {
                            setSelectedCompositeSliceId('');
                            setCompositeGraph(null);
                          }
                        }}
                      >Delete Selected</button>
                    </div>
                  )}
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: '2px solid var(--fabric-border)', textAlign: 'left' }}>
                        <th style={{ padding: '8px 6px', width: 30 }}>
                          <input
                            type="checkbox"
                            checked={checkedCompositeIds.size === compositeSlices.length && compositeSlices.length > 0}
                            onChange={(e) => {
                              if (e.target.checked) setCheckedCompositeIds(new Set(compositeSlices.map(s => s.id)));
                              else setCheckedCompositeIds(new Set());
                            }}
                            style={{ accentColor: '#27aae1' }}
                          />
                        </th>
                        <th style={{ padding: '8px 12px', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>Name</th>
                        <th style={{ padding: '8px 12px', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>State</th>
                        <th style={{ padding: '8px 12px', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>Members</th>
                        <th style={{ padding: '8px 12px', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--fabric-text-muted)' }}>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {compositeSlices.map(cs => {
                        const isSelected = cs.id === selectedCompositeSliceId;
                        const fabSummaries = cs.fabric_member_summaries || [];
                        const chiSummaries = cs.chameleon_member_summaries || [];
                        const fabCount = (cs.fabric_slices || []).length;
                        const chiCount = (cs.chameleon_slices || []).length;
                        return (
                          <React.Fragment key={cs.id}>
                            <tr
                              onClick={() => {
                                setSelectedCompositeSliceId(cs.id);
                                setCompositeGraph(null);
                                api.getCompositeSlice(cs.id).then(data => {
                                  setCompositeSlices(prev => prev.map(s => s.id === data.id ? data : s));
                                }).catch(() => {});
                                api.getCompositeGraph(cs.id).then(setCompositeGraph).catch(() => {});
                              }}
                              style={{
                                cursor: 'pointer',
                                borderBottom: isSelected && (fabSummaries.length > 0 || chiSummaries.length > 0) ? 'none' : '1px solid var(--fabric-border)',
                                background: isSelected ? 'rgba(39, 170, 225, 0.08)' : undefined,
                              }}
                            >
                              <td style={{ padding: '8px 6px', width: 30 }} onClick={(e) => e.stopPropagation()}>
                                <input
                                  type="checkbox"
                                  checked={checkedCompositeIds.has(cs.id)}
                                  onChange={(e) => {
                                    setCheckedCompositeIds(prev => {
                                      const next = new Set(prev);
                                      if (e.target.checked) next.add(cs.id); else next.delete(cs.id);
                                      return next;
                                    });
                                  }}
                                  style={{ accentColor: '#27aae1' }}
                                />
                              </td>
                              <td style={{ padding: '8px 12px', fontWeight: 600 }}>
                                <span style={{ marginRight: 6 }}>{isSelected ? '▾' : '▸'}</span>
                                {cs.name}
                              </td>
                              <td style={{ padding: '8px 12px' }}>
                                <span style={{
                                  fontSize: 10, fontWeight: 600, textTransform: 'uppercase', padding: '2px 6px', borderRadius: 4,
                                  background: cs.state === 'Active' ? 'rgba(0, 142, 122, 0.15)' : cs.state === 'Degraded' ? 'rgba(226, 82, 65, 0.15)' : 'rgba(39, 170, 225, 0.15)',
                                  color: cs.state === 'Active' ? '#008e7a' : cs.state === 'Degraded' ? '#e25241' : '#27aae1',
                                }}>{cs.state}</span>
                              </td>
                              <td style={{ padding: '8px 12px' }}>
                                {fabCount > 0 && <span style={{ color: '#5798bc', fontWeight: 500, marginRight: 8 }}>{fabCount} FABRIC</span>}
                                {chiCount > 0 && <span style={{ color: '#39B54A', fontWeight: 500 }}>{chiCount} Chameleon</span>}
                                {fabCount === 0 && chiCount === 0 && <span style={{ color: 'var(--fabric-text-muted)' }}>No members</span>}
                              </td>
                              <td style={{ padding: '8px 12px', color: 'var(--fabric-text-muted)', fontSize: 11 }}>{cs.created ? new Date(cs.created).toLocaleDateString() : ''}</td>
                            </tr>
                            {/* Expandable member details */}
                            {isSelected && (fabSummaries.length > 0 || chiSummaries.length > 0) && (
                              <tr style={{ background: 'rgba(39, 170, 225, 0.04)', borderBottom: '1px solid var(--fabric-border)' }}>
                                <td colSpan={5} style={{ padding: '4px 12px 8px 36px' }}>
                                  {fabSummaries.map((m: any) => (
                                    <div key={m.id} style={{ fontSize: 11, padding: '3px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: '#5798bc', background: 'rgba(87, 152, 188, 0.15)', padding: '1px 4px', borderRadius: 3 }}>FAB</span>
                                      <span style={{ fontWeight: 500 }}>{m.name}</span>
                                      <span style={{ color: m.state === 'StableOK' ? '#008e7a' : 'var(--fabric-text-muted)', fontSize: 10 }}>{m.state}</span>
                                      <span style={{ color: 'var(--fabric-text-muted)', fontSize: 10 }}>{m.node_count} node{m.node_count !== 1 ? 's' : ''}</span>
                                    </div>
                                  ))}
                                  {chiSummaries.map((m: any) => (
                                    <div key={m.id} style={{ fontSize: 11, padding: '3px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                                      <span style={{ fontSize: 9, fontWeight: 700, color: '#39B54A', background: 'rgba(57, 181, 74, 0.15)', padding: '1px 4px', borderRadius: 3 }}>CHI</span>
                                      <span style={{ fontWeight: 500 }}>{m.name}</span>
                                      <span style={{ color: m.state === 'Active' ? '#008e7a' : 'var(--fabric-text-muted)', fontSize: 10 }}>{m.state}</span>
                                      {m.site && <span style={{ color: 'var(--fabric-text-muted)', fontSize: 10 }}>@ {m.site}</span>}
                                    </div>
                                  ))}
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                  </>
                )}
              </div>
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
                chameleonSites={chameleonEnabled ? chameleonSites : undefined}
                chameleonInstances={chameleonEnabled ? chameleonInstances : undefined}
              />
            ) : slicesSubView === 'calendar' ? (
              <ResourceCalendar sites={infraSites} slices={slices} />
            ) : (
              <ClientView
                slices={slices}
                selectedSliceName={selectedSliceName}
                sliceData={sliceData}
                clientTarget={clientTarget}
                onTargetChange={setClientTarget}
              />
            )
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
            {rightCollapsed.length > 0 && (
              <div className="collapsed-tab-rail">
                {rightCollapsed.map((id) => (
                  <button key={id} className="panel-icon-tab right" onClick={() => toggleCollapse(id)} title={`Show ${PANEL_LABELS[id]}`}>
                    {renderPanelIcon(PANEL_ICONS[id])}
                  </button>
                ))}
              </div>
            )}
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
            onClearErrors={handleClearErrors}
            sliceErrors={sliceData?.error_messages ?? []}
            bootConfigErrors={bootConfigErrors}
            onClearBootConfigErrors={handleClearBootConfigErrors}
            fullWidth={consoleFullWidth || !showSidePanels}
            onToggleFullWidth={() => setConsoleFullWidth(fw => !fw)}
            showWidthToggle={showSidePanels}
            expanded={consoleExpanded}
            onExpandedChange={setConsoleExpanded}
            panelHeight={consoleHeight}
            onPanelHeightChange={setConsoleHeight}
            recipeConsole={recipeConsole}
            recipeRunning={recipeRunning}
            onClearRecipeConsole={handleClearRecipeConsole}
            sliceBootLogs={sliceBootLogs}
            sliceBootRunning={sliceBootRunning}
            onClearSliceBootLog={handleClearSliceBootLog}
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

      {/* Save Weave / VM Template Modal */}
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
              placeholder={saveTemplateModal?.type === 'slice' ? 'Weave name...' : 'Template name...'}
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

      {/* Save Experiment Template Modal */}
      {saveExperimentModal && (
        <div className="toolbar-modal-overlay" onClick={() => setSaveExperimentModal(false)}>
          <div className="toolbar-modal toolbar-modal-wide" onClick={(e) => e.stopPropagation()}>
            <h4>Save as Experiment Template</h4>
            <p>
              Save <strong>{selectedSliceName}</strong> as a cross-testbed experiment template
              with {(sliceData?.nodes || []).length} FABRIC node{(sliceData?.nodes || []).length !== 1 ? 's' : ''} and {(sliceData?.chameleon_nodes || []).length} Chameleon node{(sliceData?.chameleon_nodes || []).length !== 1 ? 's' : ''}.
            </p>
            <input
              type="text"
              className="toolbar-modal-input"
              placeholder="Experiment name..."
              value={saveExpName}
              onChange={(e) => setSaveExpName(e.target.value)}
              autoFocus
            />
            <textarea
              className="toolbar-modal-input"
              placeholder="Description (optional)..."
              value={saveExpDesc}
              onChange={(e) => setSaveExpDesc(e.target.value)}
              rows={2}
              style={{ resize: 'vertical', marginTop: 8 }}
            />

            {/* Variable editor */}
            <div style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--fabric-text-muted)' }}>Variables</label>
                <button
                  className="toolbar-btn"
                  onClick={handleAddExpVar}
                  style={{ fontSize: 11, padding: '2px 8px' }}
                >
                  + Add Variable
                </button>
              </div>
              {saveExpVariables.length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)', fontStyle: 'italic', padding: '4px 0' }}>
                  No variables defined. Add variables to make the experiment template configurable.
                </div>
              )}
              {saveExpVariables.map((v, i) => (
                <div key={i} className="experiment-var-row">
                  <input
                    type="text"
                    className="experiment-var-input"
                    placeholder="NAME"
                    value={v.name}
                    onChange={(e) => handleExpVarChange(i, 'name', e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))}
                    style={{ width: 110 }}
                  />
                  <input
                    type="text"
                    className="experiment-var-input"
                    placeholder="Label"
                    value={v.label}
                    onChange={(e) => handleExpVarChange(i, 'label', e.target.value)}
                    style={{ width: 100 }}
                  />
                  <select
                    className="experiment-var-input"
                    value={v.type}
                    onChange={(e) => handleExpVarChange(i, 'type', e.target.value)}
                    style={{ width: 100 }}
                  >
                    <option value="string">String</option>
                    <option value="number">Number</option>
                    <option value="site">FABRIC Site</option>
                    <option value="chameleon_site">Chameleon Site</option>
                  </select>
                  <input
                    type={v.type === 'number' ? 'number' : 'text'}
                    className="experiment-var-input"
                    placeholder="Default"
                    value={String(v.default)}
                    onChange={(e) => handleExpVarChange(i, 'default', v.type === 'number' ? Number(e.target.value) : e.target.value)}
                    style={{ width: 80 }}
                  />
                  <label className="experiment-var-req" title="Required">
                    <input
                      type="checkbox"
                      checked={v.required}
                      onChange={(e) => handleExpVarChange(i, 'required', e.target.checked)}
                    />
                    Req
                  </label>
                  <button
                    className="experiment-var-remove"
                    onClick={() => handleRemoveExpVar(i)}
                    title="Remove variable"
                  >
                    {'\u2715'}
                  </button>
                </div>
              ))}
            </div>

            <div className="toolbar-modal-actions">
              <button onClick={() => setSaveExperimentModal(false)}>Cancel</button>
              <button
                className="success"
                onClick={handleSaveExperimentConfirm}
                disabled={!saveExpName.trim() || saveExpBusy}
              >
                {saveExpBusy ? 'Saving...' : 'Save Experiment'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Experiment Variable Substitution Popup */}
      {experimentVarsPopup && (
        <div className="toolbar-modal-overlay" onClick={() => setExperimentVarsPopup(null)}>
          <div className="toolbar-modal" onClick={(e) => e.stopPropagation()}>
            <h4>Load Experiment</h4>
            <p>
              Configure variables for <strong>{experimentVarsPopup.templateName}</strong> before loading.
            </p>
            {experimentVarsPopup.variables.map((v) => (
              <div key={v.name} style={{ marginBottom: 8 }}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--fabric-text-muted)', marginBottom: 2 }}>
                  {v.label || v.name}{v.required ? ' *' : ''}
                </label>
                <input
                  type={v.type === 'number' ? 'number' : 'text'}
                  className="toolbar-modal-input"
                  placeholder={`${v.label || v.name}...`}
                  value={experimentVarValues[v.name] || ''}
                  onChange={(e) => setExperimentVarValues(prev => ({ ...prev, [v.name]: e.target.value }))}
                  onKeyDown={(e) => e.key === 'Enter' && handleExperimentVarsSubmit()}
                />
              </div>
            ))}
            <div className="toolbar-modal-actions">
              <button onClick={() => setExperimentVarsPopup(null)}>Cancel</button>
              <button
                className="success"
                onClick={handleExperimentVarsSubmit}
                disabled={loading || experimentVarsPopup.variables.some(v => v.required && !experimentVarValues[v.name]?.trim())}
              >
                {loading ? 'Loading...' : 'Load'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Chameleon Lease Creation Dialog — portal to body, inline styles for guaranteed centering */}
      {showChameleonLeaseDialog && chameleonSliceData && typeof document !== 'undefined' && createPortal(
        <div className="toolbar-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }} onClick={() => setShowChameleonLeaseDialog(false)}>
          <div className="toolbar-modal toolbar-modal-wide" onClick={e => e.stopPropagation()} style={{ maxHeight: '80vh', overflowY: 'auto' }}>
            <h4>Create Lease from Draft</h4>
            {/* Resource summary grouped by site */}
            <div style={{ marginBottom: 12 }}>
              <label className="toolbar-modal-label" style={{ marginBottom: 4 }}>Resources</label>
              <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>
                {chiDraftSites.map(site => {
                  const siteNodes = chameleonSliceData.nodes.filter(n => n.site === site);
                  const typeCounts = siteNodes.reduce((acc: Record<string, number>, n) => {
                    acc[n.node_type] = (acc[n.node_type] || 0) + (n.count || 1);
                    return acc;
                  }, {});
                  return (
                    <div key={site} style={{ marginBottom: 4 }}>
                      <div style={{ fontWeight: 600 }}>{site}</div>
                      {Object.entries(typeCounts).map(([type, count]) => (
                        <div key={type} style={{ paddingLeft: 12 }}>{count}{'\u00d7'} {type}</div>
                      ))}
                    </div>
                  );
                })}
                {chameleonSliceData.networks.length > 0 && <div>{chameleonSliceData.networks.length} network(s)</div>}
              </div>
            </div>
            {/* Duration */}
            <label className="toolbar-modal-label">Duration (hours)</label>
            <input type="number" className="toolbar-modal-input" value={chiLeaseDuration} min={1} max={168}
              onChange={e => setChiLeaseDuration(parseInt(e.target.value) || 24)} />
            {/* Start time */}
            <label className="toolbar-modal-label" style={{ marginTop: 8 }}>Start Time</label>
            <label className="toolbar-modal-label" style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
              <input type="checkbox" checked={chiLeaseStartNow} onChange={e => setChiLeaseStartNow(e.target.checked)} />
              Start now
            </label>
            {!chiLeaseStartNow && (
              <input type="datetime-local" className="toolbar-modal-input" value={chiLeaseStartDate}
                onChange={e => setChiLeaseStartDate(e.target.value)} style={{ marginTop: 4 }} />
            )}
            {/* Network selector */}
            <div style={{ marginTop: 8 }}>
              <label className="toolbar-modal-label">Network</label>
              <select className="toolbar-modal-input" value={chiSelectedNetworkId} onChange={e => setChiSelectedNetworkId(e.target.value)}>
                <option value="">-- Auto (first shared) --</option>
                {chiDeployNetworks.map((n: any) => (
                  <option key={n.id} value={n.id}>{n.name}{n.shared ? ' (shared)' : ''}</option>
                ))}
              </select>
            </div>
            {/* Deploy mode */}
            <div style={{ marginTop: 12 }}>
              <label className="toolbar-modal-label" style={{ marginBottom: 4 }}>Deploy Mode</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                  <input type="radio" name="chi-deploy-mode" checked={chiDeployMode === 'auto-deploy'} onChange={() => setChiDeployMode('auto-deploy')} />
                  Create Lease &amp; Auto-Deploy (recommended)
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                  <input type="radio" name="chi-deploy-mode" checked={chiDeployMode === 'lease-only'} onChange={() => setChiDeployMode('lease-only')} />
                  Create Lease Only (deploy later)
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                  <input type="radio" name="chi-deploy-mode" checked={chiDeployMode === 'existing-lease'} onChange={() => setChiDeployMode('existing-lease')} />
                  Deploy on Existing Lease
                </label>
              </div>
              {chiDeployMode === 'existing-lease' && (
                <select className="toolbar-modal-input" value={chiExistingLeaseId} onChange={e => setChiExistingLeaseId(e.target.value)} style={{ marginTop: 4 }}>
                  <option value="">-- Select ACTIVE Lease --</option>
                  {chiActiveLeases.map((l: any) => (
                    <option key={l.id} value={l.id}>{l.name} ({l._site})</option>
                  ))}
                </select>
              )}
            </div>
            {/* Availability check */}
            <div style={{ marginTop: 12, borderTop: '1px solid var(--fabric-border)', paddingTop: 8 }}>
              <button onClick={handleCheckChiAvailability} disabled={chiAvailLoading} style={{ fontSize: 11, padding: '3px 10px' }}>
                {chiAvailLoading ? 'Checking...' : 'Check Availability'}
              </button>
              {Object.entries(chiAvailability).map(([type, r]) => (
                <div key={type} style={{ fontSize: 11, marginTop: 4 }}>
                  <strong>{type}:</strong>{' '}
                  {r.error ? (
                    <span style={{ color: 'var(--fabric-coral, #e25241)' }}>{r.error}</span>
                  ) : r.earliest_start === 'now' || r.available_now > 0 ? (
                    <>
                      <span style={{ color: 'var(--fabric-success, #008e7a)' }}>Available now ({r.available_now}/{r.total})</span>
                      {r.warning && <div style={{ fontSize: 10, color: 'var(--fabric-warning, #ff8542)', marginTop: 1, fontStyle: 'italic' }}>{r.warning}</div>}
                    </>
                  ) : r.earliest_start ? (
                    <span style={{ color: 'var(--fabric-warning, #ff8542)' }}>Available from {r.earliest_start}</span>
                  ) : (
                    <span style={{ color: 'var(--fabric-coral, #e25241)' }}>Not available (0/{r.total})</span>
                  )}
                </div>
              ))}
            </div>
            {chiDeployStatus && (
              <div style={{ marginTop: 8, padding: '6px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                background: chiDeployStatus.startsWith('Error') ? 'var(--state-error-bg, rgba(176,0,32,0.1))' : 'rgba(0,142,122,0.1)',
                color: chiDeployStatus.startsWith('Error') ? 'var(--state-error, #b00020)' : 'var(--fabric-success, #008e7a)' }}>
                {chiDeployStatus}
              </div>
            )}
            <div className="toolbar-modal-actions" style={{ marginTop: 16 }}>
              <button onClick={() => setShowChameleonLeaseDialog(false)}>Cancel</button>
              <button className="success" onClick={handleDeployChameleonLease} disabled={chiLeaseDeploying || (chiDeployMode === 'existing-lease' && !chiExistingLeaseId)}>
                {chiLeaseDeploying ? chiDeployStatus || 'Working...' :
                 chiDeployMode === 'lease-only' ? 'Create Lease' :
                 chiDeployMode === 'existing-lease' ? 'Deploy on Lease' :
                 'Create Lease & Deploy'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Chameleon Delete Slice dialog */}
      {showChameleonDeleteDialog && typeof document !== 'undefined' && createPortal(
        <div className="toolbar-modal-overlay" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }} onClick={() => setShowChameleonDeleteDialog(false)}>
          <div className="toolbar-modal" onClick={e => e.stopPropagation()} style={{ maxHeight: '80vh', overflowY: 'auto' }}>
            <h4>Delete Slice</h4>
            <p style={{ fontSize: 12, color: 'var(--fabric-text-muted)', margin: '8px 0 12px' }}>
              Choose how to handle deployed resources:
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="radio" name="chi-delete-mode" checked={chiDeleteMode === 'release'} onChange={() => setChiDeleteMode('release')} />
                <span><strong>Release</strong> &mdash; remove slice record only, servers keep running</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="radio" name="chi-delete-mode" checked={chiDeleteMode === 'delete-all'} onChange={() => setChiDeleteMode('delete-all')} />
                <span style={{ color: 'var(--fabric-coral, #e25241)' }}><strong>Delete All</strong> &mdash; terminate instances and delete leases</span>
              </label>
            </div>
            <div className="toolbar-modal-actions" style={{ marginTop: 16 }}>
              <button onClick={() => setShowChameleonDeleteDialog(false)} disabled={chiDeleting}>Cancel</button>
              <button
                className={chiDeleteMode === 'delete-all' ? 'danger' : ''}
                onClick={handleConfirmDeleteChameleon}
                disabled={chiDeleting}
              >
                {chiDeleting ? 'Deleting...' : chiDeleteMode === 'delete-all' ? 'Delete All' : 'Release'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
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

      {/* Post-login project picker modal */}
      {availabilityResult && createPortal(
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }}
          onClick={() => setAvailabilityResult(null)}>
          <div style={{ background: 'var(--fabric-white, #fff)', borderRadius: 12, padding: '24px 28px', maxWidth: 520, width: '90%', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,0.3)' }}
            onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 700, color: 'var(--fabric-text)' }}>Resource Availability</h3>
            <div style={{
              padding: '10px 14px', borderRadius: 8, marginBottom: 14, fontSize: 13, fontWeight: 600,
              background: availabilityResult.feasible_now ? '#e6f9f0' : availabilityResult.next_slot ? '#fff8e6' : '#fde8e8',
              color: availabilityResult.feasible_now ? '#1a7a4c' : availabilityResult.next_slot ? '#8a6d00' : '#c0392b',
              border: `1px solid ${availabilityResult.feasible_now ? '#b7e4c7' : availabilityResult.next_slot ? '#f0d980' : '#f0b4b4'}`,
            }}>
              {availabilityResult.message}
            </div>
            {availabilityResult.slots.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--fabric-text-muted)', marginBottom: 6 }}>Available Slots</div>
                {availabilityResult.slots.map((slot, i) => (
                  <div key={i} style={{ fontSize: 12, padding: '4px 0', color: 'var(--fabric-text)' }}>
                    {new Date(slot.start).toLocaleString()}
                  </div>
                ))}
              </div>
            )}
            {availabilityResult.node_requirements.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--fabric-text-muted)', marginBottom: 6 }}>Node Requirements</div>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--fabric-border-solid, #dde)' }}>
                      <th style={{ textAlign: 'left', padding: '4px 6px', fontWeight: 600 }}>Node</th>
                      <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600 }}>Cores</th>
                      <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600 }}>RAM</th>
                      <th style={{ textAlign: 'right', padding: '4px 6px', fontWeight: 600 }}>Disk</th>
                      <th style={{ textAlign: 'left', padding: '4px 6px', fontWeight: 600 }}>Site</th>
                    </tr>
                  </thead>
                  <tbody>
                    {availabilityResult.node_requirements.map((nr, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--fabric-border-solid, #eef)' }}>
                        <td style={{ padding: '4px 6px' }}>{nr.name}</td>
                        <td style={{ textAlign: 'right', padding: '4px 6px' }}>{nr.cores}</td>
                        <td style={{ textAlign: 'right', padding: '4px 6px' }}>{nr.ram} GB</td>
                        <td style={{ textAlign: 'right', padding: '4px 6px' }}>{nr.disk} GB</td>
                        <td style={{ padding: '4px 6px' }}>{nr.site || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div style={{ textAlign: 'right' }}>
              <button onClick={() => setAvailabilityResult(null)}
                style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--fabric-border-solid, #ccc)', background: 'var(--fabric-bg, #f8f9fa)', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
                Close
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
      {showPostLoginProjectPicker && createPortal(
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.5)', zIndex: 99999 }}>
          <div style={{ background: 'var(--fabric-white, #fff)', borderRadius: 12, padding: '28px 32px', maxWidth: 420, width: '90%', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,0.3)' }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 16, fontWeight: 700, color: 'var(--fabric-text)' }}>Select a Project</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--fabric-text-muted)' }}>
              You belong to multiple FABRIC projects. Choose one to get started.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {postLoginProjects.map((p) => (
                <button
                  key={p.uuid}
                  disabled={postLoginBusy}
                  onClick={() => runAutoSetup(p.uuid)}
                  style={{
                    padding: '10px 16px', borderRadius: 8, border: '1px solid var(--fabric-border-solid, #dde)',
                    background: 'var(--fabric-bg, #f8f9fa)', cursor: postLoginBusy ? 'wait' : 'pointer',
                    textAlign: 'left', fontSize: 13, fontWeight: 600, color: 'var(--fabric-text)',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                  onMouseEnter={(e) => { (e.target as HTMLElement).style.borderColor = '#5798bc'; }}
                  onMouseLeave={(e) => { (e.target as HTMLElement).style.borderColor = 'var(--fabric-border-solid, #dde)'; }}
                >
                  {p.name}
                  <span style={{ display: 'block', fontSize: 10, fontWeight: 400, opacity: 0.5, marginTop: 2 }}>{p.uuid}</span>
                </button>
              ))}
            </div>
            <button
              onClick={() => { setShowPostLoginProjectPicker(false); setSettingsOpen(true); }}
              style={{ marginTop: 16, background: 'none', border: 'none', color: 'var(--fabric-text-muted)', fontSize: 12, cursor: 'pointer', padding: 0 }}
            >
              Skip — configure manually in Settings
            </button>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
