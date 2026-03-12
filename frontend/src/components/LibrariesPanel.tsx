'use client';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceData, VMTemplateSummary, RecipeSummary } from '../types/fabric';
import type { TemplateSummary, ScriptArg, BackgroundRun } from '../api/client';
import * as api from '../api/client';
import Tooltip from './Tooltip';
import '../styles/template-panel.css';
import '../styles/vm-template-panel.css';

interface DragHandleProps {
  draggable: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
}

interface LibrariesPanelProps {
  // Slice template props
  onSliceImported: (data: SliceData) => void;
  // Deploy weave callback — loads template + submits + polls + boot config
  onDeployWeave?: (templateDirName: string, sliceName: string, args: Record<string, string>) => void;
  // Run weave script callback — executes run.sh with args from run.json
  onRunWeaveScript?: (templateDirName: string, weaveName: string, args: Record<string, string>) => void;
  // Orchestrated run: deploy first (if has deploy.sh), then run run.sh
  onRunExperiment?: (templateDirName: string, weaveName: string, args: Record<string, string>) => void;
  // Active background runs (for showing "running" state on weave cards)
  activeRuns?: BackgroundRun[];
  // View output of a running/completed weave run
  onViewRunOutput?: (weaveName: string) => void;
  // Stop a running background run
  onStopRun?: (runId: string) => void;
  // Reset/revert a published artifact to its original version
  onResetArtifact?: (dirName: string) => Promise<void>;
  // VM template props
  onVmTemplatesChanged: () => void;
  sliceName: string;
  sliceData: SliceData | null;
  onNodeAdded: (data: SliceData) => void;
  // Recipe execution callback (lifted to App for BottomPanel console)
  onExecuteRecipe: (recipeDirName: string, nodeName: string) => void;
  executingRecipe: string | null;
  // Notify parent when recipes change (star toggled) so context menu stays in sync
  onRecipesChanged?: () => void;
  // Notebook launch callback — switches App to JupyterLab view with a specific path
  onLaunchNotebook?: (jupyterPath: string) => void;
  // Notebook publish callback — switches App to Artifacts view with publish dialog
  onPublishNotebook?: (dirName: string) => void;
  // Publish any artifact — switches App to Artifacts view with publish dialog
  onPublishArtifact?: (dirName: string, category: string) => void;
  // Navigate to marketplace with a category filter (from empty-state links)
  onNavigateToMarketplace?: (category: 'weave' | 'vm-template' | 'recipe' | 'notebook') => void;
  // Edit artifact in editor view
  onEditArtifact?: (dirName: string) => void;
  // Panel chrome
  onCollapse: () => void;
  dragHandleProps?: DragHandleProps;
  panelIcon?: string;
}

type TabId = 'weaves' | 'vm' | 'recipes' | 'notebooks';

interface OverflowMenuItem {
  label: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  separator?: boolean;
}

