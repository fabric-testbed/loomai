'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import * as api from '../api/client';
import type { FileEntry, SliceData } from '../types/fabric';
import FileEditor, { isTextFile, isLikelyBinary } from './FileEditor';
import '../styles/file-browser.css';
import '../styles/file-transfer.css';

/** Recursively walk FileSystemEntry trees from drag-and-drop, collecting all files with relative paths. */
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
            if (batch.length === 0) {
              resolve(all);
            } else {
              all.push(...batch);
              readBatch();
            }
          }, reject);
        };
        readBatch();
      });
      const childBase = basePath ? `${basePath}/${entry.name}` : entry.name;
      await walkEntries(children, childBase, result);
    }
  }
}

interface FileTransferViewProps {
  sliceName: string;
  sliceData: SliceData | null;
}

function humanSize(bytes: number): string {
  if (bytes === 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

export default function FileTransferView({ sliceName, sliceData }: FileTransferViewProps) {
  // Left panel state (container)
  const [leftPath, setLeftPath] = useState('');
  const [leftEntries, setLeftEntries] = useState<FileEntry[]>([]);
  const [leftSelected, setLeftSelected] = useState<Set<string>>(new Set());
  const [leftLoading, setLeftLoading] = useState(false);
  const [leftError, setLeftError] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const leftFileInputRef = useRef<HTMLInputElement>(null);

  // Right panel state (VM)
  const [vmNode, setVmNode] = useState('');
  const [rightPath, setRightPath] = useState('/home');
  const [rightEntries, setRightEntries] = useState<FileEntry[]>([]);
  const [rightSelected, setRightSelected] = useState<Set<string>>(new Set());
  const [rightLoading, setRightLoading] = useState(false);
  const [rightError, setRightError] = useState('');
  const [rightDragOver, setRightDragOver] = useState(false);
  const [showVmNewFolder, setShowVmNewFolder] = useState(false);
  const [vmNewFolderName, setVmNewFolderName] = useState('');
  const [editingVmFile, setEditingVmFile] = useState<string | null>(null);
  const rightFileInputRef = useRef<HTMLInputElement>(null);

  // Remember per-node paths so switching nodes preserves where you were
  const vmPathsRef = useRef<Record<string, string>>({});

  // Confirm-open prompt for unknown file types
  const [confirmOpen, setConfirmOpen] = useState<{ path: string; side: 'left' | 'right' } | null>(null);

  // Transfer state
  const [transferring, setTransferring] = useState(false);
  const [transferDir, setTransferDir] = useState<'right' | 'left' | null>(null);
  const [transferCurrent, setTransferCurrent] = useState(0);
  const [transferTotal, setTransferTotal] = useState(0);
  const [transferError, setTransferError] = useState('');

  const nodes = sliceData?.nodes ?? [];
  const nodeNames = nodes.map((n) => n.name);

  /** Get the home directory for a node based on its username. */
  const getHomeDir = useCallback((nodeName: string) => {
    const node = nodes.find((n) => n.name === nodeName);
    const username = node?.username || 'ubuntu';
    return `/home/${username}`;
  }, [nodes]);

  // Auto-select first node and set its home dir
  useEffect(() => {
    if (!vmNode && nodeNames.length > 0) {
      const first = nodeNames[0];
      setVmNode(first);
      const home = getHomeDir(first);
      setRightPath(vmPathsRef.current[first] || home);
    }
  }, [nodeNames, vmNode, getHomeDir]);

  // Save the current path whenever it changes so we can restore it
  useEffect(() => {
    if (vmNode) {
      vmPathsRef.current[vmNode] = rightPath;
    }
  }, [vmNode, rightPath]);

  // Refresh left (container)
  const refreshLeft = useCallback(async () => {
    setLeftLoading(true);
    setLeftError('');
    setLeftSelected(new Set());
    try {
      const data = await api.listFiles(leftPath);
      setLeftEntries(data);
    } catch (e: any) {
      setLeftError(e.message);
    } finally {
      setLeftLoading(false);
    }
  }, [leftPath]);

  useEffect(() => { refreshLeft(); }, [refreshLeft]);

  // Refresh right (VM)
  const refreshRight = useCallback(async () => {
    if (!sliceName || !vmNode) {
      setRightEntries([]);
      return;
    }
    setRightLoading(true);
    setRightError('');
    setRightSelected(new Set());
    try {
      const data = await api.listVmFiles(sliceName, vmNode, rightPath);
      setRightEntries(data);
    } catch (e: any) {
      setRightError(e.message);
    } finally {
      setRightLoading(false);
    }
  }, [sliceName, vmNode, rightPath]);

  useEffect(() => { refreshRight(); }, [refreshRight]);

  // --- Left panel handlers ---
  const leftNavigate = (dir: string) => setLeftPath(leftPath ? `${leftPath}/${dir}` : dir);
  const leftGoUp = () => {
    const parts = leftPath.split('/').filter(Boolean);
    parts.pop();
    setLeftPath(parts.join('/'));
  };
  const leftGoToSegment = (i: number) => {
    const parts = leftPath.split('/').filter(Boolean);
    setLeftPath(i < 0 ? '' : parts.slice(0, i + 1).join('/'));
  };
  const leftHandleClick = (name: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setLeftSelected((prev) => {
        const next = new Set(prev);
        if (next.has(name)) next.delete(name); else next.add(name);
        return next;
      });
    } else {
      setLeftSelected(new Set([name]));
    }
  };
  /** Try to open a file for editing. Known text files open directly; unknown files prompt. */
  const tryOpenFile = (filePath: string, fileName: string, side: 'left' | 'right') => {
    if (isTextFile(fileName)) {
      if (side === 'left') setEditingFile(filePath);
      else setEditingVmFile(filePath);
    } else {
      setConfirmOpen({ path: filePath, side });
    }
  };

  const leftHandleDoubleClick = (entry: FileEntry) => {
    if (entry.type === 'dir') {
      leftNavigate(entry.name);
    } else {
      const filePath = leftPath ? `${leftPath}/${entry.name}` : entry.name;
      tryOpenFile(filePath, entry.name, 'left');
    }
  };
  const handleUpload = async (fileList: FileList | File[]) => {
    setLeftLoading(true);
    try {
      await api.uploadFiles(leftPath, fileList);
      await refreshLeft();
    } catch (e: any) {
      setLeftError(e.message);
    } finally {
      setLeftLoading(false);
    }
  };
  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) handleUpload(e.target.files);
    e.target.value = '';
  };
  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await api.createFolder(leftPath, newFolderName.trim());
      setNewFolderName('');
      setShowNewFolder(false);
      await refreshLeft();
    } catch (e: any) {
      setLeftError(e.message);
    }
  };
  const handleDeleteLeft = async () => {
    if (leftSelected.size === 0) return;
    setLeftLoading(true);
    try {
      for (const name of leftSelected) {
        const fullPath = leftPath ? `${leftPath}/${name}` : name;
        await api.deleteFile(fullPath);
      }
      await refreshLeft();
    } catch (e: any) {
      setLeftError(e.message);
    } finally {
      setLeftLoading(false);
    }
  };
  const handleDownloadLeft = async () => {
    setLeftLoading(true);
    try {
      for (const name of leftSelected) {
        const entry = leftEntries.find((e) => e.name === name);
        if (!entry) continue;
        const fullPath = leftPath ? `${leftPath}/${name}` : name;
        if (entry.type === 'dir') await api.downloadFolder(fullPath);
        else await api.downloadFile(fullPath);
      }
    } catch (e: any) {
      setLeftError(e.message);
    } finally {
      setLeftLoading(false);
    }
  };

  // --- Right panel handlers ---
  const rightNavigate = (dir: string) => setRightPath(rightPath === '/' ? `/${dir}` : `${rightPath}/${dir}`);
  const rightGoUp = () => {
    const parts = rightPath.split('/').filter(Boolean);
    parts.pop();
    setRightPath(parts.length === 0 ? '/' : `/${parts.join('/')}`);
  };
  const rightGoToSegment = (i: number) => {
    const parts = rightPath.split('/').filter(Boolean);
    setRightPath(i < 0 ? '/' : `/${parts.slice(0, i + 1).join('/')}`);
  };
  const rightHandleClick = (name: string, e: React.MouseEvent) => {
    if (e.ctrlKey || e.metaKey) {
      setRightSelected((prev) => {
        const next = new Set(prev);
        if (next.has(name)) next.delete(name); else next.add(name);
        return next;
      });
    } else {
      setRightSelected(new Set([name]));
    }
  };
  const rightHandleDoubleClick = (entry: FileEntry) => {
    if (entry.type === 'dir') {
      rightNavigate(entry.name);
    } else {
      const fullPath = rightPath === '/' ? `/${entry.name}` : `${rightPath}/${entry.name}`;
      tryOpenFile(fullPath, entry.name, 'right');
    }
  };

  // --- Right panel: drag/drop to VM ---
  const handleRightDragOver = (e: React.DragEvent) => { e.preventDefault(); setRightDragOver(true); };
  const handleRightDragLeave = () => setRightDragOver(false);

  const handleDropRight = async (e: React.DragEvent) => {
    e.preventDefault();
    setRightDragOver(false);
    if (!sliceName || !vmNode) return;

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    // Try webkitGetAsEntry for folder support
    const entryList: FileSystemEntry[] = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry?.();
      if (entry) entryList.push(entry);
    }

    setRightLoading(true);
    setRightError('');
    try {
      if (entryList.length > 0 && entryList.some((en) => en.isDirectory)) {
        // Has directories — walk the tree and upload with paths
        const fileEntries: Array<{ file: File; relativePath: string }> = [];
        await walkEntries(entryList, '', fileEntries);
        if (fileEntries.length > 0) {
          await api.uploadDirectToVmWithPaths(sliceName, vmNode, rightPath, fileEntries);
          await refreshRight();
        }
      } else if (e.dataTransfer.files.length > 0) {
        // Plain files
        await api.uploadDirectToVm(sliceName, vmNode, rightPath, e.dataTransfer.files);
        await refreshRight();
      }
    } catch (err: any) {
      setRightError(err.message);
    } finally {
      setRightLoading(false);
    }
  };

  // --- Right panel: download from VM to desktop (files + folders) ---
  const handleDownloadRight = async () => {
    if (!sliceName || !vmNode || rightSelected.size === 0) return;
    setRightLoading(true);
    setRightError('');
    try {
      for (const name of rightSelected) {
        const entry = rightEntries.find((e) => e.name === name);
        if (!entry) continue;
        const remotePath = rightPath === '/' ? `/${name}` : `${rightPath}/${name}`;
        if (entry.type === 'dir') {
          await api.downloadFolderFromVm(sliceName, vmNode, remotePath);
        } else {
          await api.downloadDirectFromVm(sliceName, vmNode, remotePath);
        }
      }
    } catch (err: any) {
      setRightError(err.message);
    } finally {
      setRightLoading(false);
    }
  };

  // --- Right panel: upload from desktop to VM ---
  const handleVmUpload = async (fileList: FileList | File[]) => {
    if (!sliceName || !vmNode) return;
    setRightLoading(true);
    setRightError('');
    try {
      await api.uploadDirectToVm(sliceName, vmNode, rightPath, fileList);
      await refreshRight();
    } catch (err: any) {
      setRightError(err.message);
    } finally {
      setRightLoading(false);
    }
  };
  const handleVmFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) handleVmUpload(e.target.files);
    e.target.value = '';
  };

  // --- Right panel: new folder on VM ---
  const handleVmCreateFolder = async () => {
    if (!sliceName || !vmNode || !vmNewFolderName.trim()) return;
    setRightError('');
    try {
      const newPath = rightPath === '/' ? `/${vmNewFolderName.trim()}` : `${rightPath}/${vmNewFolderName.trim()}`;
      await api.vmMkdir(sliceName, vmNode, newPath);
      setVmNewFolderName('');
      setShowVmNewFolder(false);
      await refreshRight();
    } catch (err: any) {
      setRightError(err.message);
    }
  };

  // --- Right panel: delete on VM ---
  const handleDeleteRight = async () => {
    if (!sliceName || !vmNode || rightSelected.size === 0) return;
    setRightLoading(true);
    setRightError('');
    try {
      for (const name of rightSelected) {
        const remotePath = rightPath === '/' ? `/${name}` : `${rightPath}/${name}`;
        await api.vmDelete(sliceName, vmNode, remotePath);
      }
      await refreshRight();
    } catch (err: any) {
      setRightError(err.message);
    } finally {
      setRightLoading(false);
    }
  };

  // --- Transfer: Container → VM ---
  const handleTransferRight = async () => {
    if (!sliceName || !vmNode || leftSelected.size === 0) return;
    const items = Array.from(leftSelected);
    setTransferring(true);
    setTransferDir('right');
    setTransferCurrent(0);
    setTransferTotal(items.length);
    setTransferError('');
    try {
      for (let i = 0; i < items.length; i++) {
        const name = items[i];
        const source = leftPath ? `${leftPath}/${name}` : name;
        const dest = rightPath === '/' ? `/${name}` : `${rightPath}/${name}`;
        await api.uploadToVm(sliceName, vmNode, source, dest);
        setTransferCurrent(i + 1);
      }
      await refreshRight();
    } catch (e: any) {
      setTransferError(e.message);
    } finally {
      setTransferring(false);
    }
  };

  // --- Transfer: VM → Container ---
  const handleTransferLeft = async () => {
    if (!sliceName || !vmNode || rightSelected.size === 0) return;
    const items = Array.from(rightSelected);
    setTransferring(true);
    setTransferDir('left');
    setTransferCurrent(0);
    setTransferTotal(items.length);
    setTransferError('');
    try {
      for (let i = 0; i < items.length; i++) {
        const name = items[i];
        const remotePath = rightPath === '/' ? `/${name}` : `${rightPath}/${name}`;
        await api.downloadVmFile(sliceName, vmNode, remotePath, leftPath);
        setTransferCurrent(i + 1);
      }
      await refreshLeft();
    } catch (e: any) {
      setTransferError(e.message);
    } finally {
      setTransferring(false);
    }
  };

  // Drag and drop (supports folders via webkitGetAsEntry)
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true); };
  const handleDragLeave = () => setDragOver(false);

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    // Try webkitGetAsEntry for folder support
    const entryList: FileSystemEntry[] = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry?.();
      if (entry) entryList.push(entry);
    }

    if (entryList.length > 0 && entryList.some((e) => e.isDirectory)) {
      // Has directories — walk the tree
      setLeftLoading(true);
      setLeftError('');
      try {
        const fileEntries: Array<{ file: File; relativePath: string }> = [];
        await walkEntries(entryList, '', fileEntries);
        if (fileEntries.length > 0) {
          await api.uploadFilesWithPaths(leftPath, fileEntries);
          await refreshLeft();
        }
      } catch (err: any) {
        setLeftError(err.message);
      } finally {
        setLeftLoading(false);
      }
    } else if (e.dataTransfer.files.length > 0) {
      // Plain files only
      handleUpload(e.dataTransfer.files);
    }
  };

  const isDark = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';

  const leftPathParts = leftPath.split('/').filter(Boolean);
  const rightPathParts = rightPath.split('/').filter(Boolean);

  const leftHasSelection = leftSelected.size > 0;
  const rightHasSelection = rightSelected.size > 0;

  // Check if exactly one file is selected (for Edit buttons — any file, not just known text)
  const leftEditableFile = (() => {
    if (leftSelected.size !== 1) return null;
    const name = Array.from(leftSelected)[0];
    const entry = leftEntries.find((e) => e.name === name);
    if (!entry || entry.type !== 'file') return null;
    return leftPath ? `${leftPath}/${name}` : name;
  })();
  const leftEditableName = leftSelected.size === 1 ? Array.from(leftSelected)[0] : null;
  const rightEditableFile = (() => {
    if (rightSelected.size !== 1) return null;
    const name = Array.from(rightSelected)[0];
    const entry = rightEntries.find((e) => e.name === name);
    if (!entry || entry.type !== 'file') return null;
    return rightPath === '/' ? `/${name}` : `${rightPath}/${name}`;
  })();
  const rightEditableName = rightSelected.size === 1 ? Array.from(rightSelected)[0] : null;

  return (
    <div className="ftv-outer">
    <div className="file-transfer-view">
      {/* ============ LEFT PANEL: Container ============ */}
      <div className={`ftv-panel ftv-left ${dragOver ? 'fb-dropzone-active' : ''}`}
        onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
      >
        {editingFile ? (
          <FileEditor filePath={editingFile} onClose={() => { setEditingFile(null); refreshLeft(); }} dark={isDark} />
        ) : (
          <>
            <div className="ftv-panel-header">Local Storage</div>
            <div className="fb-breadcrumbs">
              <button onClick={() => leftGoToSegment(-1)}>Storage</button>
              {leftPathParts.map((part, i) => (
                <span key={i}><span className="fb-sep">/</span><button onClick={() => leftGoToSegment(i)}>{part}</button></span>
              ))}
            </div>
            <div className="fb-actions">
              <button onClick={() => setLeftPath('')} title="Go to storage root">⌂</button>
              <button onClick={() => leftFileInputRef.current?.click()}>Upload</button>
              <input ref={leftFileInputRef} type="file" multiple style={{ display: 'none' }} onChange={handleFileInput} />
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
              <button onClick={handleDownloadLeft} disabled={leftSelected.size === 0}>Download</button>
              <button onClick={handleDeleteLeft} disabled={leftSelected.size === 0}>Delete</button>
              <button onClick={() => leftEditableFile && leftEditableName && tryOpenFile(leftEditableFile, leftEditableName, 'left')} disabled={!leftEditableFile}>Edit</button>
              <button onClick={refreshLeft} disabled={leftLoading} title="Refresh">↻</button>
            </div>
            {leftError && <div className="fb-error">{leftError}</div>}
            <FileTable
              entries={leftEntries}
              selected={leftSelected}
              loading={leftLoading}
              currentPath={leftPath}
              mode="container"
              onGoUp={leftGoUp}
              onClick={leftHandleClick}
              onDoubleClick={leftHandleDoubleClick}
              emptyMessage="Empty directory. Upload files or create a folder."
            />
          </>
        )}
      </div>

      {/* ============ CENTER: Transfer Controls ============ */}
      <div className="ftv-center">
        <button
          className="ftv-arrow-btn"
          onClick={handleTransferRight}
          disabled={!leftHasSelection || !vmNode || transferring}
          title="Transfer selected to VM →"
        >
          →
        </button>

        {transferring && (
          <div className="ftv-progress">
            <div className="ftv-progress-label">
              {transferDir === 'right' ? '→ VM' : '← Local'}
            </div>
            <div className="ftv-progress-bar">
              <div
                className="ftv-progress-fill"
                style={{ width: `${transferTotal > 0 ? (transferCurrent / transferTotal) * 100 : 0}%` }}
              />
            </div>
            <div className="ftv-progress-text">{transferCurrent}/{transferTotal}</div>
          </div>
        )}

        {transferError && (
          <div className="ftv-transfer-error" title={transferError}>Error</div>
        )}

        <button
          className="ftv-arrow-btn"
          onClick={handleTransferLeft}
          disabled={!rightHasSelection || !vmNode || transferring}
          title="← Transfer selected to Local"
        >
          ←
        </button>
      </div>

      {/* ============ RIGHT PANEL: VM ============ */}
      <div
        className={`ftv-panel ftv-right ${rightDragOver ? 'fb-dropzone-active' : ''}`}
        onDragOver={handleRightDragOver}
        onDragLeave={handleRightDragLeave}
        onDrop={handleDropRight}
      >
        {editingVmFile && vmNode ? (
          <FileEditor
            filePath={editingVmFile}
            vmContext={{ sliceName, nodeName: vmNode }}
            onClose={() => { setEditingVmFile(null); refreshRight(); }}
            dark={isDark}
          />
        ) : (
          <>
            <div className="ftv-panel-header">
              <span>VM Files</span>
              <select
                className="ftv-node-select"
                value={vmNode}
                onChange={(e) => {
                  const n = e.target.value;
                  setVmNode(n);
                  setRightPath(vmPathsRef.current[n] || getHomeDir(n));
                  setRightSelected(new Set());
                }}
              >
                {nodeNames.length === 0 && <option value="">No nodes</option>}
                {nodeNames.map((n) => {
                  const node = sliceData?.nodes.find((nd) => nd.name === n);
                  return <option key={n} value={n}>{n}{node?.site ? ` (${node.site})` : ''}</option>;
                })}
              </select>
            </div>
            <div className="fb-breadcrumbs">
              <button onClick={() => rightGoToSegment(-1)}>/</button>
              {rightPathParts.map((part, i) => (
                <span key={i}><span className="fb-sep">/</span><button onClick={() => rightGoToSegment(i)}>{part}</button></span>
              ))}
            </div>
            <div className="fb-actions">
              <button onClick={() => setRightPath(getHomeDir(vmNode))} disabled={!vmNode} title="Go to home directory">⌂</button>
              <button onClick={() => rightFileInputRef.current?.click()} disabled={!vmNode}>Upload</button>
              <input ref={rightFileInputRef} type="file" multiple style={{ display: 'none' }} onChange={handleVmFileInput} />
              {showVmNewFolder ? (
                <div className="fb-new-folder">
                  <input value={vmNewFolderName} onChange={(e) => setVmNewFolderName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleVmCreateFolder()} placeholder="Folder name..." autoFocus />
                  <button onClick={handleVmCreateFolder}>OK</button>
                  <button onClick={() => { setShowVmNewFolder(false); setVmNewFolderName(''); }}>Cancel</button>
                </div>
              ) : (
                <button onClick={() => setShowVmNewFolder(true)} disabled={!vmNode}>New Folder</button>
              )}
              <button onClick={handleDownloadRight} disabled={rightSelected.size === 0 || rightLoading || !vmNode}>Download</button>
              <button onClick={handleDeleteRight} disabled={rightSelected.size === 0 || rightLoading || !vmNode}>Delete</button>
              <button onClick={() => rightEditableFile && rightEditableName && tryOpenFile(rightEditableFile, rightEditableName, 'right')} disabled={!rightEditableFile}>Edit</button>
              <button onClick={refreshRight} disabled={rightLoading || !vmNode} title="Refresh">↻</button>
            </div>
            {rightError && <div className="fb-error">{rightError}</div>}
            {!vmNode ? (
              <div className="fb-empty">Select a node to browse VM files.</div>
            ) : (
              <FileTable
                entries={rightEntries}
                selected={rightSelected}
                loading={rightLoading}
                currentPath={rightPath}
                mode="vm"
                onGoUp={rightGoUp}
                onClick={rightHandleClick}
                onDoubleClick={rightHandleDoubleClick}
                emptyMessage="Empty directory. Drag and drop files here to upload."
              />
            )}
          </>
        )}
      </div>
    </div>


    {/* Confirm-open dialog for unknown file types */}
    {confirmOpen && (
      <div className="toolbar-modal-overlay" onClick={() => setConfirmOpen(null)}>
        <div className="toolbar-modal" onClick={(e) => e.stopPropagation()}>
          <h4>Open file as text?</h4>
          <p>
            <strong>{confirmOpen.path.split('/').pop()}</strong>
            {isLikelyBinary(confirmOpen.path)
              ? ' appears to be a binary file. Opening it in the text editor may show garbled content.'
              : ' has an unrecognized file type. It may or may not be a text file.'}
          </p>
          <p>Open it anyway?</p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
            <button onClick={() => setConfirmOpen(null)}>Cancel</button>
            <button onClick={() => {
              if (confirmOpen.side === 'left') setEditingFile(confirmOpen.path);
              else setEditingVmFile(confirmOpen.path);
              setConfirmOpen(null);
            }} style={{ background: 'var(--fabric-primary, #5798bc)', color: '#fff', border: 'none', borderRadius: 4, padding: '5px 14px', cursor: 'pointer' }}>
              Open
            </button>
          </div>
        </div>
      </div>
    )}
    </div>
  );
}


