import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import * as api from '../api/client';

interface SphereSelection { experiment: string; realization: string }

interface SphereEditorPanelProps {
  selected: SphereSelection | null;
  project: string;
  matStatus?: string;
  /** Data of the topology/resource element currently clicked (a SPHERE node). */
  selectedElement: Record<string, any> | null;
  onCollapse: () => void;
  dragHandleProps?: Record<string, unknown>;
  panelIcon?: ReactNode;
  /** Refresh the main SPHERE view (realizations list) after a change. */
  onChanged?: () => void;
  /** Focus a realization in the main view (e.g. after Realize). */
  onSelectRealization?: (sel: SphereSelection) => void;
  onError?: (msg: string) => void;
  /** XDCs (with readiness), owned by App; managed here. */
  xdcs?: import('../types/sphere').SphereXdc[];
  selectedXdc?: string;
  onSelectXdc?: (bareName: string) => void;
  onXdcsChanged?: () => void;
}

const bareXdc = (name: string) => (name || '').split('.', 1)[0];

interface TopoNode { name: string; facility?: string }
interface TopoLink { id: number; members: string[]; addrs: Record<string, string> }

const EXP_RE = /^[a-z][a-z0-9]{0,62}$/;
const DEFAULT_NODES: TopoNode[] = [{ name: 'a' }, { name: 'b' }];
const DEFAULT_LINKS: TopoLink[] = [{ id: 1, members: ['a', 'b'], addrs: { a: '10.0.0.1/24', b: '10.0.0.2/24' } }];

/** Sanitise a node name into a Python identifier for the generated model. */
function ident(name: string): string {
  let s = (name || '').replace(/[^a-zA-Z0-9_]/g, '_');
  if (/^[0-9]/.test(s)) s = '_' + s;
  return s || 'n';
}

/** Generate a mergexp model from a node/link topology — the same shape as the
 *  canonical MergeTB "hello world" model, including facility pins. */
function genMergexp(expName: string, nodes: TopoNode[], links: TopoLink[]): string {
  const names = nodes.map(n => n.name);
  const lines: string[] = ['from mergexp import *', ''];
  lines.push(`net = Network('${expName || 'experiment'}')`);
  for (const n of nodes) {
    const fac = (n.facility || '').trim();
    lines.push(fac
      ? `${ident(n.name)} = net.node('${n.name}', facility == '${fac}')`
      : `${ident(n.name)} = net.node('${n.name}')`);
  }
  links.forEach((lk, i) => {
    const members = lk.members.filter(m => names.includes(m));
    if (members.length < 2) return;
    const v = `link${i}`;
    lines.push(`${v} = net.connect([${members.map(ident).join(', ')}])`);
    members.forEach(m => {
      const addr = lk.addrs[m];
      if (addr) lines.push(`${v}[${ident(m)}].socket.addrs = ip4('${addr}')`);
    });
  });
  lines.push('', 'experiment(net)', '');
  return lines.join('\n');
}

type BuilderTab = 'experiment' | 'topology' | 'model' | 'realize' | 'xdc' | 'materialize' | 'package';
const TABS: { key: BuilderTab; label: string }[] = [
  { key: 'experiment', label: 'Experiment' },
  { key: 'topology', label: 'Topology' },
  { key: 'model', label: 'Model' },
  { key: 'realize', label: 'Realize' },
  { key: 'materialize', label: 'Materialize' },
  { key: 'xdc', label: 'XDC' },
  { key: 'package', label: 'Package' },
];

interface PkgScript { name: string; target: string; content: string }

function KV({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="sph-kv">
      <span className="sph-kv-label">{label}</span>
      <span style={{ fontFamily: mono ? 'monospace' : undefined, wordBreak: 'break-all' }}>{value}</span>
    </div>
  );
}

/**
 * SPHERE-tailored editor: a guided **experiment builder** (not the FABRIC slice
 * editor). Walks the full lifecycle so a user who doesn't write mergexp models
 * can still get an experiment running:
 *   1. Experiment — create / pick / delete
 *   2. Topology   — add nodes + links; LoomAI generates the mergexp model
 *   3. Model      — review/edit the generated source, then push (compile-checked)
 *   4. Realize    — reserve resources for a named realization
 *   5. Materialize— provision; then Access via XDC + Connect (Realizations tab)
 */