function OverflowMenu({ items, isOpen, onToggle, onClose }: {
  items: OverflowMenuItem[];
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [above, setAbove] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen || !wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    setAbove(window.innerHeight - rect.bottom < 200);
  }, [isOpen]);

  return (
    <div className="tp-overflow-wrap" ref={wrapRef}>
      <button className="tp-overflow-btn" onClick={onToggle} title="More actions">{'\u22EF'}</button>
      {isOpen && (
        <div className={`tp-overflow-menu${above ? ' tp-overflow-above' : ''}`}>
          {items.map((item, i) => {
            if (item.separator) return <div key={`sep-${i}`} className="tp-overflow-sep" />;
            return (
              <button
                key={item.label}
                className={`tp-overflow-item${item.danger ? ' tp-overflow-danger' : ''}`}
                disabled={item.disabled}
                onClick={() => { item.onClick(); onClose(); }}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default React.memo(function LibrariesPanel({
  onSliceImported, onDeployWeave, onRunWeaveScript, onRunExperiment, activeRuns, onViewRunOutput, onStopRun, onResetArtifact,
  onVmTemplatesChanged, sliceName, sliceData, onNodeAdded,
  onExecuteRecipe, executingRecipe, onRecipesChanged, onLaunchNotebook, onPublishNotebook,
  onPublishArtifact, onNavigateToMarketplace, onEditArtifact, onCollapse, dragHandleProps, panelIcon,
}: LibrariesPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('weaves');
  const [overflowOpen, setOverflowOpen] = useState<string | null>(null);

  // ─── Slice Templates state ───
  const [sliceTemplates, setSliceTemplates] = useState<TemplateSummary[]>([]);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [sliceError, setSliceError] = useState('');
  const [loadingTemplate, setLoadingTemplate] = useState<string | null>(null);  // display name
  const [loadingTemplateDirName, setLoadingTemplateDirName] = useState<string | null>(null);  // dir_name for API
  const [loadSliceName, setLoadSliceName] = useState('');
  const [loadProgress, setLoadProgress] = useState<{ active: boolean; step: number } | null>(null);
  const loadStepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [sliceSearchFilter, setSliceSearchFilter] = useState('');

  const LOAD_STEPS = [
    'Reading template...',
    'Creating draft slice...',
    'Adding nodes...',
    'Configuring components...',
    'Setting up networks...',
    'Resolving site assignments...',
    'Checking resource availability...',
    'Finalizing topology...',
  ];

  const refreshSliceTemplates = useCallback(async () => {
    setSliceLoading(true);
    setSliceError('');
    try {
      const list = await api.listTemplates();
      setSliceTemplates(list);
    } catch (e: any) {
      setSliceError(e.message);
    } finally {
      setSliceLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshSliceTemplates();
  }, [refreshSliceTemplates]);

  // Re-fetch when slice tab becomes active
  useEffect(() => {
    if (activeTab === 'weaves') refreshSliceTemplates();
  }, [activeTab]);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleLoadSliceTemplate = async () => {
    if (!loadingTemplateDirName) return;
    const name = loadSliceName.trim() || loadingTemplate || loadingTemplateDirName;
    setSliceError('');
    setLoadingTemplate(null);
    setLoadProgress({ active: true, step: 0 });

    let step = 0;
    loadStepTimerRef.current = setInterval(() => {
      step = Math.min(step + 1, LOAD_STEPS.length - 1);
      setLoadProgress({ active: true, step });
    }, 2000);

    try {
      const data = await api.loadTemplate(loadingTemplateDirName, name);
      onSliceImported(data);
      setLoadSliceName('');
    } catch (e: any) {
      setSliceError(e.message);
    } finally {
      if (loadStepTimerRef.current) clearInterval(loadStepTimerRef.current);
      setLoadProgress(null);
    }
  };


  // ─── VM Templates state ───
  const [vmTemplates, setVmTemplates] = useState<VMTemplateSummary[]>([]);
  const [vmLoading, setVmLoading] = useState(false);
  const [vmError, setVmError] = useState('');
  const [vmSearchFilter, setVmSearchFilter] = useState('');
  const [addingTemplate, setAddingTemplate] = useState<string | null>(null);
  const [variantPicker, setVariantPicker] = useState<{ dirName: string; images: string[] } | null>(null);

  const refreshVmTemplates = useCallback(async () => {
    setVmLoading(true);
    setVmError('');
    try {
      const list = await api.listVmTemplates();
      setVmTemplates(list);
    } catch (e: any) {
      setVmError(e.message);
    } finally {
      setVmLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshVmTemplates();
  }, [refreshVmTemplates]);

  // Re-fetch when VM tab becomes active
  useEffect(() => {
    if (activeTab === 'vm') refreshVmTemplates();
  }, [activeTab]);  // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Recipes state ───
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [recipesLoading, setRecipesLoading] = useState(false);
  const [recipeSearchFilter, setRecipeSearchFilter] = useState('');
  const [recipeNodePicker, setRecipeNodePicker] = useState<string | null>(null);

  // ─── Notebooks state ───
  const [notebooks, setNotebooks] = useState<{ name: string; description?: string; dir_name: string; created?: string; artifact_uuid?: string }[]>([]);
  const [notebooksLoading, setNotebooksLoading] = useState(false);
  const [notebookSearchFilter, setNotebookSearchFilter] = useState('');
  const [launchingNotebook, setLaunchingNotebook] = useState<string | null>(null);

  // ─── Delete confirmation state ───
  const [deleteConfirm, setDeleteConfirm] = useState<{ dirName: string; name: string; category: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ─── Script args modal state (shared by Deploy and Run) ───
  const DEFAULT_DEPLOY_ARGS: ScriptArg[] = [
    { name: 'SLICE_NAME', label: 'Slice Name', type: 'string', required: true, default: '', description: 'Name for the new slice' },
  ];
  const DEFAULT_RUN_ARGS: ScriptArg[] = [
    { name: 'SLICE_NAME', label: 'Slice Name', type: 'string', required: true, default: '', description: 'Passed to the script as SLICE_NAME — may be used to create a new slice or reference an existing one' },
  ];

  const [scriptModal, setScriptModal] = useState<{
    mode: 'deploy' | 'run';
    weaveName: string;
    dirName: string;
    argDefs: ScriptArg[];
  } | null>(null);
  const [scriptArgValues, setScriptArgValues] = useState<Record<string, string>>({});

  const uniqueSliceName = (base: string) => {
    const suffix = Math.random().toString(36).slice(2, 6);
    return `${base}-${suffix}`;
  };

  const openDeployModal = (t: TemplateSummary) => {
    const argDefs = t.deploy_args?.length ? t.deploy_args : DEFAULT_DEPLOY_ARGS;
    const defaults: Record<string, string> = {};
    for (const arg of argDefs) {
      defaults[arg.name] = arg.name === 'SLICE_NAME' ? uniqueSliceName(t.name || 'slice') : (arg.default || '');
    }
    setScriptArgValues(defaults);
    setScriptModal({ mode: 'deploy', weaveName: t.name, dirName: t.dir_name, argDefs });
  };

  const openRunModal = (t: TemplateSummary) => {
    const argDefs = t.run_args?.length ? t.run_args : DEFAULT_RUN_ARGS;
    const defaults: Record<string, string> = {};
    for (const arg of argDefs) {
      defaults[arg.name] = arg.name === 'SLICE_NAME' ? uniqueSliceName(t.name || 'slice') : (arg.default || '');
    }
    setScriptArgValues(defaults);
    setScriptModal({ mode: 'run', weaveName: t.name, dirName: t.dir_name, argDefs });
  };

  const scriptModalValid = scriptModal?.argDefs.every(
    (a) => !a.required || scriptArgValues[a.name]?.trim()
  ) ?? false;

  const confirmScriptModal = () => {
    if (!scriptModal || !scriptModalValid) return;
    const { mode, dirName, weaveName, argDefs } = scriptModal;
    // Build trimmed args, only include non-empty values
    const args: Record<string, string> = {};
    for (const a of argDefs) {
      const v = scriptArgValues[a.name]?.trim() || '';
      if (v) args[a.name] = v;
    }
    setScriptModal(null);
    if (mode === 'deploy') {
      const deploySliceName = args.SLICE_NAME || weaveName || dirName;
      onDeployWeave?.(dirName, deploySliceName, args);
    } else {
      // Orchestrated run: if weave also has deploy.sh, use onRunExperiment which deploys first
      const tmpl = sliceTemplates.find(t => t.dir_name === dirName);
      if (tmpl?.has_deploy && onRunExperiment) {
        onRunExperiment(dirName, weaveName, args);
      } else {
        onRunWeaveScript?.(dirName, weaveName, args);
      }
    }
  };

  const refreshRecipes = useCallback(async () => {
    setRecipesLoading(true);
    try {
      const list = await api.listRecipes();
      setRecipes(list);
    } catch {
      // ignore
    } finally {
      setRecipesLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshRecipes();
  }, [refreshRecipes]);

  // Re-fetch when recipes tab becomes active
  useEffect(() => {
    if (activeTab === 'recipes') refreshRecipes();
  }, [activeTab]);  // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Notebooks fetch ───
  const refreshNotebooks = useCallback(async () => {
    setNotebooksLoading(true);
    try {
      const data = await api.getMyArtifacts();
      setNotebooks(data.local_artifacts.filter((a: any) => a.category === 'notebook'));
    } catch {
      // ignore
    } finally {
      setNotebooksLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshNotebooks();
  }, [refreshNotebooks]);

  useEffect(() => {
    if (activeTab === 'notebooks') refreshNotebooks();
  }, [activeTab]);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleLaunchNotebook = async (dirName: string) => {
    setLaunchingNotebook(dirName);
    try {
      const result = await api.launchNotebook(dirName);
      if (result.status === 'running' && result.jupyter_path) {
        onLaunchNotebook?.(result.jupyter_path);
      }
    } catch (e: any) {
      alert(`Failed to launch notebook: ${e.message}`);
    } finally {
      setLaunchingNotebook(null);
    }
  };

  const handleEditInJupyter = async (dirName: string) => {
    setLaunchingNotebook(dirName);
    try {
      const result = await api.startJupyter();
      if (result.status === 'running') {
        onLaunchNotebook?.(`/jupyter/lab/tree/my_artifacts/${encodeURIComponent(dirName)}`);
      }
    } catch (e: any) {
      alert(`Failed to open in JupyterLab: ${e.message}`);
    } finally {
      setLaunchingNotebook(null);
    }
  };

  const handleDeleteArtifact = async () => {
    if (!deleteConfirm) return;
    setDeleting(true);
    try {
      const { dirName, category } = deleteConfirm;
      if (category === 'weave') {
        await api.deleteTemplate(dirName);
        refreshSliceTemplates();
      } else if (category === 'vm-template') {
        await api.deleteVmTemplate(dirName);
        refreshVmTemplates();
        onVmTemplatesChanged();
      } else if (category === 'recipe') {
        await api.deleteExperiment(dirName);
        refreshRecipes();
        onRecipesChanged?.();
      } else {
        await api.deleteExperiment(dirName);
        refreshNotebooks();
      }
    } catch (e: any) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(false);
      setDeleteConfirm(null);
    }
  };

  // Periodic polling — pick up templates created externally or manually
  // Only polls when the browser tab is visible to avoid unnecessary requests
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      if (activeTab === 'weaves') refreshSliceTemplates();
      else if (activeTab === 'vm') refreshVmTemplates();
      else if (activeTab === 'recipes') refreshRecipes();
      else if (activeTab === 'notebooks') refreshNotebooks();
    }, 15_000);
    return () => clearInterval(interval);
  }, [activeTab, refreshSliceTemplates, refreshVmTemplates, refreshRecipes, refreshNotebooks]);

  const handleExecuteRecipe = (recipeDirName: string, nodeName: string) => {
    setRecipeNodePicker(null);
    onExecuteRecipe(recipeDirName, nodeName);
  };

  const handleToggleRecipeStar = async (dirName: string, starred: boolean) => {
    try {
      await api.toggleRecipeStar(dirName, starred);
      setRecipes((prev) => prev.map((r) => r.dir_name === dirName ? { ...r, starred } : r));
      onRecipesChanged?.();
    } catch {
      // ignore
    }
  };

  const generateNodeName = useCallback((baseName: string): string => {
    const existingNames = new Set(sliceData?.nodes.map(n => n.name) || []);
    const sanitized = baseName.toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
    const base = sanitized || 'node';
    if (!existingNames.has(base)) return base;
    for (let i = 1; ; i++) {
      const candidate = `${base}${i}`;
      if (!existingNames.has(candidate)) return candidate;
    }
  }, [sliceData]);

  const handleAddVm = async (dirName: string, variantImage?: string) => {
    if (!sliceName) return;
    setVmError('');
    setAddingTemplate(dirName);
    setVariantPicker(null);
    try {
      const detail = await api.getVmTemplate(dirName);
      const nodeName = generateNodeName(detail.name);

      // Build node params from template (resource sizing + hardware)
      const nodeParams: Parameters<typeof api.addNode>[1] = {
        name: nodeName,
        image: variantImage || detail.image,
      };
      if (detail.cores) nodeParams.cores = detail.cores;
      if (detail.ram) nodeParams.ram = detail.ram;
      if (detail.disk) nodeParams.disk = detail.disk;
      if (detail.host) nodeParams.host = detail.host;
      if (detail.image_type) nodeParams.image_type = detail.image_type;
      if (detail.username) nodeParams.username = detail.username;
      if (detail.instance_type) nodeParams.instance_type = detail.instance_type;
      if (detail.components?.length) nodeParams.components = detail.components;

      if (variantImage && detail.variants) {
        // Multi-variant: use variant endpoint to get synthesized boot_config
        const variant = await api.getVmTemplateVariant(dirName, variantImage);
        const result = await api.addNode(sliceName, nodeParams);
        const bc = variant.boot_config;
        if (bc && (bc.commands.length > 0 || bc.uploads.length > 0 || bc.network.length > 0)) {
          await api.saveBootConfig(sliceName, nodeName, bc);
        }
        onNodeAdded(result);
      } else {
        // Single-image template
        const result = await api.addNode(sliceName, nodeParams);
        const bc = detail.boot_config;
        if (bc && (bc.commands.length > 0 || bc.uploads.length > 0 || bc.network.length > 0)) {
          await api.saveBootConfig(sliceName, nodeName, bc);
        }
        onNodeAdded(result);
      }
    } catch (e: any) {
      setVmError(e.message);
    } finally {
      setAddingTemplate(null);
    }
  };


  // ─── Shared ───
  const formatDate = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
      return iso;
    }
  };

  return (
    <div className="template-panel" data-help-id="templates.panel">
      <div className="template-header" {...(dragHandleProps || {})}>
        <Tooltip text="Browse and load weaves, VM templates, or recipes">
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="panel-drag-handle">{'\u283F'}</span>
            My Artifacts
          </span>
        </Tooltip>
        <button
          className="collapse-btn"
          onClick={(e) => {
            e.stopPropagation();
            if (activeTab === 'weaves') refreshSliceTemplates();
            else if (activeTab === 'vm') refreshVmTemplates();
            else if (activeTab === 'recipes') refreshRecipes();
            else if (activeTab === 'notebooks') refreshNotebooks();
          }}
          title="Refresh"
          style={{ marginRight: 2 }}
        >
          {'\u21BB'}
        </button>
        <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">
          {'\u2715'}
        </button>
      </div>

      {/* Tab bar */}
      <div className="templates-tab-bar">
        <button
          className={`templates-tab${activeTab === 'weaves' ? ' active' : ''}`}
          onClick={() => setActiveTab('weaves')}
        >
          Weaves
        </button>
        <button
          className={`templates-tab${activeTab === 'vm' ? ' active' : ''}`}
          onClick={() => setActiveTab('vm')}
        >
          VM
        </button>
        <button
          className={`templates-tab${activeTab === 'recipes' ? ' active' : ''}`}
          onClick={() => setActiveTab('recipes')}
        >
          Recipes
        </button>
        <button
          className={`templates-tab${activeTab === 'notebooks' ? ' active' : ''}`}
          onClick={() => setActiveTab('notebooks')}
        >
          Notebooks
        </button>
      </div>

      {/* ─── Weaves Tab ─── */}
      {activeTab === 'weaves' && (
        <div className="template-body">
          {sliceError && <div className="template-error">{sliceError}</div>}

          {sliceTemplates.length > 0 && (
            <div className="template-search-wrapper">
              <input
                type="text"
                className="template-search-input"
                placeholder="Filter weaves..."
                value={sliceSearchFilter}
                onChange={(e) => setSliceSearchFilter(e.target.value)}
              />
            </div>
          )}

          <div className="template-list">
            {sliceLoading && sliceTemplates.length === 0 && (
              <div className="template-empty">Loading...</div>
            )}
            {!sliceLoading && sliceTemplates.length === 0 && (
              <div className="template-empty">
                No weaves yet. Save a weave from the toolbar or{' '}
                <a href="#" onClick={(e) => { e.preventDefault(); onNavigateToMarketplace?.('weave'); }}>get one from the marketplace</a>.
              </div>
            )}
            {sliceTemplates
              .filter((t) => {
                if (!sliceSearchFilter) return true;
                const q = sliceSearchFilter.toLowerCase();
                return t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
              })
              .map((t) => {
              const weaveRuns = (activeRuns || []).filter(r => r.weave_dir_name === t.dir_name);
              const isRunning = weaveRuns.some(r => r.status === 'running');
              const hasCompleted = weaveRuns.some(r => r.status === 'done' || r.status === 'error' || r.status === 'interrupted');
              const lastRun = weaveRuns.length > 0 ? weaveRuns[weaveRuns.length - 1] : null;
              const activeRunId = weaveRuns.find(r => r.status === 'running')?.run_id;

              // Determine ▶ button: Run > Deploy > Load priority
              const playMode = t.has_run ? 'run' : t.has_deploy ? 'deploy' : 'load';
              const playLabel = playMode === 'run' ? 'Run' : playMode === 'deploy' ? 'Deploy' : 'Load';
              const playDisabled = isRunning;

              const handlePlay = () => {
                if (playMode === 'run' && onRunWeaveScript) openRunModal(t);
                else if (playMode === 'deploy' && onDeployWeave) openDeployModal(t);
                else if (t.has_template !== false) {
                  setLoadSliceName(t.name);
                  setLoadingTemplate(t.name);
                  setLoadingTemplateDirName(t.dir_name);
                }
              };

              return (
              <div className="template-card" key={t.dir_name}>
                <div className="template-card-header">
                  <span className="template-card-name">{t.name}</span>
                  {isRunning && <span className="tp-status-badge tp-status-running">{'\u25CF'} running</span>}
                  {!isRunning && lastRun?.status === 'done' && <span className="tp-status-badge tp-status-done">{'\u2713'} done</span>}
                  {!isRunning && (lastRun?.status === 'error' || lastRun?.status === 'interrupted') && <span className="tp-status-badge tp-status-error">{'\u2717'} error</span>}
                  <OverflowMenu
                    isOpen={overflowOpen === `weave-${t.dir_name}`}
                    onToggle={() => setOverflowOpen(overflowOpen === `weave-${t.dir_name}` ? null : `weave-${t.dir_name}`)}
                    onClose={() => setOverflowOpen(null)}
                    items={[
                      { label: 'Load...', onClick: () => { setLoadSliceName(t.name); setLoadingTemplate(t.name); setLoadingTemplateDirName(t.dir_name); }, disabled: t.has_template === false },
                      { label: 'Deploy...', onClick: () => openDeployModal(t), disabled: !t.has_deploy || !onDeployWeave || isRunning },
                      { label: 'Run...', onClick: () => openRunModal(t), disabled: !t.has_run || !onRunWeaveScript || isRunning },
                      { label: 'Stop', onClick: () => activeRunId && onStopRun?.(activeRunId), disabled: !isRunning || !activeRunId || !onStopRun },
                      { label: 'Reset', onClick: async () => { if (confirm(`Reset "${t.name}" to its original version? Local changes will be lost.`)) { await onResetArtifact?.(t.dir_name); refreshSliceTemplates(); } }, disabled: !hasCompleted || !onResetArtifact },
                      { label: 'Open Log', onClick: () => onViewRunOutput?.(t.name), disabled: weaveRuns.length === 0 || !onViewRunOutput },
                      { label: '', onClick: () => {}, separator: true },
                      { label: 'Edit', onClick: () => onEditArtifact?.(t.dir_name), disabled: !onEditArtifact },
                      { label: 'JupyterLab', onClick: () => handleEditInJupyter(t.dir_name), disabled: launchingNotebook === t.dir_name },
                      { label: '', onClick: () => {}, separator: true },
                      { label: 'Delete', onClick: () => setDeleteConfirm({ dirName: t.dir_name, name: t.name, category: 'weave' }), danger: true },
                    ]}
                  />
                </div>
                {t.description && (
                  <div className="template-card-desc">{t.description}</div>
                )}
                <div className="template-card-meta">
                  <span>{t.node_count} node{t.node_count !== 1 ? 's' : ''}</span>
                  <span>{t.network_count} net{t.network_count !== 1 ? 's' : ''}</span>
                  <span>{formatDate(t.created)}</span>
                </div>
                <div className="template-card-actions">
                  <div className="tp-transport-group">
                    <Tooltip text={playMode === 'run' ? 'Execute run.sh' : playMode === 'deploy' ? 'Deploy this weave' : 'Load as new draft slice'}>
                      <button
                        className="tp-transport-btn tp-transport-play"
                        disabled={playDisabled}
                        onClick={handlePlay}
                        data-help-id="templates.load"
                      >
                        {'\u25B6'} {playLabel}
                      </button>
                    </Tooltip>
                    <Tooltip text="Stop the running script">
                      <button
                        className="tp-transport-btn tp-transport-stop"
                        disabled={!isRunning || !activeRunId || !onStopRun}
                        onClick={() => activeRunId && onStopRun?.(activeRunId)}
                      >
                        {'\u25A0'} Stop
                      </button>
                    </Tooltip>
                    <Tooltip text="Reset to original version">
                      <button
                        className="tp-transport-btn tp-transport-reset"
                        disabled={!hasCompleted || !onResetArtifact}
                        onClick={async () => {
                          if (confirm(`Reset "${t.name}" to its original version? Local changes will be lost.`)) {
                            await onResetArtifact?.(t.dir_name);
                            refreshSliceTemplates();
                          }
                        }}
                      >
                        {'\u21BA'} Reset
                      </button>
                    </Tooltip>
                  </div>
                </div>
              </div>
            );
            })}
          </div>

          {/* Load Modal */}
          {loadingTemplate && (
            <div className="template-modal-overlay" onClick={() => setLoadingTemplate(null)}>
              <div className="template-modal" onClick={(e) => e.stopPropagation()}>
                <h4>Load Template</h4>
                <p>Create a new draft slice from template <strong>{loadingTemplate}</strong>.</p>
                <input
                  type="text"
                  className="template-input"
                  placeholder="Slice name..."
                  value={loadSliceName}
                  onChange={(e) => setLoadSliceName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleLoadSliceTemplate()}
                  autoFocus
                />
                <div className="template-modal-actions">
                  <button onClick={() => setLoadingTemplate(null)}>Cancel</button>
                  <button className="primary" onClick={() => handleLoadSliceTemplate()}>Load</button>
                </div>
              </div>
            </div>
          )}

          {/* Deploy / Run Args Modal */}
          {scriptModal && (
            <div className="template-modal-overlay" onClick={() => setScriptModal(null)}>
              <div className="template-modal" onClick={(e) => e.stopPropagation()}>
                <h4>{scriptModal.mode === 'deploy' ? 'Deploy Weave' : 'Run Experiment'}</h4>
                <p>
                  {scriptModal.mode === 'deploy'
                    ? <>Load, submit, and configure <strong>{scriptModal.weaveName}</strong> as a new slice.</>
                    : (() => {
                        const tmpl = sliceTemplates.find(t => t.dir_name === scriptModal.dirName);
                        return tmpl?.has_deploy
                          ? <>Deploy <strong>{scriptModal.weaveName}</strong> then run <strong>run.sh</strong>.</>
                          : <>Execute <strong>run.sh</strong> from <strong>{scriptModal.weaveName}</strong>.</>;
                      })()}
                </p>
                {scriptModal.argDefs.map((arg, i) => (
                  <div key={arg.name} style={{ marginBottom: 8 }}>
                    <label style={{ display: 'block', fontSize: 12, color: '#8aa', marginBottom: 2 }}>
                      {arg.label}{arg.required ? ' *' : ''}
                    </label>
                    {arg.description && (
                      <div style={{ fontSize: 11, color: '#688', marginBottom: 3 }}>{arg.description}</div>
                    )}
                    {arg.type === 'boolean' ? (
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={scriptArgValues[arg.name] === 'true'}
                          onChange={(e) => setScriptArgValues(prev => ({ ...prev, [arg.name]: e.target.checked ? 'true' : 'false' }))}
                        />
                        {arg.label}
                      </label>
                    ) : (
                      <input
                        type={arg.type === 'number' ? 'number' : 'text'}
                        className="template-input"
                        placeholder={arg.placeholder || `${arg.label}...`}
                        value={scriptArgValues[arg.name] || ''}
                        onChange={(e) => setScriptArgValues(prev => ({ ...prev, [arg.name]: e.target.value }))}
                        onKeyDown={(e) => e.key === 'Enter' && scriptModalValid && confirmScriptModal()}
                        autoFocus={i === 0}
                      />
                    )}
                  </div>
                ))}
                <div className="template-modal-actions">
                  <button onClick={() => setScriptModal(null)}>Cancel</button>
                  <button
                    className="primary"
                    onClick={confirmScriptModal}
                    disabled={!scriptModalValid}
                  >
                    {scriptModal.mode === 'deploy' ? 'Deploy' : 'Run'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Loading Progress Overlay */}
          {loadProgress && (
            <div className="template-modal-overlay">
              <div className="template-modal template-loading-modal">
                <div className="template-loading-spinner" />
                <h4>Loading Template</h4>
                <div className="template-loading-steps">
                  {LOAD_STEPS.map((msg, i) => (
                    <div
                      key={i}
                      className={`template-loading-step${i < loadProgress.step ? ' done' : i === loadProgress.step ? ' active' : ''}`}
                    >
                      <span className="template-step-icon">
                        {i < loadProgress.step ? '\u2713' : i === loadProgress.step ? '\u25CF' : '\u25CB'}
                      </span>
                      {msg}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

        </div>
      )}

      {/* ─── VM Templates Tab ─── */}
      {activeTab === 'vm' && (
        <div className="vmt-body">
          {vmError && <div className="vmt-error">{vmError}</div>}

          {vmTemplates.length > 0 && (
            <div className="vmt-search-wrapper">
              <input
                type="text"
                className="vmt-search-input"
                placeholder="Filter VM templates..."
                value={vmSearchFilter}
                onChange={(e) => setVmSearchFilter(e.target.value)}
              />
            </div>
          )}

          <div className="vmt-list">
            {vmLoading && vmTemplates.length === 0 && (
              <div className="vmt-empty">Loading...</div>
            )}
            {!vmLoading && vmTemplates.length === 0 && (
              <div className="vmt-empty">
                No VM templates yet. Right-click a node to create one, or{' '}
                <a href="#" onClick={(e) => { e.preventDefault(); onNavigateToMarketplace?.('vm-template'); }}>get one from the marketplace</a>.
              </div>
            )}
            {vmTemplates
              .filter((t) => {
                if (!vmSearchFilter) return true;
                const q = vmSearchFilter.toLowerCase();
                return t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
              })
              .map((t) => (
              <div className="vmt-card" key={t.dir_name}>
                <div className="vmt-card-header">
                  <span className="vmt-card-name">{t.name}</span>
                  {t.version && <span className="vmt-badge-version">v{t.version}</span>}
                  <OverflowMenu
                    isOpen={overflowOpen === `vm-${t.dir_name}`}
                    onToggle={() => setOverflowOpen(overflowOpen === `vm-${t.dir_name}` ? null : `vm-${t.dir_name}`)}
                    onClose={() => setOverflowOpen(null)}
                    items={[
                      { label: 'Edit', onClick: () => handleEditInJupyter(t.dir_name), disabled: launchingNotebook === t.dir_name },
                      { label: '', onClick: () => {}, separator: true },
                      { label: 'Delete', onClick: () => setDeleteConfirm({ dirName: t.dir_name, name: t.name, category: 'vm-template' }), danger: true },
                    ]}
                  />
                </div>
                {t.description && (
                  <div className="vmt-card-desc">{t.description}</div>
                )}
                <div className="vmt-card-meta">
                  {t.variant_count > 0 ? (
                    <span>{t.variant_count} images</span>
                  ) : (
                    <span>Image: {t.image}</span>
                  )}
                  <span>{formatDate(t.created)}</span>
                </div>
                {/* Inline variant picker */}
                {variantPicker?.dirName === t.dir_name && (
                  <div className="vmt-variant-picker">
                    {t.images.map((img) => (
                      <button
                        key={img}
                        className="vmt-variant-btn"
                        onClick={() => handleAddVm(t.dir_name, img)}
                        disabled={addingTemplate === t.dir_name}
                      >
                        {img}
                      </button>
                    ))}
                    <button className="vmt-variant-btn vmt-variant-cancel" onClick={() => setVariantPicker(null)}>Cancel</button>
                  </div>
                )}
                <div className="vmt-card-actions">
                  <Tooltip text={!sliceName ? 'Select or create a slice first' : 'Add a new node to the current slice using this VM template configuration'}>
                    <button
                      className="vmt-btn-add"
                      style={{ width: '100%' }}
                      disabled={!sliceName || addingTemplate === t.dir_name}
                      onClick={() => {
                        if (t.variant_count > 0) {
                          setVariantPicker({ dirName: t.dir_name, images: t.images });
                        } else {
                          handleAddVm(t.dir_name);
                        }
                      }}
                      data-help-id="vm-templates.add-vm"
                    >
                      {addingTemplate === t.dir_name ? 'Adding...' : 'Add VM'}
                    </button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>

        </div>
      )}

      {/* ─── Recipes Tab ─── */}
      {activeTab === 'recipes' && (
        <div className="vmt-body">
          {recipes.length > 0 && (
            <div className="vmt-search-wrapper">
              <input
                type="text"
                className="vmt-search-input"
                placeholder="Filter recipes..."
                value={recipeSearchFilter}
                onChange={(e) => setRecipeSearchFilter(e.target.value)}
              />
            </div>
          )}

          <div className="vmt-list">
            {recipesLoading && recipes.length === 0 && (
              <div className="vmt-empty">Loading...</div>
            )}
            {!recipesLoading && recipes.length === 0 && (
              <div className="vmt-empty">
                No recipes yet.{' '}
                <a href="#" onClick={(e) => { e.preventDefault(); onNavigateToMarketplace?.('recipe'); }}>Get one from the marketplace</a>.
              </div>
            )}
            {recipes
              .filter((r) => {
                if (!recipeSearchFilter) return true;
                const q = recipeSearchFilter.toLowerCase();
                return r.name.toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q);
              })
              .map((r) => (
              <div className="vmt-card" key={r.dir_name}>
                <div className="vmt-card-header">
                  <button
                    className="recipe-star-btn"
                    title={r.starred ? 'Unstar (hide from context menu)' : 'Star (show in context menu)'}
                    onClick={() => handleToggleRecipeStar(r.dir_name, !r.starred)}
                  >
                    {r.starred ? '\u2605' : '\u2606'}
                  </button>
                  <span className="vmt-card-name">{r.name}</span>
                  <OverflowMenu
                    isOpen={overflowOpen === `recipe-${r.dir_name}`}
                    onToggle={() => setOverflowOpen(overflowOpen === `recipe-${r.dir_name}` ? null : `recipe-${r.dir_name}`)}
                    onClose={() => setOverflowOpen(null)}
                    items={[
                      { label: 'Edit', onClick: () => handleEditInJupyter(r.dir_name), disabled: launchingNotebook === r.dir_name },
                      { label: '', onClick: () => {}, separator: true },
                      { label: 'Delete', onClick: () => setDeleteConfirm({ dirName: r.dir_name, name: r.name, category: 'recipe' }), danger: true },
                    ]}
                  />
                </div>
                {r.description && (
                  <div className="vmt-card-desc">{r.description}</div>
                )}
                <div className="vmt-card-meta">
                  <span>Images: {Object.keys(r.image_patterns).join(', ')}</span>
                </div>
                {/* Node picker for Apply */}
                {recipeNodePicker === r.dir_name && sliceData && sliceData.nodes.length > 0 && (
                  <div className="vmt-variant-picker">
                    {sliceData.nodes.map((n) => (
                      <button
                        key={n.name}
                        className="vmt-variant-btn"
                        onClick={() => handleExecuteRecipe(r.dir_name, n.name)}
                        disabled={executingRecipe === r.dir_name}
                      >
                        {n.name}
                      </button>
                    ))}
                    <button className="vmt-variant-btn vmt-variant-cancel" onClick={() => setRecipeNodePicker(null)}>Cancel</button>
                  </div>
                )}
                <div className="vmt-card-actions">
                  <Tooltip text={!sliceName || !sliceData?.nodes.length ? 'Need a slice with nodes first' : 'Apply this recipe to a node'}>
                    <button
                      className="vmt-btn-add"
                      style={{ width: '100%' }}
                      disabled={!sliceName || !sliceData?.nodes.length || executingRecipe === r.dir_name}
                      onClick={() => setRecipeNodePicker(r.dir_name)}
                    >
                      {executingRecipe === r.dir_name ? 'Applying...' : 'Apply'}
                    </button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>

        </div>
      )}

      {/* ─── Notebooks Tab ─── */}
      {activeTab === 'notebooks' && (
        <div className="vmt-body">
          {notebooks.length > 0 && (
            <div className="vmt-search-wrapper">
              <input
                type="text"
                className="vmt-search-input"
                placeholder="Filter notebooks..."
                value={notebookSearchFilter}
                onChange={(e) => setNotebookSearchFilter(e.target.value)}
              />
            </div>
          )}

          <div className="vmt-list">
            {notebooksLoading && notebooks.length === 0 && (
              <div className="vmt-empty">Loading...</div>
            )}
            {!notebooksLoading && notebooks.length === 0 && (
              <div className="vmt-empty">
                No notebooks yet.{' '}
                <a href="#" onClick={(e) => { e.preventDefault(); onNavigateToMarketplace?.('notebook'); }}>Get one from the marketplace</a>.
              </div>
            )}
            {notebooks
              .filter((n) => {
                if (!notebookSearchFilter) return true;
                const q = notebookSearchFilter.toLowerCase();
                return n.name.toLowerCase().includes(q) || (n.description || '').toLowerCase().includes(q);
              })
              .map((n) => (
              <div className="vmt-card" key={n.dir_name}>
                <div className="vmt-card-header">
                  <span className="vmt-card-name">{n.name}</span>
                  <OverflowMenu
                    isOpen={overflowOpen === `nb-${n.dir_name}`}
                    onToggle={() => setOverflowOpen(overflowOpen === `nb-${n.dir_name}` ? null : `nb-${n.dir_name}`)}
                    onClose={() => setOverflowOpen(null)}
                    items={[
                      ...(onPublishNotebook ? [{ label: 'Publish', onClick: () => onPublishNotebook(n.dir_name) }] : []),
                      { label: '', onClick: () => {}, separator: true },
                      { label: 'Delete', onClick: () => setDeleteConfirm({ dirName: n.dir_name, name: n.name, category: 'notebook' }), danger: true },
                    ]}
                  />
                </div>
                {n.description && (
                  <div className="vmt-card-desc">{n.description}</div>
                )}
                {n.created && (
                  <div className="vmt-card-meta">
                    <span>{formatDate(n.created)}</span>
                  </div>
                )}
                <div className="vmt-card-actions">
                  <Tooltip text="Open this notebook's folder in JupyterLab">
                    <button
                      className="vmt-btn-add"
                      style={{ width: '100%' }}
                      onClick={() => handleEditInJupyter(n.dir_name)}
                      disabled={launchingNotebook === n.dir_name}
                    >
                      {launchingNotebook === n.dir_name ? 'Opening...' : 'JupyterLab'}
                    </button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── Delete Confirmation Modal ─── */}
      {deleteConfirm && (
        <div className="template-modal-overlay" onClick={() => !deleting && setDeleteConfirm(null)}>
          <div className="template-modal" onClick={(e) => e.stopPropagation()}>
            <h4>Delete Artifact</h4>
            <p>Are you sure you want to delete <strong>{deleteConfirm.name}</strong>? This cannot be undone.</p>
            <div className="template-modal-actions">
              <button onClick={() => setDeleteConfirm(null)} disabled={deleting}>Cancel</button>
              <button className="primary" style={{ background: '#e25241' }} onClick={handleDeleteArtifact} disabled={deleting}>
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});
