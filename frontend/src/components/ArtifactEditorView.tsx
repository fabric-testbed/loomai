'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import CytoscapeGraph from './CytoscapeGraph';
import EditorPanel from './EditorPanel';
import ContainerFileBrowser from './ContainerFileBrowser';
import * as api from '../api/client';
import type { SliceData, SiteInfo, ComponentModel, FileEntry, ProjectInfo } from '../types/fabric';
import type { PersonSearchResult } from '../api/client';
import '../styles/artifact-editor.css';

interface ArtifactEditorViewProps {
  dirName: string;
  onBack: () => void;
  onLaunchJupyter: (path: string) => void;
  sites: SiteInfo[];
  images: string[];
  componentModels: ComponentModel[];
  dark: boolean;
}

type TabId = 'metadata' | 'topology' | 'files';

const ARTIFACT_BASE = 'my_artifacts';

export default function ArtifactEditorView({
  dirName,
  onBack,
  onLaunchJupyter,
  sites,
  images,
  componentModels,
  dark,
}: ArtifactEditorViewProps) {
  // --- Tab state ---
  const [activeTab, setActiveTab] = useState<TabId>('metadata');

  // --- Metadata state ---
  const [metaName, setMetaName] = useState('');
  const [metaDescShort, setMetaDescShort] = useState('');
  const [metaDescLong, setMetaDescLong] = useState('');
  const [metaTags, setMetaTags] = useState<string[]>([]);
  const [metaAuthors, setMetaAuthors] = useState<string[]>([]);
  const [metaProjectUuid, setMetaProjectUuid] = useState('');
  const [metaVisibility, setMetaVisibility] = useState('author');
  const [metaCategory, setMetaCategory] = useState('');
  const [metaLoaded, setMetaLoaded] = useState(false);
  const [metaSaving, setMetaSaving] = useState(false);
  const [metaSaved, setMetaSaved] = useState(false);
  const [metaError, setMetaError] = useState('');
  const [tagInput, setTagInput] = useState('');
  const [projects, setProjects] = useState<ProjectInfo[]>([]);

  // --- Author search state ---
  const [authorSearch, setAuthorSearch] = useState('');
  const [authorResults, setAuthorResults] = useState<PersonSearchResult[]>([]);
  const [authorSearching, setAuthorSearching] = useState(false);
  const [showAuthorSearch, setShowAuthorSearch] = useState(false);
  const authorSearchRef = useRef<HTMLDivElement>(null);
  const authorDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // --- File existence ---
  const [hasSliceJson, setHasSliceJson] = useState(false);
  const [filesChecked, setFilesChecked] = useState(false);

  // --- Topology state ---
  const [topoSliceData, setTopoSliceData] = useState<SliceData | null>(null);
  const [topoSelectedElement, setTopoSelectedElement] = useState<Record<string, string> | null>(null);
  const [topoLayout, setTopoLayout] = useState('dagre');
  const [topoLoading, setTopoLoading] = useState(false);
  const [topoSaving, setTopoSaving] = useState(false);
  const [topoError, setTopoError] = useState('');
  const [topoSaved, setTopoSaved] = useState(false);
  const tempDraftNameRef = useRef<string>('');

  const artifactPath = `${ARTIFACT_BASE}/${dirName}`;

  // --- Load metadata on mount ---
  useEffect(() => {
    loadMetadata();
    checkFiles();
    api.getProjects().then(r => setProjects(r.projects)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirName]);

  const loadMetadata = useCallback(async () => {
    try {
      const result = await api.readFileContent(`${artifactPath}/metadata.json`);
      const meta = JSON.parse(result.content);
      setMetaName(meta.name || '');
      setMetaDescShort(meta.description_short || meta.description || '');
      setMetaDescLong(meta.description_long || '');
      setMetaTags(Array.isArray(meta.tags) ? meta.tags : []);
      setMetaAuthors(Array.isArray(meta.authors) ? meta.authors : []);
      setMetaProjectUuid(meta.project_uuid || '');
      setMetaVisibility(meta.visibility || 'author');
      setMetaCategory(meta.category || '');
      setMetaLoaded(true);
    } catch {
      setMetaName(dirName);
      setMetaLoaded(true);
    }
  }, [artifactPath, dirName]);

  const checkFiles = useCallback(async () => {
    try {
      const files = await api.listFiles(artifactPath);
      const names = new Set(files.map((f: FileEntry) => f.name));
      setHasSliceJson(names.has('slice.json'));
    } catch {
      // Empty or missing dir
    }
    setFilesChecked(true);
  }, [artifactPath]);

  // --- Cleanup temp draft on unmount ---
  useEffect(() => {
    return () => {
      if (tempDraftNameRef.current) {
        api.deleteSlice(tempDraftNameRef.current).catch(() => {});
      }
    };
  }, []);

  // --- Metadata save ---
  const handleSaveMetadata = async () => {
    if (metaDescShort.length > 0 && metaDescShort.length < 5) {
      setMetaError('Short description must be at least 5 characters');
      return;
    }
    if (metaDescShort.length > 255) {
      setMetaError('Short description must be at most 255 characters');
      return;
    }
    setMetaSaving(true);
    setMetaError('');
    setMetaSaved(false);
    try {
      await api.updateLocalArtifactMetadata(dirName, {
        name: metaName,
        description_short: metaDescShort,
        description_long: metaDescLong,
        tags: metaTags,
        authors: metaAuthors,
        project_uuid: metaProjectUuid || undefined,
        visibility: metaVisibility,
      });
      setMetaSaved(true);
      setTimeout(() => setMetaSaved(false), 3000);
    } catch (e: any) {
      setMetaError(e.message);
    } finally {
      setMetaSaving(false);
    }
  };

  // --- Tag management ---
  const addTag = () => {
    const t = tagInput.trim();
    if (t && !metaTags.includes(t)) {
      setMetaTags([...metaTags, t]);
    }
    setTagInput('');
  };

  const removeTag = (tag: string) => {
    setMetaTags(metaTags.filter(t => t !== tag));
  };

  // --- Author management ---
  const removeAuthor = (index: number) => {
    setMetaAuthors(metaAuthors.filter((_, i) => i !== index));
  };

  const handleAuthorSearchChange = (value: string) => {
    setAuthorSearch(value);
    if (authorDebounceRef.current) clearTimeout(authorDebounceRef.current);
    if (value.length < 3) {
      setAuthorResults([]);
      setAuthorSearching(false);
      return;
    }
    setAuthorSearching(true);
    authorDebounceRef.current = setTimeout(async () => {
      try {
        const data = await api.searchPeople(value);
        setAuthorResults(data.results);
      } catch {
        setAuthorResults([]);
      } finally {
        setAuthorSearching(false);
      }
    }, 300);
  };

  const selectAuthor = (person: PersonSearchResult) => {
    const entry = person.email ? `${person.name} <${person.email}>` : person.name;
    if (!metaAuthors.includes(entry)) {
      setMetaAuthors([...metaAuthors, entry]);
    }
    setShowAuthorSearch(false);
    setAuthorSearch('');
    setAuthorResults([]);
  };

  const addCustomAuthor = () => {
    const text = authorSearch.trim();
    if (text && !metaAuthors.includes(text)) {
      setMetaAuthors([...metaAuthors, text]);
    }
    setShowAuthorSearch(false);
    setAuthorSearch('');
    setAuthorResults([]);
  };

  // Click-outside handler for author search dropdown
  useEffect(() => {
    if (!showAuthorSearch) return;
    const handleClick = (e: MouseEvent) => {
      if (authorSearchRef.current && !authorSearchRef.current.contains(e.target as Node)) {
        setShowAuthorSearch(false);
        setAuthorSearch('');
        setAuthorResults([]);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showAuthorSearch]);

  // --- Topology ---
  const loadTopology = useCallback(async () => {
    if (topoSliceData) return;
    setTopoLoading(true);
    setTopoError('');
    try {
      const result = await api.readFileContent(`${artifactPath}/slice.json`);
      const model = JSON.parse(result.content);
      const tempName = `__ae_${dirName}_${Date.now()}`;
      tempDraftNameRef.current = tempName;
      model.name = tempName;
      const sd = await api.importSlice(model);
      setTopoSliceData(sd);
    } catch (e: any) {
      setTopoError(e.message);
    } finally {
      setTopoLoading(false);
    }
  }, [artifactPath, dirName, topoSliceData]);

  const handleSaveTopology = async () => {
    if (!tempDraftNameRef.current) return;
    setTopoSaving(true);
    setTopoError('');
    setTopoSaved(false);
    try {
      const exported = await api.exportSliceJson(tempDraftNameRef.current);
      await api.writeFileContent(
        `${artifactPath}/slice.json`,
        JSON.stringify(exported, null, 2)
      );
      setTopoSaved(true);
      setTimeout(() => setTopoSaved(false), 3000);
    } catch (e: any) {
      setTopoError(e.message);
    } finally {
      setTopoSaving(false);
    }
  };

  const handleCreateSliceJson = async () => {
    const minimal = {
      format: 'fabric-slice-v1',
      name: metaName || dirName,
      nodes: [],
      networks: [],
    };
    try {
      await api.writeFileContent(
        `${artifactPath}/slice.json`,
        JSON.stringify(minimal, null, 2)
      );
      setHasSliceJson(true);
    } catch (e: any) {
      setTopoError(e.message);
    }
  };

  const handleTopoSliceUpdated = useCallback((data: SliceData) => {
    setTopoSliceData(data);
  }, []);

  // Auto-load topology as soon as we know slice.json exists
  useEffect(() => {
    if (hasSliceJson && !topoSliceData && !topoLoading) {
      loadTopology();
    }
  }, [hasSliceJson, topoSliceData, topoLoading, loadTopology]);

  // Auto-switch to topology tab when slice.json is detected on initial load
  useEffect(() => {
    if (filesChecked && hasSliceJson && activeTab === 'metadata') {
      setActiveTab('topology');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filesChecked]);

  // --- JupyterLab ---
  const handleOpenJupyter = async () => {
    try {
      const result = await api.startJupyter();
      if (result.status === 'running') {
        onLaunchJupyter(`/jupyter/lab/tree/my_artifacts/${encodeURIComponent(dirName)}`);
      }
    } catch (e: any) {
      alert(`Failed to open JupyterLab: ${e.message}`);
    }
  };

  // --- Render ---
  const categoryLabel = metaCategory || 'artifact';

  return (
    <div className="ae-root">
      {/* Header */}
      <div className="ae-header">
        <button className="ae-back-btn" onClick={onBack}>&larr; Back</button>
        <span className="ae-header-title">{metaName || dirName}</span>
        <span className="ae-header-badge">{categoryLabel}</span>
        <div className="ae-header-actions">
          <button className="tv-btn" onClick={handleOpenJupyter}>JupyterLab</button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="ae-tabs">
        <button className={`ae-tab ${activeTab === 'metadata' ? 'active' : ''}`}
          onClick={() => setActiveTab('metadata')}>Metadata</button>
        <button className={`ae-tab ${activeTab === 'topology' ? 'active' : ''}`}
          onClick={() => setActiveTab('topology')}>
          Topology{hasSliceJson ? '' : ' +'}
        </button>
        <button className={`ae-tab ${activeTab === 'files' ? 'active' : ''}`}
          onClick={() => setActiveTab('files')}>Files</button>
      </div>

      {/* Tab content */}
      {activeTab === 'metadata' && (
        <div className="ae-content">
          {metaLoaded ? (
            <div className="ae-metadata">
              <div className="ae-field">
                <label>Name</label>
                <input value={metaName} onChange={e => setMetaName(e.target.value)} />
              </div>

              <div className="ae-field">
                <label>Short Description</label>
                <input value={metaDescShort} onChange={e => setMetaDescShort(e.target.value)}
                  maxLength={255} placeholder="Brief summary (5-255 chars)" />
                <span className={`ae-char-count ${metaDescShort.length > 0 && (metaDescShort.length < 5 || metaDescShort.length > 255) ? 'over' : ''}`}>
                  {metaDescShort.length}/255{metaDescShort.length > 0 && metaDescShort.length < 5 ? ' (min 5)' : ''}
                </span>
              </div>

              <div className="ae-field">
                <label>Long Description</label>
                <textarea value={metaDescLong} onChange={e => setMetaDescLong(e.target.value)}
                  placeholder="Detailed description of this artifact..." />
              </div>

              <div className="ae-field">
                <label>Project</label>
                <select value={metaProjectUuid} onChange={e => setMetaProjectUuid(e.target.value)}>
                  <option value="">— None —</option>
                  {projects.map(p => (
                    <option key={p.uuid} value={p.uuid}>{p.name}</option>
                  ))}
                </select>
              </div>

              <div className="ae-field">
                <label>Visibility</label>
                <div className="ae-vis-options">
                  {(['author', 'project', 'public'] as const).map(v => (
                    <label key={v} className={`ae-vis-option ${metaVisibility === v ? 'active' : ''}`}>
                      <input type="radio" name="ae-vis" value={v}
                        checked={metaVisibility === v} onChange={() => setMetaVisibility(v)} />
                      {v === 'author' ? 'Only Me' : v === 'project' ? 'My Project' : 'Public'}
                    </label>
                  ))}
                </div>
              </div>

              <div className="ae-field">
                <label>Tags</label>
                <div className="ae-tags">
                  {metaTags.map(tag => (
                    <span key={tag} className="ae-tag-chip">
                      {tag}
                      <button className="ae-tag-remove" onClick={() => removeTag(tag)}>&times;</button>
                    </span>
                  ))}
                  <span className="ae-tag-add">
                    <input value={tagInput}
                      onChange={e => setTagInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                      placeholder="Add tag..." />
                    <button className="tv-btn" onClick={addTag} disabled={!tagInput.trim()}>+</button>
                  </span>
                </div>
              </div>

              <div className="ae-field">
                <label>Authors</label>
                <div className="ae-authors">
                  {metaAuthors.map((author, i) => (
                    <div key={i} className="ae-author-row">
                      <span className="ae-author-display">{author}</span>
                      <button className="ae-author-remove" onClick={() => removeAuthor(i)}>&times;</button>
                    </div>
                  ))}
                  {showAuthorSearch ? (
                    <div className="ae-author-search" ref={authorSearchRef}>
                      <input
                        value={authorSearch}
                        onChange={e => handleAuthorSearchChange(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter' && authorSearch.trim()) {
                            e.preventDefault();
                            addCustomAuthor();
                          } else if (e.key === 'Escape') {
                            setShowAuthorSearch(false);
                            setAuthorSearch('');
                            setAuthorResults([]);
                          }
                        }}
                        placeholder="Search by name, email, or UUID..."
                        autoFocus
                      />
                      {(authorSearch.length >= 3 || authorSearching) && (
                        <div className="ae-author-dropdown">
                          {authorSearching ? (
                            <div className="ae-author-no-results">Searching...</div>
                          ) : authorResults.length > 0 ? (
                            authorResults.map(person => (
                              <button
                                key={person.uuid}
                                className="ae-author-option"
                                onClick={() => selectAuthor(person)}
                              >
                                <span className="ae-author-option-name">{person.name}</span>
                                <span className="ae-author-option-detail">
                                  {person.email}{person.affiliation ? ` — ${person.affiliation}` : ''}
                                </span>
                              </button>
                            ))
                          ) : (
                            <div className="ae-author-no-results">
                              No matching users.{' '}
                              <button className="ae-author-add-custom" onClick={addCustomAuthor}>
                                Add &quot;{authorSearch}&quot; as custom entry
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ) : (
                    <button className="ae-add-btn" onClick={() => setShowAuthorSearch(true)}>+ Add Author</button>
                  )}
                </div>
              </div>

              {metaError && <div className="ae-error">{metaError}</div>}

              <div className="ae-save-row">
                <button className="tv-btn tv-btn-primary" onClick={handleSaveMetadata}
                  disabled={metaSaving}>
                  {metaSaving ? 'Saving...' : 'Save Metadata'}
                </button>
                {metaSaved && <span className="ae-saved-msg">Saved</span>}
              </div>
            </div>
          ) : (
            <div className="ae-info">Loading metadata...</div>
          )}
        </div>
      )}

      {activeTab === 'topology' && (
        <div className="ae-topology-wrap">
          {!hasSliceJson && filesChecked ? (
            <div className="ae-topology-empty">
              <div>No slice.json found in this artifact.</div>
              <button className="tv-btn tv-btn-primary" onClick={handleCreateSliceJson}>
                Add Topology (slice.json)
              </button>
            </div>
          ) : topoLoading ? (
            <div className="ae-topology-empty">
              <div>Loading topology...</div>
            </div>
          ) : topoError && !topoSliceData ? (
            <div className="ae-topology-empty">
              <div className="ae-error">{topoError}</div>
            </div>
          ) : topoSliceData ? (
            <>
              <div className="ae-topology">
                <div className="ae-topology-graph">
                  <CytoscapeGraph
                    graph={topoSliceData.graph ?? null}
                    layout={topoLayout}
                    dark={dark}
                    sliceData={topoSliceData}
                    onLayoutChange={setTopoLayout}
                    onNodeClick={setTopoSelectedElement}
                    onEdgeClick={setTopoSelectedElement}
                    onBackgroundClick={() => setTopoSelectedElement(null)}
                    onContextAction={() => {}}
                  />
                </div>
                <div className="ae-topology-sidebar">
                  <EditorPanel
                    sliceData={topoSliceData}
                    sliceName={tempDraftNameRef.current}
                    onSliceUpdated={handleTopoSliceUpdated}
                    onCollapse={() => {}}
                    sites={sites}
                    images={images}
                    componentModels={componentModels}
                    selectedElement={topoSelectedElement}
                  />
                </div>
              </div>
              <div className="ae-topology-actions">
                <button className="tv-btn tv-btn-primary" onClick={handleSaveTopology}
                  disabled={topoSaving}>
                  {topoSaving ? 'Saving...' : 'Save Topology'}
                </button>
                {topoSaved && <span className="ae-saved-msg">Saved to slice.json</span>}
                {topoError && <span className="ae-error">{topoError}</span>}
              </div>
            </>
          ) : (
            <div className="ae-topology-empty">
              <div>Loading...</div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'files' && (
        <div className="ae-files-wrap">
          <ContainerFileBrowser rootPath={artifactPath} headerLabel={`Files: ${metaName || dirName}`} />
        </div>
      )}
    </div>
  );
}
