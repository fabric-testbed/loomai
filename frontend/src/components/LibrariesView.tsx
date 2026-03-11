'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { SliceData, FileEntry } from '../types/fabric';
import type {
  RemoteArtifact, TagInfo, ValidTag,
  LocalArtifact,
} from '../api/client';
import * as api from '../api/client';
import '../styles/libraries-view.css';

interface LibrariesViewProps {
  onLoadSlice: (data: SliceData) => void;
  onLaunchNotebook?: (jupyterPath: string) => void;
  onEditArtifact?: (dirName: string) => void;
  initialPublishNotebook?: string;   // dir_name — opens publish dialog on mount
  onClearPublishNotebook?: () => void;
  initialPublishArtifact?: { dirName: string; category: string };  // opens publish dialog for any artifact type
  onClearPublishArtifact?: () => void;
  initialMarketplaceCategory?: CategoryFilter;  // pre-set marketplace tab + category filter
  onClearMarketplaceCategory?: () => void;
  onNavigateToSlicesView?: (dirName: string) => void;
}

type TabId = 'my-artifacts' | 'published' | 'community';
type CategoryFilter = 'all' | 'weave' | 'vm-template' | 'recipe' | 'notebook';
type ViewMode = 'grid' | 'table' | 'preview';

/** Dual-label button text: shows full text normally, abbreviated when container is narrow. */
const BtnText = ({ full, short }: { full: string; short: string }) => (
  <><span className="tv-btn-full">{full}</span><span className="tv-btn-short">{short}</span></>
);

