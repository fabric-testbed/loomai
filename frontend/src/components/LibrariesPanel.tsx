'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceData, VMTemplateSummary, RecipeSummary } from '../types/fabric';
import type { TemplateSummary } from '../api/client';
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
  onDeployWeave?: (templateDirName: string, sliceName: string) => void;
  // Run weave script callback — executes run.sh autonomously (no slice needed)
  onRunWeaveScript?: (templateDirName: string, weaveName: string) => void;
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

export default function LibrariesPanel({
  onSliceImported, onDeployWeave, onRunWeaveScript, onVmTemplatesChanged, sliceName, sliceData, onNodeAdded,
  onExecuteRecipe, executingRecipe, onRecipesChanged, onLaunchNotebook, onPublishNotebook,
  onPublishArtifact, onNavigateToMarketplace, onEditArtifact, onCollapse, dragHandleProps, panelIcon,
}: LibrariesPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('weaves');

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

  // ─── Deploy modal state ───
  const [deployingTemplate, setDeployingTemplate] = useState<string | null>(null); // display name
  const [deployingTemplateDirName, setDeployingTemplateDirName] = useState<string | null>(null);
  const [deploySliceName, setDeploySliceName] = useState('');

  const handleDeployWeave = () => {
    if (!deployingTemplateDirName || !onDeployWeave) return;
    const name = deploySliceName.trim() || deployingTemplate || deployingTemplateDirName;
    setDeployingTemplate(null);
    setDeployingTemplateDirName(null);
    onDeployWeave(deployingTemplateDirName, name);
  };

  const handleRunWeave = (dirName: string, weaveName: string) => {
    onRunWeaveScript?.(dirName, weaveName);
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
        onLaunchNotebook?.(`/jupyter/lab/tree/artifacts/${encodeURIComponent(dirName)}`);
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
  useEffect(() => {
    const interval = setInterval(() => {
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
              .map((t) => (
              <div className="template-card" key={t.dir_name}>
                <div className="template-card-header">
                  <span className="template-card-name">{t.name}</span>
                  {t.builtin && <span className="template-builtin-badge">built-in</span>}
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
                  {t.has_template !== false && (
                    <Tooltip text="Create a new draft slice from this template with pre-configured nodes and networks">
                      <button
                        className="template-btn-load"
                        onClick={() => {
                          setLoadSliceName(t.name);
                          setLoadingTemplate(t.name);
                          setLoadingTemplateDirName(t.dir_name);
                        }}
                        data-help-id="templates.load"
                      >
                        Load
                      </button>
                    </Tooltip>
                  )}
                  {t.has_template !== false && t.has_deploy && onDeployWeave && (
                    <Tooltip text="Load this weave as a new slice, submit it to FABRIC, and run boot configuration">
                      <button
                        className="template-btn-load"
                        style={{ background: 'rgba(0,142,122,0.08)', color: '#008e7a', borderColor: '#008e7a' }}
                        onClick={() => {
                          setDeploySliceName(t.name);
                          setDeployingTemplate(t.name);
                          setDeployingTemplateDirName(t.dir_name);
                        }}
                      >
                        Deploy
                      </button>
                    </Tooltip>
                  )}
                  {t.has_run && onRunWeaveScript && (
                    <Tooltip text="Execute run.sh — the script manages its own slices, experiments, and data collection">
                      <button
                        className="template-btn-load"
                        style={{ background: 'rgba(255,133,66,0.08)', color: '#ff8542', borderColor: '#ff8542' }}
                        onClick={() => handleRunWeave(t.dir_name, t.name)}
                      >
                        Run
                      </button>
                    </Tooltip>
                  )}
                  {!t.builtin && (
                    <Tooltip text="Open this artifact's folder in JupyterLab for editing">
                      <button
                        className="template-btn-load"
                        onClick={() => handleEditInJupyter(t.dir_name)}
                        disabled={launchingNotebook === t.dir_name}
                      >
                        {launchingNotebook === t.dir_name ? 'Opening...' : 'JupyterLab'}
                      </button>
                    </Tooltip>
                  )}
                  {!t.builtin && onEditArtifact && (
                    <Tooltip text="Open the artifact editor for this weave">
                      <button
                        className="template-btn-load"
                        onClick={() => onEditArtifact(t.dir_name)}
                      >
                        Edit
                      </button>
                    </Tooltip>
                  )}
                  {!t.builtin && (
                    <Tooltip text="Delete this weave">
                      <button
                        className="template-btn-load template-btn-delete"
                        onClick={() => setDeleteConfirm({ dirName: t.dir_name, name: t.name, category: 'weave' })}
                      >
                        Delete
                      </button>
                    </Tooltip>
                  )}
                </div>
              </div>
            ))}
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

          {/* Deploy Modal */}
          {deployingTemplate && (
            <div className="template-modal-overlay" onClick={() => setDeployingTemplate(null)}>
              <div className="template-modal" onClick={(e) => e.stopPropagation()}>
                <h4>Deploy Weave</h4>
                <p>Load, submit, and configure <strong>{deployingTemplate}</strong> as a new slice.</p>
                <input
                  type="text"
                  className="template-input"
                  placeholder="Slice name..."
                  value={deploySliceName}
                  onChange={(e) => setDeploySliceName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleDeployWeave()}
                  autoFocus
                />
                <div className="template-modal-actions">
                  <button onClick={() => setDeployingTemplate(null)}>Cancel</button>
                  <button className="primary" style={{ background: '#008e7a' }} onClick={() => handleDeployWeave()}>Deploy</button>
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
                  {t.builtin && <span className="vmt-badge-builtin">built-in</span>}
                  {t.version && <span className="vmt-badge-version">v{t.version}</span>}
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
                  {!t.builtin && (
                    <Tooltip text="Open this artifact's folder in JupyterLab for editing">
                      <button
                        className="vmt-btn-add"
                        onClick={() => handleEditInJupyter(t.dir_name)}
                        disabled={launchingNotebook === t.dir_name}
                      >
                        {launchingNotebook === t.dir_name ? 'Opening...' : 'Edit'}
                      </button>
                    </Tooltip>
                  )}
                  {!t.builtin && (
                    <Tooltip text="Delete this VM template">
                      <button
                        className="vmt-btn-add vmt-btn-delete"
                        onClick={() => setDeleteConfirm({ dirName: t.dir_name, name: t.name, category: 'vm-template' })}
                      >
                        Delete
                      </button>
                    </Tooltip>
                  )}
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
                  {r.builtin && <span className="vmt-badge-builtin">built-in</span>}
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
                      disabled={!sliceName || !sliceData?.nodes.length || executingRecipe === r.dir_name}
                      onClick={() => setRecipeNodePicker(r.dir_name)}
                    >
                      {executingRecipe === r.dir_name ? 'Applying...' : 'Apply'}
                    </button>
                  </Tooltip>
                  {!r.builtin && (
                    <Tooltip text="Open this artifact's folder in JupyterLab for editing">
                      <button
                        className="vmt-btn-add"
                        onClick={() => handleEditInJupyter(r.dir_name)}
                        disabled={launchingNotebook === r.dir_name}
                      >
                        {launchingNotebook === r.dir_name ? 'Opening...' : 'Edit'}
                      </button>
                    </Tooltip>
                  )}
                  {!r.builtin && (
                    <Tooltip text="Delete this recipe">
                      <button
                        className="vmt-btn-add vmt-btn-delete"
                        onClick={() => setDeleteConfirm({ dirName: r.dir_name, name: r.name, category: 'recipe' })}
                      >
                        Delete
                      </button>
                    </Tooltip>
                  )}
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
                      onClick={() => handleEditInJupyter(n.dir_name)}
                      disabled={launchingNotebook === n.dir_name}
                    >
                      {launchingNotebook === n.dir_name ? 'Opening...' : 'JupyterLab'}
                    </button>
                  </Tooltip>
                  <Tooltip text="Delete this notebook">
                    <button
                      className="vmt-btn-add vmt-btn-delete"
                      onClick={() => setDeleteConfirm({ dirName: n.dir_name, name: n.name, category: 'notebook' })}
                    >
                      Delete
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
}
