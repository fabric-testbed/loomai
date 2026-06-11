'use client';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import cytoscape, { type Core, type EventObject } from 'cytoscape';
import type { CyGraph, SliceData, RecipeSummary } from '../types/fabric';
import * as api from '../api/client';
import '../styles/context-menu.css';

// Register layout extensions
import dagre from 'cytoscape-dagre';
import cola from 'cytoscape-cola';
cytoscape.use(dagre);
cytoscape.use(cola);

/** Build Cytoscape stylesheet, adapting colors for dark/light mode */
function buildStylesheet(dark: boolean): any[] {
  const bg = dark ? '#1a1a2e' : '#edf2f8';
  const containerBorder = dark ? '#4a4a6a' : '#c5cfd8';
  const containerLabel = dark ? '#8888aa' : '#838385';
  const vmText = dark ? '#e0e0e0' : '#212121';
  const edgeLabelBg = dark ? '#16213e' : '#ffffff';
  const edgeText = dark ? '#c0c0c0' : '#374955';
  const l2Color = dark ? '#5bb8d9' : '#1f6a8c';
  const l2NodeBg = dark ? '#1a3050' : '#ddeaf2';
  const l3Color = dark ? '#2bb5a0' : '#008e7a';
  const l3NodeBg = dark ? '#1a3a30' : '#e0f2f1';
  const internetColor = dark ? '#a78bfa' : '#7c3aed';
  const internetBg = dark ? '#1e1040' : '#ede9fe';
  const selectOverlay = dark ? '#ffa562' : '#ff8542';

  // Component badge colors by type
  const nicColor = dark ? '#5bb8d9' : '#1f6a8c';
  const gpuColor = dark ? '#66bb6a' : '#2e7d32';
  const fpgaColor = dark ? '#ba68c8' : '#7b1fa2';
  const nvmeColor = dark ? '#ffa726' : '#e65100';
  const compText = dark ? '#e0e0e0' : '#ffffff';

  return [
    { selector: '.slice', style: {
      'shape': 'roundrectangle', 'border-width': 2, 'border-style': 'dashed',
      'border-color': containerBorder, 'background-color': bg, 'background-opacity': 0.3,
      'padding': '30px', 'label': 'data(label)', 'text-valign': 'top', 'text-halign': 'center',
      'font-size': '14px', 'font-weight': 'bold', 'color': containerLabel,
      'font-family': 'Montserrat, sans-serif',
    }},
    // VM nodes — always fixed size with centered label
    { selector: '.vm', style: {
      'shape': 'roundrectangle', 'width': 180, 'height': 70,
      'background-color': dark ? 'data(state_bg_dark)' : 'data(state_bg)',
      'border-width': 2, 'border-color': dark ? 'data(state_color_dark)' : 'data(state_color)',
      'label': 'data(label)', 'text-valign': 'center', 'text-halign': 'center',
      'font-size': '10px', 'text-wrap': 'wrap', 'text-max-width': '170px',
      'color': vmText, 'font-family': 'Montserrat, sans-serif',
    }},
    // Boot config status overlays on VM nodes
    { selector: '.boot-pending', style: {
      'border-style': 'dashed',
      'border-color': dark ? '#ffb74d' : '#ff8542',
      'border-width': 3,
    }},
    { selector: '.boot-running', style: {
      'border-style': 'dashed',
      'border-color': dark ? '#ffb74d' : '#ff8542',
      'border-width': 3,
    }},
    { selector: '.boot-done', style: {
      'border-width': 3,
      'border-color': dark ? '#4dd0b8' : '#008e7a',
      'border-style': 'double',
    }},
    { selector: '.boot-error', style: {
      'border-width': 3,
      'border-color': dark ? '#ff6b6b' : '#b00020',
      'border-style': 'double',
    }},
    // Component badge nodes — small pills that sit at VM edges
    { selector: '.component', style: {
      'shape': 'roundrectangle', 'width': 'label', 'height': 20,
      'padding': '6px',
      'label': 'data(label)', 'text-valign': 'center', 'text-halign': 'center',
      'font-size': '8px', 'font-weight': 'bold',
      'font-family': 'Montserrat, sans-serif',
      'border-width': 1.5, 'border-opacity': 0.9,
      'color': compText,
      'z-index': 10,
    }},
    { selector: '.component-nic', style: {
      'background-color': nicColor, 'border-color': nicColor, 'color': compText,
    }},
    { selector: '.component-gpu', style: {
      'background-color': gpuColor, 'border-color': gpuColor, 'color': compText,
    }},
    { selector: '.component-fpga', style: {
      'background-color': fpgaColor, 'border-color': fpgaColor, 'color': compText,
    }},
    { selector: '.component-nvme', style: {
      'background-color': nvmeColor, 'border-color': nvmeColor, 'color': compText,
    }},
    // Hidden components (when toggled off)
    { selector: '.component-hidden', style: {
      'display': 'none',
    }},
    // Hidden slice container (when toggled off)
    { selector: '.slice-hidden', style: {
      'display': 'none',
    }},
    { selector: '.network-l2', style: {
      'shape': 'ellipse', 'width': 90, 'height': 80, 'background-color': l2NodeBg,
      'border-width': 2, 'border-color': l2Color, 'label': 'data(label)',
      'text-valign': 'center', 'text-halign': 'center', 'font-size': '9px',
      'text-wrap': 'wrap', 'text-max-width': '80px', 'color': l2Color,
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.network-l3', style: {
      'shape': 'ellipse', 'width': 90, 'height': 80, 'background-color': l3NodeBg,
      'border-width': 2, 'border-color': l3Color, 'label': 'data(label)',
      'text-valign': 'center', 'text-halign': 'center', 'font-size': '9px',
      'text-wrap': 'wrap', 'text-max-width': '80px', 'color': l3Color,
      'font-family': 'Montserrat, sans-serif',
    }},
    // Public ext L3 networks — dashed border, coral color to distinguish from private
    { selector: '.network-l3-ext', style: {
      'border-style': 'dashed',
      'border-width': 2.5,
      'border-color': dark ? '#ff8a80' : '#e25241',
      'color': dark ? '#ff8a80' : '#e25241',
      'background-color': dark ? '#3a1818' : '#fce4ec',
    }},
    { selector: '.edge-l2', style: {
      'width': 3, 'line-color': l2Color, 'target-arrow-color': l2Color,
      'curve-style': 'unbundled-bezier', 'label': 'data(label)', 'font-size': '8px',
      'text-rotation': 'autorotate', 'text-background-color': edgeLabelBg,
      'text-background-opacity': 1, 'text-background-padding': '2px', 'text-wrap': 'wrap',
      'color': edgeText, 'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.edge-l3', style: {
      'width': 2, 'line-color': l3Color, 'line-style': 'dashed',
      'target-arrow-color': l3Color, 'curve-style': 'unbundled-bezier',
      'label': 'data(label)', 'font-size': '8px', 'text-rotation': 'autorotate',
      'text-background-color': edgeLabelBg, 'text-background-opacity': 1,
      'text-background-padding': '2px', 'text-wrap': 'wrap', 'color': edgeText,
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.fabnet-internet', style: {
      'shape': 'ellipse', 'width': 110, 'height': 90, 'background-color': internetBg,
      'border-width': 3, 'border-color': internetColor, 'border-style': 'dashed',
      'label': 'data(label)', 'text-valign': 'center', 'text-halign': 'center',
      'font-size': '10px', 'font-weight': 'bold', 'text-wrap': 'wrap',
      'text-max-width': '100px', 'color': internetColor,
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.fabnet-internet-hidden', style: {
      'display': 'none',
    }},
    { selector: '.edge-fabnet-internet', style: {
      'width': 2, 'line-color': internetColor, 'line-style': 'dashed',
      'target-arrow-color': internetColor, 'target-arrow-shape': 'triangle',
      'curve-style': 'unbundled-bezier',
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.edge-fabnet-internet-hidden', style: {
      'display': 'none',
    }},
    { selector: '.facility-port', style: {
      'shape': 'diamond', 'width': 90, 'height': 80, 'background-color': internetBg,
      'border-width': 3, 'border-color': internetColor, 'border-style': 'dashed',
      'label': 'data(label)',
      'text-valign': 'center', 'text-halign': 'center', 'font-size': '9px',
      'text-wrap': 'wrap', 'text-max-width': '80px', 'color': internetColor,
      'font-family': 'Montserrat, sans-serif',
    }},
    // Port mirror service nodes — hexagon shape, coral/orange
    { selector: '.port-mirror', style: {
      'shape': 'hexagon', 'width': 90, 'height': 80,
      'background-color': dark ? '#3a1818' : '#fce4ec',
      'border-width': 2, 'border-style': 'dashed',
      'border-color': dark ? '#ff8a80' : '#e25241',
      'label': 'data(label)',
      'text-valign': 'center', 'text-halign': 'center', 'font-size': '9px',
      'text-wrap': 'wrap', 'text-max-width': '80px',
      'color': dark ? '#ff8a80' : '#e25241',
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.edge-port-mirror', style: {
      'width': 2, 'line-color': dark ? '#ff8a80' : '#e25241',
      'line-style': 'dotted',
      'target-arrow-color': dark ? '#ff8a80' : '#e25241',
      'target-arrow-shape': 'triangle',
      'curve-style': 'unbundled-bezier',
      'label': 'data(label)', 'font-size': '8px', 'text-rotation': 'autorotate',
      'text-background-color': edgeLabelBg, 'text-background-opacity': 1,
      'text-background-padding': '2px',
      'color': dark ? '#ff8a80' : '#e25241',
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: ':selected', style: {
      'overlay-color': selectOverlay, 'overlay-opacity': 0.2, 'overlay-padding': 6,
    }},
    // --- Chameleon Cloud nodes ---
    { selector: '.chameleon-cluster', style: {
      'shape': 'round-rectangle',
      'background-color': dark ? '#3a2008' : '#fff3e0',
      'border-color': '#ff8542',
      'border-width': 2,
      'border-style': 'dashed',
      'label': 'data(label)',
      'text-valign': 'top',
      'text-halign': 'center',
      'font-size': 11,
      'color': '#ff8542',
      'padding': '16px',
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.chameleon-instance', style: {
      'shape': 'round-rectangle',
      'width': 160,
      'height': 50,
      'background-color': dark ? 'data(bg_color_dark)' : 'data(bg_color)',
      'border-color': dark ? 'data(border_color_dark)' : 'data(border_color)',
      'border-width': 2,
      'label': 'data(label)',
      'text-wrap': 'wrap',
      'text-valign': 'center',
      'text-halign': 'center',
      'font-size': 10,
      'color': vmText,
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.edge-cross-testbed', style: {
      'line-color': '#ff8542',
      'target-arrow-color': '#ff8542',
      'target-arrow-shape': 'triangle',
      'width': 2,
      'line-style': 'dashed',
      'label': 'data(label)',
      'font-size': 9,
      'text-background-color': edgeLabelBg,
      'text-background-opacity': 0.9,
      'text-background-padding': '2px',
      'color': '#ff8542',
    }},
    { selector: '.edge-facility-port-l2', style: {
      'line-color': internetColor,
      'target-arrow-color': internetColor,
      'line-style': 'dashed',
      'width': 2,
      'color': internetColor,
    }},
    // --- Composite member bounding boxes ---
    { selector: '.composite-member', style: {
      'shape': 'round-rectangle',
      'border-width': 2,
      'border-style': 'dashed',
      'label': 'data(label)',
      'text-valign': 'top',
      'text-halign': 'center',
      'font-size': 12,
      'font-weight': 'bold' as any,
      'padding': '20px',
      'font-family': 'Montserrat, sans-serif',
    }},
    { selector: '.composite-member-fabric', style: {
      'background-color': dark ? '#0d2135' : '#e8f4fc',
      'border-color': '#5798bc',
      'color': '#5798bc',
    }},
    { selector: '.composite-member-chameleon', style: {
      'background-color': dark ? '#0d2b12' : '#e8fce8',
      'border-color': '#39B54A',
      'color': '#39B54A',
    }},
    { selector: '.composite-shared-network', style: {
      'border-color': '#27aae1',
      'border-width': 3,
      'color': '#27aae1',
    }},
    { selector: '.facility-port.composite-shared-network', style: {
      'background-color': internetBg,
      'border-color': internetColor,
      'border-width': 3,
      'color': internetColor,
    }},
  ];
}

/**
 * Position component badge nodes at the bottom edge of their parent VM,
 * overlapping the border so they look attached. Badges are spread
 * horizontally and locked in place.
 */
function positionComponentsAtVmEdge(cy: Core) {
  const compNodes = cy.nodes('.component').not('.component-hidden');
  if (compNodes.empty()) return;

  // Group components by parent VM
  const byVm: Record<string, any[]> = {};
  compNodes.forEach((n: any) => {
    const vmId = n.data('parent_vm');
    if (!vmId) return;
    if (!byVm[vmId]) byVm[vmId] = [];
    byVm[vmId].push(n);
  });

  for (const [vmId, comps] of Object.entries(byVm)) {
    positionComponentsForVm(cy, vmId, comps);
  }
}

function positionComponentsForVm(cy: Core, vmId: string, compsArg?: any[]) {
  const vm = cy.getElementById(vmId);
  if (vm.empty()) return;

  const comps = compsArg ?? cy.nodes('.component').filter(
    (n: any) => n.data('parent_vm') === vmId && !n.hasClass('component-hidden')
  ).toArray();
  if (!comps.length) return;

  const vmPos = vm.position();
  const vmBox = vm.boundingBox({ includeLabels: false, includeOverlays: false });
  const vmWidth = Math.max(70, vmBox.w || Number(vm.width()) || 120);
  const vmHeight = Math.max(50, vmBox.h || Number(vm.height()) || 70);
  const gap = 8;

  const widths = comps.map((comp: any) => {
    const box = comp.boundingBox({ includeLabels: true, includeOverlays: false });
    return Math.max(28, box.w || Number(comp.width()) || 34);
  });
  const totalWidth = widths.reduce((sum: number, width: number) => sum + width, 0) + gap * (comps.length - 1);
  const bottomY = vmPos.y + vmHeight / 2;

  if (totalWidth <= vmWidth + 12) {
    let x = vmPos.x - totalWidth / 2;
    comps.forEach((comp: any, i: number) => {
      const width = widths[i];
      comp.unlock();
      comp.position({ x: x + width / 2, y: bottomY });
      comp.lock();
      x += width + gap;
    });
    return;
  }

  const rowCount = Math.ceil(totalWidth / (vmWidth + 12));
  const rows: any[][] = Array.from({ length: Math.min(rowCount, comps.length) }, () => []);
  const rowWidths: number[] = rows.map(() => 0);
  comps.forEach((comp: any, i: number) => {
    const rowIndex = rowWidths.indexOf(Math.min(...rowWidths));
    rows[rowIndex].push({ comp, width: widths[i] });
    rowWidths[rowIndex] += widths[i] + (rows[rowIndex].length > 1 ? gap : 0);
  });

  rows.forEach((row, rowIndex) => {
    const rowWidth = row.reduce((sum, item) => sum + item.width, 0) + gap * Math.max(0, row.length - 1);
    let x = vmPos.x - rowWidth / 2;
    const y = bottomY + rowIndex * 24;
    row.forEach(({ comp, width }) => {
      comp.unlock();
      comp.position({ x: x + width / 2, y });
      comp.lock();
      x += width + gap;
    });
  });
}

/** Layout presets matching fabvis layouts.py */
const LAYOUTS: Record<string, any> = {
  dagre: { name: 'dagre', rankDir: 'TB', rankSep: 100, nodeSep: 60, animate: true, animationDuration: 300 },
  cola: { name: 'cola', nodeSpacing: 60, animate: true, maxSimulationTime: 2000 },
  breadthfirst: { name: 'breadthfirst', spacingFactor: 1.5, animate: true, animationDuration: 300 },
  grid: { name: 'grid', condense: true, animate: true, animationDuration: 300 },
  concentric: { name: 'concentric', minNodeSpacing: 50, animate: true, animationDuration: 300 },
  cose: { name: 'cose', animate: true, animationDuration: 300 },
};

export interface ContextMenuAction {
  type: 'terminal' | 'delete' | 'delete-slice' | 'delete-component' | 'delete-facility-port' | 'save-vm-template' | 'apply-recipe' | 'open-client' | 'open-boot-log' | 'run-boot-config' | 'run-boot-config-node' | 'chi-ssh' | 'chi-reboot' | 'chi-stop' | 'chi-start' | 'chi-delete' | 'chi-apply-recipe' | 'chi-assign-fip' | 'chi-run-boot-config' | 'chi-open-web' | 'chi-save-template';
  elements: Record<string, string>[];
  sliceNames?: string[];
  nodeName?: string;
  componentName?: string;
  fpName?: string;
  recipeName?: string;
  port?: number;
  instanceId?: string;
  instanceSite?: string;
  instanceName?: string;
}

export function isTopologyElementDeletable(el: Record<string, any>): boolean {
  const elementType = String(el.element_type || '');
  const testbed = String(el.testbed || '').toLowerCase();
  const deletableFlag = String(el.deletable ?? '').toLowerCase();
  const name = String(el.name || '').toLowerCase();
  const netType = String(el.net_type || el.type || '').toLowerCase();
  const compactName = name.replace(/[^a-z0-9]/g, '');

  if (testbed === 'shared') return false;
  if (elementType === 'fabnet-internet' || elementType === 'chameleon_draft' || elementType === 'chameleon_cluster') return false;

  if (elementType === 'facility-port') return true;
  if (deletableFlag === 'false') return false;
  if (elementType === 'node' || elementType === 'port-mirror') return true;
  if (elementType === 'network') {
    if (compactName.startsWith('fabnetv4') || compactName.startsWith('fabnetv6') || netType.includes('fabnet')) return false;
    if (testbed === 'chameleon') {
      return deletableFlag === 'true' || Boolean(el.resource_id);
    }
    return true;
  }
  if (testbed === 'chameleon' && elementType === 'chameleon_resource') {
    return Boolean(el.resource_id);
  }
  if (elementType === 'chameleon_instance') {
    return String(el.status || '').toUpperCase() === 'DRAFT' && Boolean(el.node_id || el.planned_node_id);
  }
  return false;
}

interface CytoscapeGraphProps {
  graph: CyGraph | null;
  layout: string;
  dark: boolean;
  sliceData: SliceData | null;
  recipes?: RecipeSummary[];
  bootNodeStatus?: Record<string, 'pending' | 'running' | 'done' | 'error'>;
  /** Optional Chameleon graph elements to merge (from /api/chameleon/graph) */
  chameleonGraph?: { nodes: any[]; edges: any[] } | null;
  /** When true, update element data in-place; topology additions/removals still re-layout. */
  preserveLayout?: boolean;
  onLayoutChange: (layout: string) => void;
  onNodeClick: (data: Record<string, string>) => void;
  onEdgeClick: (data: Record<string, string>) => void;
  onBackgroundClick: () => void;
  onContextAction: (action: ContextMenuAction) => void;
}

interface MenuState {
  x: number;
  y: number;
  selected: Record<string, string>[];
  sliceName?: string;  // set when right-clicking a slice compound node
}

type GraphElementInput = {
  data?: Record<string, any>;
  classes?: string;
};

type NormalizedGraphElement = {
  data: Record<string, any>;
  classes?: string;
};

export interface SanitizedGraphElements {
  nodes: NormalizedGraphElement[];
  edges: NormalizedGraphElement[];
  droppedEdges: Array<{ id: string; source: string; target: string; reason: string }>;
  droppedNodes: Array<{ id: string; reason: string }>;
}

export interface GraphElementIdSnapshot {
  nodeIds: string[];
  edgeIds: string[];
}

function elementId(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

export function graphElementIdSnapshot(
  nodes: GraphElementInput[],
  edges: GraphElementInput[],
): GraphElementIdSnapshot {
  return {
    nodeIds: nodes.map((node) => elementId(node.data?.id)).filter(Boolean).sort(),
    edgeIds: edges.map((edge) => elementId(edge.data?.id)).filter(Boolean).sort(),
  };
}

export function graphElementIdsChanged(previous: GraphElementIdSnapshot | null, next: GraphElementIdSnapshot): boolean {
  if (!previous) return true;
  if (previous.nodeIds.length !== next.nodeIds.length || previous.edgeIds.length !== next.edgeIds.length) return true;
  return previous.nodeIds.some((id, index) => id !== next.nodeIds[index])
    || previous.edgeIds.some((id, index) => id !== next.edgeIds[index]);
}

export function sanitizeGraphElements(
  nodes: GraphElementInput[],
  edges: GraphElementInput[],
): SanitizedGraphElements {
  const normalizedNodes: NormalizedGraphElement[] = [];
  const droppedNodes: SanitizedGraphElements['droppedNodes'] = [];
  const nodeIds = new Set<string>();

  for (const node of nodes) {
    const data = { ...(node.data ?? {}) };
    const id = elementId(data.id);
    if (!id) {
      droppedNodes.push({ id: '', reason: 'missing node id' });
      continue;
    }
    if (nodeIds.has(id)) {
      droppedNodes.push({ id, reason: 'duplicate node id' });
      continue;
    }
    data.id = id;
    nodeIds.add(id);
    normalizedNodes.push({ data, classes: node.classes });
  }

  for (const node of normalizedNodes) {
    const parent = elementId(node.data.parent);
    if (parent && !nodeIds.has(parent)) {
      delete node.data.parent;
    } else if (parent) {
      node.data.parent = parent;
    }
  }

  const normalizedEdges: NormalizedGraphElement[] = [];
  const droppedEdges: SanitizedGraphElements['droppedEdges'] = [];
  const edgeIds = new Set<string>();

  edges.forEach((edge, index) => {
    const data = { ...(edge.data ?? {}) };
    const source = elementId(data.source);
    const target = elementId(data.target);
    const id = elementId(data.id) || `edge:${source}->${target}:${index}`;

    if (!source || !target) {
      droppedEdges.push({ id, source, target, reason: 'missing endpoint' });
      return;
    }
    if (!nodeIds.has(source) || !nodeIds.has(target)) {
      droppedEdges.push({ id, source, target, reason: 'endpoint node not found' });
      return;
    }
    if (edgeIds.has(id)) {
      droppedEdges.push({ id, source, target, reason: 'duplicate edge id' });
      return;
    }

    data.id = id;
    data.source = source;
    data.target = target;
    edgeIds.add(id);
    normalizedEdges.push({ data, classes: edge.classes });
  });

  return { nodes: normalizedNodes, edges: normalizedEdges, droppedEdges, droppedNodes };
}

function warnAboutDroppedGraphElements(sanitized: SanitizedGraphElements) {
  if (sanitized.droppedNodes.length === 0 && sanitized.droppedEdges.length === 0) return;
  console.warn('Dropped invalid topology elements before rendering', {
    nodes: sanitized.droppedNodes,
    edges: sanitized.droppedEdges,
  });
}

export default React.memo(function CytoscapeGraph({
  graph,
  layout,
  dark,
  sliceData,
  recipes,
  bootNodeStatus,
  onLayoutChange,
  onNodeClick,
  onEdgeClick,
  onBackgroundClick,
  onContextAction,
  chameleonGraph,
  preserveLayout,
}: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const prevGraphRef = useRef<CyGraph | null>(null);
  const prevElementIdsRef = useRef<GraphElementIdSnapshot | null>(null);
  const prevLayoutRef = useRef<string>(layout);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [showComponents, setShowComponents] = useState(true);
  const showComponentsRef = useRef(showComponents);
  showComponentsRef.current = showComponents;
  const [showSliceBox, setShowSliceBox] = useState(true);
  const showSliceBoxRef = useRef(showSliceBox);
  showSliceBoxRef.current = showSliceBox;
  const [showFabnetInternet, setShowFabnetInternet] = useState(true);
  const showFabnetInternetRef = useRef(showFabnetInternet);
  showFabnetInternetRef.current = showFabnetInternet;

  // PNG save dialog state
  const [pngDialog, setPngDialog] = useState<{ dataUrl: string } | null>(null);
  const [pngFilename, setPngFilename] = useState('fabric-slice.png');
  const [pngSavePath, setPngSavePath] = useState('/home/fabric/work');
  const [pngSaving, setPngSaving] = useState(false);
  const [pngSaveResult, setPngSaveResult] = useState<{ ok: boolean; message: string } | null>(null);

  // Close context menu on clicks or escape
  const menuOpenTime = useRef(0);
  useEffect(() => {
    if (!menu) return;
    menuOpenTime.current = Date.now();
    const close = () => {
      if (Date.now() - menuOpenTime.current < 100) return;
      setMenu(null);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null); };
    window.addEventListener('mousedown', close);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  // Initialize cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      style: buildStylesheet(dark),
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.3,
      selectionType: 'additive',
      boxSelectionEnabled: true,
    });

    cyRef.current = cy;

    // Keep component badges attached to their parent VM during drag
    cy.on('drag', '.vm, .chameleon-instance', (e: any) => {
      const vm = e.target;
      const vmId = vm.id();
      const comps = cy.nodes('.component').filter((n: any) => n.data('parent_vm') === vmId && !n.hasClass('component-hidden'));
      if (comps.empty()) return;
      positionComponentsForVm(cy, vmId, comps.toArray());
    });

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // Resize cytoscape when container dimensions change
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => {
      cyRef.current?.resize();
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Update stylesheet when dark mode changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.style(buildStylesheet(dark) as any);
  }, [dark]);

  // Handle left-click events
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const handleNodeClick = (e: EventObject) => {
      const node = e.target;
      // Component badge clicked — delegate to parent VM
      if (node.hasClass('component')) {
        const vmId = node.data('parent_vm');
        if (vmId) {
          const vm = cy.getElementById(vmId);
          if (!vm.empty()) {
            onNodeClick(vm.data());
            return;
          }
        }
      }
      onNodeClick(node.data());
    };
    const handleEdgeClick = (e: EventObject) => {
      onEdgeClick(e.target.data());
    };
    const handleBgClick = (e: EventObject) => {
      if (e.target === cy) onBackgroundClick();
    };

    const handleDblClick = (e: EventObject) => {
      const data = e.target.data();
      // Chameleon: double-click ACTIVE instance → SSH
      if (data.element_type === 'chameleon_instance' && data.status === 'ACTIVE' && data.instance_id && (data.floating_ip || data.ip)) {
        onContextActionRef.current({ type: 'chi-ssh', elements: [], instanceId: data.instance_id, instanceSite: data.site, instanceName: data.name || data.label });
      }
      // FABRIC: double-click VM with IP → terminal
      else if (data.element_type === 'node' && data.management_ip) {
        onContextActionRef.current({ type: 'terminal', elements: [data] });
      }
    };

    cy.on('tap', 'node', handleNodeClick);
    cy.on('tap', 'edge', handleEdgeClick);
    cy.on('tap', handleBgClick);
    cy.on('dbltap', 'node', handleDblClick);

    return () => {
      cy.off('tap', 'node', handleNodeClick);
      cy.off('tap', 'edge', handleEdgeClick);
      cy.off('tap', handleBgClick);
      cy.off('dbltap', 'node', handleDblClick);
    };
  }, [onNodeClick, onEdgeClick, onBackgroundClick]);

  // Right-click context menu: prevent native menu + show custom one
  const onContextActionRef = useRef(onContextAction);
  onContextActionRef.current = onContextAction;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const suppress = (e: MouseEvent) => { e.preventDefault(); };
    container.addEventListener('contextmenu', suppress);

    const handleRightClick = (e: MouseEvent) => {
      if (e.button !== 2) return;

      const cy = cyRef.current;
      if (!cy) return;

      const r = (cy as any)._private.renderer;
      if (!r) return;
      const pos = r.projectIntoViewport(e.clientX, e.clientY);
      const near = r.findNearestElement(pos[0], pos[1], true, false);

      if (!near || near.isEdge()) return;

      // Container/cluster nodes don't get a context menu
      if (near.hasClass('chameleon-cluster')) return;
      if (near.hasClass('composite-member')) return;

      // Right-clicked a slice compound node — show slice-level menu
      if (near.hasClass('slice')) {
        const sliceName = near.data('label') || near.data('name') || near.id();
        setMenu({ x: e.clientX, y: e.clientY, selected: [], sliceName });
        return;
      }

      // If right-clicked a component badge, target its parent VM instead
      let target = near;
      if (near.hasClass('component')) {
        const vmId = near.data('parent_vm');
        if (vmId) {
          const vm = cy.getElementById(vmId);
          if (!vm.empty()) target = vm;
          else return;
        } else return;
      }

      if (!target.selected()) {
        cy.elements().unselect();
        target.select();
      }

      const selected = cy.nodes(':selected').filter((n: any) => !n.hasClass('slice') && !n.hasClass('component'));
      if (selected.length === 0) return;

      const items: Record<string, string>[] = [];
      selected.forEach((n: any) => { items.push(n.data()); });
      setMenu({ x: e.clientX, y: e.clientY, selected: items });
    };

    container.addEventListener('mouseup', handleRightClick);

    return () => {
      container.removeEventListener('contextmenu', suppress);
      container.removeEventListener('mouseup', handleRightClick);
    };
  }, []);

  // Update graph data
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (!graph && !chameleonGraph) {
      cy.elements().remove();
      prevGraphRef.current = null;
      prevElementIdsRef.current = null;
      return;
    }

    // Build the full element set (FABRIC + optional Chameleon)
    const allNodes = [
      ...(graph?.nodes ?? []),
      ...(chameleonGraph?.nodes ?? []),
    ];
    const allEdges = [
      ...(graph?.edges ?? []),
      ...(chameleonGraph?.edges ?? []),
    ];
    const sanitized = sanitizeGraphElements(allNodes, allEdges);
    warnAboutDroppedGraphElements(sanitized);
    const allRenderableNodes = sanitized.nodes;
    const allRenderableEdges = sanitized.edges;
    const nextElementIds = graphElementIdSnapshot(allRenderableNodes, allRenderableEdges);
    const topologyChanged = graphElementIdsChanged(prevElementIdsRef.current, nextElementIds);

    // Determine whether we can do a stable in-place update:
    // preserveLayout is requested AND the graph already has elements AND layout algorithm hasn't changed
    const layoutChanged = layout !== prevLayoutRef.current;
    prevLayoutRef.current = layout;
    const canPreserve = preserveLayout && !layoutChanged && prevGraphRef.current && cy.elements().length > 0;

    if (canPreserve) {
      // --- Stable update: diff data in-place without re-running layout ---
      cy.startBatch();

      const newNodeIds = new Set(allRenderableNodes.map(n => n.data.id));
      const newEdgeIds = new Set(allRenderableEdges.map(e => e.data.id));

      // Update existing nodes or add new ones
      const addedElements: cytoscape.ElementDefinition[] = [];
      for (const n of allRenderableNodes) {
        const existing = cy.getElementById(n.data.id);
        if (existing.length > 0) {
          // Update data attributes (state colors, labels, etc.) without moving
          existing.data(n.data);
          // Update visual classes (preserves position)
          if (n.classes) existing.classes(n.classes);
        } else {
          addedElements.push({ group: 'nodes' as const, data: n.data, classes: n.classes });
        }
      }

      // Update existing edges or add new ones
      for (const e of allRenderableEdges) {
        const existing = cy.getElementById(e.data.id);
        if (existing.length > 0) {
          existing.data(e.data);
          if (e.classes) existing.classes(e.classes);
        } else {
          addedElements.push({ group: 'edges' as const, data: e.data, classes: e.classes });
        }
      }

      // Remove elements that no longer exist in the new graph
      cy.nodes().forEach(n => {
        if (!newNodeIds.has(n.id())) n.remove();
      });
      cy.edges().forEach(e => {
        if (!newEdgeIds.has(e.id())) e.remove();
      });

      // Add genuinely new elements
      if (addedElements.length > 0) {
        cy.add(addedElements);
      }

      cy.endBatch();

      // Re-apply visibility toggles
      applyComponentVisibility(cy, showComponentsRef.current);
      applySliceBoxVisibility(cy, showSliceBoxRef.current);
      applyFabnetInternetVisibility(cy, showFabnetInternetRef.current);

      // State-only updates keep positions; topology edits need layout so new
      // nodes such as facility ports are placed on the visible canvas.
      if (topologyChanged) {
        const layoutElements = cy.elements().not('.component');
        const lay = layoutElements.layout(LAYOUTS[layout] || LAYOUTS.dagre);
        lay.on('layoutstop', () => {
          if (showComponentsRef.current) {
            positionComponentsAtVmEdge(cy);
          }
          setTimeout(() => cy.fit(undefined, 30), 100);
        });
        lay.run();
      } else if (showComponentsRef.current) {
        positionComponentsAtVmEdge(cy);
      }
    } else {
      // --- Full rebuild: remove everything and re-layout ---
      cy.elements().remove();

      const elements: cytoscape.ElementDefinition[] = [
        ...allRenderableNodes.map((n) => ({ group: 'nodes' as const, data: n.data, classes: n.classes })),
        ...allRenderableEdges.map((e) => ({ group: 'edges' as const, data: e.data, classes: e.classes })),
      ];

      cy.add(elements);

      // Apply component visibility before layout
      applyComponentVisibility(cy, showComponentsRef.current);
      // Apply slice box visibility before layout
      applySliceBoxVisibility(cy, showSliceBoxRef.current);
      // Apply fabnet internet visibility before layout
      applyFabnetInternetVisibility(cy, showFabnetInternetRef.current);

      // Run layout on non-component elements; then position components at VM edges
      const layoutElements = cy.elements().not('.component');
      const lay = layoutElements.layout(LAYOUTS[layout] || LAYOUTS.dagre);
      lay.on('layoutstop', () => {
        if (showComponentsRef.current) {
          positionComponentsAtVmEdge(cy);
        }
        setTimeout(() => cy.fit(undefined, 30), 100);
      });
      lay.run();
    }

    prevGraphRef.current = graph;
    prevElementIdsRef.current = nextElementIds;
  }, [graph, chameleonGraph, layout, preserveLayout]);

  // Apply boot config status classes to VM nodes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !bootNodeStatus) return;
    const bootClasses = ['boot-pending', 'boot-running', 'boot-done', 'boot-error'];
    cy.nodes('.vm').forEach((node) => {
      const name = node.data('name');
      const status = bootNodeStatus[name];
      // Remove all boot classes first
      for (const cls of bootClasses) node.removeClass(cls);
      if (status) node.addClass(`boot-${status}`);
    });
  }, [bootNodeStatus, graph]);

  // Toggle component visibility
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    applyComponentVisibility(cy, showComponents);
    if (showComponents) {
      positionComponentsAtVmEdge(cy);
    }
  }, [showComponents]);

  // Toggle slice box visibility
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    applySliceBoxVisibility(cy, showSliceBox);
  }, [showSliceBox]);

  // Toggle fabnet internet node visibility
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    applyFabnetInternetVisibility(cy, showFabnetInternet);
  }, [showFabnetInternet]);

  const handleFit = useCallback(() => {
    cyRef.current?.fit(undefined, 30);
  }, []);

  const handleExport = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const exportBg = dark ? '#1a1a2e' : '#ffffff';
    const dataUrl = cy.png({ full: true, scale: 2, bg: exportBg });
    // Derive a default filename from the slice name if available
    const sliceName = sliceData?.name || 'fabric-slice';
    const safeName = sliceName.replace(/[^a-zA-Z0-9_-]/g, '_');
    setPngFilename(`${safeName}.png`);
    setPngSaveResult(null);
    setPngDialog({ dataUrl });
  }, [dark, sliceData]);

  const handlePngSave = useCallback(async () => {
    if (!pngDialog) return;
    setPngSaving(true);
    setPngSaveResult(null);
    try {
      // Convert data URL to File
      const res = await fetch(pngDialog.dataUrl);
      const blob = await res.blob();
      const file = new File([blob], pngFilename, { type: 'image/png' });
      await api.uploadFiles(pngSavePath, [file]);
      setPngSaveResult({ ok: true, message: `Saved to ${pngSavePath}/${pngFilename}` });
    } catch (err: any) {
      setPngSaveResult({ ok: false, message: err.message || 'Save failed' });
    } finally {
      setPngSaving(false);
    }
  }, [pngDialog, pngFilename, pngSavePath]);

  // Context menu helpers
  const hasUsableAddress = (value: unknown) => {
    const text = String(value ?? '').trim();
    return !!text && !['none', 'null', 'undefined', '-', '—'].includes(text.toLowerCase());
  };
  const liveFabricNodeByName = new Map((sliceData?.nodes || []).map(node => [node.name, node]));
  const withLiveFabricRuntime = (el: Record<string, string>): Record<string, string> => {
    if (el.element_type !== 'node') return el;
    const live = liveFabricNodeByName.get(el.name || el.label || '');
    if (!live) return el;
    return {
      ...el,
      site: el.site || live.site || '',
      image: el.image || live.image || '',
      username: el.username || live.username || '',
      reservation_state: el.reservation_state || live.reservation_state || '',
      management_ip: hasUsableAddress(el.management_ip) ? el.management_ip : (live.management_ip || ''),
    };
  };
  const selectedWithRuntime = menu?.selected.map(withLiveFabricRuntime) ?? [];
  const currentSliceVmsWithIp = (sliceData?.nodes || [])
    .filter((node) => hasUsableAddress(node.management_ip))
    .map((node): Record<string, string> => ({
      id: node.name,
      element_type: 'node',
      name: node.name,
      label: node.name,
      site: node.site,
      management_ip: node.management_ip,
      username: node.username,
      reservation_state: node.reservation_state,
      image: node.image,
    }));
  const vmsWithIp = selectedWithRuntime.filter(
    (el) => el.element_type === 'node' && hasUsableAddress(el.management_ip)
  );
  const sliceVmsWithIp = menu?.sliceName ? currentSliceVmsWithIp : [];
  const contextualSliceVmsWithIp = !menu?.sliceName && selectedWithRuntime.length > 0
    ? currentSliceVmsWithIp
    : [];
  const terminalTargetsForMenu = vmsWithIp.length > 0 ? vmsWithIp : contextualSliceVmsWithIp;
  const deletable = menu?.selected.filter(
    isTopologyElementDeletable
  ) ?? [];

  const singleVm = selectedWithRuntime.length === 1 && selectedWithRuntime[0].element_type === 'node'
    ? selectedWithRuntime[0] : null;
  const vmComponents = singleVm
    ? (sliceData?.nodes.find((n) => n.name === singleVm.name)?.components ?? [])
    : [];

  // Chameleon instance detection
  const chameleonInstances = (menu?.selected || []).filter(
    (el: any) => el.element_type === 'chameleon_instance' && el.status && el.status !== 'DRAFT' && el.instance_id
  );
  const singleChi = chameleonInstances.length === 1 ? chameleonInstances[0] : null;

  const handleTerminal = () => {
    const terminalTargets = menu?.sliceName ? sliceVmsWithIp : terminalTargetsForMenu;
    if (terminalTargets.length > 0) {
      onContextAction({ type: 'terminal', elements: terminalTargets });
    }
    setMenu(null);
  };

  const handleDelete = () => {
    if (deletable.length > 0) {
      onContextAction({ type: 'delete', elements: deletable });
    }
    setMenu(null);
  };

  const handleDeleteComponent = (nodeName: string, compName: string) => {
    onContextAction({ type: 'delete-component', elements: [], nodeName, componentName: compName });
    setMenu(null);
  };

  return (
    <div className="graph-panel" data-testid="topology-panel">
      <div className="cytoscape-container" ref={containerRef} data-help-id="topology.graph" data-testid="topology-graph" />
      <div className="graph-controls" data-testid="topology-controls">
        <label>Layout:</label>
        <select value={layout} onChange={(e) => onLayoutChange(e.target.value)} data-help-id="topology.layout" data-testid="topology-layout-select">
          <option value="dagre" title="Hierarchical layout — best for tree topologies">dagre</option>
          <option value="cola" title="Force-directed layout — good for general topologies">cola</option>
          <option value="breadthfirst" title="Tree layout from root — good for hierarchical networks">breadthfirst</option>
          <option value="grid" title="Aligned grid — good for regular topologies">grid</option>
          <option value="concentric" title="Radial circles — good for star topologies">concentric</option>
          <option value="cose" title="Physics simulation — good for organic layouts">cose</option>
        </select>
        <button onClick={handleFit} title="Fit graph to viewport" data-help-id="topology.fit" data-testid="topology-fit">Fit</button>
        <button onClick={handleExport} title="Save graph as PNG image" data-help-id="topology.export" data-testid="topology-export">Save PNG</button>
        <span className="graph-controls-sep" />
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showSliceBox}
            onChange={(e) => setShowSliceBox(e.target.checked)}
            data-testid="topology-toggle-slice-box"
          />
          Slice Box
        </label>
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showComponents}
            onChange={(e) => setShowComponents(e.target.checked)}
            data-testid="topology-toggle-components"
          />
          Components
        </label>
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showFabnetInternet}
            onChange={(e) => setShowFabnetInternet(e.target.checked)}
            data-testid="topology-toggle-fabnet-internet"
          />
          FABNet Internet
        </label>
      </div>

      {menu && menu.sliceName && (
        <div
          className="graph-context-menu"
          style={{ left: menu.x, top: menu.y }}
          data-testid="topology-context-menu"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="graph-context-menu-label">{menu.sliceName}</div>
          {sliceVmsWithIp.length > 0 && (
            <button className="graph-context-menu-item" data-testid="topology-context-open-terminal" onClick={handleTerminal}>
              ▸ Open Terminal{sliceVmsWithIp.length > 1 ? ` (${sliceVmsWithIp.length})` : ''}
            </button>
          )}
          <button className="graph-context-menu-item" data-testid="topology-context-open-build-log" onClick={() => {
            onContextActionRef.current({ type: 'open-boot-log', elements: [], sliceNames: [menu.sliceName!] });
            setMenu(null);
          }}>
            {'\u2630'} Open Build Log
          </button>
          <button className="graph-context-menu-item" data-testid="topology-context-run-post-boot" onClick={() => {
            onContextActionRef.current({ type: 'run-boot-config', sliceNames: [menu.sliceName!], elements: [] });
            setMenu(null);
          }}>
            ↻ Run Post-Boot Config
          </button>
        </div>
      )}
      {menu && !menu.sliceName && (
        <div
          className="graph-context-menu"
          style={{ left: menu.x, top: menu.y }}
          data-testid="topology-context-menu"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          {menu.selected.length > 1 && (
            <div className="graph-context-menu-label">
              {menu.selected.length} selected
            </div>
          )}
          {terminalTargetsForMenu.length > 0 && (
            <button className="graph-context-menu-item" data-testid="topology-context-open-terminal" onClick={handleTerminal}>
              ▸ Open Terminal{terminalTargetsForMenu.length > 1 ? ` (${terminalTargetsForMenu.length})` : ''}
            </button>
          )}
          {vmsWithIp.length === 1 && (
            <button className="graph-context-menu-item" data-testid="topology-context-run-boot-config" onClick={() => {
              onContextActionRef.current({ type: 'run-boot-config-node', elements: vmsWithIp, nodeName: vmsWithIp[0].name });
              setMenu(null);
            }}>
              ↻ Run Boot Config
            </button>
          )}
          {singleVm && singleVm.management_ip && (
            <button className="graph-context-menu-item" data-testid="topology-context-open-web-app" onClick={() => {
              onContextAction({ type: 'open-client', elements: [singleVm], port: 80 });
              setMenu(null);
            }}>
              ▸ Open in Web Apps
            </button>
          )}
          {vmComponents.length > 0 && vmsWithIp.length > 0 && (
            <div className="graph-context-menu-sep" />
          )}
          {vmComponents.length > 0 && singleVm && (
            <>
              <div className="graph-context-menu-label">Components</div>
              {vmComponents.map((comp) => (
                <button
                  key={comp.name}
                  className="graph-context-menu-item component-delete"
                  data-testid="topology-context-delete-component"
                  data-component-name={comp.name}
                  onClick={() => handleDeleteComponent(singleVm.name, comp.name)}
                >
                  <span className="component-info">{comp.name} <span className="component-model">{comp.model}</span></span>
                  <span className="component-delete-icon">✕</span>
                </button>
              ))}
            </>
          )}
          {singleVm && (
            <>
              {(vmsWithIp.length > 0 || vmComponents.length > 0) && (
                <div className="graph-context-menu-sep" />
              )}
              <button
                className="graph-context-menu-item"
                data-testid="topology-context-save-vm-template"
                onClick={() => {
                  onContextAction({ type: 'save-vm-template', elements: [singleVm], nodeName: singleVm.name });
                  setMenu(null);
                }}
              >
                ⚙ Save as VM Template
              </button>
            </>
          )}
          {singleVm && singleVm.management_ip && recipes && recipes.length > 0 && (() => {
            const vmImage = singleVm.image || '';
            const compatible = recipes.filter((r) => {
              if (!r.starred) return false;
              const patterns = r.image_patterns || {};
              return Object.keys(patterns).some((key) =>
                key === '*' || vmImage.toLowerCase().includes(key.toLowerCase())
              );
            });
            return (
              <>
                <div className="graph-context-menu-sep" />
                <div className="graph-context-menu-label">Recipes</div>
                {compatible.length > 0 ? compatible.map((r) => (
                  <button
                    key={r.dir_name}
                    className="graph-context-menu-item"
                    onClick={() => {
                      onContextAction({ type: 'apply-recipe', elements: [singleVm], nodeName: singleVm.name, recipeName: r.dir_name });
                      setMenu(null);
                    }}
                  >
                    ▸ {r.name}
                  </button>
                )) : (
                  <div className="graph-context-menu-item" style={{ opacity: 0.5, cursor: 'default' }}>
                    No recipes for this image
                  </div>
                )}
              </>
            );
          })()}
          {deletable.length > 0 && (singleVm || vmsWithIp.length > 0 || vmComponents.length > 0) && (
            <div className="graph-context-menu-sep" />
          )}
          {deletable.length > 0 && (
            <button className="graph-context-menu-item danger" data-testid="topology-context-delete" onClick={handleDelete}>
              ✕ Delete{deletable.length > 1 ? ` (${deletable.length})` : ''}
            </button>
          )}
          {/* Chameleon instance context menu items */}
          {singleChi && (singleChi.status === 'ACTIVE' && (singleChi.floating_ip || singleChi.ip)) && (
            <button className={`graph-context-menu-item${!singleChi.ssh_ready ? ' graph-context-menu-dim' : ''}`} data-testid="topology-context-chameleon-terminal" onClick={() => {
              onContextAction({ type: 'chi-ssh', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              {singleChi.ssh_ready ? '▸ Open Terminal' : '▸ Open Terminal (Connecting...)'}
            </button>
          )}
          {/* Open in Web Apps — floating IP instances */}
          {singleChi && singleChi.status === 'ACTIVE' && singleChi.floating_ip && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-open-web" onClick={() => {
              onContextAction({ type: 'chi-open-web', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ▸ Open in Web Apps
            </button>
          )}
          {/* Run Boot Config */}
          {singleChi && singleChi.status === 'ACTIVE' && (singleChi.floating_ip || singleChi.ip) && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-run-boot-config" onClick={() => {
              onContextAction({ type: 'chi-run-boot-config', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ↻ Run Boot Config
            </button>
          )}
          {/* Assign Floating IP — for instances without one */}
          {singleChi && singleChi.status === 'ACTIVE' && !singleChi.floating_ip && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-assign-fip" onClick={() => {
              onContextAction({ type: 'chi-assign-fip', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              + Assign Floating IP
            </button>
          )}
          {/* Recipes — match by image */}
          {singleChi && singleChi.status === 'ACTIVE' && (singleChi.floating_ip || singleChi.ip) && recipes && recipes.length > 0 && (() => {
            const chiImage = singleChi.image || '';
            const compatible = recipes.filter((r) => {
              if (!r.starred) return false;
              const patterns = r.image_patterns || {};
              return Object.keys(patterns).some((key) =>
                key === '*' || chiImage.toLowerCase().includes(key.toLowerCase())
              );
            });
            if (compatible.length === 0) return null;
            return (
              <>
                <div className="graph-context-menu-sep" />
                <div className="graph-context-menu-label">Recipes</div>
                {compatible.map((r) => (
                  <button
                    key={r.dir_name}
                    className="graph-context-menu-item"
                    onClick={() => {
                      onContextAction({ type: 'chi-apply-recipe', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label, recipeName: r.dir_name });
                      setMenu(null);
                    }}
                  >
                    ▸ {r.name}
                  </button>
                ))}
              </>
            );
          })()}
          {singleChi && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-save-template" onClick={() => {
              onContextAction({ type: 'chi-save-template', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ⚙ Save as VM Template
            </button>
          )}
          <div className="graph-context-menu-sep" />
          {singleChi && (singleChi.status === 'ACTIVE' || singleChi.status === 'SHUTOFF') && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-reboot" onClick={() => {
              onContextAction({ type: 'chi-reboot', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ↻ Reboot
            </button>
          )}
          {singleChi && singleChi.status === 'ACTIVE' && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-stop" onClick={() => {
              onContextAction({ type: 'chi-stop', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ◼ Stop
            </button>
          )}
          {singleChi && singleChi.status === 'SHUTOFF' && (
            <button className="graph-context-menu-item" data-testid="topology-context-chameleon-start" onClick={() => {
              onContextAction({ type: 'chi-start', elements: [], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
              setMenu(null);
            }}>
              ▶ Start
            </button>
          )}
          {singleChi && (
            <>
              <div className="graph-context-menu-sep" />
              <button className="graph-context-menu-item danger" data-testid="topology-context-chameleon-delete" onClick={() => {
                onContextAction({ type: 'chi-delete', elements: [singleChi], instanceId: singleChi.instance_id, instanceSite: singleChi.site, instanceName: singleChi.name || singleChi.label });
                setMenu(null);
              }}>
                ✕ Delete Instance
              </button>
            </>
          )}
        </div>
      )}

      {/* PNG save-to-container dialog */}
      {pngDialog && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(0,0,0,0.5)',
        }} onClick={() => { if (!pngSaving) setPngDialog(null); }}>
          <div style={{
            background: dark ? '#1e1e2e' : '#fff',
            color: dark ? '#e0e0e0' : '#222',
            border: `1px solid ${dark ? '#444' : '#ccc'}`,
            borderRadius: 8, padding: '20px 24px', minWidth: 380, maxWidth: 480,
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 16 }}>Save PNG to Container</div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4, opacity: 0.7 }}>Filename</label>
              <input
                style={{
                  width: '100%', padding: '6px 8px', borderRadius: 4, border: `1px solid ${dark ? '#555' : '#ccc'}`,
                  background: dark ? '#2a2a3e' : '#f8f8f8', color: 'inherit', fontSize: 13, boxSizing: 'border-box',
                }}
                value={pngFilename}
                onChange={e => setPngFilename(e.target.value)}
                disabled={pngSaving}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4, opacity: 0.7 }}>Save to directory</label>
              <input
                style={{
                  width: '100%', padding: '6px 8px', borderRadius: 4, border: `1px solid ${dark ? '#555' : '#ccc'}`,
                  background: dark ? '#2a2a3e' : '#f8f8f8', color: 'inherit', fontSize: 13, boxSizing: 'border-box',
                }}
                value={pngSavePath}
                onChange={e => setPngSavePath(e.target.value)}
                disabled={pngSaving}
              />
            </div>

            {/* Thumbnail preview */}
            <div style={{ marginBottom: 16, textAlign: 'center' }}>
              <img
                src={pngDialog.dataUrl}
                alt="PNG preview"
                style={{ maxWidth: '100%', maxHeight: 150, borderRadius: 4, border: `1px solid ${dark ? '#444' : '#ddd'}` }}
              />
            </div>

            {pngSaveResult && (
              <div style={{
                fontSize: 12, marginBottom: 12, padding: '6px 10px', borderRadius: 4,
                background: pngSaveResult.ok ? (dark ? '#1a3a2a' : '#e8f5e9') : (dark ? '#3a1a1a' : '#fce4ec'),
                color: pngSaveResult.ok ? (dark ? '#66bb6a' : '#2e7d32') : (dark ? '#ef5350' : '#c62828'),
              }}>
                {pngSaveResult.message}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setPngDialog(null)}
                disabled={pngSaving}
                style={{
                  padding: '6px 14px', borderRadius: 4, border: `1px solid ${dark ? '#555' : '#ccc'}`,
                  background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: 13,
                }}
              >Cancel</button>
              <button
                onClick={handlePngSave}
                disabled={pngSaving || !pngFilename.trim()}
                style={{
                  padding: '6px 14px', borderRadius: 4, border: 'none',
                  background: '#5798bc', color: '#fff', cursor: 'pointer', fontSize: 13,
                  opacity: pngSaving || !pngFilename.trim() ? 0.6 : 1,
                }}
              >{pngSaving ? 'Saving...' : 'Save'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

/**
 * Show or hide the slice compound container node.
 * When hidden, child nodes are moved out of the compound parent so they
 * float freely; the slice node itself is hidden.
 * When shown, child nodes are re-parented and the slice node is revealed.
 */
function applySliceBoxVisibility(cy: Core, show: boolean) {
  cy.batch(() => {
    const sliceNodes = cy.nodes('.slice');
    if (sliceNodes.empty()) return;

    if (show) {
      sliceNodes.removeClass('slice-hidden');
      // Restore parent on children
      cy.nodes().forEach((n: any) => {
        const origParent = n.data('_orig_parent');
        if (origParent && n.data('parent') !== origParent) {
          n.move({ parent: origParent });
        }
      });
    } else {
      // Save original parent and remove it
      cy.nodes().forEach((n: any) => {
        const p = n.data('parent');
        if (p && cy.getElementById(p).hasClass('slice')) {
          n.data('_orig_parent', p);
          n.move({ parent: null });
        }
      });
      sliceNodes.addClass('slice-hidden');
    }
  });
}

/**
 * Show or hide component badge nodes and re-route edges accordingly.
 * When components are visible, edges go from component nodes to networks.
 * When hidden, edges fall back to the parent VM node.
 */
function applyComponentVisibility(cy: Core, show: boolean) {
  cy.batch(() => {
    const compNodes = cy.nodes('.component');

    if (show) {
      compNodes.removeClass('component-hidden');
      // Route edges from component nodes (restore original source)
      cy.edges().forEach((edge: any) => {
        const sourceComp = edge.data('source_comp');
        if (sourceComp && edge.data('source') !== sourceComp) {
          edge.move({ source: sourceComp });
        }
      });
    } else {
      compNodes.addClass('component-hidden');
      // Route edges from VM nodes (fallback source)
      cy.edges().forEach((edge: any) => {
        const sourceVm = edge.data('source_vm');
        if (sourceVm && edge.data('source') !== sourceVm) {
          edge.move({ source: sourceVm });
        }
      });
    }
  });
}

/**
 * Show or hide the synthetic FABRIC Internet node and its uplink edges.
 */
function applyFabnetInternetVisibility(cy: Core, show: boolean) {
  cy.batch(() => {
    const internetNode = cy.getElementById('fabnet-internet-v4');
    const internetEdges = cy.edges('.edge-fabnet-internet');
    if (show) {
      internetNode.removeClass('fabnet-internet-hidden');
      internetEdges.removeClass('edge-fabnet-internet-hidden');
    } else {
      internetNode.addClass('fabnet-internet-hidden');
      internetEdges.addClass('edge-fabnet-internet-hidden');
    }
  });
}

export { LAYOUTS };