// --- Shared file table component ---
function FileTable({
  entries, selected, loading, currentPath, mode, onGoUp, onClick, onDoubleClick, emptyMessage,
}: {
  entries: FileEntry[];
  selected: Set<string>;
  loading: boolean;
  currentPath: string;
  mode: 'container' | 'vm';
  onGoUp: () => void;
  onClick: (name: string, e: React.MouseEvent) => void;
  onDoubleClick: (entry: FileEntry) => void;
  emptyMessage: string;
}) {
  const showGoUp = currentPath !== '' && (mode !== 'vm' || currentPath !== '/');

  return (
    <div className="fb-table-wrap">
      {loading ? (
        <div className="fb-loading">Loading...</div>
      ) : entries.length === 0 && !showGoUp ? (
        <div className="fb-empty">{emptyMessage}</div>
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
              <tr className="fb-row" onDoubleClick={onGoUp}>
                <td><span className="fb-icon">📁</span></td>
                <td className="fb-name">..</td>
                <td></td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr
                key={entry.name}
                className={`fb-row ${selected.has(entry.name) ? 'selected' : ''}`}
                onClick={(e) => onClick(entry.name, e)}
                onDoubleClick={() => onDoubleClick(entry)}
              >
                <td><span className="fb-icon">{entry.type === 'dir' ? '📁' : '📄'}</span></td>
                <td className="fb-name">{entry.name}</td>
                <td className="fb-size">{entry.type === 'file' ? humanSize(entry.size) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

