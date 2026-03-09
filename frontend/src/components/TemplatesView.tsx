'use client';
import { useState, useEffect, useCallback } from 'react';
import type { SliceData, VMTemplateSummary, RecipeSummary } from '../types/fabric';
import type { TemplateSummary } from '../api/client';
import * as api from '../api/client';
import '../styles/templates-view.css';

interface TemplatesViewProps {
  onLoadSlice: (data: SliceData) => void;
}

type TabId = 'slice' | 'vm' | 'recipes';

interface ToolEntry {
  filename: string;
}

export default function TemplatesView({ onLoadSlice }: TemplatesViewProps) {
  const [tab, setTab] = useState<TabId>('slice');
  const [search, setSearch] = useState('');
  const [reloading, setReloading] = useState(false);

  // Slice templates
  const [sliceTemplates, setSliceTemplates] = useState<TemplateSummary[]>([]);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [sliceError, setSliceError] = useState('');

  // VM templates
  const [vmTemplates, setVmTemplates] = useState<VMTemplateSummary[]>([]);
  const [vmLoading, setVmLoading] = useState(false);
  const [vmError, setVmError] = useState('');

  // Recipes
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [recipesLoading, setRecipesLoading] = useState(false);

  // Loading a template
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [loadSliceName, setLoadSliceName] = useState('');
  const [showLoadInput, setShowLoadInput] = useState<string | null>(null);

  // Edit state
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editingType, setEditingType] = useState<TabId>('slice');
  const [editDesc, setEditDesc] = useState('');
  const [editTools, setEditTools] = useState<ToolEntry[]>([]);
  const [editDirty, setEditDirty] = useState(false);

  // Script editor state
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [scriptContent, setScriptContent] = useState('');
  const [scriptDirty, setScriptDirty] = useState(false);
  const [scriptLoading, setScriptLoading] = useState(false);

  // New file input
  const [newFileName, setNewFileName] = useState('');

  // Fetch slice templates
  const fetchSliceTemplates = useCallback(async () => {
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

  // Fetch VM templates
  const fetchVmTemplates = useCallback(async () => {
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

  // Fetch recipes
  const fetchRecipes = useCallback(async () => {
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
    fetchSliceTemplates();
    fetchVmTemplates();
    fetchRecipes();
  }, [fetchSliceTemplates, fetchVmTemplates, fetchRecipes]);

  // Reload (resync)
  const handleReload = async () => {
    setReloading(true);
    try {
      const [st, vm] = await Promise.all([
        api.resyncTemplates(),
        api.resyncVmTemplates(),
      ]);
      setSliceTemplates(st);
      setVmTemplates(vm);
    } catch (e: any) {
      // fallback: just refresh
      await Promise.all([fetchSliceTemplates(), fetchVmTemplates()]);
    } finally {
      setReloading(false);
    }
  };

  // Load slice template
  const handleLoad = async (dirName: string) => {
    setLoadingName(dirName);
    try {
      const data = await api.loadTemplate(dirName, loadSliceName || undefined);
      onLoadSlice(data);
    } catch (e: any) {
      setSliceError(e.message);
    } finally {
      setLoadingName(null);
      setShowLoadInput(null);
      setLoadSliceName('');
    }
  };

  // Delete slice template
  const handleDeleteSlice = async (dirName: string) => {
    try {
      await api.deleteTemplate(dirName);
      setSliceTemplates(prev => prev.filter(t => t.dir_name !== dirName));
      if (editingName === dirName && editingType === 'slice') closeEditor();
    } catch (e: any) {
      setSliceError(e.message);
    }
  };

  // Delete VM template
  const handleDeleteVm = async (dirName: string) => {
    try {
      await api.deleteVmTemplate(dirName);
      setVmTemplates(prev => prev.filter(t => t.dir_name !== dirName));
      if (editingName === dirName && editingType === 'vm') closeEditor();
    } catch (e: any) {
      setVmError(e.message);
    }
  };

  // Open editor
  const openEditor = async (dirName: string, type: TabId) => {
    setEditingName(dirName);
    setEditingType(type);
    setEditDirty(false);
    setEditingFile(null);
    setScriptDirty(false);
    setNewFileName('');

    try {
      if (type === 'slice') {
        const detail = await api.getTemplate(dirName);
        setEditDesc(detail.description || '');
        setEditTools(detail.tools || []);
      } else {
        const detail = await api.getVmTemplate(dirName);
        setEditDesc(detail.description || '');
        setEditTools((detail as any).tools || []);
      }
    } catch (e: any) {
      setEditDesc('');
      setEditTools([]);
    }
  };

  const closeEditor = () => {
    setEditingName(null);
    setEditingFile(null);
    setScriptDirty(false);
    setEditDirty(false);
    setNewFileName('');
  };

  // Save description
  const saveDescription = async () => {
    if (!editingName) return;
    try {
      if (editingType === 'slice') {
        await api.updateTemplate(editingName, { description: editDesc });
        setSliceTemplates(prev => prev.map(t =>
          t.dir_name === editingName ? { ...t, description: editDesc } : t
        ));
      } else {
        await api.updateVmTemplate(editingName, { description: editDesc });
        setVmTemplates(prev => prev.map(t =>
          t.dir_name === editingName ? { ...t, description: editDesc } : t
        ));
      }
      setEditDirty(false);
    } catch (e: any) {
      // show inline error if needed
    }
  };

  // Open script file
  const openScript = async (filename: string) => {
    if (!editingName) return;
    setScriptLoading(true);
    setEditingFile(filename);
    try {
      const readFn = editingType === 'slice' ? api.readTemplateTool : api.readVmTemplateTool;
      const result = await readFn(editingName, filename);
      setScriptContent(result.content);
      setScriptDirty(false);
    } catch (e: any) {
      setScriptContent(`# Error loading file: ${e.message}`);
    } finally {
      setScriptLoading(false);
    }
  };

  // Save script
  const saveScript = async () => {
    if (!editingName || !editingFile) return;
    try {
      const writeFn = editingType === 'slice' ? api.writeTemplateTool : api.writeVmTemplateTool;
      await writeFn(editingName, editingFile, scriptContent);
      setScriptDirty(false);
    } catch (e: any) {
      // error
    }
  };

  // Add new tool file
  const addNewFile = async () => {
    if (!editingName || !newFileName.trim()) return;
    const fname = newFileName.trim();
    try {
      const writeFn = editingType === 'slice' ? api.writeTemplateTool : api.writeVmTemplateTool;
      await writeFn(editingName, fname, '#!/bin/bash\n');
      setEditTools(prev => [...prev, { filename: fname }]);
      setNewFileName('');
      openScript(fname);
    } catch (e: any) {
      // error
    }
  };

  // Delete tool file
  const deleteToolFile = async (filename: string) => {
    if (!editingName) return;
    try {
      const deleteFn = editingType === 'slice' ? api.deleteTemplateTool : api.deleteVmTemplateTool;
      await deleteFn(editingName, filename);
      setEditTools(prev => prev.filter(t => t.filename !== filename));
      if (editingFile === filename) {
        setEditingFile(null);
        setScriptContent('');
        setScriptDirty(false);
      }
    } catch (e: any) {
      // error
    }
  };

  // Filtered lists
  const filteredSlice = sliceTemplates.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) ||
    (t.description || '').toLowerCase().includes(search.toLowerCase())
  );

  const filteredVm = vmTemplates.filter(t =>
    !search || t.name.toLowerCase().includes(search.toLowerCase()) ||
    (t.description || '').toLowerCase().includes(search.toLowerCase())
  );

  const filteredRecipes = recipes.filter(r =>
    !search || r.name.toLowerCase().includes(search.toLowerCase()) ||
    (r.description || '').toLowerCase().includes(search.toLowerCase())
  );

  const renderSliceCard = (t: TemplateSummary) => {
    const isEditing = editingName === t.dir_name && editingType === 'slice';
    return (
      <div key={t.dir_name} className={`tv-card ${isEditing ? 'tv-card-editing' : ''}`}>
        <div className="tv-card-header">
          <span className="tv-card-name">{t.name}</span>
          {t.builtin ? (
            <span className="tv-badge tv-badge-builtin">Built-in</span>
          ) : (
            <span className="tv-badge tv-badge-user">User</span>
          )}
        </div>
        {t.description && <div className="tv-card-desc">{t.description}</div>}
        <div className="tv-card-meta">
          <span>{t.node_count} node{t.node_count !== 1 ? 's' : ''}</span>
          <span>{t.network_count} network{t.network_count !== 1 ? 's' : ''}</span>
        </div>
        {showLoadInput === t.dir_name ? (
          <div className="tv-load-row">
            <input
              className="tv-load-input"
              placeholder="Slice name (optional)"
              value={loadSliceName}
              onChange={e => setLoadSliceName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleLoad(t.dir_name); if (e.key === 'Escape') { setShowLoadInput(null); setLoadSliceName(''); } }}
              autoFocus
            />
            <button className="tv-btn tv-btn-primary" onClick={() => handleLoad(t.dir_name)} disabled={loadingName === t.dir_name}>
              {loadingName === t.dir_name ? 'Loading...' : 'Go'}
            </button>
            <button className="tv-btn" onClick={() => { setShowLoadInput(null); setLoadSliceName(''); }}>Cancel</button>
          </div>
        ) : (
          <div className="tv-card-actions">
            <button className="tv-btn tv-btn-primary" onClick={() => { setShowLoadInput(t.dir_name); setLoadSliceName(''); }}>
              Load
            </button>
            <button className="tv-btn" onClick={() => openEditor(t.dir_name, 'slice')}>
              Edit
            </button>
            <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteSlice(t.dir_name)}>
              Delete
            </button>
          </div>
        )}
      </div>
    );
  };

  const renderVmCard = (t: VMTemplateSummary) => {
    const isEditing = editingName === t.dir_name && editingType === 'vm';
    return (
      <div key={t.dir_name} className={`tv-card ${isEditing ? 'tv-card-editing' : ''}`}>
        <div className="tv-card-header">
          <span className="tv-card-name">{t.name}</span>
          {t.builtin ? (
            <span className="tv-badge tv-badge-builtin">Built-in</span>
          ) : (
            <span className="tv-badge tv-badge-user">User</span>
          )}
        </div>
        {t.description && <div className="tv-card-desc">{t.description}</div>}
        <div className="tv-card-meta">
          <span>Image: {t.image}</span>
        </div>
        <div className="tv-card-actions">
          <button className="tv-btn" onClick={() => openEditor(t.dir_name, 'vm')}>
            Edit
          </button>
          <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteVm(t.dir_name)}>
            Delete
          </button>
        </div>
      </div>
    );
  };

  const renderEditDrawer = () => {
    if (!editingName) return null;
    const templateName = editingType === 'slice'
      ? sliceTemplates.find(t => t.dir_name === editingName)?.name
      : vmTemplates.find(t => t.dir_name === editingName)?.name;

    return (
      <div className="tv-edit-drawer">
        <div className="tv-edit-title">
          Editing: {templateName || editingName}
          <button className="tv-btn" onClick={closeEditor} style={{ marginLeft: 'auto' }}>Close</button>
        </div>

        {/* Description */}
        <div className="tv-edit-section">
          <label className="tv-edit-label">Description</label>
          <textarea
            className="tv-edit-textarea"
            value={editDesc}
            onChange={e => { setEditDesc(e.target.value); setEditDirty(true); }}
          />
          <div className="tv-edit-actions">
            <button className="tv-btn tv-btn-primary" onClick={saveDescription} disabled={!editDirty}>
              Save Description
            </button>
          </div>
        </div>

        {/* Tools */}
        <div className="tv-edit-section">
          <label className="tv-edit-label">Tool Scripts ({editTools.length})</label>
          {editTools.length > 0 ? (
            <ul className="tv-tools-list">
              {editTools.map(tool => (
                <li key={tool.filename} className="tv-tool-item">
                  <span className="tv-tool-name">{tool.filename}</span>
                  <button className="tv-tool-btn" onClick={() => openScript(tool.filename)}>
                    {editingFile === tool.filename ? 'Editing' : 'Edit'}
                  </button>
                  <button className="tv-tool-btn tv-tool-btn-danger" onClick={() => deleteToolFile(tool.filename)}>
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="tv-empty" style={{ padding: '10px 0' }}>No tool scripts</div>
          )}
          <div className="tv-new-file-row">
            <input
              className="tv-new-file-input"
              placeholder="new_script.sh"
              value={newFileName}
              onChange={e => setNewFileName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addNewFile(); }}
            />
            <button className="tv-btn" onClick={addNewFile} disabled={!newFileName.trim()}>
              + New File
            </button>
          </div>
        </div>

        {/* Script editor */}
        {editingFile && (
          <div className="tv-script-editor">
            <div className="tv-script-header">
              {editingFile}
              <div className="tv-script-header-actions">
                <button className="tv-btn tv-btn-primary" onClick={saveScript} disabled={!scriptDirty}>
                  Save
                </button>
                <button className="tv-btn" onClick={() => { setEditingFile(null); setScriptDirty(false); }}>
                  Close
                </button>
              </div>
            </div>
            {scriptLoading ? (
              <div className="tv-loading">Loading...</div>
            ) : (
              <textarea
                className="tv-script-textarea"
                value={scriptContent}
                onChange={e => { setScriptContent(e.target.value); setScriptDirty(true); }}
                spellCheck={false}
              />
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="tv-root">
      <div className="tv-header">
        <h1 className="tv-title">Slice Artifacts</h1>
        <button className="tv-reload-btn" onClick={handleReload} disabled={reloading}>
          {reloading ? 'Reloading...' : 'Reload'}
        </button>
      </div>

      <div className="tv-tabs">
        <button className={`tv-tab ${tab === 'slice' ? 'active' : ''}`} onClick={() => setTab('slice')}>
          Slice Templates ({sliceTemplates.length})
        </button>
        <button className={`tv-tab ${tab === 'vm' ? 'active' : ''}`} onClick={() => setTab('vm')}>
          VM Templates ({vmTemplates.length})
        </button>
        <button className={`tv-tab ${tab === 'recipes' ? 'active' : ''}`} onClick={() => setTab('recipes')}>
          Recipes ({recipes.length})
        </button>
      </div>

      <div className="tv-search">
        <input
          className="tv-search-input"
          placeholder={tab === 'recipes' ? 'Search recipes...' : 'Search templates...'}
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {tab === 'slice' ? (
        <>
          {sliceLoading && !sliceTemplates.length && <div className="tv-loading">Loading slice templates...</div>}
          {sliceError && <div className="tv-error">{sliceError}</div>}
          <div className="tv-grid">
            {filteredSlice.map(renderSliceCard)}
          </div>
          {!sliceLoading && !filteredSlice.length && <div className="tv-empty">No slice templates found.</div>}
          {editingType === 'slice' && renderEditDrawer()}
        </>
      ) : tab === 'vm' ? (
        <>
          {vmLoading && !vmTemplates.length && <div className="tv-loading">Loading VM templates...</div>}
          {vmError && <div className="tv-error">{vmError}</div>}
          <div className="tv-grid">
            {filteredVm.map(renderVmCard)}
          </div>
          {!vmLoading && !filteredVm.length && <div className="tv-empty">No VM templates found.</div>}
          {editingType === 'vm' && renderEditDrawer()}
        </>
      ) : (
        <>
          {recipesLoading && !recipes.length && <div className="tv-loading">Loading recipes...</div>}
          <div className="tv-grid">
            {filteredRecipes.map(r => (
              <div key={r.dir_name} className="tv-card">
                <div className="tv-card-header">
                  <span className="tv-card-name">{r.name}</span>
                  {r.builtin ? (
                    <span className="tv-badge tv-badge-builtin">Built-in</span>
                  ) : (
                    <span className="tv-badge tv-badge-user">User</span>
                  )}
                </div>
                {r.description && <div className="tv-card-desc">{r.description}</div>}
                <div className="tv-card-meta">
                  <span>Images: {Object.keys(r.image_patterns).join(', ')}</span>
                </div>
              </div>
            ))}
          </div>
          {!recipesLoading && !filteredRecipes.length && <div className="tv-empty">No recipes found.</div>}
        </>
      )}
    </div>
  );
}