export default function LibrariesView({ onLoadSlice, onLaunchNotebook, onEditArtifact, initialPublishNotebook, onClearPublishNotebook, initialPublishArtifact, onClearPublishArtifact, initialMarketplaceCategory, onClearMarketplaceCategory, onNavigateToSlicesView }: LibrariesViewProps) {
  const [tab, setTab] = useState<TabId>('my-artifacts');
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [previewSelected, setPreviewSelected] = useState<string | null>(null);

  // ---- Local tab ----
  const [myArtifacts, setMyArtifacts] = useState<LocalArtifact[]>([]);
  const [authoredRemoteOnly, setAuthoredRemoteOnly] = useState<RemoteArtifact[]>([]);
  const [userEmail, setUserEmail] = useState('');
  const [myLoading, setMyLoading] = useState(false);
  const [myError, setMyError] = useState('');
  const [myCategoryFilter, setMyCategoryFilter] = useState<CategoryFilter>('all');

  // Overflow menu state
  const [overflowOpen, setOverflowOpen] = useState<string | null>(null);

  // Loading a template
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [loadSliceName, setLoadSliceName] = useState('');
  const [showLoadInput, setShowLoadInput] = useState<string | null>(null);

  // ---- Marketplace tab ----
  const [mpAllArtifacts, setMpAllArtifacts] = useState<RemoteArtifact[]>([]);
  const [mpAllTags, setMpAllTags] = useState<TagInfo[]>([]);
  const [mpLoading, setMpLoading] = useState(false);
  const [mpLoaded, setMpLoaded] = useState(false);
  const [mpError, setMpError] = useState('');
  const [mpSearch, setMpSearch] = useState('');
  const [mpActiveTags, setMpActiveTags] = useState<Set<string>>(new Set());
  const [mpSort, setMpSort] = useState<'popular' | 'newest' | 'az'>('popular');
  const [mpCategoryFilter, setMpCategoryFilter] = useState<CategoryFilter>('all');
  const [mpAuthorFilter, setMpAuthorFilter] = useState('');
  const [mpDownloading, setMpDownloading] = useState<string | null>(null);
  const [mpExpanded, setMpExpanded] = useState<string | null>(null);
  // Version picker for get/download
  const [versionPickerArt, setVersionPickerArt] = useState<RemoteArtifact | null>(null);

  // Inline edit state for authored marketplace artifacts
  const [mpEditing, setMpEditing] = useState<string | null>(null); // uuid
  const [mpEditTitle, setMpEditTitle] = useState('');
  const [mpEditDesc, setMpEditDesc] = useState('');
  const [mpEditVisibility, setMpEditVisibility] = useState('author');
  const [mpEditTags, setMpEditTags] = useState<Set<string>>(new Set());
  const [mpEditValidTags, setMpEditValidTags] = useState<ValidTag[]>([]);
  const [mpEditSaving, setMpEditSaving] = useState(false);
  const [mpEditError, setMpEditError] = useState('');
  const [mpDeleteConfirm, setMpDeleteConfirm] = useState<string | null>(null);
  const [mpDeleteBusy, setMpDeleteBusy] = useState(false);

  // ---- Create new artifact ----
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDesc, setCreateDesc] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');

  const handleCreateArtifact = async () => {
    if (!createName.trim()) return;
    setCreateBusy(true);
    setCreateError('');
    try {
      const result = await api.createBlankArtifact({ name: createName.trim(), description: createDesc.trim() });
      setShowCreateDialog(false);
      setCreateName('');
      setCreateDesc('');
      fetchMyArtifacts();
      if (onEditArtifact) onEditArtifact(result.dir_name);
    } catch (e: any) {
      setCreateError(e.message || 'Failed to create artifact');
    } finally {
      setCreateBusy(false);
    }
  };

  // ---- Editor state ----
  const [editing, setEditing] = useState<LocalArtifact | null>(null);
  const [editFiles, setEditFiles] = useState<FileEntry[]>([]);
  const [editCwd, setEditCwd] = useState('');
  const [editSelectedFile, setEditSelectedFile] = useState<string | null>(null);
  const [editFileContent, setEditFileContent] = useState('');
  const [editFileOriginal, setEditFileOriginal] = useState('');
  const [editFileLoading, setEditFileLoading] = useState(false);
  const [editFileSaving, setEditFileSaving] = useState(false);
  const [editNewFileName, setEditNewFileName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editDescDirty, setEditDescDirty] = useState(false);
  const [editSavingMeta, setEditSavingMeta] = useState(false);
  const [editError, setEditError] = useState('');
  const [editReverting, setEditReverting] = useState(false);
  const [editRevertVersion, setEditRevertVersion] = useState<string | null>(null);
  const editUploadRef = useRef<HTMLInputElement>(null);
  // Remote settings within editor
  const [editRemoteTitle, setEditRemoteTitle] = useState('');
  const [editRemoteDesc, setEditRemoteDesc] = useState('');
  const [editRemoteVisibility, setEditRemoteVisibility] = useState('author');
  const [editRemoteTags, setEditRemoteTags] = useState<Set<string>>(new Set());
  const [editRemoteValidTags, setEditRemoteValidTags] = useState<ValidTag[]>([]);
  const [editRemoteSaving, setEditRemoteSaving] = useState(false);

  // Upload version dialog
  const [uvOpen, setUvOpen] = useState(false);
  const [uvArtifactUuid, setUvArtifactUuid] = useState('');
  const [uvCategory, setUvCategory] = useState('');
  const [uvDirName, setUvDirName] = useState('');
  const [uvBusy, setUvBusy] = useState(false);
  const [uvError, setUvError] = useState('');

  // Delete remote confirmation
  const [deleteConfirmUuid, setDeleteConfirmUuid] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Publish dialog state
  const [pubOpen, setPubOpen] = useState(false);
  const [pubDirName, setPubDirName] = useState('');
  const [pubCategory, setPubCategory] = useState('');
  const [pubTitle, setPubTitle] = useState('');
  const [pubDesc, setPubDesc] = useState('');
  const [pubVisibility, setPubVisibility] = useState('author');
  const [pubTags, setPubTags] = useState<Set<string>>(new Set());
  const [pubValidTags, setPubValidTags] = useState<ValidTag[]>([]);
  const [pubBusy, setPubBusy] = useState(false);
  const [pubError, setPubError] = useState('');

  // Notebook actions
  const [launchingNotebook, setLaunchingNotebook] = useState<string | null>(null);
  const [resettingNotebook, setResettingNotebook] = useState<string | null>(null);
  const [resetConfirmNotebook, setResetConfirmNotebook] = useState<string | null>(null);

  // Remote-only editing (from Authored tab)
  const [editingRemote, setEditingRemote] = useState<RemoteArtifact | null>(null);

  // Inline metadata editing in detail view (local)
  const [detailEditName, setDetailEditName] = useState('');
  const [detailEditDesc, setDetailEditDesc] = useState('');
  const [detailEditing, setDetailEditing] = useState<string | null>(null); // dir_name
  const [detailSaving, setDetailSaving] = useState(false);

  // Authors editing (shared between local editor and remote editor)
  const [editAuthors, setEditAuthors] = useState<{ name: string; affiliation: string }[]>([]);
  const [editNewAuthorName, setEditNewAuthorName] = useState('');
  const [editNewAuthorAffil, setEditNewAuthorAffil] = useState('');

  // Project affiliation
  const [editProjectUuid, setEditProjectUuid] = useState('');
  const [availableProjects, setAvailableProjects] = useState<{ name: string; uuid: string }[]>([]);

  // Version management
  const [editVersions, setEditVersions] = useState<{ uuid: string; version: string; urn: string; active: boolean; created: string; version_downloads: number }[]>([]);
  const [deletingVersion, setDeletingVersion] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchMyArtifacts = useCallback(async () => {
    setMyLoading(true);
    setMyError('');
    try {
      const data = await api.getMyArtifacts();
      setMyArtifacts(data.local_artifacts);
      setAuthoredRemoteOnly(data.authored_remote_only);
      setUserEmail(data.user_email);
    } catch (e: any) {
      setMyError(e.message);
    } finally {
      setMyLoading(false);
    }
  }, []);

  const fetchMarketplace = useCallback(async (force = false) => {
    if (mpLoaded && !force) return;
    setMpLoading(true);
    setMpError('');
    try {
      const data = force
        ? await api.refreshRemoteArtifacts()
        : await api.listRemoteArtifacts();
      setMpAllArtifacts(data.artifacts);
      setMpAllTags(data.tags);
      setMpLoaded(true);
    } catch (e: any) {
      setMpError(e.message);
    } finally {
      setMpLoading(false);
    }
  }, [mpLoaded]);

  useEffect(() => {
    fetchMyArtifacts();
  }, [fetchMyArtifacts]);

  // Open publish dialog when navigated from side panel with a notebook dir_name
  useEffect(() => {
    if (!initialPublishNotebook || myLoading) return;
    const art = myArtifacts.find(a => a.category === 'notebook' && a.dir_name === initialPublishNotebook);
    if (art) {
      setTab('my-artifacts');
      setMyCategoryFilter('notebook');
      openPublishNotebook(art.dir_name, art.name, art.description || '');
      onClearPublishNotebook?.();
    }
  }, [initialPublishNotebook, myArtifacts, myLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Open publish dialog when navigated from side panel with any artifact type
  useEffect(() => {
    if (!initialPublishArtifact || myLoading) return;
    const art = myArtifacts.find(a => a.category === initialPublishArtifact.category && a.dir_name === initialPublishArtifact.dirName);
    if (art) {
      setTab('my-artifacts');
      setMyCategoryFilter(initialPublishArtifact.category as CategoryFilter);
      openPublish(art.dir_name, art.category, art.name, art.description || '');
      onClearPublishArtifact?.();
    }
  }, [initialPublishArtifact, myArtifacts, myLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Navigate to marketplace with a pre-set category filter (from side panel empty-state links)
  useEffect(() => {
    if (!initialMarketplaceCategory) return;
    setTab('community');
    setMpCategoryFilter(initialMarketplaceCategory);
    if (!mpLoaded) fetchMarketplace();
    onClearMarketplaceCategory?.();
  }, [initialMarketplaceCategory]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Helpers for all authored artifacts (local + remote-only)
  // ---------------------------------------------------------------------------

  const allAuthoredArtifacts: RemoteArtifact[] = (() => {
    const fromLocal = myArtifacts
      .filter(a => a.is_author && a.remote_artifact)
      .map(a => a.remote_artifact!);
    return [...fromLocal, ...authoredRemoteOnly];
  })();

  // Set of remote UUIDs that have been downloaded locally
  const downloadedUuids = new Set(
    myArtifacts
      .filter(a => a.artifact_uuid)
      .map(a => a.artifact_uuid!)
  );

  // ---------------------------------------------------------------------------
  // My Artifacts — filtering
  // ---------------------------------------------------------------------------

  const filteredMyArtifacts = (() => {
    let list = myArtifacts;
    if (myCategoryFilter !== 'all') {
      list = list.filter(a => a.category === myCategoryFilter);
    }
    if (search) {
      const s = search.toLowerCase();
      list = list.filter(a =>
        a.name.toLowerCase().includes(s) ||
        (a.description || '').toLowerCase().includes(s)
      );
    }
    return list;
  })();

  // ---------------------------------------------------------------------------
  // Marketplace — filtering & sorting
  // ---------------------------------------------------------------------------

  // Unique authors for the author dropdown
  const mpUniqueAuthors = (() => {
    const names = new Map<string, number>();
    for (const a of mpAllArtifacts) {
      for (const au of a.authors || []) {
        if (au.name) names.set(au.name, (names.get(au.name) || 0) + 1);
      }
    }
    return [...names.entries()].sort((a, b) => b[1] - a[1]);
  })();

  // Unique categories in the marketplace
  const mpUniqueCategories = (() => {
    const cats = new Set<string>();
    for (const a of mpAllArtifacts) if (a.category) cats.add(a.category);
    return cats;
  })();

  const filterMpList = (list: RemoteArtifact[], searchText: string, catFilter: CategoryFilter, authorFilter: string, tags: Set<string>, sort: 'popular' | 'newest' | 'az') => {
    if (catFilter !== 'all') {
      list = list.filter(a => a.category === catFilter);
    }
    if (authorFilter) {
      list = list.filter(a => a.authors?.some(au => au.name === authorFilter));
    }
    if (searchText) {
      const s = searchText.toLowerCase();
      list = list.filter(a =>
        (a.title || '').toLowerCase().includes(s) ||
        (a.description_long || a.description_short || '').toLowerCase().includes(s) ||
        a.authors?.some(au => au.name.toLowerCase().includes(s)) ||
        a.tags?.some(t => t.toLowerCase().includes(s))
      );
    }
    if (tags.size > 0) {
      list = list.filter(a => {
        const artTags = new Set(a.tags?.map(t => t.toLowerCase()) || []);
        for (const t of tags) {
          if (!artTags.has(t.toLowerCase())) return false;
        }
        return true;
      });
    }
    if (sort === 'popular') {
      list = [...list].sort((a, b) => (b.artifact_downloads_active || 0) - (a.artifact_downloads_active || 0));
    } else if (sort === 'newest') {
      list = [...list].sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    } else {
      list = [...list].sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    }
    return list;
  };

  const filteredMpArtifacts = filterMpList(mpAllArtifacts, mpSearch, mpCategoryFilter, mpAuthorFilter, mpActiveTags, mpSort);

  // Authored artifacts for the "My Artifacts" tab (remote)
  const filteredAuthoredArtifacts = (() => {
    const authoredUuids = new Set(allAuthoredArtifacts.map(a => a.uuid));
    const authored = mpAllArtifacts.filter(a => authoredUuids.has(a.uuid));
    return filterMpList(authored, mpSearch, mpCategoryFilter, '', mpActiveTags, mpSort);
  })();

  const toggleMpTag = (tag: string) => {
    setMpActiveTags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag); else next.add(tag);
      return next;
    });
  };

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleDownloadArtifact = async (art: RemoteArtifact, versionUuid?: string) => {
    setMpDownloading(art.uuid);
    setVersionPickerArt(null);
    try {
      const result = await api.downloadArtifact(art.uuid, versionUuid);
      alert(`Got "${result.title}" — added to local ${result.category} library as "${result.local_name}"`);
      fetchMyArtifacts();
    } catch (e: any) {
      if (e.message.includes('409')) {
        // Name conflict — ask user what to do
        const choice = prompt(
          `"${art.title}" already exists locally.\n\n` +
          `Enter a new folder name, or leave blank and click OK to overwrite the existing copy:`,
          ''
        );
        if (choice === null) {
          // User cancelled
          setMpDownloading(null);
          return;
        }
        try {
          if (choice.trim()) {
            // Use a different local name
            const result = await api.downloadArtifact(art.uuid, versionUuid, choice.trim());
            alert(`Got "${result.title}" — saved as "${result.local_name}"`);
          } else {
            // Overwrite existing
            const result = await api.downloadArtifact(art.uuid, versionUuid, undefined, true);
            alert(`Updated "${result.title}" in local library`);
          }
          fetchMyArtifacts();
        } catch (e2: any) {
          alert(`Failed: ${e2.message}`);
        }
      } else {
        alert(`Failed to get artifact: ${e.message}`);
      }
    } finally {
      setMpDownloading(null);
    }
  };

  const openVersionPicker = (art: RemoteArtifact) => {
    if (!art.versions || art.versions.length <= 1) {
      // Only one or zero versions — download directly
      handleDownloadArtifact(art);
    } else {
      setVersionPickerArt(art);
    }
  };

  const handleLoadSliceTemplate = async (dirName: string) => {
    setLoadingName(dirName);
    try {
      const data = await api.loadTemplate(dirName, loadSliceName || undefined);
      onLoadSlice(data);
    } catch (e: any) {
      setMyError(e.message);
    } finally {
      setLoadingName(null);
      setShowLoadInput(null);
      setLoadSliceName('');
    }
  };

  const handleDeleteLocal = async (art: LocalArtifact) => {
    if (!confirm(`Delete local artifact "${art.name}"?`)) return;
    try {
      if (art.category === 'weave') {
        await api.deleteTemplate(art.dir_name);
      } else if (art.category === 'vm-template') {
        await api.deleteVmTemplate(art.dir_name);
      } else {
        await api.deleteExperiment(art.dir_name);
      }
      fetchMyArtifacts();
    } catch (e: any) {
      setMyError(e.message);
    }
  };

  // Publish dialog
  const openPublish = async (dirName: string, category: string, name: string, description: string) => {
    setPubDirName(dirName);
    setPubCategory(category);
    setPubTitle(name);
    setPubDesc(description || '');
    setPubVisibility('author');
    setPubTags(new Set());
    setPubError('');
    setPubOpen(true);
    try {
      const { tags } = await api.listValidTags();
      setPubValidTags(tags);
    } catch {
      setPubValidTags([]);
    }
  };

  const handlePublish = async () => {
    if (!pubTitle.trim()) { setPubError('Title is required'); return; }
    const descLen = (pubDesc.trim() || pubTitle.trim()).length;
    if (descLen < 5) { setPubError('Description must be at least 5 characters'); return; }
    if (descLen > 255) { setPubError('Description must be at most 255 characters (it will be used as the short description)'); return; }
    setPubBusy(true);
    setPubError('');
    try {
      const result = await api.publishArtifact({
        dir_name: pubDirName,
        category: pubCategory,
        title: pubTitle.trim(),
        description: pubDesc.trim() || pubTitle.trim(),
        tags: [...pubTags],
        visibility: pubVisibility,
      });
      setPubOpen(false);
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
      alert(`Published "${result.title}" to FABRIC Artifact Manager (${result.visibility})`);
    } catch (e: any) {
      setPubError(e.message);
    } finally {
      setPubBusy(false);
    }
  };

  const togglePubTag = (tag: string) => {
    setPubTags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag); else next.add(tag);
      return next;
    });
  };

  // Upload version
  const openUploadVersion = (art: RemoteArtifact, localDirName?: string, category?: string) => {
    setUvArtifactUuid(art.uuid);
    setUvCategory(category || art.category || '');
    setUvDirName(localDirName || '');
    setUvError('');
    setUvOpen(true);
  };

  const handleUploadVersion = async () => {
    if (!uvArtifactUuid || !uvDirName || !uvCategory) return;
    setUvBusy(true);
    setUvError('');
    try {
      const result = await api.uploadArtifactVersion(uvArtifactUuid, uvDirName, uvCategory);
      setUvOpen(false);
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
      alert(`New version published: ${result.version}`);
    } catch (e: any) {
      setUvError(e.message);
    } finally {
      setUvBusy(false);
    }
  };

  // Notebook-specific publish (uses publishNotebookFork for workspace + fork provenance)
  const openPublishNotebook = async (dirName: string, name: string, description: string) => {
    setPubDirName(dirName);
    setPubCategory('notebook');
    setPubTitle(name + ' (fork)');
    setPubDesc(description || '');
    setPubVisibility('author');
    setPubTags(new Set());
    setPubError('');
    setPubOpen(true);
    try {
      const { tags } = await api.listValidTags();
      setPubValidTags(tags);
    } catch {
      setPubValidTags([]);
    }
  };

  const handlePublishNotebookFork = async () => {
    if (!pubTitle.trim()) { setPubError('Title is required'); return; }
    const descLen = (pubDesc.trim() || pubTitle.trim()).length;
    if (descLen < 5) { setPubError('Description must be at least 5 characters'); return; }
    if (descLen > 255) { setPubError('Description must be at most 255 characters (it will be used as the short description)'); return; }
    setPubBusy(true);
    setPubError('');
    try {
      const result = await api.publishNotebookFork(pubDirName, {
        title: pubTitle.trim(),
        description: pubDesc.trim() || pubTitle.trim(),
        visibility: pubVisibility,
        tags: [...pubTags],
      });
      setPubOpen(false);
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
      alert(`Published "${result.title}" to FABRIC Artifact Manager.${result.forked_from ? ` Forked from ${result.forked_from}.` : ''}`);
    } catch (e: any) {
      setPubError(e.message);
    } finally {
      setPubBusy(false);
    }
  };

  // Notebook launch/reset
  const handleLaunchNotebook = async (dirName: string) => {
    setLaunchingNotebook(dirName);
    try {
      const result = await api.launchNotebook(dirName);
      if (result.status === 'running' && result.jupyter_path) {
        onLaunchNotebook?.(result.jupyter_path);
      }
    } catch (e: any) {
      alert(`Failed to open notebook in JupyterLab: ${e.message}`);
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

  const handleResetNotebook = async (dirName: string) => {
    setResettingNotebook(dirName);
    try {
      await api.resetNotebook(dirName);
      setResetConfirmNotebook(null);
      alert('Notebook workspace reset to original.');
    } catch (e: any) {
      alert(`Failed to reset: ${e.message}`);
    } finally {
      setResettingNotebook(null);
    }
  };

  // Delete remote artifact
  const handleDeleteRemote = async (uuid: string) => {
    setDeleteBusy(true);
    try {
      await api.deleteRemoteArtifact(uuid);
      setDeleteConfirmUuid(null);
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
      alert('Artifact deleted from FABRIC Artifact Manager.');
    } catch (e: any) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleteBusy(false);
    }
  };

  // Marketplace inline edit
  const openMpEdit = async (art: RemoteArtifact) => {
    setMpEditing(art.uuid);
    setMpEditTitle(art.title || '');
    setMpEditDesc(stripCategoryMarker(art.description_long || art.description_short || ''));
    setMpEditVisibility(art.visibility || 'author');
    setMpEditTags(new Set(art.tags || []));
    setMpEditError('');
    try {
      const { tags } = await api.listValidTags();
      setMpEditValidTags(tags);
    } catch {
      setMpEditValidTags([]);
    }
  };

  const handleMpEditSave = async () => {
    if (!mpEditing || !mpEditTitle.trim()) { setMpEditError('Title is required'); return; }
    setMpEditSaving(true);
    setMpEditError('');
    try {
      const editArt = mpAllArtifacts.find(a => a.uuid === mpEditing);
      const cat = editArt?.category || '';
      await api.updateRemoteArtifact(mpEditing, {
        title: mpEditTitle.trim(),
        description: mpEditDesc.trim(),
        visibility: mpEditVisibility,
        tags: [...mpEditTags],
        category: cat,
      });
      setMpEditing(null);
      setMpLoaded(false);
      fetchMarketplace(true);
      fetchMyArtifacts();
    } catch (e: any) {
      setMpEditError(e.message);
    } finally {
      setMpEditSaving(false);
    }
  };

  const handleMpDelete = async (uuid: string) => {
    setMpDeleteBusy(true);
    try {
      await api.deleteRemoteArtifact(uuid);
      setMpDeleteConfirm(null);
      setMpEditing(null);
      setMpLoaded(false);
      fetchMarketplace(true);
      fetchMyArtifacts();
      alert('Artifact deleted from marketplace.');
    } catch (e: any) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setMpDeleteBusy(false);
    }
  };

  const openDetailEdit = (art: LocalArtifact) => {
    setDetailEditing(art.dir_name);
    setDetailEditName(art.name || '');
    setDetailEditDesc(art.description || '');
  };

  const saveDetailEdit = async (dirName: string) => {
    setDetailSaving(true);
    try {
      await api.updateLocalArtifactMetadata(dirName, {
        name: detailEditName.trim(),
        description: detailEditDesc.trim(),
      });
      setDetailEditing(null);
      fetchMyArtifacts();
    } catch (e: any) {
      alert(`Failed to save: ${e.message}`);
    } finally {
      setDetailSaving(false);
    }
  };

  const toggleMpEditTag = (tag: string) => {
    setMpEditTags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag); else next.add(tag);
      return next;
    });
  };

  // ---------------------------------------------------------------------------
  // Editor — open / close / file ops
  // ---------------------------------------------------------------------------

  const openEditor = async (art: LocalArtifact) => {
    setEditing(art);
    setEditingRemote(null);
    setEditDesc(art.description || '');
    setEditDescDirty(false);
    setEditSelectedFile(null);
    setEditFileContent('');
    setEditFileOriginal('');
    setEditNewFileName('');
    setEditError('');
    setEditCwd('');
    setEditReverting(false);
    setEditRevertVersion(null);
    // Load remote settings if linked
    if (art.remote_artifact) {
      const r = art.remote_artifact;
      setEditRemoteTitle(r.title || '');
      setEditRemoteDesc(stripCategoryMarker(r.description_long || r.description_short || ''));
      setEditRemoteVisibility(r.visibility || 'author');
      setEditRemoteTags(new Set(r.tags || []));
      setEditAuthors([...(r.authors || [])]);
      setEditVersions([...(r.versions || [])]);
      try {
        const { tags } = await api.listValidTags();
        setEditRemoteValidTags(tags);
      } catch { setEditRemoteValidTags([]); }
    } else {
      setEditAuthors([]);
      setEditVersions([]);
    }
    // Load projects for dropdown
    try {
      const p = await api.listUserProjects();
      setAvailableProjects(p.projects);
    } catch { setAvailableProjects([]); }
    setEditProjectUuid('');
    // Load file list (root of artifact directory)
    await fetchEditFiles(art, '');
  };

  const openRemoteEditor = async (art: RemoteArtifact) => {
    setEditingRemote(art);
    setEditing(null);
    setEditRemoteTitle(art.title || '');
    setEditRemoteDesc(stripCategoryMarker(art.description_long || art.description_short || ''));
    setEditRemoteVisibility(art.visibility || 'author');
    setEditRemoteTags(new Set(art.tags || []));
    setEditAuthors([...(art.authors || [])]);
    setEditVersions([...(art.versions || [])]);
    setEditError('');
    setEditNewAuthorName('');
    setEditNewAuthorAffil('');
    try {
      const { tags } = await api.listValidTags();
      setEditRemoteValidTags(tags);
    } catch { setEditRemoteValidTags([]); }
    try {
      const p = await api.listUserProjects();
      setAvailableProjects(p.projects);
    } catch { setAvailableProjects([]); }
    setEditProjectUuid('');
  };

  // Artifact root path in container storage
  const artBasePath = (dirName: string) => `my_artifacts/${dirName}`;

  const fetchEditFiles = async (art: LocalArtifact, subdir = '') => {
    const base = artBasePath(art.dir_name);
    const path = subdir ? `${base}/${subdir}` : base;
    try {
      const entries: FileEntry[] = await api.listFiles(path);
      setEditFiles(entries);
      setEditCwd(subdir);
    } catch (e: any) {
      setEditError(`Failed to list files: ${e.message}`);
      setEditFiles([]);
    }
  };

  const navigateDir = (dirName: string) => {
    if (!editing) return;
    const newCwd = editCwd ? `${editCwd}/${dirName}` : dirName;
    setEditSelectedFile(null);
    setEditFileContent('');
    setEditFileOriginal('');
    fetchEditFiles(editing, newCwd);
  };

  const navigateUp = () => {
    if (!editing || !editCwd) return;
    const parts = editCwd.split('/');
    parts.pop();
    const newCwd = parts.join('/');
    setEditSelectedFile(null);
    setEditFileContent('');
    setEditFileOriginal('');
    fetchEditFiles(editing, newCwd);
  };

  const selectEditFile = async (filename: string) => {
    if (!editing) return;
    const base = artBasePath(editing.dir_name);
    const fullPath = editCwd ? `${base}/${editCwd}/${filename}` : `${base}/${filename}`;
    setEditSelectedFile(filename);
    setEditFileLoading(true);
    setEditError('');
    try {
      const res = await api.readFileContent(fullPath);
      setEditFileContent(res.content);
      setEditFileOriginal(res.content);
    } catch (e: any) {
      setEditError(`Failed to read file: ${e.message}`);
      setEditFileContent('');
      setEditFileOriginal('');
    } finally {
      setEditFileLoading(false);
    }
  };

  const saveEditFile = async () => {
    if (!editing || !editSelectedFile) return;
    const base = artBasePath(editing.dir_name);
    const fullPath = editCwd ? `${base}/${editCwd}/${editSelectedFile}` : `${base}/${editSelectedFile}`;
    setEditFileSaving(true);
    setEditError('');
    try {
      await api.writeFileContent(fullPath, editFileContent);
      setEditFileOriginal(editFileContent);
    } catch (e: any) {
      setEditError(`Failed to save: ${e.message}`);
    } finally {
      setEditFileSaving(false);
    }
  };

  const addEditFile = async () => {
    if (!editing || !editNewFileName.trim()) return;
    const filename = editNewFileName.trim();
    const base = artBasePath(editing.dir_name);
    const fullPath = editCwd ? `${base}/${editCwd}/${filename}` : `${base}/${filename}`;
    setEditError('');
    try {
      await api.writeFileContent(fullPath, '');
      setEditNewFileName('');
      await fetchEditFiles(editing, editCwd);
      selectEditFile(filename);
    } catch (e: any) {
      setEditError(`Failed to create file: ${e.message}`);
    }
  };

  const addEditFolder = async () => {
    if (!editing || !editNewFileName.trim()) return;
    const folderName = editNewFileName.trim();
    const base = artBasePath(editing.dir_name);
    const parentPath = editCwd ? `${base}/${editCwd}` : base;
    setEditError('');
    try {
      await api.createFolder(parentPath, folderName);
      setEditNewFileName('');
      await fetchEditFiles(editing, editCwd);
    } catch (e: any) {
      setEditError(`Failed to create folder: ${e.message}`);
    }
  };

  const deleteEditFile = async (filename: string, isDir: boolean) => {
    if (!editing || !confirm(`Delete "${filename}"${isDir ? ' and all its contents' : ''}?`)) return;
    const base = artBasePath(editing.dir_name);
    const fullPath = editCwd ? `${base}/${editCwd}/${filename}` : `${base}/${filename}`;
    setEditError('');
    try {
      await api.deleteFile(fullPath);
      if (editSelectedFile === filename) {
        setEditSelectedFile(null);
        setEditFileContent('');
        setEditFileOriginal('');
      }
      await fetchEditFiles(editing, editCwd);
    } catch (e: any) {
      setEditError(`Failed to delete: ${e.message}`);
    }
  };

  const handleUploadFiles = async (files: FileList) => {
    if (!editing || files.length === 0) return;
    const base = artBasePath(editing.dir_name);
    const uploadPath = editCwd ? `${base}/${editCwd}` : base;
    setEditError('');
    try {
      await api.uploadFiles(uploadPath, files);
      await fetchEditFiles(editing, editCwd);
    } catch (e: any) {
      setEditError(`Upload failed: ${e.message}`);
    }
  };

  const handleRevertArtifact = async (versionUuid?: string) => {
    if (!editing) return;
    if (!confirm('Revert will replace all local files with the published version. Continue?')) return;
    setEditReverting(true);
    setEditError('');
    try {
      await api.revertArtifact(editing.dir_name, versionUuid);
      // Refresh file listing and metadata
      await fetchEditFiles(editing, '');
      setEditSelectedFile(null);
      setEditFileContent('');
      setEditFileOriginal('');
      setEditCwd('');
      fetchMyArtifacts();
    } catch (e: any) {
      setEditError(`Revert failed: ${e.message}`);
    } finally {
      setEditReverting(false);
      setEditRevertVersion(null);
    }
  };

  const saveEditMetadata = async () => {
    if (!editing) return;
    setEditSavingMeta(true);
    setEditError('');
    try {
      if (editing.category === 'weave') {
        await api.updateTemplate(editing.dir_name, { description: editDesc });
      }
      // Update local state
      setEditing({ ...editing, description: editDesc });
      setEditDescDirty(false);
      fetchMyArtifacts();
    } catch (e: any) {
      setEditError(`Failed to save metadata: ${e.message}`);
    } finally {
      setEditSavingMeta(false);
    }
  };

  const saveEditRemoteSettings = async () => {
    const uuid = editing?.remote_artifact?.uuid || editingRemote?.uuid;
    if (!uuid) return;
    const category = editing?.category || editingRemote?.category || '';
    setEditRemoteSaving(true);
    setEditError('');
    try {
      await api.updateRemoteArtifact(uuid, {
        title: editRemoteTitle,
        description: editRemoteDesc,
        visibility: editRemoteVisibility,
        tags: [...editRemoteTags],
        authors: editAuthors.length > 0 ? editAuthors : undefined,
        project_uuid: editProjectUuid || undefined,
        category,
      });
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
    } catch (e: any) {
      setEditError(`Failed to save remote settings: ${e.message}`);
    } finally {
      setEditRemoteSaving(false);
    }
  };

  const closeEditor = () => {
    setEditing(null);
    setEditingRemote(null);
    setEditFiles([]);
    setEditCwd('');
    setEditSelectedFile(null);
    setEditFileContent('');
    setEditFileOriginal('');
    setEditAuthors([]);
    setEditVersions([]);
    setEditNewAuthorName('');
    setEditNewAuthorAffil('');
    setEditProjectUuid('');
    setEditReverting(false);
    setEditRevertVersion(null);
  };

  // ---------------------------------------------------------------------------
  // Author & version management
  // ---------------------------------------------------------------------------

  const addAuthor = () => {
    const name = editNewAuthorName.trim();
    if (!name) return;
    setEditAuthors(prev => [...prev, { name, affiliation: editNewAuthorAffil.trim() }]);
    setEditNewAuthorName('');
    setEditNewAuthorAffil('');
  };

  const removeAuthor = (idx: number) => {
    setEditAuthors(prev => prev.filter((_, i) => i !== idx));
  };

  const handleDeleteVersion = async (versionUuid: string) => {
    const uuid = editingRemote?.uuid || editing?.remote_artifact?.uuid;
    if (!uuid) return;
    if (!confirm('Delete this version? This cannot be undone.')) return;
    setDeletingVersion(versionUuid);
    setEditError('');
    try {
      await api.deleteArtifactVersion(uuid, versionUuid);
      setEditVersions(prev => prev.filter(v => v.uuid !== versionUuid));
      setMpLoaded(false);
      fetchMyArtifacts();
      fetchMarketplace(true);
    } catch (e: any) {
      setEditError(`Failed to delete version: ${e.message}`);
    } finally {
      setDeletingVersion(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  /** Strip [LoomAI ...] category markers from descriptions for display. */
  const stripCategoryMarker = (text: string) =>
    text.replace(/\n?\[LoomAI (?:Weave|VM Template|Recipe|Notebook)\]\s*/gi, '').trim();

  /** Append the [LoomAI ...] marker to a description before saving. */
  const CATEGORY_MARKERS: Record<string, string> = {
    'weave': '[LoomAI Weave]',
    'vm-template': '[LoomAI VM Template]',
    'recipe': '[LoomAI Recipe]',
    'notebook': '[LoomAI Notebook]',
  };
  const ensureCategoryMarker = (desc: string, category: string) => {
    const marker = CATEGORY_MARKERS[category];
    if (!marker || desc.toLowerCase().includes(marker.toLowerCase())) return desc;
    return `${desc}\n${marker}`;
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const categoryLabel = (c: string) => {
    const labels: Record<string, string> = {
      'weave': 'Weave',
      'vm-template': 'VM Template',
      'recipe': 'Recipe',
      'notebook': 'Notebook',
    };
    return labels[c] || c;
  };

  const sourceLabel = (art: LocalArtifact) =>
    art.is_from_marketplace ? 'Installed' : art.is_author ? 'Authored' : 'Local';

  // View toggle
  const renderViewToggle = () => (
    <div className="tv-view-toggle">
      <button className={`tv-view-btn ${viewMode === 'grid' ? 'active' : ''}`} onClick={() => setViewMode('grid')} title="Grid view">Grid</button>
      <button className={`tv-view-btn ${viewMode === 'table' ? 'active' : ''}`} onClick={() => setViewMode('table')} title="Table view">Table</button>
      <button className={`tv-view-btn ${viewMode === 'preview' ? 'active' : ''}`} onClick={() => setViewMode('preview')} title="Details">Details</button>
    </div>
  );

  // --- Unified action helpers ---
  const handleOpenArtifact = (art: LocalArtifact) => {
    if (art.category === 'weave' && onNavigateToSlicesView) onNavigateToSlicesView(art.dir_name);
    else if (art.category === 'notebook') handleEditInJupyter(art.dir_name);
    else onEditArtifact?.(art.dir_name);
  };
  const handlePublishArtifact = (art: LocalArtifact) => {
    if (art.category === 'notebook') openPublishNotebook(art.dir_name, art.name, art.description || '');
    else openPublish(art.dir_name, art.category, art.name, art.description || '');
  };
  const canPublish = (art: LocalArtifact) => art.remote_status === 'not_linked';

  // Simple inline overflow menu for artifact cards
  const ArtifactOverflow = ({ art, menuKey }: { art: LocalArtifact; menuKey: string }) => {
    const wrapRef = useRef<HTMLDivElement>(null);
    const isOpen = overflowOpen === menuKey;
    useEffect(() => {
      if (!isOpen) return;
      const handleClick = (e: MouseEvent) => {
        if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOverflowOpen(null);
      };
      const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOverflowOpen(null); };
      document.addEventListener('mousedown', handleClick);
      document.addEventListener('keydown', handleKey);
      return () => { document.removeEventListener('mousedown', handleClick); document.removeEventListener('keydown', handleKey); };
    }, [isOpen]);
    const items: { label: string; onClick: () => void; disabled?: boolean; danger?: boolean; separator?: boolean }[] = [
      { label: 'Open', onClick: () => handleOpenArtifact(art) },
      { label: 'Publish', onClick: () => handlePublishArtifact(art), disabled: !canPublish(art) },
      { label: 'Edit', onClick: () => onEditArtifact?.(art.dir_name), disabled: !onEditArtifact },
      { label: 'Delete', onClick: () => handleDeleteLocal(art), danger: true },
      { label: '', onClick: () => {}, separator: true },
      { label: 'JupyterLab', onClick: () => handleEditInJupyter(art.dir_name), disabled: launchingNotebook === art.dir_name },
      { label: 'Details', onClick: () => { setViewMode('preview'); setPreviewSelected(`${art.category}-${art.dir_name}`); } },
    ];
    return (
      <div className="tv-overflow-wrap" ref={wrapRef}>
        <button className="tv-overflow-btn" onClick={() => setOverflowOpen(isOpen ? null : menuKey)} title="More actions">{'\u22EF'}</button>
        {isOpen && (
          <div className="tv-overflow-menu">
            {items.map((item, i) => {
              if (item.separator) return <div key={`sep-${i}`} className="tv-overflow-sep" />;
              return (
                <button key={item.label} className={`tv-overflow-item${item.danger ? ' tv-overflow-danger' : ''}`}
                  disabled={item.disabled} onClick={() => { item.onClick(); setOverflowOpen(null); }}>
                  {item.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  // My Artifacts card
  const renderMyArtifactCard = (art: LocalArtifact) => {
    const isLoadInput = showLoadInput === art.dir_name;
    return (
      <div key={`${art.category}-${art.dir_name}`} className="tv-card">
        <div className="tv-card-header">
          <span className="tv-card-name">{art.name}</span>
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>
            {categoryLabel(art.category)}
          </span>
          {art.is_author && <span className="tv-badge tv-badge-source-author">Author</span>}
          {art.is_from_marketplace && !art.is_author && <span className="tv-badge tv-badge-source-downloaded">Installed</span>}
          {!art.is_from_marketplace && !art.is_author && <span className="tv-badge tv-badge-source-local">Local</span>}

        </div>
        {art.description && <div className="tv-card-desc">{art.description}</div>}
        <div className="tv-card-meta">
          {art.node_count != null && <span>{art.node_count} node{art.node_count !== 1 ? 's' : ''}</span>}
          {art.network_count != null && <span>{art.network_count} network{art.network_count !== 1 ? 's' : ''}</span>}
          {art.remote_status === 'linked' && art.remote_artifact && (
            <>
              <span>{art.remote_artifact.artifact_downloads_active} downloads</span>
              <span>{art.remote_artifact.number_of_versions} version{art.remote_artifact.number_of_versions !== 1 ? 's' : ''}</span>
            </>
          )}
          {art.remote_status === 'remote_deleted' && <span className="tv-meta-warn">Remote artifact deleted</span>}
        </div>

        {art.category === 'notebook' && resetConfirmNotebook === art.dir_name && (
          <div className="tv-load-row" style={{ background: 'var(--fabric-bg-warning, #fff3e0)', padding: '6px 8px', borderRadius: 4, fontSize: 12 }}>
            <span>Reset to original? Changes will be lost.</span>
            <button className="tv-btn tv-btn-danger" onClick={() => handleResetNotebook(art.dir_name)} disabled={resettingNotebook === art.dir_name}>
              {resettingNotebook === art.dir_name ? 'Resetting...' : 'Yes, Reset'}
            </button>
            <button className="tv-btn" onClick={() => setResetConfirmNotebook(null)}>Cancel</button>
          </div>
        )}

        {isLoadInput ? (
          <div className="tv-load-row">
            <input className="tv-load-input" placeholder="Slice name (optional)" value={loadSliceName}
              onChange={e => setLoadSliceName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleLoadSliceTemplate(art.dir_name); if (e.key === 'Escape') { setShowLoadInput(null); setLoadSliceName(''); } }}
              autoFocus />
            <button className="tv-btn tv-btn-primary" onClick={() => handleLoadSliceTemplate(art.dir_name)} disabled={loadingName === art.dir_name}>
              {loadingName === art.dir_name ? 'Loading...' : 'Go'}
            </button>
            <button className="tv-btn" onClick={() => { setShowLoadInput(null); setLoadSliceName(''); }}>Cancel</button>
          </div>
        ) : (
          <div className="tv-card-actions">
            <button className="tv-btn tv-btn-primary" onClick={() => handleOpenArtifact(art)}>Open</button>
            <button className="tv-btn tv-btn-publish" onClick={() => handlePublishArtifact(art)} disabled={!canPublish(art)}>
              <BtnText full="Publish" short="Pub" />
            </button>
            <button className="tv-btn" onClick={() => onEditArtifact?.(art.dir_name)}>Edit</button>
            <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteLocal(art)}><BtnText full="Delete" short="Del" /></button>
            <ArtifactOverflow art={art} menuKey={`card-${art.category}-${art.dir_name}`} />
          </div>
        )}
      </div>
    );
  };

  // Marketplace card
  const renderMarketplaceCard = (art: RemoteArtifact) => {
    const isExpanded = mpExpanded === art.uuid;
    const isAuthored = allAuthoredArtifacts.some(a => a.uuid === art.uuid);
    const isDownloaded = downloadedUuids.has(art.uuid);
    return (
      <div key={art.uuid} className={`tv-card tv-mp-card ${isExpanded ? 'tv-card-editing' : ''}`}>
        <div className="tv-card-header">
          <span className="tv-card-name">{art.title}</span>
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>{categoryLabel(art.category)}</span>
          {isAuthored && <span className="tv-badge tv-badge-source-author">Author</span>}
          {isDownloaded && <span className="tv-badge tv-badge-source-downloaded">Installed</span>}
        </div>
        {(art.description_long || art.description_short) && <div className="tv-card-desc">{stripCategoryMarker(art.description_long || art.description_short)}</div>}
        <div className="tv-card-meta">
          {art.authors?.length > 0 && (
            <span title={art.authors.map(a => `${a.name}${a.affiliation ? ` (${a.affiliation})` : ''}`).join(', ')}>
              {art.authors.map(a => a.name).join(', ')}
            </span>
          )}
          <span>{art.artifact_downloads_active} downloads</span>
          {art.number_of_versions > 1 && <span>{art.number_of_versions} versions</span>}
        </div>
        {art.tags?.length > 0 && (
          <div className="tv-mp-tags">
            {art.tags.map(t => (
              <button key={t} className={`tv-mp-tag ${mpActiveTags.has(t) ? 'active' : ''}`}
                onClick={() => toggleMpTag(t)} title={`Filter by "${t}"`}>{t}</button>
            ))}
          </div>
        )}
        {isExpanded && (
          <div className="tv-mp-detail">
            {art.project_name && <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Project:</span> {art.project_name}</div>}
            <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Visibility:</span> {art.visibility}</div>
            <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Views:</span> {art.artifact_views}</div>
            <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Created:</span> {new Date(art.created).toLocaleDateString()}</div>
            {art.modified && <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Updated:</span> {new Date(art.modified).toLocaleDateString()}</div>}
            {art.versions?.length > 0 && (
              <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Latest:</span> {art.versions[0]?.version || 'N/A'} ({art.versions[0]?.version_downloads || 0} downloads)</div>
            )}
            {art.authors?.length > 0 && (
              <div className="tv-mp-detail-row"><span className="tv-mp-detail-label">Authors:</span> {art.authors.map(a => `${a.name}${a.affiliation ? ` (${a.affiliation})` : ''}`).join('; ')}</div>
            )}
          </div>
        )}

        <div className="tv-card-actions">
          <button className="tv-btn tv-btn-primary" disabled={mpDownloading === art.uuid} onClick={() => openVersionPicker(art)}>
            {mpDownloading === art.uuid ? 'Getting...' : 'Get'}
          </button>
          {isAuthored && (
            <button className="tv-btn" onClick={() => openRemoteEditor(art)}>Edit</button>
          )}
          <button className="tv-btn" onClick={() => setMpExpanded(isExpanded ? null : art.uuid)}>
            {isExpanded ? 'Less' : 'Details'}
          </button>
        </div>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Table renderers
  // ---------------------------------------------------------------------------

  const renderMyTable = () => (
    <div className="tv-table-wrap">
      <table className="tv-table">
        <thead><tr>
          <th>Name</th><th>Category</th><th>Source</th><th>Nodes</th><th>Networks</th><th>Downloads</th><th>Status</th><th>Actions</th>
        </tr></thead>
        <tbody>
          {filteredMyArtifacts.map(art => {
            return (
              <tr key={`${art.category}-${art.dir_name}`}>
                <td className="tv-table-name">
                  <span className="tv-table-name-text">{art.name}</span>
                </td>
                <td><span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>{categoryLabel(art.category)}</span></td>
                <td>{sourceLabel(art)}</td>
                <td>{art.node_count ?? '—'}</td>
                <td>{art.network_count ?? '—'}</td>
                <td>{art.remote_artifact?.artifact_downloads_active ?? '—'}</td>
                <td>{art.remote_status === 'linked' ? 'Linked' : art.remote_status === 'remote_deleted' ? 'Remote Deleted' : 'Local Only'}</td>
                <td className="tv-table-actions">
                  <button className="tv-btn tv-btn-primary" onClick={() => handleOpenArtifact(art)}>Open</button>
                  <button className="tv-btn tv-btn-publish" onClick={() => handlePublishArtifact(art)} disabled={!canPublish(art)}>
                    <BtnText full="Publish" short="Pub" />
                  </button>
                  <button className="tv-btn" onClick={() => onEditArtifact?.(art.dir_name)}>Edit</button>
                  <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteLocal(art)}><BtnText full="Delete" short="Del" /></button>
                  <ArtifactOverflow art={art} menuKey={`tbl-${art.category}-${art.dir_name}`} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  const renderMpTable = (arts: RemoteArtifact[] = filteredMpArtifacts) => (
    <div className="tv-table-wrap">
      <table className="tv-table">
        <thead><tr>
          <th>Title</th><th>Category</th><th>Authors</th><th>Downloads</th><th>Versions</th><th>Visibility</th><th>Tags</th><th>Actions</th>
        </tr></thead>
        <tbody>
          {arts.map(art => (
            <tr key={art.uuid}>
              <td className="tv-table-name">
                <span className="tv-table-name-text">{art.title}</span>
                {allAuthoredArtifacts.some(a => a.uuid === art.uuid) && <span className="tv-badge tv-badge-source-author" style={{ marginLeft: 6 }}>Author</span>}
                {downloadedUuids.has(art.uuid) && <span className="tv-badge tv-badge-source-downloaded" style={{ marginLeft: 6 }}>Installed</span>}
              </td>
              <td><span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>{categoryLabel(art.category)}</span></td>
              <td>{art.authors?.map(a => a.name).join(', ') || '—'}</td>
              <td>{art.artifact_downloads_active}</td>
              <td>{art.number_of_versions}</td>
              <td>{art.visibility}</td>
              <td className="tv-table-tags">{art.tags?.join(', ') || '—'}</td>
              <td className="tv-table-actions">
                <button className="tv-btn tv-btn-primary" disabled={mpDownloading === art.uuid} onClick={() => openVersionPicker(art)}>
                  {mpDownloading === art.uuid ? '...' : 'Get'}
                </button>
                {allAuthoredArtifacts.some(a => a.uuid === art.uuid) && (
                  <button className="tv-btn" onClick={() => openRemoteEditor(art)}>Edit</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Preview renderers
  // ---------------------------------------------------------------------------

  const renderLocalDetail = (art: LocalArtifact) => {
    const r = art.remote_artifact;
    const isDetailEdit = detailEditing === art.dir_name;
    return (
      <div className="tv-pv-detail">
        {isDetailEdit ? (
          <>
            <div className="tv-editor-field-row" style={{ marginBottom: 8 }}>
              <label className="tv-edit-label">Name</label>
              <input className="tv-pub-input" value={detailEditName} onChange={e => setDetailEditName(e.target.value)} />
            </div>
            <div className="tv-editor-field-row" style={{ marginBottom: 8 }}>
              <label className="tv-edit-label">Description</label>
              <textarea className="tv-pub-textarea" value={detailEditDesc} onChange={e => setDetailEditDesc(e.target.value)} rows={3} />
            </div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
              <button className="tv-btn tv-btn-primary" onClick={() => saveDetailEdit(art.dir_name)} disabled={detailSaving}>
                {detailSaving ? 'Saving...' : 'Save'}
              </button>
              <button className="tv-btn" onClick={() => setDetailEditing(null)}>Cancel</button>
            </div>
          </>
        ) : (
          <>
            <h2 className="tv-pv-detail-name">{art.name}</h2>
            {art.description && <p className="tv-pv-detail-desc">{art.description}</p>}
          </>
        )}
        <div className="tv-pv-detail-badges">
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>{categoryLabel(art.category)}</span>

          {art.is_author && <span className="tv-badge tv-badge-source-author">Author</span>}
          {art.is_from_marketplace && !art.is_author && <span className="tv-badge tv-badge-source-downloaded">Installed</span>}
          {!art.is_from_marketplace && !art.is_author && <span className="tv-badge tv-badge-source-local">Local</span>}
        </div>
        <div className="tv-pv-detail-grid">
          {art.node_count != null && <><span className="tv-pv-label">Nodes</span><span>{art.node_count}</span></>}
          {art.network_count != null && <><span className="tv-pv-label">Networks</span><span>{art.network_count}</span></>}
          <span className="tv-pv-label">Category</span><span>{categoryLabel(art.category)}</span>
          <span className="tv-pv-label">Source</span><span>{sourceLabel(art)}</span>
          {art.created && <><span className="tv-pv-label">Created</span><span>{new Date(art.created).toLocaleDateString()}</span></>}
          {r && (
            <>
              {r.authors?.length > 0 && <><span className="tv-pv-label">Authors</span><span>{r.authors.map(a => `${a.name}${a.affiliation ? ` (${a.affiliation})` : ''}`).join(', ')}</span></>}
              {r.project_name && <><span className="tv-pv-label">Project</span><span>{r.project_name}</span></>}
              <span className="tv-pv-label">Version</span><span>{r.versions?.[0]?.version || 'N/A'}</span>
              <span className="tv-pv-label">Downloads</span><span>{r.artifact_downloads_active}</span>
              <span className="tv-pv-label">Visibility</span><span>{r.visibility}</span>
            </>
          )}
        </div>
        <div className="tv-pv-detail-actions">
          <button className="tv-btn tv-btn-primary" onClick={() => handleOpenArtifact(art)}>Open</button>
          <button className="tv-btn tv-btn-publish" onClick={() => handlePublishArtifact(art)} disabled={!canPublish(art)}>Publish</button>
          {!isDetailEdit && (
            <button className="tv-btn" onClick={() => openDetailEdit(art)}>Edit Info</button>
          )}
          <button className="tv-btn" onClick={() => onEditArtifact?.(art.dir_name)}>Edit</button>
          <button className="tv-btn" onClick={() => handleEditInJupyter(art.dir_name)} disabled={launchingNotebook === art.dir_name}>
            {launchingNotebook === art.dir_name ? 'Opening...' : 'JupyterLab'}
          </button>
          <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteLocal(art)}>Delete</button>
        </div>
      </div>
    );
  };

  const renderRemoteDetail = (art: RemoteArtifact) => {
    const isAuthored = allAuthoredArtifacts.some(a => a.uuid === art.uuid);
    const isMpEdit = mpEditing === art.uuid;
    return (
      <div className="tv-pv-detail">
        <div className="tv-pv-detail-badges">
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`}>{categoryLabel(art.category)}</span>
          {isAuthored && <span className="tv-badge tv-badge-source-author">Author</span>}
          {downloadedUuids.has(art.uuid) && <span className="tv-badge tv-badge-source-downloaded">Installed</span>}
        </div>

        {isMpEdit ? (
          <div style={{ marginBottom: 12 }}>
            <div className="tv-editor-field-row" style={{ marginBottom: 6 }}>
              <label className="tv-edit-label">Title</label>
              <input className="tv-pub-input" value={mpEditTitle} onChange={e => setMpEditTitle(e.target.value)} />
            </div>
            <div className="tv-editor-field-row" style={{ marginBottom: 6 }}>
              <label className="tv-edit-label">Description</label>
              <textarea className="tv-pub-textarea" value={mpEditDesc} onChange={e => setMpEditDesc(e.target.value)} rows={3} />
            </div>
            <div className="tv-editor-field-row" style={{ marginBottom: 6 }}>
              <label className="tv-edit-label">Visibility</label>
              <div className="tv-pub-vis-options" style={{ flexDirection: 'row', gap: '6px' }}>
                {(['author', 'project', 'public'] as const).map(v => (
                  <label key={v} className={`tv-pub-vis-option ${mpEditVisibility === v ? 'active' : ''}`} style={{ flex: 1 }}>
                    <input type="radio" name="mp-detail-vis" value={v} checked={mpEditVisibility === v} onChange={() => setMpEditVisibility(v)} />
                    <span className="tv-pub-vis-label">{v === 'author' ? 'Only Me' : v === 'project' ? 'My Project' : 'Public'}</span>
                  </label>
                ))}
              </div>
            </div>
            {mpEditValidTags.length > 0 && (
              <div className="tv-editor-field-row" style={{ marginBottom: 6 }}>
                <label className="tv-edit-label">Tags</label>
                <div className="tv-pub-tags">
                  {mpEditValidTags.filter(t => !t.restricted).map(t => (
                    <button key={t.tag} className={`tv-mp-tag-chip ${mpEditTags.has(t.tag) ? 'active' : ''}`}
                      onClick={() => toggleMpEditTag(t.tag)}>
                      {t.tag}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {mpEditError && <div className="tv-error" style={{ fontSize: 11, marginBottom: 6 }}>{mpEditError}</div>}
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="tv-btn tv-btn-primary" onClick={handleMpEditSave} disabled={mpEditSaving}>
                {mpEditSaving ? 'Saving...' : 'Save'}
              </button>
              <button className="tv-btn" onClick={() => setMpEditing(null)}>Cancel</button>
              {mpDeleteConfirm === art.uuid ? (
                <>
                  <span style={{ fontSize: 11, alignSelf: 'center' }}>Delete?</span>
                  <button className="tv-btn tv-btn-danger" onClick={() => handleMpDelete(art.uuid)} disabled={mpDeleteBusy}>
                    {mpDeleteBusy ? '...' : 'Yes'}
                  </button>
                  <button className="tv-btn" onClick={() => setMpDeleteConfirm(null)}>No</button>
                </>
              ) : (
                <button className="tv-btn tv-btn-danger" onClick={() => setMpDeleteConfirm(art.uuid)}><BtnText full="Delete" short="Del" /></button>
              )}
            </div>
          </div>
        ) : (
          <>
            <h2 className="tv-pv-detail-name">{art.title}</h2>
            {(art.description_long || art.description_short) && <p className="tv-pv-detail-desc">{stripCategoryMarker(art.description_long || art.description_short)}</p>}
          </>
        )}

        {!isMpEdit && (
          <div className="tv-pv-detail-grid">
            <span className="tv-pv-label">Category</span><span>{categoryLabel(art.category)}</span>
            {art.authors?.length > 0 && <><span className="tv-pv-label">Authors</span><span>{art.authors.map(a => `${a.name}${a.affiliation ? ` (${a.affiliation})` : ''}`).join(', ')}</span></>}
            {art.project_name && <><span className="tv-pv-label">Project</span><span>{art.project_name}</span></>}
            <span className="tv-pv-label">Visibility</span><span>{art.visibility}</span>
            <span className="tv-pv-label">Downloads</span><span>{art.artifact_downloads_active}</span>
            <span className="tv-pv-label">Views</span><span>{art.artifact_views}</span>
            <span className="tv-pv-label">Versions</span><span>{art.number_of_versions}</span>
            {art.versions?.length > 0 && <><span className="tv-pv-label">Latest</span><span>{art.versions[0].version} ({art.versions[0].version_downloads} downloads)</span></>}
            <span className="tv-pv-label">Created</span><span>{new Date(art.created).toLocaleDateString()}</span>
            {art.modified && <><span className="tv-pv-label">Updated</span><span>{new Date(art.modified).toLocaleDateString()}</span></>}
            {art.tags?.length > 0 && <><span className="tv-pv-label">Tags</span><span>{art.tags.join(', ')}</span></>}
          </div>
        )}

        <div className="tv-pv-detail-actions">
          <button className="tv-btn tv-btn-primary" disabled={mpDownloading === art.uuid} onClick={() => openVersionPicker(art)}>
            {mpDownloading === art.uuid ? 'Getting...' : 'Get'}
          </button>
          {isAuthored && !isMpEdit && (
            <button className="tv-btn" onClick={() => openMpEdit(art)}>Edit</button>
          )}
        </div>
      </div>
    );
  };

  const renderMyPreview = () => {
    const selectedKey = previewSelected;
    const selected = filteredMyArtifacts.find(a => `${a.category}-${a.dir_name}` === selectedKey);
    return (
      <div className="tv-pv-container">
        <div className="tv-pv-list">
          {filteredMyArtifacts.map(art => {
            const key = `${art.category}-${art.dir_name}`;
            return (
              <button key={key} className={`tv-pv-item ${selectedKey === key ? 'active' : ''}`}
                onClick={() => setPreviewSelected(key)}>
                <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`} style={{ fontSize: '8px', padding: '1px 4px' }}>
                  {categoryLabel(art.category).split(' ')[0]}
                </span>
                <span className="tv-pv-item-name">{art.name}</span>
              </button>
            );
          })}
          {!filteredMyArtifacts.length && <div className="tv-empty" style={{ padding: '16px' }}>No artifacts match your filters.</div>}
        </div>
        <div className="tv-pv-main">
          {selected ? renderLocalDetail(selected) : <div className="tv-empty" style={{ paddingTop: '40px' }}>Select an artifact to preview its details.</div>}
        </div>
      </div>
    );
  };

  const renderMpPreview = (arts: RemoteArtifact[] = filteredMpArtifacts) => {
    const selected = arts.find(a => a.uuid === previewSelected);
    return (
      <div className="tv-pv-container">
        <div className="tv-pv-list">
          {arts.map(art => (
            <button key={art.uuid} className={`tv-pv-item ${previewSelected === art.uuid ? 'active' : ''}`}
              onClick={() => setPreviewSelected(art.uuid)}>
              <span className={`tv-badge tv-badge-cat tv-badge-cat-${art.category}`} style={{ fontSize: '8px', padding: '1px 4px' }}>
                {categoryLabel(art.category).split(' ')[0]}
              </span>
              <span className="tv-pv-item-name">{art.title}</span>
            </button>
          ))}
          {!arts.length && <div className="tv-empty" style={{ padding: '16px' }}>No artifacts match your filters.</div>}
        </div>
        <div className="tv-pv-main">
          {selected ? renderRemoteDetail(selected) : <div className="tv-empty" style={{ paddingTop: '40px' }}>Select an artifact to preview its details.</div>}
        </div>
      </div>
    );
  };

  // Local artifacts matching a category (for upload version dialog)
  const localArtifactsForCategory = (cat: string) =>
    myArtifacts.filter(a => a.category === cat);

  // ---------------------------------------------------------------------------
  // Editor requirements check
  // ---------------------------------------------------------------------------

  // Flat file names at the root level for warnings (only when cwd is root)
  const rootFileNames = editCwd === '' ? editFiles.map(f => f.name) : [];
  const editorWarnings = (() => {
    if (!editing || editCwd !== '') return [];
    const warns: string[] = [];
    const hasFile = (name: string) => rootFileNames.includes(name);
    const hasSlice = hasFile('slice.json');
    const hasDeploy = hasFile('deploy.sh');
    const hasRun = hasFile('run.sh');
    const hasVm = hasFile('vm-template.json');
    const hasRecipe = hasFile('recipe.json');

    if (!hasSlice && !hasVm && !hasRecipe) {
      warns.push('No recognized artifact type. Add slice.json (weave), vm-template.json (VM), or recipe.json (recipe).');
    }
    if (hasSlice && !hasDeploy) {
      warns.push('Missing deploy.sh — a weave needs both slice.json and deploy.sh to be loadable.');
    }
    if (hasSlice && hasDeploy && !hasRun) {
      warns.push('No run.sh — add run.sh to make this weave runnable.');
    }
    return warns;
  })();

  // ---------------------------------------------------------------------------
  // Shared remote settings editor section
  // ---------------------------------------------------------------------------

  const renderRemoteSettingsEditor = (uuid: string, localDirName?: string, category?: string) => (
    <div className="tv-editor-section">
      <div className="tv-editor-section-title">Marketplace Settings</div>
      <div className="tv-editor-field-row">
        <label className="tv-edit-label">Title</label>
        <input className="tv-pub-input" value={editRemoteTitle} onChange={e => setEditRemoteTitle(e.target.value)} />
      </div>
      <div className="tv-editor-field-row">
        <label className="tv-edit-label">Description</label>
        <textarea className="tv-pub-textarea" value={editRemoteDesc} onChange={e => setEditRemoteDesc(e.target.value)} rows={2} />
      </div>
      <div className="tv-editor-field-row">
        <label className="tv-edit-label">Visibility</label>
        <div className="tv-pub-vis-options" style={{ flexDirection: 'row', gap: '8px' }}>
          {(['author', 'project', 'public'] as const).map(v => (
            <label key={v} className={`tv-pub-vis-option ${editRemoteVisibility === v ? 'active' : ''}`} style={{ flex: 1 }}>
              <input type="radio" name="edit-vis" value={v} checked={editRemoteVisibility === v} onChange={() => setEditRemoteVisibility(v)} />
              <span className="tv-pub-vis-label">{v === 'author' ? 'Only Me' : v === 'project' ? 'My Project' : 'Public'}</span>
            </label>
          ))}
        </div>
      </div>
      {availableProjects.length > 0 && (
        <div className="tv-editor-field-row">
          <label className="tv-edit-label">Project</label>
          <select className="tv-pub-input" value={editProjectUuid} onChange={e => setEditProjectUuid(e.target.value)}>
            <option value="">No project affiliation</option>
            {availableProjects.map(p => (
              <option key={p.uuid} value={p.uuid}>{p.name}</option>
            ))}
          </select>
        </div>
      )}
      {editRemoteValidTags.length > 0 && (
        <div className="tv-editor-field-row">
          <label className="tv-edit-label">Tags</label>
          <div className="tv-pub-tags">
            {editRemoteValidTags.filter(t => !t.restricted).map(t => (
              <button key={t.tag} className={`tv-mp-tag-chip ${editRemoteTags.has(t.tag) ? 'active' : ''}`}
                onClick={() => setEditRemoteTags(prev => { const n = new Set(prev); if (n.has(t.tag)) n.delete(t.tag); else n.add(t.tag); return n; })}>
                {t.tag}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Authors */}
      <div className="tv-editor-field-row">
        <label className="tv-edit-label">Authors</label>
        <div className="tv-authors-list">
          {editAuthors.map((a, i) => (
            <div key={i} className="tv-author-row">
              <span className="tv-author-name">{a.name}</span>
              {a.affiliation && <span className="tv-author-affil">({a.affiliation})</span>}
              <button className="tv-author-remove" onClick={() => removeAuthor(i)} title="Remove author">x</button>
            </div>
          ))}
          <div className="tv-author-add">
            <input className="tv-pub-input" placeholder="Name" value={editNewAuthorName}
              onChange={e => setEditNewAuthorName(e.target.value)} style={{ flex: 2 }}
              onKeyDown={e => { if (e.key === 'Enter') addAuthor(); }} />
            <input className="tv-pub-input" placeholder="Affiliation (optional)" value={editNewAuthorAffil}
              onChange={e => setEditNewAuthorAffil(e.target.value)} style={{ flex: 2 }}
              onKeyDown={e => { if (e.key === 'Enter') addAuthor(); }} />
            <button className="tv-btn" onClick={addAuthor} disabled={!editNewAuthorName.trim()}>Add</button>
          </div>
        </div>
      </div>

      <div className="tv-editor-field-row" style={{ flexDirection: 'row', gap: '6px' }}>
        <button className="tv-btn tv-btn-primary" onClick={saveEditRemoteSettings} disabled={editRemoteSaving}>
          {editRemoteSaving ? 'Saving...' : 'Save Marketplace Settings'}
        </button>
        {localDirName && category && (
          <button className="tv-btn" onClick={() => {
            const art = { uuid, versions: editVersions } as RemoteArtifact;
            openUploadVersion(art, localDirName, category);
          }}>Upload New Version</button>
        )}
        {deleteConfirmUuid === uuid ? (
          <>
            <span style={{ fontSize: '12px', alignSelf: 'center' }}>Sure?</span>
            <button className="tv-btn tv-btn-danger" onClick={() => handleDeleteRemote(uuid)} disabled={deleteBusy}>
              {deleteBusy ? '...' : 'Yes'}
            </button>
            <button className="tv-btn" onClick={() => setDeleteConfirmUuid(null)}>No</button>
          </>
        ) : (
          <button className="tv-btn tv-btn-danger" onClick={() => setDeleteConfirmUuid(uuid)}>Delete from Marketplace</button>
        )}
      </div>
    </div>
  );

  const renderVersionsEditor = (uuid: string, localDirName?: string, category?: string) => (
    <div className="tv-editor-section">
      <div className="tv-editor-section-title">Versions ({editVersions.length})</div>
      {editVersions.length === 0 && (
        <div className="tv-empty" style={{ padding: '8px', fontSize: '12px' }}>No versions published yet.</div>
      )}
      <div className="tv-versions-list">
        {editVersions.map(v => (
          <div key={v.uuid} className="tv-version-row">
            <span className="tv-version-tag">{v.version}</span>
            <span className="tv-version-meta">{v.version_downloads} downloads</span>
            <span className="tv-version-meta">{new Date(v.created).toLocaleDateString()}</span>
            {v.active && <span className="tv-badge tv-badge-source-author" style={{ fontSize: '9px', padding: '1px 4px' }}>Active</span>}
            {localDirName && (
              <button className="tv-btn tv-btn-revert" style={{ fontSize: '10px', padding: '2px 6px' }}
                onClick={() => handleRevertArtifact(v.uuid)} disabled={editReverting}
                title="Revert local files to this version">
                {editReverting ? '...' : 'Revert'}
              </button>
            )}
            <button className="tv-btn tv-btn-danger" style={{ marginLeft: localDirName ? '0' : 'auto', fontSize: '10px', padding: '2px 6px' }}
              onClick={() => handleDeleteVersion(v.uuid)} disabled={deletingVersion === v.uuid}>
              {deletingVersion === v.uuid ? '...' : 'Delete'}
            </button>
          </div>
        ))}
      </div>
      <div style={{ marginTop: '6px', display: 'flex', gap: '6px' }}>
        {localDirName && category && (
          <button className="tv-btn" onClick={() => {
            const art = { uuid, versions: editVersions } as RemoteArtifact;
            openUploadVersion(art, localDirName, category);
          }}>Upload New Version</button>
        )}
        {localDirName && editVersions.length > 0 && (
          <button className="tv-btn tv-btn-revert" onClick={() => handleRevertArtifact()} disabled={editReverting}>
            {editReverting ? 'Reverting...' : 'Revert to Latest'}
          </button>
        )}
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // If editing a remote-only artifact, show the remote editor
  if (editingRemote) {
    return (
      <div className="tv-root">
        <div className="tv-editor-header">
          <button className="tv-btn" onClick={closeEditor}>Back</button>
          <h1 className="tv-title" style={{ fontSize: '16px' }}>{editingRemote.title}</h1>
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${editingRemote.category}`}>{categoryLabel(editingRemote.category)}</span>
          <span className="tv-badge tv-badge-source-author">Author</span>
        </div>

        {editError && <div className="tv-error" style={{ textAlign: 'left' }}>{editError}</div>}

        {renderRemoteSettingsEditor(editingRemote.uuid)}
        {renderVersionsEditor(editingRemote.uuid)}
      </div>
    );
  }

  // If editing, show the editor instead of tabs
  if (editing) {
    const r = editing.remote_artifact;
    const fileDirty = editFileContent !== editFileOriginal;
    return (
      <div className="tv-root">
        <div className="tv-editor-header">
          <button className="tv-btn" onClick={closeEditor}>Back</button>
          <h1 className="tv-title" style={{ fontSize: '16px' }}>{editing.name}</h1>
          <span className={`tv-badge tv-badge-cat tv-badge-cat-${editing.category}`}>{categoryLabel(editing.category)}</span>
        </div>

        {editError && <div className="tv-error" style={{ textAlign: 'left' }}>{editError}</div>}

        {/* Metadata section */}
        <div className="tv-editor-section">
          <div className="tv-editor-section-title">Metadata</div>
          <div className="tv-editor-field-row">
            <label className="tv-edit-label">Description</label>
            <textarea className="tv-pub-textarea" value={editDesc} rows={2}
              onChange={e => { setEditDesc(e.target.value); setEditDescDirty(true); }} />
            {editDescDirty && (
              <button className="tv-btn tv-btn-primary" onClick={saveEditMetadata} disabled={editSavingMeta}>
                {editSavingMeta ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>
        </div>

        {/* Remote settings (if linked) */}
        {r && (
          <>
            {renderRemoteSettingsEditor(r.uuid, editing.dir_name, editing.category)}
            {renderVersionsEditor(r.uuid, editing.dir_name, editing.category)}
          </>
        )}
        {!r && editing.remote_status === 'not_linked' && (
          <div className="tv-editor-section">
            <div className="tv-editor-section-title">Publishing</div>
            <button className="tv-btn tv-btn-publish" onClick={() => openPublish(editing.dir_name, editing.category, editing.name, editing.description || '')}>
              Publish to FABRIC Artifact Manager
            </button>
          </div>
        )}

        {/* Warnings */}
        {editorWarnings.length > 0 && (
          <div className="tv-editor-warnings">
            {editorWarnings.map((w, i) => <div key={i} className="tv-editor-warn">{w}</div>)}
          </div>
        )}

        {/* Files section — full file browser */}
        <div className="tv-editor-section" style={{ flex: 1, minHeight: 0 }}>
          <div className="tv-editor-section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>Files</span>
            {editCwd && <span style={{ fontWeight: 400, fontSize: '11px', opacity: 0.7 }}>/ {editCwd}</span>}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: '4px' }}>
              <button className="tv-btn" style={{ fontSize: '10px', padding: '2px 6px' }}
                onClick={() => editUploadRef.current?.click()} title="Upload files">
                Upload
              </button>
              <input ref={editUploadRef} type="file" multiple style={{ display: 'none' }}
                onChange={e => { if (e.target.files) { handleUploadFiles(e.target.files); e.target.value = ''; } }} />
            </div>
          </div>
          <div className="tv-editor-files">
            <div className="tv-editor-file-list">
              {editCwd && (
                <div className="tv-editor-file-item">
                  <button className="tv-editor-file-btn tv-editor-file-dir" onClick={navigateUp}>
                    ..
                  </button>
                </div>
              )}
              {editFiles
                .sort((a, b) => {
                  if (a.type === 'dir' && b.type !== 'dir') return -1;
                  if (a.type !== 'dir' && b.type === 'dir') return 1;
                  return a.name.localeCompare(b.name);
                })
                .map(f => (
                <div key={f.name} className={`tv-editor-file-item ${editSelectedFile === f.name ? 'active' : ''}`}>
                  {f.type === 'dir' ? (
                    <button className="tv-editor-file-btn tv-editor-file-dir" onClick={() => navigateDir(f.name)}>
                      {f.name}/
                    </button>
                  ) : (
                    <button className="tv-editor-file-btn" onClick={() => selectEditFile(f.name)}>
                      {f.name}
                    </button>
                  )}
                  <span className="tv-editor-file-size">{f.type === 'dir' ? '' : formatFileSize(f.size)}</span>
                  <button className="tv-tool-btn tv-tool-btn-danger" onClick={() => deleteEditFile(f.name, f.type === 'dir')} title={`Delete ${f.type === 'dir' ? 'folder' : 'file'}`}>x</button>
                </div>
              ))}
              {editFiles.length === 0 && !editCwd && <div className="tv-empty" style={{ padding: '12px', fontSize: '11px' }}>No files yet.</div>}
              <div className="tv-editor-new-file">
                <input className="tv-new-file-input" placeholder="filename" value={editNewFileName}
                  onChange={e => setEditNewFileName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addEditFile(); }} />
                <button className="tv-btn" onClick={addEditFile} disabled={!editNewFileName.trim()} title="New file">+</button>
                <button className="tv-btn" onClick={addEditFolder} disabled={!editNewFileName.trim()} title="New folder">D</button>
              </div>
            </div>
            <div className="tv-editor-file-content">
              {editSelectedFile ? (
                editFileLoading ? (
                  <div className="tv-loading">Loading file...</div>
                ) : (
                  <>
                    <div className="tv-script-header">
                      <span>{editCwd ? `${editCwd}/` : ''}{editSelectedFile}</span>
                      {fileDirty && <span style={{ fontSize: '10px', color: 'var(--fabric-orange, #ff8542)' }}>(unsaved)</span>}
                      <div className="tv-script-header-actions">
                        {fileDirty && (
                          <button className="tv-btn" onClick={() => { setEditFileContent(editFileOriginal); }}
                            style={{ fontSize: '10px', padding: '2px 6px' }}>Discard</button>
                        )}
                        <button className="tv-btn tv-btn-primary" onClick={saveEditFile} disabled={editFileSaving || !fileDirty}>
                          {editFileSaving ? 'Saving...' : 'Save'}
                        </button>
                      </div>
                    </div>
                    <textarea
                      className="tv-script-textarea"
                      value={editFileContent}
                      onChange={e => setEditFileContent(e.target.value)}
                      spellCheck={false}
                    />
                  </>
                )
              ) : (
                <div className="tv-empty" style={{ paddingTop: '40px' }}>Select a file to edit, or create a new one.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main tabs view
  // ---------------------------------------------------------------------------

  return (
    <div className="tv-root">
      <div className="tv-header">
        <h1 className="tv-title">Artifacts</h1>
        <button className="tv-create-btn" onClick={() => setShowCreateDialog(true)}>
          + New Artifact
        </button>
        <button className="tv-reload-btn" onClick={() => { fetchMyArtifacts(); setMpLoaded(false); fetchMarketplace(true); }} disabled={myLoading || mpLoading}>
          {myLoading || mpLoading ? 'Reloading...' : 'Reload'}
        </button>
      </div>

      {/* Create New Artifact Dialog */}
      {showCreateDialog && (
        <div className="tv-modal-overlay" onClick={() => setShowCreateDialog(false)}>
          <div className="tv-modal" onClick={(e) => e.stopPropagation()}>
            <h4>Create New Artifact</h4>
            <input
              type="text"
              className="tv-modal-input"
              placeholder="Artifact name..."
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreateArtifact()}
              autoFocus
            />
            <textarea
              className="tv-modal-input"
              placeholder="Description (optional)..."
              value={createDesc}
              onChange={(e) => setCreateDesc(e.target.value)}
              rows={2}
              style={{ resize: 'vertical', marginTop: 8 }}
            />
            {createError && <div className="tv-modal-error">{createError}</div>}
            <div className="tv-modal-actions">
              <button onClick={() => setShowCreateDialog(false)}>Cancel</button>
              <button
                className="tv-modal-primary"
                onClick={handleCreateArtifact}
                disabled={!createName.trim() || createBusy}
              >
                {createBusy ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="tv-tabs">
        <button className={`tv-tab ${tab === 'my-artifacts' ? 'active' : ''}`} onClick={() => setTab('my-artifacts')}>
          My Artifacts ({myArtifacts.length})
        </button>
        <button className={`tv-tab ${tab === 'published' ? 'active' : ''}`} onClick={() => { setTab('published'); if (!mpLoaded) fetchMarketplace(); }}>
          Published {mpLoaded ? `(${allAuthoredArtifacts.length})` : ''}
        </button>
        <button className={`tv-tab ${tab === 'community' ? 'active' : ''}`} onClick={() => { setTab('community'); if (!mpLoaded) fetchMarketplace(); }}>
          Community Marketplace {mpLoaded ? `(${mpAllArtifacts.length})` : ''}
        </button>
      </div>

      {/* ================================================================= */}
      {/* LOCAL TAB                                                          */}
      {/* ================================================================= */}
      {tab === 'my-artifacts' && (
        <>
          <div className="tv-my-filter-bar">
            <div className="tv-my-filter-group">
              <span className="tv-my-filter-label">Category:</span>
              {(['all', 'weave', 'vm-template', 'recipe', 'notebook'] as CategoryFilter[]).map(c => (
                <button key={c} className={`tv-my-filter-chip ${myCategoryFilter === c ? 'active' : ''}`}
                  onClick={() => setMyCategoryFilter(c)}>
                  {c === 'all' ? 'All' : categoryLabel(c)}
                </button>
              ))}
            </div>
            {renderViewToggle()}
          </div>

          <div className="tv-search">
            <input className="tv-search-input" placeholder="Search local artifacts..." value={search}
              onChange={e => setSearch(e.target.value)} />
          </div>

          {myLoading && !myArtifacts.length && <div className="tv-loading">Loading artifacts...</div>}
          {myError && <div className="tv-error">{myError}</div>}

          {viewMode === 'grid' && (
            <>
              <div className="tv-grid">{filteredMyArtifacts.map(renderMyArtifactCard)}</div>
              {!myLoading && !filteredMyArtifacts.length && <div className="tv-empty">No artifacts match your filters.</div>}
            </>
          )}
          {viewMode === 'table' && (
            filteredMyArtifacts.length ? renderMyTable() : <div className="tv-empty">No artifacts match your filters.</div>
          )}
          {viewMode === 'preview' && renderMyPreview()}
        </>
      )}

      {/* ================================================================= */}
      {/* MY ARTIFACTS TAB (authored remote artifacts)                       */}
      {/* ================================================================= */}
      {tab === 'published' && (
        <>
          {mpLoading && <div className="tv-loading">Loading your published artifacts...</div>}
          {mpError && <div className="tv-error">{mpError}</div>}
          {mpLoaded && (
            <>
              <div className="tv-mp-toolbar">
                <div className="tv-mp-search-wrap">
                  <input className="tv-mp-search" placeholder="Search your artifacts..." value={mpSearch}
                    onChange={e => setMpSearch(e.target.value)} />
                  {mpSearch && <button className="tv-mp-search-clear" onClick={() => setMpSearch('')} title="Clear search">x</button>}
                </div>
                <select className="tv-mp-sort" value={mpSort} onChange={e => setMpSort(e.target.value as any)}>
                  <option value="popular">Most Downloaded</option>
                  <option value="newest">Newest First</option>
                  <option value="az">A - Z</option>
                </select>
                {renderViewToggle()}
              </div>

              <div className="tv-my-filter-bar" style={{ borderTop: 'none', paddingTop: 0 }}>
                <div className="tv-my-filter-group">
                  <span className="tv-my-filter-label">Category:</span>
                  {(['all', ...mpUniqueCategories] as CategoryFilter[]).map(c => (
                    <button key={c} className={`tv-my-filter-chip ${mpCategoryFilter === c ? 'active' : ''}`}
                      onClick={() => setMpCategoryFilter(c)}>
                      {c === 'all' ? 'All' : categoryLabel(c)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="tv-mp-results-info">
                {filteredAuthoredArtifacts.length === allAuthoredArtifacts.length
                  ? `${allAuthoredArtifacts.length} published artifact${allAuthoredArtifacts.length !== 1 ? 's' : ''}`
                  : `${filteredAuthoredArtifacts.length} of ${allAuthoredArtifacts.length} artifacts`}
              </div>

              {allAuthoredArtifacts.length === 0 && (
                <div className="tv-empty">You haven't published any artifacts yet. Publish from the Local tab or from the side panel.</div>
              )}

              {viewMode === 'grid' && (
                <>
                  <div className="tv-grid">{filteredAuthoredArtifacts.map(renderMarketplaceCard)}</div>
                  {allAuthoredArtifacts.length > 0 && !filteredAuthoredArtifacts.length && (
                    <div className="tv-empty">No artifacts match your filters.</div>
                  )}
                </>
              )}
              {viewMode === 'table' && (
                filteredAuthoredArtifacts.length ? renderMpTable(filteredAuthoredArtifacts) : (
                  allAuthoredArtifacts.length > 0 ? <div className="tv-empty">No artifacts match your filters.</div> : null
                )
              )}
              {viewMode === 'preview' && renderMpPreview(filteredAuthoredArtifacts)}
            </>
          )}
        </>
      )}

      {/* ================================================================= */}
      {/* MARKETPLACE TAB                                                    */}
      {/* ================================================================= */}
      {tab === 'community' && (
        <>
          {mpLoading && <div className="tv-loading">Loading FABRIC Artifact Marketplace...</div>}
          {mpError && <div className="tv-error">{mpError}</div>}
          {mpLoaded && (
            <>
              <div className="tv-mp-toolbar">
                <div className="tv-mp-search-wrap">
                  <input className="tv-mp-search" placeholder="Search by title, description, author, or tag..." value={mpSearch}
                    onChange={e => setMpSearch(e.target.value)} />
                  {mpSearch && <button className="tv-mp-search-clear" onClick={() => setMpSearch('')} title="Clear search">x</button>}
                </div>
                <select className="tv-mp-sort" value={mpSort} onChange={e => setMpSort(e.target.value as any)}>
                  <option value="popular">Most Downloaded</option>
                  <option value="newest">Newest First</option>
                  <option value="az">A - Z</option>
                </select>
                {renderViewToggle()}
                <button className="tv-btn" onClick={() => fetchMarketplace(true)} title="Refresh from Artifact Manager">Refresh</button>
              </div>

              <div className="tv-my-filter-bar" style={{ borderTop: 'none', paddingTop: 0 }}>
                <div className="tv-my-filter-group">
                  <span className="tv-my-filter-label">Category:</span>
                  {(['all', ...mpUniqueCategories] as CategoryFilter[]).map(c => (
                    <button key={c} className={`tv-my-filter-chip ${mpCategoryFilter === c ? 'active' : ''}`}
                      onClick={() => setMpCategoryFilter(c)}>
                      {c === 'all' ? 'All' : categoryLabel(c)}
                    </button>
                  ))}
                </div>
                {mpUniqueAuthors.length > 0 && (
                  <div className="tv-my-filter-group">
                    <span className="tv-my-filter-label">Author:</span>
                    <select className="tv-mp-sort" value={mpAuthorFilter} onChange={e => setMpAuthorFilter(e.target.value)}
                      style={{ fontSize: 12, minWidth: 140 }}>
                      <option value="">All Authors</option>
                      {mpUniqueAuthors.map(([name, count]) => (
                        <option key={name} value={name}>{name} ({count})</option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              {mpAllTags.length > 0 && (
                <div className="tv-mp-tag-bar">
                  <span className="tv-mp-tag-label">Tags:</span>
                  {(mpActiveTags.size > 0 || mpCategoryFilter !== 'all' || mpAuthorFilter) && (
                    <button className="tv-mp-tag-chip tv-mp-tag-clear" onClick={() => {
                      setMpActiveTags(new Set()); setMpCategoryFilter('all'); setMpAuthorFilter(''); setMpSearch('');
                    }}>Clear all filters</button>
                  )}
                  {mpAllTags.map(t => (
                    <button key={t.name} className={`tv-mp-tag-chip ${mpActiveTags.has(t.name) ? 'active' : ''}`}
                      onClick={() => toggleMpTag(t.name)}>
                      {t.name} <span className="tv-mp-tag-count">{t.count}</span>
                    </button>
                  ))}
                </div>
              )}

              <div className="tv-mp-results-info">
                {filteredMpArtifacts.length === mpAllArtifacts.length
                  ? `${mpAllArtifacts.length} artifacts`
                  : `${filteredMpArtifacts.length} of ${mpAllArtifacts.length} artifacts`}
              </div>

              {viewMode === 'grid' && (
                <>
                  <div className="tv-grid">{filteredMpArtifacts.map(renderMarketplaceCard)}</div>
                  {!filteredMpArtifacts.length && (
                    <div className="tv-empty">
                      No artifacts match your filters.{' '}
                      <button className="tv-mp-reset-link" onClick={() => { setMpSearch(''); setMpActiveTags(new Set()); setMpCategoryFilter('all'); setMpAuthorFilter(''); }}>Clear filters</button>
                    </div>
                  )}
                </>
              )}
              {viewMode === 'table' && (
                filteredMpArtifacts.length ? renderMpTable(filteredMpArtifacts) : (
                  <div className="tv-empty">
                    No artifacts match your filters.{' '}
                    <button className="tv-mp-reset-link" onClick={() => { setMpSearch(''); setMpActiveTags(new Set()); setMpCategoryFilter('all'); setMpAuthorFilter(''); }}>Clear filters</button>
                  </div>
                )
              )}
              {viewMode === 'preview' && renderMpPreview(filteredMpArtifacts)}
            </>
          )}
        </>
      )}

      {/* ================================================================= */}
      {/* PUBLISH DIALOG                                                     */}
      {/* ================================================================= */}
      {pubOpen && (
        <div className="tv-pub-overlay" onClick={() => setPubOpen(false)}>
          <div className="tv-pub-dialog" onClick={e => e.stopPropagation()}>
            <div className="tv-pub-header">
              Publish to FABRIC Artifact Manager
              <button className="tv-btn" onClick={() => setPubOpen(false)} style={{ marginLeft: 'auto' }}>Close</button>
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Title</label>
              <input className="tv-pub-input" value={pubTitle} onChange={e => setPubTitle(e.target.value)} />
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Description <span style={{ fontSize: 11, opacity: 0.6 }}>(5-255 chars)</span></label>
              <textarea className="tv-pub-textarea" value={pubDesc} onChange={e => setPubDesc(e.target.value)} rows={3} maxLength={255} />
              <span className={`ae-char-count ${pubDesc.length > 0 && (pubDesc.length < 5 || pubDesc.length > 255) ? 'over' : ''}`} style={{ fontSize: 11, opacity: 0.7, textAlign: 'right', display: 'block', marginTop: 2 }}>
                {pubDesc.length}/255{pubDesc.length > 0 && pubDesc.length < 5 ? ' (min 5)' : ''}
              </span>
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Visibility</label>
              <div className="tv-pub-vis-options">
                {(['author', 'project', 'public'] as const).map(v => (
                  <label key={v} className={`tv-pub-vis-option ${pubVisibility === v ? 'active' : ''}`}>
                    <input type="radio" name="visibility" value={v} checked={pubVisibility === v} onChange={() => setPubVisibility(v)} />
                    <span className="tv-pub-vis-label">{v === 'author' ? 'Only Me' : v === 'project' ? 'My Project' : 'Public'}</span>
                    <span className="tv-pub-vis-desc">
                      {v === 'author' ? 'Only you can see this artifact' : v === 'project' ? 'Visible to members of your project' : 'Visible to all FABRIC users'}
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Tags</label>
              <div className="tv-pub-tags">
                {pubValidTags.filter(t => !t.restricted).map(t => (
                  <button key={t.tag} className={`tv-mp-tag-chip ${pubTags.has(t.tag) ? 'active' : ''}`}
                    onClick={() => togglePubTag(t.tag)}>{t.tag}</button>
                ))}
              </div>
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Category</label>
              <span className="tv-pub-category">{categoryLabel(pubCategory)}</span>
            </div>
            {pubCategory === 'notebook' && (
              <div className="tv-pub-field" style={{ fontSize: 12, color: 'var(--fabric-teal, #008e7a)' }}>
                This will publish your modified notebook workspace as a new artifact with fork provenance linking to the original.
              </div>
            )}
            {pubError && <div className="tv-error" style={{ padding: '8px 0' }}>{pubError}</div>}
            <div className="tv-pub-actions">
              <button className="tv-btn tv-btn-primary"
                onClick={pubCategory === 'notebook' ? handlePublishNotebookFork : handlePublish}
                disabled={pubBusy || !pubTitle.trim()}>
                {pubBusy ? 'Publishing...' : 'Publish'}
              </button>
              <button className="tv-btn" onClick={() => setPubOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* PUBLISH VERSION DIALOG                                             */}
      {/* ================================================================= */}
      {uvOpen && (
        <div className="tv-pub-overlay" onClick={() => setUvOpen(false)}>
          <div className="tv-pub-dialog" onClick={e => e.stopPropagation()} style={{ width: '420px' }}>
            <div className="tv-pub-header">
              Publish New Version
              <button className="tv-btn" onClick={() => setUvOpen(false)} style={{ marginLeft: 'auto' }}>Close</button>
            </div>
            <div className="tv-pub-field">
              <label className="tv-pub-label">Source (local artifact)</label>
              <select className="tv-mp-sort" value={uvDirName} onChange={e => setUvDirName(e.target.value)} style={{ width: '100%' }}>
                <option value="">-- Select local artifact --</option>
                {localArtifactsForCategory(uvCategory).map(a => (
                  <option key={a.dir_name} value={a.dir_name}>{a.name} ({a.dir_name})</option>
                ))}
              </select>
            </div>
            {uvError && <div className="tv-error" style={{ padding: '8px 0' }}>{uvError}</div>}
            <div className="tv-pub-actions">
              <button className="tv-btn tv-btn-primary" onClick={handleUploadVersion} disabled={uvBusy || !uvDirName}>
                {uvBusy ? 'Publishing...' : 'Publish Version'}
              </button>
              <button className="tv-btn" onClick={() => setUvOpen(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Marketplace edit dialog removed — editing now uses full-page editor via openRemoteEditor */}

      {/* Version picker dialog */}
      {versionPickerArt && (
        <div className="tv-pub-overlay" onClick={() => setVersionPickerArt(null)}>
          <div className="tv-pub-dialog" onClick={e => e.stopPropagation()} style={{ width: '420px' }}>
            <h3 style={{ margin: 0, fontSize: '14px' }}>Select Version</h3>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--fabric-text-muted)' }}>
              Choose which version of &ldquo;{versionPickerArt.title}&rdquo; to download.
            </p>
            <div className="tv-versions-list" style={{ maxHeight: '300px', overflowY: 'auto' }}>
              {(versionPickerArt.versions || []).map(v => (
                <div key={v.uuid} className="tv-version-row">
                  <span className="tv-version-tag">{v.version}</span>
                  <span className="tv-version-meta">{v.version_downloads} downloads</span>
                  <span className="tv-version-meta">{new Date(v.created).toLocaleDateString()}</span>
                  {v.active && <span className="tv-badge tv-badge-source-author" style={{ fontSize: '9px', padding: '1px 4px' }}>Active</span>}
                  <button className="tv-btn tv-btn-primary" style={{ marginLeft: 'auto', fontSize: '10px', padding: '3px 8px' }}
                    onClick={() => handleDownloadArtifact(versionPickerArt, v.uuid)}
                    disabled={mpDownloading === versionPickerArt.uuid}>
                    {mpDownloading === versionPickerArt.uuid ? '...' : 'Get'}
                  </button>
                </div>
              ))}
            </div>
            <div className="tv-pub-actions">
              <button className="tv-btn tv-btn-primary" onClick={() => handleDownloadArtifact(versionPickerArt)}
                disabled={mpDownloading === versionPickerArt.uuid}>
                {mpDownloading === versionPickerArt.uuid ? 'Getting...' : 'Get Latest'}
              </button>
              <button className="tv-btn" onClick={() => setVersionPickerArt(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
