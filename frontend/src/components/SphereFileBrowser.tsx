import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import type { SphereNodeRef } from '../api/client';
import type { FileEntry } from '../types/fabric';
import '../styles/file-transfer.css';

interface SphereFileBrowserProps {
  experiment: string;
  realization: string;
  project?: string;
  xdc: string;
  nodes: string[];
  /** True when an attached+ready XDC and a materialized realization allow access. */
  canAccess: boolean;
  accessHint?: string;
  onError?: (msg: string) => void;
}

function humanSize(b: number): string {
  if (!b) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), u.length - 1);
  const v = b / Math.pow(1024, i);
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

/**
 * SPHERE Storage — a dual-panel file manager mirroring the FABRIC Storage view:
 * Local Storage (LoomAI container) on the left, the experiment node on the right,
 * with transfer arrows. The node side reaches files over the jump → XDC → node
 * SSH chain.
 */
export default function SphereFileBrowser({
  experiment, realization, project, xdc, nodes, canAccess, accessHint, onError,
}: SphereFileBrowserProps) {
  // Left (container) state
  const [leftPath, setLeftPath] = useState('');
  const [leftEntries, setLeftEntries] = useState<FileEntry[]>([]);
  const [leftSel, setLeftSel] = useState<Set<string>>(new Set());
  const [leftLoading, setLeftLoading] = useState(false);
  const leftInput = useRef<HTMLInputElement>(null);
  const [leftNewFolder, setLeftNewFolder] = useState('');
  const [leftShowNF, setLeftShowNF] = useState(false);

  // Right (node) state
  const [node, setNode] = useState(nodes[0] || '');
  const [rightPath, setRightPath] = useState('.');
  const [rightEntries, setRightEntries] = useState<FileEntry[]>([]);
  const [rightSel, setRightSel] = useState<Set<string>>(new Set());
  const [rightLoading, setRightLoading] = useState(false);
  const rightInput = useRef<HTMLInputElement>(null);
  const [rightNewFolder, setRightNewFolder] = useState('');
  const [rightShowNF, setRightShowNF] = useState(false);

  const [busy, setBusy] = useState('');
  const ref: SphereNodeRef = { experiment, realization, node, xdc, project };
  const fail = (m: string) => onError?.(m);

  useEffect(() => { if (!node && nodes.length) setNode(nodes[0]); }, [nodes, node]);

  const loadLeft = useCallback(async (p: string) => {
    setLeftLoading(true);
    try { setLeftEntries(await api.listFiles(p)); setLeftPath(p); setLeftSel(new Set()); }
    catch (e: any) { fail(`Local list failed — ${e?.message || e}`); }
    finally { setLeftLoading(false); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadRight = useCallback(async (p: string) => {
    if (!node || !canAccess) return;
    setRightLoading(true);
    try { setRightEntries(await api.listSphereNodeFiles({ experiment, realization, node, xdc, project }, p)); setRightPath(p); setRightSel(new Set()); }
    catch (e: any) { fail(`Node list failed — ${e?.message || e}`); }
    finally { setRightLoading(false); }
  }, [node, canAccess, experiment, realization, xdc, project]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { loadLeft(''); }, [loadLeft]);
  useEffect(() => { if (node && canAccess) loadRight('.'); }, [node, canAccess]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── helpers ──
  const leftJoin = (n: string) => (leftPath ? `${leftPath}/${n}` : n);
  const rightJoin = (n: string) => (rightPath === '.' ? n : `${rightPath}/${n}`);
  const toggle = (set: Set<string>, setSet: (s: Set<string>) => void, n: string) => {
    const s = new Set(set); s.has(n) ? s.delete(n) : s.add(n); setSet(s);
  };

  // ── left actions ──
  const leftUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy('l'); try { await api.uploadFiles(leftPath, files); await loadLeft(leftPath); }
    catch (e: any) { fail(`Upload failed — ${e?.message || e}`); } finally { setBusy(''); if (leftInput.current) leftInput.current.value = ''; }
  };
  const leftDelete = async () => {
    if (!leftSel.size || (typeof window !== 'undefined' && !window.confirm(`Delete ${leftSel.size} item(s) from local storage?`))) return;
    setBusy('l'); for (const n of leftSel) { try { await api.deleteFile(leftJoin(n)); } catch (e: any) { fail(`Delete failed — ${e?.message || e}`); } }
    setBusy(''); loadLeft(leftPath);
  };
  const leftMkdir = async () => {
    if (!leftNewFolder.trim()) return;
    setBusy('l'); try { await api.createFolder(leftPath, leftNewFolder.trim()); setLeftNewFolder(''); setLeftShowNF(false); await loadLeft(leftPath); }
    catch (e: any) { fail(`New folder failed — ${e?.message || e}`); } finally { setBusy(''); }
  };

  // ── right actions ──
  const rightUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy('r'); try { await api.uploadDirectToSphere(ref, rightPath === '.' ? '' : rightPath, files); await loadRight(rightPath); }
    catch (e: any) { fail(`Node upload failed — ${e?.message || e}`); } finally { setBusy(''); if (rightInput.current) rightInput.current.value = ''; }
  };
  const rightDelete = async () => {
    if (!rightSel.size || (typeof window !== 'undefined' && !window.confirm(`Delete ${rightSel.size} item(s) from ${node}?`))) return;
    setBusy('r'); for (const n of rightSel) { try { await api.sphereNodeDelete(ref, rightJoin(n)); } catch (e: any) { fail(`Delete failed — ${e?.message || e}`); } }
    setBusy(''); loadRight(rightPath);
  };
  const rightMkdir = async () => {
    if (!rightNewFolder.trim()) return;
    setBusy('r'); try { await api.sphereNodeMkdir(ref, rightJoin(rightNewFolder.trim())); setRightNewFolder(''); setRightShowNF(false); await loadRight(rightPath); }
    catch (e: any) { fail(`New folder failed — ${e?.message || e}`); } finally { setBusy(''); }
  };

  // ── transfers ──
  const pushRight = async () => {
    if (!leftSel.size) return;
    setBusy('t');
    for (const n of leftSel) {
      const entry = leftEntries.find(e => e.name === n);
      if (entry?.type === 'dir') { fail(`Skipped folder "${n}" (file transfer only)`); continue; }
      try { const f = await api.fetchContainerFile(leftJoin(n)); await api.uploadDirectToSphere(ref, rightPath === '.' ? '' : rightPath, [f]); }
      catch (e: any) { fail(`Transfer of ${n} failed — ${e?.message || e}`); }
    }
    setBusy(''); loadRight(rightPath);
  };
  const pullLeft = async () => {
    if (!rightSel.size) return;
    setBusy('t');
    for (const n of rightSel) {
      const entry = rightEntries.find(e => e.name === n);
      if (entry?.type === 'dir') { fail(`Skipped folder "${n}" (file transfer only)`); continue; }
      try { const f = await api.fetchSphereNodeFile(ref, rightJoin(n)); await api.uploadFiles(leftPath, [f]); }
      catch (e: any) { fail(`Transfer of ${n} failed — ${e?.message || e}`); }
    }
    setBusy(''); loadLeft(leftPath);
  };

  const Crumbs = ({ parts, onRoot, onSeg, rootLabel }: { parts: string[]; onRoot: () => void; onSeg: (i: number) => void; rootLabel: string }) => (
    <div className="fb-breadcrumbs">
      <button onClick={onRoot}>{rootLabel}</button>
      {parts.map((p, i) => <span key={i}><span className="fb-sep">/</span><button onClick={() => onSeg(i)}>{p}</button></span>)}
    </div>
  );

  const Table = ({ entries, loading, sel, onToggle, onEnter, onUp, canUp }: {
    entries: FileEntry[]; loading: boolean; sel: Set<string>;
    onToggle: (n: string) => void; onEnter: (n: string) => void; onUp: () => void; canUp: boolean;
  }) => (
    <div className="fb-table-wrap">
      {loading ? <div className="fb-loading">Loading…</div> : (
        <table className="fb-table"><tbody>
          {canUp && <tr className="fb-row" onClick={onUp}><td className="fb-icon">📁</td><td className="fb-name">..</td><td className="fb-size" /></tr>}
          {entries.length === 0 && !canUp ? <tr><td colSpan={3}><div className="fb-empty">Empty.</div></td></tr> : null}
          {entries.map(e => (
            <tr key={e.name} className={`fb-row${sel.has(e.name) ? ' selected' : ''}`}
              onClick={() => onToggle(e.name)}
              onDoubleClick={() => e.type === 'dir' && onEnter(e.name)}
              style={sel.has(e.name) ? { background: 'rgba(87,152,188,0.18)' } : undefined}>
              <td className="fb-icon">{e.type === 'dir' ? '📁' : '📄'}</td>
              <td className="fb-name">
                {e.type === 'dir'
                  ? <a role="button" onClick={(ev) => { ev.stopPropagation(); onEnter(e.name); }} style={{ cursor: 'pointer' }}>{e.name}/</a>
                  : e.name}
              </td>
              <td className="fb-size">{e.type === 'dir' ? '' : humanSize(e.size)}</td>
            </tr>
          ))}
        </tbody></table>
      )}
    </div>
  );

  if (!canAccess) {
    return <div style={{ padding: 16, fontSize: 12, opacity: 0.75 }}>{accessHint || 'Attach a ready XDC to a materialized realization to manage node files.'}</div>;
  }

  const leftParts = leftPath.split('/').filter(Boolean);
  const rightParts = rightPath === '.' ? [] : rightPath.split('/').filter(Boolean);

  return (
    <div className="ftv-outer">
      <div className="file-transfer-view">
        {/* LEFT: container */}
        <div className="ftv-panel ftv-left"
          onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); leftUpload(e.dataTransfer?.files); }}>
          <div className="ftv-panel-header">Local Storage</div>
          <Crumbs parts={leftParts} rootLabel="Storage" onRoot={() => loadLeft('')} onSeg={i => loadLeft(leftParts.slice(0, i + 1).join('/'))} />
          <div className="fb-actions">
            <button onClick={() => loadLeft('')} title="Home">⌂</button>
            <button onClick={() => leftInput.current?.click()}>Upload</button>
            <input ref={leftInput} type="file" multiple style={{ display: 'none' }} onChange={e => leftUpload(e.target.files)} />
            {leftShowNF ? (
              <span className="fb-new-folder">
                <input value={leftNewFolder} autoFocus onChange={e => setLeftNewFolder(e.target.value)} onKeyDown={e => e.key === 'Enter' && leftMkdir()} placeholder="Folder…" />
                <button onClick={leftMkdir}>OK</button><button onClick={() => { setLeftShowNF(false); setLeftNewFolder(''); }}>✕</button>
              </span>
            ) : <button onClick={() => setLeftShowNF(true)}>New Folder</button>}
            <button disabled={!leftSel.size} onClick={() => leftSel.forEach(n => { const e = leftEntries.find(x => x.name === n); if (e?.type === 'dir') api.downloadFolder(leftJoin(n)); else api.downloadFile(leftJoin(n)); })}>Download</button>
            <button disabled={!leftSel.size} onClick={leftDelete}>Delete</button>
            <button onClick={() => loadLeft(leftPath)} title="Refresh">↻</button>
          </div>
          <Table entries={leftEntries} loading={leftLoading} sel={leftSel}
            onToggle={n => toggle(leftSel, setLeftSel, n)} onEnter={n => loadLeft(leftJoin(n))}
            onUp={() => loadLeft(leftParts.slice(0, -1).join('/'))} canUp={!!leftPath} />
        </div>

        {/* CENTER */}
        <div className="ftv-center">
          <button className="ftv-arrow-btn" disabled={!leftSel.size || busy === 't'} onClick={pushRight} title="Transfer selected to node →">→</button>
          {busy === 't' && <div className="ftv-progress-text">…</div>}
          <button className="ftv-arrow-btn" disabled={!rightSel.size || busy === 't'} onClick={pullLeft} title="← Transfer selected to local">←</button>
        </div>

        {/* RIGHT: node */}
        <div className="ftv-panel ftv-right"
          onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); rightUpload(e.dataTransfer?.files); }}>
          <div className="ftv-panel-header" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>{node === api.SPHERE_XDC_TARGET ? 'XDC files' : 'Node files'}</span>
            <select className="ftv-node-select" value={node} onChange={e => setNode(e.target.value)} style={{ marginLeft: 'auto' }}>
              {nodes.map(n => <option key={n} value={n}>{n}</option>)}
              {/* The XDC itself — its home is what JupyterLab serves; drop notebooks/scripts here. */}
              <option value={api.SPHERE_XDC_TARGET}>XDC ({xdc})</option>
            </select>
          </div>
          <Crumbs parts={rightParts} rootLabel="~" onRoot={() => loadRight('.')} onSeg={i => loadRight(rightParts.slice(0, i + 1).join('/'))} />
          <div className="fb-actions">
            <button onClick={() => loadRight('.')} title="Home">⌂</button>
            <button onClick={() => rightInput.current?.click()}>Upload</button>
            <input ref={rightInput} type="file" multiple style={{ display: 'none' }} onChange={e => rightUpload(e.target.files)} />
            {rightShowNF ? (
              <span className="fb-new-folder">
                <input value={rightNewFolder} autoFocus onChange={e => setRightNewFolder(e.target.value)} onKeyDown={e => e.key === 'Enter' && rightMkdir()} placeholder="Folder…" />
                <button onClick={rightMkdir}>OK</button><button onClick={() => { setRightShowNF(false); setRightNewFolder(''); }}>✕</button>
              </span>
            ) : <button onClick={() => setRightShowNF(true)}>New Folder</button>}
            <button disabled={!rightSel.size} onClick={() => rightSel.forEach(n => { const e = rightEntries.find(x => x.name === n); if (e?.type === 'dir') api.downloadFolderFromSphere(ref, rightJoin(n)); else api.downloadDirectFromSphere(ref, rightJoin(n)); })}>Download</button>
            <button disabled={!rightSel.size} onClick={rightDelete}>Delete</button>
            <button onClick={() => loadRight(rightPath)} title="Refresh">↻</button>
          </div>
          <Table entries={rightEntries} loading={rightLoading} sel={rightSel}
            onToggle={n => toggle(rightSel, setRightSel, n)} onEnter={n => loadRight(rightJoin(n))}
            onUp={() => loadRight(rightParts.length ? rightParts.slice(0, -1).join('/') || '.' : '.')} canUp={rightPath !== '.'} />
        </div>
      </div>
    </div>
  );
}
