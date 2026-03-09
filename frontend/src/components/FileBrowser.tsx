'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import * as api from '../api/client';
import type { FileEntry, SliceData, SliceNode } from '../types/fabric';
import FileEditor, { isTextFile } from './FileEditor';
import '../styles/file-browser.css';

interface FileBrowserProps {
  mode: 'container' | 'vm';
  sliceName?: string;
  nodeName?: string;
  sliceData?: SliceData | null;
  onProvisionAdded?: () => void;
}

function humanSize(bytes: number): string {
  if (bytes === 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

export default function FileBrowser({ mode, sliceName, nodeName, sliceData, onProvisionAdded }: FileBrowserProps) {
  const [currentPath, setCurrentPath] = useState(mode === 'vm' ? '/home' : '');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [showProvision, setShowProvision] = useState(false);
  const [provNode, setProvNode] = useState('');
  const [provDest, setProvDest] = useState('/home/');
  const [dragOver, setDragOver] = useState(false);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    setSelected(new Set());
    try {
      if (mode === 'container') {
        const data = await api.listFiles(currentPath);
        setEntries(data);
      } else if (sliceName && nodeName) {
        const data = await api.listVmFiles(sliceName, nodeName, currentPath);
        setEntries(data);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [mode, currentPath, sliceName, nodeName]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const navigate = (dir: string) => {
    if (mode === 'vm') {
      setCurrentPath(currentPath === '/' ? `/${dir}` : `${currentPath}/${dir}`);
    } else {
      setCurrentPath(currentPath ? `${currentPath}/${dir}` : dir);
    }
  };

  const goUp = () => {
    if (mode === 'vm') {
      const parts = currentPath.split('/').filter(Boolean);
      parts.pop();
      setCurrentPath(parts.length === 0 ? '/' : `/${parts.join('/')}`);
    } else {
      const parts = currentPath.split('/').filter(Boolean);
      parts.pop();
      setCurrentPath(parts.join('/'));
    }
  };

  const goToSegment = (index: number) => {
    const parts = currentPath.split('/').filter(Boolean);
    if (mode === 'vm') {
      setCurrentPath(index < 0 ? '/' : `/${parts.slice(0, index + 1).join('/')}`);
    } else {
      setCurrentPath(index < 0 ? '' : parts.slice(0, index + 1).join('/'));
    }
  };

  const handleClick = (name: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(name)) next.delete(name);
        else next.add(name);
        return next;
      });
    } else {
      setSelected(new Set([name]));
    }
  };

  const handleDoubleClick = (entry: FileEntry) => {
    if (entry.type === 'dir') {
      navigate(entry.name);
    } else if (mode === 'container' && isTextFile(entry.name)) {
      const fullPath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
      setEditingFile(fullPath);
    }
  };

  // Container mode: upload files
  const handleUpload = async (fileList: FileList | File[]) => {
    if (mode !== 'container') return;
    setLoading(true);
    try {
      await api.uploadFiles(currentPath, fileList);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleUpload(e.target.files);
    }
    e.target.value = '';
  };

  // Drag-and-drop (container mode only)
  const handleDragOver = (e: React.DragEvent) => {
    if (mode !== 'container') return;
    e.preventDefault();
    setDragOver(true);
  };
  const handleDragLeave = () => setDragOver(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (mode !== 'container') return;
    if (e.dataTransfer.files.length > 0) {
      handleUpload(e.dataTransfer.files);
    }
  };

  // Create folder
  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await api.createFolder(currentPath, newFolderName.trim());
      setNewFolderName('');
      setShowNewFolder(false);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Download
  const handleDownload = async () => {
    if (selected.size === 0) return;
    setLoading(true);
    try {
      for (const name of selected) {
        const entry = entries.find((e) => e.name === name);
        if (!entry) continue;
        const fullPath = currentPath ? `${currentPath}/${name}` : name;
        if (mode === 'container') {
          if (entry.type === 'dir') {
            await api.downloadFolder(fullPath);
          } else {
            await api.downloadFile(fullPath);
          }
        }
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // Download VM file to container
  const handleDownloadToContainer = async () => {
    if (mode !== 'vm' || !sliceName || !nodeName || selected.size === 0) return;
    setLoading(true);
    try {
      for (const name of selected) {
        const entry = entries.find((e) => e.name === name);
        if (!entry || entry.type === 'dir') continue;
        const remotePath = currentPath === '/' ? `/${name}` : `${currentPath}/${name}`;
        await api.downloadVmFile(sliceName, nodeName, remotePath, '');
      }
      setError('');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // Delete
  const handleDelete = async () => {
    if (mode !== 'container' || selected.size === 0) return;
    setLoading(true);
    try {
      for (const name of selected) {
        const fullPath = currentPath ? `${currentPath}/${name}` : name;
        await api.deleteFile(fullPath);
      }
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // Provision dialog
  const handleProvisionSubmit = async () => {
    if (!provNode || !provDest) return;
    const selectedFiles = Array.from(selected);
    if (selectedFiles.length === 0) return;
    try {
      for (const name of selectedFiles) {
        const entry = entries.find((e) => e.name === name);
        if (!entry || entry.type === 'dir') continue;
        const source = currentPath ? `${currentPath}/${name}` : name;
        const dest = provDest.endsWith('/') ? `${provDest}${name}` : provDest;
        await api.addProvision({
          source,
          slice_name: sliceName || '',
          node_name: provNode,
          dest,
        });
      }
      setShowProvision(false);
      onProvisionAdded?.();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Build breadcrumb segments
  const pathParts = currentPath.split('/').filter(Boolean);
  const nodes: SliceNode[] = sliceData?.nodes ?? [];

  const visibleEntries = showHidden ? entries : entries.filter((e) => !e.name.startsWith('.'));

  const hasSelectedFiles = Array.from(selected).some((name) => {
    const entry = visibleEntries.find((e) => e.name === name);
    return entry && entry.type === 'file';
  });

  const isDark = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';

  if (editingFile) {
    return (
      <div className="file-browser" style={{ position: 'relative' }}>
        <FileEditor
          filePath={editingFile}
          onClose={() => { setEditingFile(null); refresh(); }}
          dark={isDark}
        />
      </div>
    );
  }

  return (
    <div
      className={`file-browser ${dragOver ? 'fb-dropzone-active' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{ position: 'relative' }}
    >
      {/* Breadcrumbs */}
      <div className="fb-breadcrumbs">
        <button onClick={() => goToSegment(-1)}>
          {mode === 'vm' ? '/' : 'Storage'}
        </button>
        {pathParts.map((part, i) => (
          <span key={i}>
            <span className="fb-sep">/</span>
            <button onClick={() => goToSegment(i)}>{part}</button>
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="fb-actions">
        {mode === 'container' && (
          <>
            <button onClick={() => fileInputRef.current?.click()}>Upload</button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              style={{ display: 'none' }}
              onChange={handleFileInput}
            />
            {showNewFolder ? (
              <div className="fb-new-folder">
                <input
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
                  placeholder="Folder name..."
                  autoFocus
                />
                <button onClick={handleCreateFolder}>OK</button>
                <button onClick={() => { setShowNewFolder(false); setNewFolderName(''); }}>Cancel</button>
              </div>
            ) : (
              <button onClick={() => setShowNewFolder(true)}>New Folder</button>
            )}
          </>
        )}
        {mode === 'container' && (
          <button onClick={handleDownload} disabled={selected.size === 0}>Download</button>
        )}
        {mode === 'container' && (
          <button onClick={handleDelete} disabled={selected.size === 0}>Delete</button>
        )}
        {mode === 'container' && sliceName && hasSelectedFiles && (
          <button className="primary" onClick={() => { setShowProvision(true); setProvNode(nodes[0]?.name ?? ''); }}>
            Provision to VM
          </button>
        )}
        {mode === 'vm' && (
          <button className="primary" onClick={handleDownloadToContainer} disabled={!hasSelectedFiles}>
            Download to Local
          </button>
        )}
        <button
          className={showHidden ? 'fb-toggle-active' : ''}
          onClick={() => setShowHidden((v) => !v)}
          title={showHidden ? 'Hide hidden files' : 'Show hidden files'}
        >
          .hidden
        </button>
        <button onClick={refresh} disabled={loading} title="Refresh">↻</button>
      </div>

      {error && <div className="fb-error">{error}</div>}

      {/* File table */}
      <div className="fb-table-wrap">
        {loading ? (
          <div className="fb-loading">Loading...</div>
        ) : visibleEntries.length === 0 ? (
          <div className="fb-empty">
            {mode === 'container' ? 'Empty directory. Upload files or create a folder.' : 'Empty directory.'}
          </div>
        ) : (
          <table className="fb-table">
            <thead>
              <tr>
                <th style={{ width: 30 }}></th>
                <th>Name</th>
                <th style={{ width: 80 }}>Size</th>
                <th style={{ width: 150 }}>Modified</th>
              </tr>
            </thead>
            <tbody>
              {(currentPath !== '' && (mode !== 'vm' || currentPath !== '/')) && (
                <tr className="fb-row" onDoubleClick={goUp}>
                  <td><span className="fb-icon">📁</span></td>
                  <td className="fb-name">..</td>
                  <td></td>
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
                  <td><span className="fb-icon">{entry.type === 'dir' ? '📁' : '📄'}</span></td>
                  <td className="fb-name">{entry.name}</td>
                  <td className="fb-size">{entry.type === 'file' ? humanSize(entry.size) : '—'}</td>
                  <td className="fb-modified">{entry.modified ? new Date(entry.modified).toLocaleString() : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Provision dialog */}
      {showProvision && (
        <div className="fb-provision-dialog">
          <h4>Provision to VM</h4>
          <label>Target Node</label>
          <select value={provNode} onChange={(e) => setProvNode(e.target.value)}>
            {nodes.map((n) => (
              <option key={n.name} value={n.name}>{n.name} ({n.site})</option>
            ))}
          </select>
          <label>Destination Path</label>
          <input
            value={provDest}
            onChange={(e) => setProvDest(e.target.value)}
            placeholder="/home/ubuntu/"
          />
          <div className="btn-row">
            <button onClick={() => setShowProvision(false)}>Cancel</button>
            <button className="primary" onClick={handleProvisionSubmit}>Add Provision</button>
          </div>
        </div>
      )}
    </div>
  );
}