export default function SphereEditorPanel({
  selected, project, matStatus, selectedElement,
  onCollapse, dragHandleProps, panelIcon, onChanged, onSelectRealization, onError,
  xdcs = [], selectedXdc = '', onSelectXdc, onXdcsChanged,
}: SphereEditorPanelProps) {
  const [experiments, setExperiments] = useState<any[]>([]);
  const [activeExp, setActiveExp] = useState('');
  const [nodes, setNodes] = useState<TopoNode[]>(DEFAULT_NODES);
  const [newNode, setNewNode] = useState('');
  const [links, setLinks] = useState<TopoLink[]>(DEFAULT_LINKS);
  const [modelSrc, setModelSrc] = useState('');
  const [tag, setTag] = useState('v1');
  const [realizationName, setRealizationName] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [tab, setTab] = useState<BuilderTab>('experiment');
  const modelFileRef = useRef<HTMLInputElement>(null);

  // ── Package-as-weave state ──
  const [pkgName, setPkgName] = useState('');
  const [pkgDesc, setPkgDesc] = useState('');
  const [pkgRid, setPkgRid] = useState('');
  const [pkgNotebook, setPkgNotebook] = useState(true);
  const [pkgScripts, setPkgScripts] = useState<PkgScript[]>([]);
  const scriptFileRef = useRef<HTMLInputElement>(null);

  const note = useCallback((m: string) => { setMsg(m); }, []);
  const fail = useCallback((m: string) => { onError?.(m); }, [onError]);

  const refreshExperiments = useCallback(() => {
    if (!project) return;
    api.listSphereExperiments(project)
      .then(setExperiments)
      .catch(e => fail(`SPHERE: list experiments failed — ${e?.message || e}`));
  }, [project, fail]);

  useEffect(() => { refreshExperiments(); }, [refreshExperiments]);

  // Sync the active experiment to the selected realization ONLY when that
  // selection actually changes — otherwise a user's explicit dropdown pick
  // (e.g. an unrealized experiment) would get snapped back on every re-render.
  const lastSelExpRef = useRef('');
  useEffect(() => {
    const exp = selected?.experiment || '';
    if (exp && exp !== lastSelExpRef.current) {
      lastSelExpRef.current = exp;
      setActiveExp(exp);
    } else if (!activeExp && experiments.length) {
      setActiveExp(experiments[0].name);
    }
  }, [selected, experiments]); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear the status line when the active realization changes/clears (e.g. after
  // a weave Stop relinquishes it) so a stale "attached to …" note doesn't linger.
  const lastSelKeyRef = useRef('');
  useEffect(() => {
    const key = selected ? `${selected.realization}.${selected.experiment}` : '';
    if (key !== lastSelKeyRef.current) { lastSelKeyRef.current = key; setMsg(''); }
  }, [selected]);

  // Load the active experiment's pushed model into the builder so Topology/Model
  // reflect *that* experiment (not a stale default). Reset to a fresh template
  // when the experiment has no model yet.
  useEffect(() => {
    if (!activeExp || !project) return;
    let cancelled = false;
    api.getSphereExperimentModel(activeExp, project)
      .then(m => {
        if (cancelled) return;
        if (m?.found && (m.nodes || []).length) {
          setNodes(m.nodes.map((n: any) => ({ name: n.name, facility: n.facility || '' })));
          setLinks((m.links || []).map((l: any, i: number) => ({ id: i + 1, members: l.members || [], addrs: l.addrs || {} })));
        } else {
          setNodes(DEFAULT_NODES);
          setLinks(DEFAULT_LINKS);
        }
        setModelSrc('');  // regenerate from the loaded topology
      })
      .catch(() => { /* best-effort; keep current builder state */ });
    return () => { cancelled = true; };
  }, [activeExp, project]);

  const generated = useMemo(() => genMergexp(activeExp, nodes, links), [activeExp, nodes, links]);
  const effectiveModel = modelSrc || generated;

  // Experiment creation lives in the top bar (+ New Experiment); the editor
  // only selects/deletes and builds the rest.
  const handleDeleteExp = useCallback(async () => {
    if (!activeExp) return;
    if (typeof window !== 'undefined' && !window.confirm(`Delete experiment "${activeExp}"? This cannot be undone.`)) return;
    setBusy('exp');
    try {
      await api.deleteSphereExperiment(activeExp, project || undefined);
      setActiveExp('');
      refreshExperiments();
      onChanged?.();
      note(`Experiment "${activeExp}" deleted.`);
    } catch (e: any) { fail(`SPHERE: delete experiment failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [activeExp, project, refreshExperiments, onChanged, note, fail]);

  // ── XDC actions ──
  const realizationRef = selected ? `${selected.realization}.${selected.experiment}.${project}` : '';
  const selectedXdcObj = xdcs.find(x => bareXdc(x.name) === selectedXdc) || null;
  // Attached only when the XDC has a (non-empty) materialization matching the
  // active realization — guard against '' === '' reading as attached once both
  // the realization and the XDC's materialization clear (post-relinquish).
  const selectedXdcAttached = !!selectedXdcObj && !!realizationRef
    && (selectedXdcObj.materialization || '') === realizationRef;

  const handleCreateXdc = useCallback(async () => {
    const name = (typeof window !== 'undefined' ? window.prompt('New shared XDC name (lowercase, e.g. x0):') : '')?.trim();
    if (!name) return;
    if (!EXP_RE.test(name)) { fail('SPHERE: invalid XDC name (lowercase letter then lowercase letters/digits).'); return; }
    setBusy('xdc');
    try {
      await api.createSphereXdc(name, 'shared', project || undefined);
      onSelectXdc?.(name);
      onXdcsChanged?.();
      note(`XDC "${name}" created — it may take a minute to become ready.`);
    } catch (e: any) { fail(`SPHERE: create XDC failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [project, onSelectXdc, onXdcsChanged, note, fail]);

  const handleAttachXdc = useCallback(async () => {
    if (!selected || !selectedXdc) return;
    setBusy('xdc');
    try {
      await api.attachSphereXdc(selectedXdc, selected.experiment, selected.realization, project || undefined);
      onXdcsChanged?.();
      note(`XDC ${selectedXdc} attached to ${selected.realization}.${selected.experiment}.`);
    } catch (e: any) { fail(`SPHERE: attach XDC failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [selected, selectedXdc, project, onXdcsChanged, note, fail]);

  const handleDetachXdc = useCallback(async () => {
    if (!selected || !selectedXdc) return;
    setBusy('xdc');
    try {
      await api.detachSphereXdc(selectedXdc, selected.experiment, selected.realization, project || undefined);
      onXdcsChanged?.();
      note(`XDC ${selectedXdc} detached.`);
    } catch (e: any) { fail(`SPHERE: detach XDC failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [selected, selectedXdc, project, onXdcsChanged, note, fail]);

  const handleDeleteXdc = useCallback(async () => {
    if (!selectedXdc) return;
    if (typeof window !== 'undefined' && !window.confirm(`Delete XDC "${selectedXdc}"?`)) return;
    setBusy('xdc');
    try {
      await api.deleteSphereXdc(selectedXdc, project || undefined);
      onXdcsChanged?.();
      note(`XDC ${selectedXdc} deleted.`);
    } catch (e: any) { fail(`SPHERE: delete XDC failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [selectedXdc, project, onXdcsChanged, note, fail]);

  // ── Topology actions ──
  const nodeNames = nodes.map(n => n.name);
  const addNode = () => {
    const n = newNode.trim();
    if (!n || nodeNames.includes(n)) return;
    setNodes(prev => [...prev, { name: n, facility: '' }]);
    setNewNode('');
  };
  const removeNode = (n: string) => {
    setNodes(prev => prev.filter(x => x.name !== n));
    setLinks(prev => prev.map(l => ({ ...l, members: l.members.filter(m => m !== n) })).filter(l => l.members.length > 0));
  };
  const setNodeFacility = (name: string, facility: string) =>
    setNodes(prev => prev.map(x => x.name === name ? { ...x, facility } : x));
  const addLink = () => {
    setLinks(prev => {
      const i = prev.length;
      const members = nodeNames.slice(0, 2);
      const addrs: Record<string, string> = {};
      members.forEach((m, k) => { addrs[m] = `10.0.${i}.${k + 1}/24`; });
      return [...prev, { id: Date.now(), members, addrs }];
    });
  };
  const toggleLinkMember = (linkId: number, node: string) => {
    setLinks(prev => prev.map(l => {
      if (l.id !== linkId) return l;
      const has = l.members.includes(node);
      const members = has ? l.members.filter(m => m !== node) : [...l.members, node];
      const addrs = { ...l.addrs };
      if (has) delete addrs[node];
      else if (!addrs[node]) addrs[node] = `10.0.${links.findIndex(x => x.id === linkId)}.${members.length}/24`;
      return { ...l, members, addrs };
    }));
  };
  const removeLink = (linkId: number) => setLinks(prev => prev.filter(l => l.id !== linkId));

  // ── Model push ──
  const handlePush = useCallback(async () => {
    if (!activeExp) { fail('SPHERE: select or create an experiment first.'); return; }
    const src = effectiveModel;
    setBusy('push');
    try {
      const c = await api.compileSphereModel(src, project || undefined);
      if (!c.success) { fail(`SPHERE: model has errors — ${(c.errors || []).join('; ') || 'compile failed'}`); return; }
      const r = await api.pushSphereModel(src, activeExp, tag || 'v1', project || undefined);
      note(`Model pushed to ${activeExp} (tag ${tag || 'v1'}, rev ${String(r?.revision || '').slice(0, 8)}).`);
    } catch (e: any) { fail(`SPHERE: push model failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [activeExp, effectiveModel, project, tag, note, fail]);

  // ── Realize / Materialize ──
  const handleRealize = useCallback(async () => {
    const rname = realizationName.trim();
    if (!activeExp || !EXP_RE.test(rname)) {
      fail('SPHERE: pick an experiment and a valid realization name (lowercase letter, then lowercase letters/digits).');
      return;
    }
    setBusy('realize');
    try {
      await api.realizeSphere(activeExp, rname, { tag: tag || 'v1' }, project || undefined);
      onChanged?.();
      onSelectRealization?.({ experiment: activeExp, realization: rname });
      note(`Realize requested: ${rname}.${activeExp}.`);
    } catch (e: any) { fail(`SPHERE: realize failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [activeExp, realizationName, tag, project, onChanged, onSelectRealization, note, fail]);

  const lifecycle = useCallback(async (label: string, fn: () => Promise<any>) => {
    setBusy(label);
    try { await fn(); onChanged?.(); note(`${label} requested.`); }
    catch (e: any) { fail(`SPHERE: ${label} failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [onChanged, note, fail]);

  // ── Package as weave ──
  // Default the form fields from the active experiment / selected realization.
  useEffect(() => {
    if (!pkgName && activeExp) setPkgName(`${activeExp}-weave`);
  }, [activeExp]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const rid = selected?.realization || realizationName.trim();
    if (rid && !pkgRid) setPkgRid(rid);
  }, [selected, realizationName]); // eslint-disable-line react-hooks/exhaustive-deps

  const addScript = () => setPkgScripts(prev => [...prev, { name: '', target: 'all', content: '' }]);
  const updateScript = (i: number, patch: Partial<PkgScript>) =>
    setPkgScripts(prev => prev.map((s, idx) => idx === i ? { ...s, ...patch } : s));
  const removeScript = (i: number) => setPkgScripts(prev => prev.filter((_, idx) => idx !== i));

  const importScriptFile = useCallback(async (file: File) => {
    const content = await file.text();
    const name = file.name.replace(/[^A-Za-z0-9._-]/g, '_');
    setPkgScripts(prev => [...prev, { name, target: 'all', content }]);
  }, []);

  const handlePackage = useCallback(async () => {
    if (!activeExp) { fail('SPHERE: select an experiment to package.'); return; }
    if (!pkgName.trim()) { fail('SPHERE: enter a weave name.'); return; }
    // Validate bundled scripts before sending.
    for (const s of pkgScripts) {
      if (!s.name.trim() || !/^[A-Za-z0-9._-]+$/.test(s.name) || s.name.startsWith('.')) {
        fail(`SPHERE: invalid script filename "${s.name}" (letters, digits, . _ - only).`); return;
      }
    }
    setBusy('package');
    try {
      const r = await api.packageSphereExperiment(activeExp, {
        name: pkgName.trim(),
        description: pkgDesc.trim(),
        realization: pkgRid.trim() || 'r0',
        scripts: pkgScripts.map(s => ({ name: s.name.trim(), content: s.content, target: s.target || 'all' })),
        include_notebook: pkgNotebook,
        project: project || undefined,
      });
      note(`Packaged "${r.dir_name}" (${r.files.length} files) into My Artifacts. Open Libraries to run or publish it.`);
      onChanged?.();
    } catch (e: any) { fail(`SPHERE: package failed — ${e?.message || e}`); }
    finally { setBusy(''); }
  }, [activeExp, pkgName, pkgDesc, pkgRid, pkgScripts, pkgNotebook, project, note, fail, onChanged]);

  const el = selectedElement;
  const isNode = el?.element_type === 'node';

  return (
    <div className="editor-panel" data-testid="sphere-editor-panel" data-view-context="sphere">
      <div className="editor-header" {...(dragHandleProps || {})} data-testid="sphere-editor-header">
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="panel-drag-handle">{'⠿'}</span>
          {panelIcon} Experiment Builder
        </span>
        <button className="collapse-btn" onClick={(e) => { e.stopPropagation(); onCollapse(); }} title="Close panel">{'✕'}</button>
      </div>

      {/* Tabbed steps — mirrors the Chameleon/FABRIC editor tab bar */}
      <div className="editor-top-tabs" data-testid="sphere-editor-tabs">
        {TABS.map(t => (
          <button key={t.key} className={tab === t.key ? 'active' : ''} type="button"
            data-testid="sphere-editor-tab" data-sphere-tab={t.key}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      <div className="tab-content" style={{ padding: 12, overflow: 'auto' }}>
        {msg && <div className="sph-msg">{msg}</div>}

        {tab === 'experiment' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <label className="sph-label">Active experiment</label>
            <div className="sph-row" style={{ marginTop: 0 }}>
              <select className="sph-input" value={activeExp} onChange={e => setActiveExp(e.target.value)} style={{ flex: 1 }}>
                <option value="">— select —</option>
                {experiments.map(x => <option key={x.name} value={x.name}>{x.name}</option>)}
              </select>
              <button className="sph-btn sph-btn-danger" disabled={!activeExp || busy === 'exp'} onClick={handleDeleteExp}>Delete</button>
            </div>
            <div className="sph-hint" style={{ marginTop: 8 }}>
              Create a new experiment with <strong>+ New Experiment</strong> in the top bar. Then define the <strong>Topology</strong> here.
            </div>
          </div>
        )}

        {tab === 'topology' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <label className="sph-label">Nodes</label>
            {nodes.map(n => (
              <div key={n.name} className="sph-row" style={{ marginTop: 0, marginBottom: 4 }}>
                <span className="sph-chip" style={{ minWidth: 70 }}>{n.name}
                  <button onClick={() => removeNode(n.name)} title="Remove node">×</button></span>
                <input className="sph-input" style={{ flex: 1 }} placeholder="facility (e.g. embed) — optional"
                  value={n.facility || ''} onChange={e => setNodeFacility(n.name, e.target.value)} />
              </div>
            ))}
            <div className="sph-row" style={{ marginTop: 0 }}>
              <input className="sph-input" placeholder="node name (e.g. c)" value={newNode}
                onChange={e => setNewNode(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') addNode(); }} />
              <button className="sph-btn sph-btn-secondary" onClick={addNode}>Add</button>
            </div>
            <div className="sph-hint" style={{ marginTop: 2 }}>Facility pins the node to a tier — e.g. <code>embed</code> (RPi edge), <code>sphereiot</code> (IoT), <code>generalserver</code>. Blank = default.</div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label className="sph-label">Links</label>
              <button className="sph-btn sph-btn-secondary" onClick={addLink} disabled={nodeNames.length < 2}>+ Link</button>
            </div>
            {links.length === 0 && <div className="sph-hint">No links — add one to connect nodes.</div>}
            {links.map((lk, i) => (
              <div key={lk.id} className="sph-link-card">
                <div className="sph-card-head">
                  <span>link{i}</span>
                  <button className="sph-link-remove" onClick={() => removeLink(lk.id)}>remove</button>
                </div>
                <div style={{ marginBottom: 4 }}>
                  {nodeNames.map(n => (
                    <label key={n} className="sph-cbx">
                      <input type="checkbox" checked={lk.members.includes(n)} onChange={() => toggleLinkMember(lk.id, n)} />{n}
                    </label>
                  ))}
                </div>
                {lk.members.map(m => (
                  <div key={m} className="sph-row" style={{ marginTop: 3 }}>
                    <span style={{ fontSize: 10, minWidth: 22, opacity: 0.7 }}>{m}</span>
                    <input className="sph-input" value={lk.addrs[m] || ''} placeholder="10.0.0.1/24"
                      onChange={e => setLinks(prev => prev.map(x => x.id === lk.id ? { ...x, addrs: { ...x.addrs, [m]: e.target.value } } : x))} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {tab === 'model' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <div className="sph-hint" style={{ marginTop: 0, marginBottom: 6 }}>
              LoomAI generates the model from your topology — or import a mergexp <code>.py</code> file / paste your own.
            </div>
            <div className="sph-row" style={{ marginTop: 0, flexWrap: 'wrap' }}>
              <button className="sph-btn sph-btn-secondary" onClick={() => setModelSrc(generated)}>Generate from topology</button>
              <button className="sph-btn sph-btn-secondary" onClick={() => modelFileRef.current?.click()}>Import .py</button>
              <input ref={modelFileRef} type="file" accept=".py,text/x-python,text/plain" style={{ display: 'none' }}
                onChange={async e => {
                  const f = e.target.files?.[0];
                  if (f) { setModelSrc(await f.text()); note(`Loaded ${f.name} into the model.`); }
                  if (modelFileRef.current) modelFileRef.current.value = '';
                }} />
              {modelSrc && <button className="sph-btn sph-btn-secondary" onClick={() => setModelSrc('')}>Reset</button>}
            </div>
            <textarea className="sph-textarea" style={{ marginTop: 6 }} value={effectiveModel}
              spellCheck={false} onChange={e => setModelSrc(e.target.value)} />
            <div className="sph-row">
              <span style={{ fontSize: 11, opacity: 0.7 }}>tag</span>
              <input className="sph-input" style={{ width: 80 }} value={tag} onChange={e => setTag(e.target.value)} />
              <button className="sph-btn" style={{ marginLeft: 'auto' }} disabled={!activeExp || busy === 'push'} onClick={handlePush}>
                {busy === 'push' ? 'Pushing…' : 'Compile & Push'}
              </button>
            </div>
          </div>
        )}

        {tab === 'realize' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <label className="sph-label">Realization name</label>
            <div className="sph-row" style={{ marginTop: 0 }}>
              <input className="sph-input" placeholder="e.g. world" value={realizationName}
                onChange={e => setRealizationName(e.target.value)} />
              <button className="sph-btn" disabled={busy === 'realize'} onClick={handleRealize}>
                {busy === 'realize' ? 'Realizing…' : 'Realize'}
              </button>
            </div>
            <div className="sph-hint">Reserves resources for the pushed model (tag {tag || 'v1'}).</div>
            {selected && (
              <div className="sph-row">
                <button className="sph-btn sph-btn-danger" disabled={!!busy}
                  onClick={() => lifecycle('Relinquish', () => api.relinquishSphere(selected.experiment, selected.realization, project || undefined))}>
                  Relinquish {selected.realization}
                </button>
              </div>
            )}
          </div>
        )}

        {tab === 'xdc' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <div className="sph-hint" style={{ marginTop: 0, marginBottom: 6 }}>
              An XDC is the jump container used to SSH into experiment nodes. Create one,
              then attach it to the active realization.
            </div>
            <label className="sph-label">XDC</label>
            <div className="sph-row" style={{ marginTop: 0 }}>
              <select className="sph-input" value={selectedXdc} onChange={e => onSelectXdc?.(e.target.value)} style={{ flex: 1 }}>
                {xdcs.length === 0 && <option value="">— none —</option>}
                {xdcs.map(x => {
                  const r = x.ready === true ? '✓ ' : x.ready === false ? '⏳ ' : '';
                  return <option key={x.name} value={bareXdc(x.name)}>
                    {r}{x.name}{(x.materialization && x.materialization === realizationRef) ? ' (attached)' : ''}
                  </option>;
                })}
              </select>
              <button className="sph-btn sph-btn-secondary" disabled={busy === 'xdc'} onClick={onXdcsChanged} title="Refresh XDC status">↻</button>
            </div>
            {selectedXdcObj && (
              <div className="sph-hint" style={{ color: selectedXdcObj.ready === true ? '#008e7a' : selectedXdcObj.ready === false ? '#e2a23b' : undefined }}>
                status: {selectedXdcObj.ready === true ? 'ready' : selectedXdcObj.ready === false ? `provisioning (${selectedXdcObj.status || '…'})` : (selectedXdcObj.status || 'unknown')}
                {selectedXdcObj.fqdn ? ` · ${selectedXdcObj.fqdn}` : ''}
              </div>
            )}
            {selectedXdcObj?.url && (
              <div className="sph-row">
                <a className="sph-btn sph-btn-secondary" href={selectedXdcObj.url} target="_blank" rel="noopener noreferrer"
                  style={{ textDecoration: 'none' }} title="Open this XDC's JupyterLab in a new tab">
                  Open Jupyter ↗
                </a>
                <span className="sph-hint" style={{ margin: 0 }}>or use the Notebook tab</span>
              </div>
            )}
            <div className="sph-row">
              <button className="sph-btn" disabled={busy === 'xdc'} onClick={handleCreateXdc}>+ New XDC</button>
              {selectedXdc && !selectedXdcAttached && (
                <button className="sph-btn sph-btn-secondary" disabled={busy === 'xdc' || !selected || selectedXdcObj?.ready === false}
                  title={selectedXdcObj?.ready === false ? 'XDC is still provisioning' : !selected ? 'Select a realization first' : 'Attach to the active realization'}
                  onClick={handleAttachXdc}>Attach</button>
              )}
              {selectedXdc && selectedXdcAttached && (
                <button className="sph-btn sph-btn-secondary" disabled={busy === 'xdc'} onClick={handleDetachXdc}>Detach</button>
              )}
              {selectedXdc && (
                <button className="sph-btn sph-btn-danger" style={{ marginLeft: 'auto' }} disabled={busy === 'xdc'} onClick={handleDeleteXdc}>Delete</button>
              )}
            </div>
            {!selected && <div className="sph-hint">Select a realization (Realizations tab) to attach an XDC to it.</div>}
          </div>
        )}

        {tab === 'materialize' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <div className="sph-hint" style={{ marginTop: 0, marginBottom: 6 }}>
              Materialize provisions the reserved nodes (power on, image, wire the network).
              Then attach an XDC (XDC tab) and Connect to a node.
            </div>
            {selected ? (
              <>
                <KV label="Realization" value={`${selected.realization}.${selected.experiment}`} />
                <KV label="Status" value={<span style={{ color: matStatus === 'Success' ? '#008e7a' : 'inherit' }}>{matStatus || '…'}</span>} />
                <div className="sph-row">
                  <button className="sph-btn" disabled={!!busy}
                    onClick={() => lifecycle('Materialize', () => api.materializeSphere(selected.experiment, selected.realization, project || undefined))}>
                    Materialize
                  </button>
                  <button className="sph-btn sph-btn-danger" disabled={!!busy}
                    onClick={() => lifecycle('Dematerialize', () => api.dematerializeSphere(selected.experiment, selected.realization, project || undefined))}>
                    Dematerialize
                  </button>
                </div>
              </>
            ) : (
              <div className="sph-hint" style={{ marginTop: 0 }}>Select a realization to materialize it.</div>
            )}
          </div>
        )}

        {tab === 'package' && (
          <div className="sph-body" style={{ paddingTop: 0 }}>
            <div className="sph-hint" style={{ marginTop: 0, marginBottom: 6 }}>
              Package this experiment as a reproducible weave (model + setup scripts +
              a starter notebook) into <b>My Artifacts</b>. Others can Run it to recreate
              the experiment, or you can Publish it from the Libraries view.
            </div>
            <label className="sph-label">Weave name</label>
            <input className="sph-input" value={pkgName} placeholder="e.g. edgeids-weave"
              onChange={e => setPkgName(e.target.value)} />
            <label className="sph-label">Description</label>
            <textarea className="sph-input" rows={2} value={pkgDesc}
              placeholder="What this experiment does…"
              onChange={e => setPkgDesc(e.target.value)} style={{ resize: 'vertical' }} />
            <div className="sph-row" style={{ marginTop: 6 }}>
              <div style={{ flex: 1 }}>
                <label className="sph-label" style={{ marginTop: 0 }}>Realization id</label>
                <input className="sph-input" value={pkgRid} placeholder="e.g. ids"
                  onChange={e => setPkgRid(e.target.value)} />
              </div>
              <label className="sph-hint" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 18 }}>
                <input type="checkbox" checked={pkgNotebook}
                  onChange={e => setPkgNotebook(e.target.checked)} />
                Starter notebook
              </label>
            </div>

            <div className="sph-row" style={{ marginTop: 10, justifyContent: 'space-between' }}>
              <label className="sph-label" style={{ marginTop: 0 }}>Setup scripts</label>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="sph-btn sph-btn-secondary" type="button" onClick={() => scriptFileRef.current?.click()}>
                  Import file
                </button>
                <button className="sph-btn sph-btn-secondary" type="button" onClick={addScript}>+ Script</button>
              </div>
            </div>
            <input ref={scriptFileRef} type="file" style={{ display: 'none' }}
              onChange={e => { const f = e.target.files?.[0]; if (f) importScriptFile(f); e.currentTarget.value = ''; }} />
            {pkgScripts.length === 0 && (
              <div className="sph-hint" style={{ marginTop: 0 }}>
                No scripts yet. Add per-node setup scripts (firewall, IDS sensor, etc.)
                that the notebook will push and run on each node.
              </div>
            )}
            {pkgScripts.map((s, i) => (
              <div key={i} style={{ border: '1px solid var(--fabric-border)', borderRadius: 6, padding: 6, marginTop: 6 }}>
                <div className="sph-row" style={{ marginTop: 0 }}>
                  <input className="sph-input" style={{ flex: 2 }} placeholder="filename.sh"
                    value={s.name} onChange={e => updateScript(i, { name: e.target.value })} />
                  <select className="sph-input" style={{ flex: 1 }} value={s.target}
                    onChange={e => updateScript(i, { target: e.target.value })}>
                    <option value="all">all nodes</option>
                    {nodes.map(n => <option key={n.name} value={n.name}>{n.name}</option>)}
                  </select>
                  <button className="sph-btn sph-btn-danger" type="button" onClick={() => removeScript(i)}>✕</button>
                </div>
                <textarea className="sph-input" rows={4} placeholder="#!/bin/bash&#10;# setup commands…"
                  value={s.content} onChange={e => updateScript(i, { content: e.target.value })}
                  style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }} />
              </div>
            ))}

            <div className="sph-row" style={{ marginTop: 10 }}>
              <button className="sph-btn" disabled={busy === 'package' || !activeExp} onClick={handlePackage}>
                {busy === 'package' ? 'Packaging…' : 'Save as Weave'}
              </button>
            </div>
            <div className="sph-hint">
              The mergexp model is regenerated from the current topology of
              <b> {activeExp || '(no experiment)'}</b>.
            </div>
          </div>
        )}

        {/* Node inspector — always visible when a topology/resource node is selected */}
        {isNode && (
          <div style={{ borderTop: '1px solid var(--fabric-border)', marginTop: 10, paddingTop: 8 }}>
            <label className="sph-label" style={{ marginTop: 0 }}>Selected node · {el?.name}</label>
            <KV label="Addresses" value={(el?.addresses && el.addresses.length ? el.addresses.join(', ') : '—')} mono />
            <KV label="Facility" value={el?.facility || '—'} />
          </div>
        )}
      </div>
    </div>
  );
}
