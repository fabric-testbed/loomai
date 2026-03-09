'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import * as api from '../api/client';
import type { FileEntry } from '../types/fabric';
import FileEditor, { isTextFile, isLikelyBinary } from './FileEditor';
import '../styles/file-browser.css';

/** Recursively walk FileSystemEntry trees from drag-and-drop. */
async function walkEntries(
  entries: FileSystemEntry[],
  basePath: string,
  result: Array<{ file: File; relativePath: string }>
): Promise<void> {
  for (const entry of entries) {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      const file = await new Promise<File>((resolve, reject) =>
        fileEntry.file(resolve, reject)
      );
      const relativePath = basePath ? `${basePath}/${entry.name}` : entry.name;
      result.push({ file, relativePath });
    } else if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const reader = dirEntry.createReader();
      const children = await new Promise<FileSystemEntry[]>((resolve, reject) => {
        const all: FileSystemEntry[] = [];
        const readBatch = () => {
          reader.readEntries((batch) => {
            if (batch.length === 0) resolve(all);
            else { all.push(...batch); readBatch(); }
          }, reject);
        };
        readBatch();
      });
      const childBase = basePath ? `${basePath}/${entry.name}` : entry.name;
      await walkEntries(children, childBase, result);
    }
  }
}

function humanSize(bytes: number): string {
  if (bytes === 0) return '\u2014';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

interface ContainerFileBrowserProps {
  rootPath?: string;
  headerLabel?: string;
}

export default function ContainerFileBrowser({ rootPath, headerLabel }: ContainerFileBrowserProps = {}) {
  const [path, setPath] = useState(rootPath || '');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset path when rootPath changes
  useEffect(() => {
    setPath(rootPath || '');
  }, [rootPath]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    setSelected(new Set());
    try {
      setEntries(await api.listFiles(path));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { refresh(); }, [refresh]);

  const basePath = rootPath || '';
  const navigate = (dir: string) => setPath(path ? `${path}/${dir}` : dir);
  const goUp = () => {
    const parts = path.split('/').filter(Boolean);
    parts.pop();
    const newPath = parts.join('/');
    // Don't navigate above rootPath
    if (basePath && !newPath.startsWith(basePath) && newPath !== basePath) {
      setPath(basePath);
    } else {
      setPath(newPath);
    }
  };
  const goToSegment = (i: number) => {
    const parts = path.split('/').filter(Boolean);
    const newPath = i < 0 ? '' : parts.slice(0, i + 1).join('/');
    // Don't navigate above rootPath
    if (basePath && !newPath.startsWith(basePath) && newPath !== basePath) {
      setPath(basePath);
    } else {
      setPath(newPath);
    }
  };

  const handleClick = (name: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(name)) next.delete(name); else next.add(name);
        return next;
      });
    } else {
      setSelected(new Set([name]));
    }
  };

  const tryOpenFile = (filePath: string, fileName: string) => {
    if (isTextFile(fileName)) {
      setEditingFile(filePath);
    } else {
      setConfirmOpen(filePath);
    }
  };

  const handleDoubleClick = (entry: FileEntry) => {
    if (entry.type === 'dir') {
      navigate(entry.name);
    } else {
      const filePath = path ? `${path}/${entry.name}` : entry.name;
      tryOpenFile(filePath, entry.name);
    }
  };

  const handleUpload = async (fileList: FileList | File[]) => {
    setLoading(true);
    try {
      await api.uploadFiles(path, fileList);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) handleUpload(e.target.files);
    e.target.value = '';
  };

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await api.createFolder(path, newFolderName.trim());
      setNewFolderName('');
      setShowNewFolder(false);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleDelete = async () => {
    if (selected.size === 0) return;
    setLoading(true);
    try {
      for (const name of selected) {
        await api.deleteFile(path ? `${path}/${name}` : name);
      }
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    setLoading(true);
    try {
      for (const name of selected) {
        const entry = entries.find((e) => e.name === name);
        if (!entry) continue;
        const fullPath = path ? `${path}/${name}` : name;
        if (entry.type === 'dir') await api.downloadFolder(fullPath);
        else await api.downloadFile(fullPath);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;
    const entryList: FileSystemEntry[] = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry?.();
      if (entry) entryList.push(entry);
    }
    if (entryList.length > 0 && entryList.some((en) => en.isDirectory)) {
      setLoading(true);
      setError('');
      try {
        const fileEntries: Array<{ file: File; relativePath: string }> = [];
        await walkEntries(entryList, '', fileEntries);
        if (fileEntries.length > 0) {
          await api.uploadFilesWithPaths(path, fileEntries);
          await refresh();
        }
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    } else if (e.dataTransfer.files.length > 0) {
      handleUpload(e.dataTransfer.files);
    }
  };

  const isDark = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';
  const pathParts = path.split('/').filter(Boolean);
  const showGoUp = basePath ? path !== basePath : path !== '';
  const visibleEntries = showHidden ? entries : entries.filter((e) => !e.name.startsWith('.'));

  // For breadcrumbs: show segments relative to rootPath
  const baseSegments = basePath ? basePath.split('/').filter(Boolean).length : 0;
  const displayParts = pathParts.slice(baseSegments);

  const editableFile = (() => {
    if (selected.size !== 1) return null;
    const name = Array.from(selected)[0];
    const entry = visibleEntries.find((e) => e.name === name);
    if (!entry || entry.type !== 'file') return null;
    return path ? `${path}/${name}` : name;
  })();
  const editableName = selected.size === 1 ? Array.from(selected)[0] : null;

  return (
    <div
      className={`cfb-panel ${dragOver ? 'fb-dropzone-active' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {editingFile ? (
        <FileEditor filePath={editingFile} onClose={() => { setEditingFile(null); refresh(); }} dark={isDark} />
      ) : (
        <>
          <div className="ftv-panel-header">{headerLabel || 'Local Storage'}</div>
          <div className="fb-breadcrumbs">
            <button onClick={() => setPath(basePath)}>{basePath ? 'Root' : 'Storage'}</button>
            {displayParts.map((part, i) => (
              <span key={i}><span className="fb-sep">/</span><button onClick={() => goToSegment(baseSegments + i)}>{part}</button></span>
            ))}
          </div>
          <div className="fb-actions">
            <button onClick={() => setPath(basePath)} title={basePath ? 'Go to artifact root' : 'Go to storage root'}>{'\u2302'}</button>
            <button onClick={() => fileInputRef.current?.click()}>Upload</button>
            <input ref={fileInputRef} type="file" multiple style={{ display: 'none' }} onChange={handleFileInput} />
            {showNewFolder ? (
              <div className="fb-new-folder">
                <input value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()} placeholder="Folder name..." autoFocus />
                <button onClick={handleCreateFolder}>OK</button>
                <button onClick={() => { setShowNewFolder(false); setNewFolderName(''); }}>Cancel</button>
              </div>
            ) : (
              <button onClick={() => setShowNewFolder(true)}>New Folder</button>
            )}
            <button onClick={handleDownload} disabled={selected.size === 0}>Download</button>
            <button onClick={handleDelete} disabled={selected.size === 0}>Delete</button>
            <button onClick={() => editableFile && editableName && tryOpenFile(editableFile, editableName)} disabled={!editableFile}>Edit</button>
            <button
              className={showHidden ? 'fb-toggle-active' : ''}
              onClick={() => setShowHidden((v) => !v)}
              title={showHidden ? 'Hide hidden files' : 'Show hidden files'}
            >
              .hidden
            </button>
            <button onClick={refresh} disabled={loading} title="Refresh">{'\u21BB'}</button>
          </div>
          {error && <div className="fb-error">{error}</div>}
          <div className="fb-table-wrap">
            {loading ? (
              <div className="fb-loading">Loading...</div>
            ) : visibleEntries.length === 0 && !showGoUp ? (
              <div className="fb-empty">Empty directory. Upload files or create a folder.</div>
            ) : (
              <table className="fb-table">
                <thead>
                  <tr>
                    <th style={{ width: 30 }}></th>
                    <th>Name</th>
                    <th style={{ width: 70 }}>Size</th>
                  </tr>
                </thead>
                <tbody>
                  {showGoUp && (
                    <tr className="fb-row" onDoubleClick={goUp}>
                      <td><span className="fb-icon">{'\uD83D\uDCC1'}</span></td>
                      <td className="fb-name">..</td>
                      <td></td>
                    </tr>
                  )}
                  {visibleEntries.map((entry) => (
                    <tr
                      key={entry.name}
                      className={`fb-row ${selected.has(entry.name) ? 'selected' : ''}`}
                      onClick={(e) => handleClick(entry.name, e)}
                      onDoubleClick={() => handleDoubleClick(entry)}
                    >
                      <td><span className="fb-icon">{entry.type === 'dir' ? '\uD83D\uDCC1' : '\uD83D\uDCC4'}</span></td>
                      <td className="fb-name">{entry.name}</td>
                      <td className="fb-size">{entry.type === 'file' ? humanSize(entry.size) : '\u2014'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {confirmOpen && (
        <div className="toolbar-modal-overlay" onClick={() => setConfirmOpen(null)}>
          <div className="toolbar-modal" onClick={(e) => e.stopPropagation()}>
            <h4>Open file as text?</h4>
            <p>
              <strong>{confirmOpen.split('/').pop()}</strong>
              {isLikelyBinary(confirmOpen)
                ? ' appears to be a binary file. Opening it in the text editor may show garbled content.'
                : ' has an unrecognized file type. It may or may not be a text file.'}
            </p>
            <p>Open it anyway?</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
              <button onClick={() => setConfirmOpen(null)}>Cancel</button>
              <button onClick={() => { setEditingFile(confirmOpen); setConfirmOpen(null); }}
                style={{ background: 'var(--fabric-primary, #5798bc)', color: '#fff', border: 'none', borderRadius: 4, padding: '5px 14px', cursor: 'pointer' }}>
                Open
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
