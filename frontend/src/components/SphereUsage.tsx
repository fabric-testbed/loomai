'use client';
import { memo, useMemo } from 'react';
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js';
import { Pie } from 'react-chartjs-2';

ChartJS.register(ArcElement, Tooltip, Legend);

interface SphereUsageProps {
  resources: any[];
  dark: boolean;
}

const PALETTE = ['#39B54A', '#008e7a', '#e6b34a', '#ff8542', '#5798bc', '#9b59b6', '#e25241', '#1f6a8c', '#888'];
const UNUSED_COLOR = '#2f6fb0';

const resRec = (r: any) => (r?.resource || r || {});
const resCores = (r: any) => (resRec(r).procs || []).reduce((s: number, p: any) => s + (Number(p.cores) || 0), 0);
const resMemBytes = (r: any) => {
  const m = resRec(r).memory;
  const arr = Array.isArray(m) ? m : (m ? [m] : []);
  return arr.reduce((s: number, x: any) => s + (Number(x.capacity) || 0), 0);
};
const fmtMem = (b: number) => {
  const tb = b / 1024 ** 4;
  if (tb >= 1) return `${tb.toFixed(1)} TB`;
  return `${(b / 1024 ** 3).toFixed(0)} GB`;
};

/** Build a {labels, data, colors} pie dataset of per-project usage + unused. */
function buildPie(total: number, byProject: Map<string, number>, topN = 6) {
  const sorted = [...byProject.entries()].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const top = sorted.slice(0, topN);
  const restSum = sorted.slice(topN).reduce((s, [, v]) => s + v, 0);
  const usedSum = sorted.reduce((s, [, v]) => s + v, 0);
  const unused = Math.max(0, total - usedSum);
  const labels = ['Unused', ...top.map(([k]) => k)];
  const data = [unused, ...top.map(([, v]) => v)];
  const colors = [UNUSED_COLOR, ...top.map((_, i) => PALETTE[i % PALETTE.length])];
  if (restSum > 0) { labels.push('other'); data.push(restSum); colors.push('#bbb'); }
  return { labels, data, colors };
}

/**
 * "Resource Usage by Project" — mirrors the SPHERE portal dashboard. Aggregates
 * total cores/memory from the inventory and per-project usage from each
 * resource's allocations (Allocation.pid / cores_used / memory_used).
 */
function SphereUsage({ resources, dark }: SphereUsageProps) {
  // Aggregate once per resources change (not on every render / filter keystroke).
  const { totalCores, totalMem, mem, cores } = useMemo(() => {
    let totalCores = 0;
    let totalMem = 0;
    const coresByProj = new Map<string, number>();
    const memByProj = new Map<string, number>();
    for (const r of resources) {
      const rc = resCores(r);
      const rm = resMemBytes(r);
      totalCores += rc;
      totalMem += rm;
      const allocs = r.allocated || [];
      // cores_used/memory_used are often 0 in the API (whole-node reservations),
      // so fall back to attributing the resource's capacity (split if a node has
      // multiple allocations) to the owning project — matching the portal's
      // "in use vs unused" split.
      for (const a of allocs) {
        const pid = a.pid || a.eid || 'unknown';
        const c = Number(a.cores_used) || Math.round(rc / allocs.length);
        const m = Number(a.memory_used) || Math.round(rm / allocs.length);
        coresByProj.set(pid, (coresByProj.get(pid) || 0) + c);
        memByProj.set(pid, (memByProj.get(pid) || 0) + m);
      }
    }
    return { totalCores, totalMem, mem: buildPie(totalMem, memByProj), cores: buildPie(totalCores, coresByProj) };
  }, [resources]);
  const textColor = dark ? '#ddd' : '#333';
  const legend = { position: 'right' as const, labels: { color: textColor, boxWidth: 12, font: { size: 11 } } };

  const memData = { labels: mem.labels, datasets: [{ data: mem.data, backgroundColor: mem.colors, borderWidth: 0 }] };
  const coreData = { labels: cores.labels, datasets: [{ data: cores.data, backgroundColor: cores.colors, borderWidth: 0 }] };
  const memOpts = {
    plugins: { legend, tooltip: { callbacks: { label: (c: any) => `${c.label}: ${fmtMem(c.raw)}` } } },
    maintainAspectRatio: false,
  };
  const coreOpts = {
    plugins: { legend, tooltip: { callbacks: { label: (c: any) => `${c.label}: ${c.raw} cores` } } },
    maintainAspectRatio: false,
  };

  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '4px 12px 12px' }}>
      <div style={{ flex: '1 1 280px', minWidth: 260 }}>
        <div style={{ fontSize: 11, textAlign: 'center', opacity: 0.75, marginBottom: 4 }}>Memory — {fmtMem(totalMem)} total</div>
        <div style={{ height: 180 }}><Pie data={memData} options={memOpts} /></div>
      </div>
      <div style={{ flex: '1 1 280px', minWidth: 260 }}>
        <div style={{ fontSize: 11, textAlign: 'center', opacity: 0.75, marginBottom: 4 }}>Cores — {totalCores.toLocaleString()} total</div>
        <div style={{ height: 180 }}><Pie data={coreData} options={coreOpts} /></div>
      </div>
    </div>
  );
}

export default memo(SphereUsage);
