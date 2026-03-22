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
  const fpColor = dark ? '#ffa562' : '#ff8542';
  const fpNodeBg = dark ? '#3a2008' : '#fff3e0';
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
      'shape': 'diamond', 'width': 80, 'height': 70, 'background-color': fpNodeBg,
      'border-width': 2, 'border-color': fpColor, 'label': 'data(label)',
      'text-valign': 'center', 'text-halign': 'center', 'font-size': '9px',
      'text-wrap': 'wrap', 'text-max-width': '70px', 'color': fpColor,
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
    const vm = cy.getElementById(vmId);
    if (vm.empty()) continue;

    const vmPos = vm.position();
    const vmH = 70;  // fixed VM height from stylesheet

    // Spread components horizontally along the bottom edge
    const spacing = 50;
    const totalWidth = (comps.length - 1) * spacing;
    const startX = vmPos.x - totalWidth / 2;

    comps.forEach((comp: any, i: number) => {
      comp.unlock();
      comp.position({
        x: startX + i * spacing,
        y: vmPos.y + vmH / 2,  // bottom edge of VM
      });
      comp.lock();
    });
  }
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
  type: 'terminal' | 'delete' | 'delete-slice' | 'delete-component' | 'delete-facility-port' | 'save-vm-template' | 'apply-recipe' | 'open-client' | 'open-boot-log';
  elements: Record<string, string>[];
  sliceNames?: string[];
  nodeName?: string;
  componentName?: string;
  fpName?: string;
  recipeName?: string;
  port?: number;
}

interface CytoscapeGraphProps {
  graph: CyGraph | null;
  layout: string;
  dark: boolean;
  sliceData: SliceData | null;
  recipes?: RecipeSummary[];
  bootNodeStatus?: Record<string, 'pending' | 'running' | 'done' | 'error'>;
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
}: CytoscapeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
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
    cy.on('drag', '.vm', (e: any) => {
      const vm = e.target;
      const vmId = vm.id();
      const vmPos = vm.position();
      const comps = cy.nodes('.component').filter((n: any) => n.data('parent_vm') === vmId && !n.hasClass('component-hidden'));
      if (comps.empty()) return;

      const spacing = 50;
      const total = (comps.length - 1) * spacing;
      const startX = vmPos.x - total / 2;

      comps.forEach((comp: any, i: number) => {
        comp.unlock();
        comp.position({
          x: startX + i * spacing,
          y: vmPos.y + 35,
        });
        comp.lock();
      });
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

    cy.on('tap', 'node', handleNodeClick);
    cy.on('tap', 'edge', handleEdgeClick);
    cy.on('tap', handleBgClick);

    return () => {
      cy.off('tap', 'node', handleNodeClick);
      cy.off('tap', 'edge', handleEdgeClick);
      cy.off('tap', handleBgClick);
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
    if (!graph) { cy.elements().remove(); return; }

    cy.elements().remove();

    const elements: cytoscape.ElementDefinition[] = [
      ...graph.nodes.map((n) => ({
        group: 'nodes' as const,
        data: n.data,
        classes: n.classes,
      })),
      ...graph.edges.map((e) => ({
        group: 'edges' as const,
        data: e.data,
        classes: e.classes,
      })),
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
  }, [graph, layout]);

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
  const vmsWithIp = menu?.selected.filter(
    (el) => el.element_type === 'node' && el.management_ip
  ) ?? [];
  const deletable = menu?.selected.filter(
    (el) => el.element_type === 'node' || el.element_type === 'network' || el.element_type === 'facility-port' || el.element_type === 'port-mirror'
  ) ?? [];

  const singleVm = menu?.selected.length === 1 && menu.selected[0].element_type === 'node'
    ? menu.selected[0] : null;
  const vmComponents = singleVm
    ? (sliceData?.nodes.find((n) => n.name === singleVm.name)?.components ?? [])
    : [];

  const handleTerminal = () => {
    if (vmsWithIp.length > 0) {
      onContextAction({ type: 'terminal', elements: vmsWithIp });
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
    <div className="graph-panel">
      <div className="cytoscape-container" ref={containerRef} data-help-id="topology.graph" />
      <div className="graph-controls">
        <label>Layout:</label>
        <select value={layout} onChange={(e) => onLayoutChange(e.target.value)} data-help-id="topology.layout">
          <option value="dagre" title="Hierarchical layout — best for tree topologies">dagre</option>
          <option value="cola" title="Force-directed layout — good for general topologies">cola</option>
          <option value="breadthfirst" title="Tree layout from root — good for hierarchical networks">breadthfirst</option>
          <option value="grid" title="Aligned grid — good for regular topologies">grid</option>
          <option value="concentric" title="Radial circles — good for star topologies">concentric</option>
          <option value="cose" title="Physics simulation — good for organic layouts">cose</option>
        </select>
        <button onClick={handleFit} title="Fit graph to viewport" data-help-id="topology.fit">Fit</button>
        <button onClick={handleExport} title="Save graph as PNG image" data-help-id="topology.export">Save PNG</button>
        <span className="graph-controls-sep" />
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showSliceBox}
            onChange={(e) => setShowSliceBox(e.target.checked)}
          />
          Slice Box
        </label>
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showComponents}
            onChange={(e) => setShowComponents(e.target.checked)}
          />
          Components
        </label>
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showFabnetInternet}
            onChange={(e) => setShowFabnetInternet(e.target.checked)}
          />
          FABNet Internet
        </label>
      </div>

      {menu && menu.sliceName && (
        <div
          className="graph-context-menu"
          style={{ left: menu.x, top: menu.y }}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="graph-context-menu-label">{menu.sliceName}</div>
          <button className="graph-context-menu-item" onClick={() => {
            onContextActionRef.current({ type: 'open-boot-log', elements: [], sliceNames: [menu.sliceName!] });
            setMenu(null);
          }}>
            {'\u2630'} Open Build Log
          </button>
        </div>
      )}
      {menu && !menu.sliceName && (
        <div
          className="graph-context-menu"
          style={{ left: menu.x, top: menu.y }}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          {menu.selected.length > 1 && (
            <div className="graph-context-menu-label">
              {menu.selected.length} selected
            </div>
          )}
          {vmsWithIp.length > 0 && (
            <button className="graph-context-menu-item" onClick={handleTerminal}>
              ▸ Open Terminal{vmsWithIp.length > 1 ? ` (${vmsWithIp.length})` : ''}
            </button>
          )}
          {singleVm && singleVm.management_ip && (
            <button className="graph-context-menu-item" onClick={() => {
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
            <button className="graph-context-menu-item danger" onClick={handleDelete}>
              ✕ Delete{deletable.length > 1 ? ` (${deletable.length})` : ''}
            </button>
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
