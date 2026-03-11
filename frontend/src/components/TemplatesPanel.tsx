'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceData, VMTemplateSummary } from '../types/fabric';
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

interface TemplatesPanelProps {
  // Slice template props
  onSliceImported: (data: SliceData) => void;
  // VM template props
  onVmTemplatesChanged: () => void;
  sliceName: string;
  sliceData: SliceData | null;
  onNodeAdded: (data: SliceData) => void;
  // Panel chrome
  onCollapse: () => void;
  dragHandleProps?: DragHandleProps;
  panelIcon?: string;
}

type TabId = 'slice' | 'vm';

export default function TemplatesPanel({
  onSliceImported, onVmTemplatesChanged, sliceName, sliceData, onNodeAdded,
  onCollapse, dragHandleProps, panelIcon,
}: TemplatesPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('slice');

  // ─── Slice Templates state ───
  const [sliceTemplates, setSliceTemplates] = useState<TemplateSummary[]>([]);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [sliceError, setSliceError] = useState('');
  const [loadingTemplate, setLoadingTemplate] = useState<string | null>(null);  // display name
  const [loadingTemplateDirName, setLoadingTemplateDirName] = useState<string | null>(null);  // dir_name for API
  const [loadSliceName, setLoadSliceName] = useState('');
  const [deletingSliceTemplate, setDeletingSliceTemplate] = useState<string | null>(null);  // dir_name
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

  const handleDeleteSliceTemplate = async (templateName: string) => {
    setSliceError('');
    try {
      await api.deleteTemplate(templateName);
      setDeletingSliceTemplate(null);
      refreshSliceTemplates();
    } catch (e: any) {
      setSliceError(e.message);
    }
  };

  // ─── VM Templates state ───
  const [vmTemplates, setVmTemplates] = useState<VMTemplateSummary[]>([]);
  const [vmLoading, setVmLoading] = useState(false);
  const [vmError, setVmError] = useState('');
  const [vmSearchFilter, setVmSearchFilter] = useState('');
  const [addingTemplate, setAddingTemplate] = useState<string | null>(null);
  const [deletingVmTemplate, setDeletingVmTemplate] = useState<string | null>(null);

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

  const handleAddVm = async (dirName: string) => {
    if (!sliceName) return;
    setVmError('');
    setAddingTemplate(dirName);
    try {
      const detail = await api.getVmTemplate(dirName);
      const nodeName = generateNodeName(detail.name);

      // Build node params from template (resource sizing + hardware)
      const nodeParams: Parameters<typeof api.addNode>[1] = {
        name: nodeName,
        image: detail.image,
      };
      if (detail.cores) nodeParams.cores = detail.cores;
      if (detail.ram) nodeParams.ram = detail.ram;
      if (detail.disk) nodeParams.disk = detail.disk;
      if (detail.host) nodeParams.host = detail.host;
      if (detail.image_type) nodeParams.image_type = detail.image_type;
      if (detail.username) nodeParams.username = detail.username;
      if (detail.instance_type) nodeParams.instance_type = detail.instance_type;
      if (detail.components?.length) nodeParams.components = detail.components;

      const result = await api.addNode(sliceName, nodeParams);
      const bc = detail.boot_config;
      if (bc && (bc.commands.length > 0 || bc.uploads.length > 0 || bc.network.length > 0)) {
        await api.saveBootConfig(sliceName, nodeName, bc);
      }
      onNodeAdded(result);
    } catch (e: any) {
      setVmError(e.message);
    } finally {
      setAddingTemplate(null);
    }
  };

  const handleDeleteVmTemplate = async (templateName: string) => {
    setVmError('');
    try {
      await api.deleteVmTemplate(templateName);
      setDeletingVmTemplate(null);
      refreshVmTemplates();
      onVmTemplatesChanged();
    } catch (e: any) {
      setVmError(e.message);
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
        <Tooltip text="Browse and load slice templates, VM templates, or recipes">
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className="panel-drag-handle">{'\u283F'}</span>
            Artifacts
          </span>
        </Tooltip>
        <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">
          {'\u2715'}
        </button>
      </div>

      {/* Tab bar */}
      <div className="templates-tab-bar">
        <button
          className={`templates-tab${activeTab === 'slice' ? ' active' : ''}`}
          onClick={() => setActiveTab('slice')}
        >
          Slice
        </button>
        <button
          className={`templates-tab${activeTab === 'vm' ? ' active' : ''}`}
          onClick={() => setActiveTab('vm')}
        >
          VM
        </button>
      </div>

      {/* ─── Slice Templates Tab ─── */}
      {activeTab === 'slice' && (
        <div className="template-body">
          {sliceError && <div className="template-error">{sliceError}</div>}

          {sliceTemplates.length > 0 && (
            <div className="template-search-wrapper">
              <input
                type="text"
                className="template-search-input"
                placeholder="Filter slice templates..."
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
                No templates saved yet. Use the "Save Template" button in the toolbar to create one.
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
                  <Tooltip text="Permanently remove this template">
                    <button
                      className="template-btn-delete"
                      onClick={() => setDeletingSliceTemplate(t.dir_name)}
                      data-help-id="templates.delete"
                    >
                      Delete
                    </button>
                  </Tooltip>
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

          {/* Delete Confirmation Modal */}
          {deletingSliceTemplate && (
            <div className="template-modal-overlay" onClick={() => setDeletingSliceTemplate(null)}>
              <div className="template-modal" onClick={(e) => e.stopPropagation()}>
                <h4>Delete Template</h4>
                <p>Are you sure you want to delete <strong>{sliceTemplates.find(t => t.dir_name === deletingSliceTemplate)?.name ?? deletingSliceTemplate}</strong>?</p>
                <div className="template-modal-actions">
                  <button onClick={() => setDeletingSliceTemplate(null)}>Cancel</button>
                  <button className="danger" onClick={() => handleDeleteSliceTemplate(deletingSliceTemplate)}>Delete</button>
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
                No VM templates yet. Right-click a node or use "Save VM Template" in the editor to create one.
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
                </div>
                {t.description && (
                  <div className="vmt-card-desc">{t.description}</div>
                )}
                <div className="vmt-card-meta">
                  <span>Image: {t.image}</span>
                  <span>{formatDate(t.created)}</span>
                </div>
                <div className="vmt-card-actions">
                  <Tooltip text={!sliceName ? 'Select or create a slice first' : 'Add a new node to the current slice using this VM template configuration'}>
                    <button
                      className="vmt-btn-add"
                      disabled={!sliceName || addingTemplate === t.dir_name}
                      onClick={() => handleAddVm(t.dir_name)}
                      data-help-id="vm-templates.add-vm"
                    >
                      {addingTemplate === t.dir_name ? 'Adding...' : 'Add VM'}
                    </button>
                  </Tooltip>
                  <Tooltip text="Permanently remove this VM template">
                    <button
                      className="vmt-btn-delete"
                      onClick={() => setDeletingVmTemplate(t.name)}
                      data-help-id="vm-templates.delete"
                    >
                      Delete
                    </button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>

          {/* Delete Confirmation Modal */}
          {deletingVmTemplate && (
            <div className="vmt-modal-overlay" onClick={() => setDeletingVmTemplate(null)}>
              <div className="vmt-modal" onClick={(e) => e.stopPropagation()}>
                <h4>Delete VM Template</h4>
                <p>Are you sure you want to delete <strong>{deletingVmTemplate}</strong>?</p>
                <div className="vmt-modal-actions">
                  <button onClick={() => setDeletingVmTemplate(null)}>Cancel</button>
                  <button className="danger" onClick={() => handleDeleteVmTemplate(deletingVmTemplate)}>Delete</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
