'use client';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import '../styles/bottom-panel.css';
import type { ValidationIssue, SliceErrorMessage } from '../types/fabric';

const LogView = React.lazy(() => import('./LogView'));
const TerminalHost = React.lazy(() => import('./TerminalHost'));
import { destroyTerminalSession } from '../utils/terminalStore';
import {
  type SplitDirection, type SplitNode, type LeafNode, type LayoutNode,
  type DropZone, type DragState, type ConsoleDragData,
  CONSOLE_DRAG_TYPE, nextNodeId,
  findLeaf, findLeafByTab, collectAllLeaves,
  updateLeaf, splitLeaf, removeTabFromTree,
  addTabToFirstLeaf, addTabToLeafAtPosition, updateSplitSizes, computeDropZone,
} from '../utils/consoleLayout';

export interface TerminalTab {
  id: string;
  label: string;
  sliceName: string;
  nodeName: string;
  managementIp: string;
}

export interface BootConfigError {
  node: string;
  type: string;
  id: string;
  detail: string;
}

export interface RecipeConsoleLine {
  type: string;   // 'step' | 'output' | 'error'
  message: string;
}

export interface BootConsoleLine {
  type: string;   // 'build' | 'node' | 'step' | 'output' | 'error'
  message: string;
}

interface BottomPanelProps {
  terminals: TerminalTab[];
  onCloseTerminal: (id: string) => void;
  validationIssues: ValidationIssue[];
  validationValid: boolean;
  sliceState: string;
  dirty: boolean;
  errors: string[];
  onClearErrors: () => void;
  sliceErrors: SliceErrorMessage[];
  bootConfigErrors: BootConfigError[];
  onClearBootConfigErrors?: () => void;
  fullWidth?: boolean;
  onToggleFullWidth?: () => void;
  showWidthToggle?: boolean;
  leftOffset?: number;
  rightOffset?: number;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  panelHeight: number;
  onPanelHeightChange: (height: number) => void;
  // Recipe console
  recipeConsole: RecipeConsoleLine[];
  recipeRunning: boolean;
  onClearRecipeConsole: () => void;
  // Boot config console (per-slice)
  sliceBootLogs: Record<string, BootConsoleLine[]>;
  sliceBootRunning: Record<string, boolean>;
  onClearSliceBootLog: (sliceName: string) => void;
  // Open boot log tabs (per-slice)
  openBootLogSlices: string[];
  onOpenBootLog: (sliceName: string) => void;
  onCloseBootLog: (sliceName: string) => void;
  // Cross-panel coordination
  panelId?: string;
  excludeTabIds?: string[];
  onReceiveExternalTab?: (tabId: string, fromPanel: string) => void;
}

// Fixed tab IDs (non-terminal)
const FIXED_TABS = ['slice-errors', 'errors', 'validation', 'log', 'recipes', 'local-terminal'] as const;

export default React.memo(function BottomPanel({ terminals, onCloseTerminal, validationIssues, validationValid, sliceState, dirty, errors, onClearErrors, sliceErrors, bootConfigErrors, onClearBootConfigErrors, fullWidth = true, onToggleFullWidth, showWidthToggle = false, leftOffset = 0, rightOffset = 0, expanded, onExpandedChange, panelHeight, onPanelHeightChange, recipeConsole, recipeRunning, onClearRecipeConsole, sliceBootLogs, sliceBootRunning, onClearSliceBootLog, openBootLogSlices, onOpenBootLog, onCloseBootLog, panelId = 'bottom', excludeTabIds = [], onReceiveExternalTab }: BottomPanelProps) {
  const setExpanded = onExpandedChange;
  const setPanelHeight = onPanelHeightChange;

  // --- Layout tree state ---
  const [layout, setLayout] = useState<LayoutNode>(() => ({
    type: 'leaf',
    id: nextNodeId(),
    tabIds: [...FIXED_TABS],
    activeTabId: 'local-terminal',
  }));
  const [dragState, setDragState] = useState<DragState | null>(null);

  // --- Extra local terminals ---
  const [extraLocalTerminals, setExtraLocalTerminals] = useState<string[]>([]);
  const localTermCounter = useRef(1);

  // (terminal group dropdown removed — each terminal gets its own tab)

  // --- Tab metadata ---
  const termCount = terminals.length;
  const validationErrorCount = validationIssues.filter((i) => i.severity === 'error').length;
  const warnCount = validationIssues.filter((i) => i.severity === 'warning').length;
  const apiErrorCount = errors.length;
  const sliceErrorCount = sliceErrors.length;
  const bootErrorCount = bootConfigErrors.length;
  const totalSliceIssues = sliceErrorCount + bootErrorCount;

  const [containerTermActive, setContainerTermActive] = useState(false);

  // All tab IDs that should exist
  const allTabIds = useMemo(() => {
    const ids: string[] = [...FIXED_TABS];
    extraLocalTerminals.forEach(id => ids.push(id));
    openBootLogSlices.forEach(sn => ids.push(`boot:${sn}`));
    terminals.forEach(t => ids.push(t.id));
    const excluded = new Set(excludeTabIds);
    return ids.filter(id => !excluded.has(id));
  }, [terminals, openBootLogSlices, extraLocalTerminals, excludeTabIds]);

  // Default leaf for reset
  const makeDefaultLeaf = useCallback((): LeafNode => ({
    type: 'leaf',
    id: nextNodeId(),
    tabIds: [...FIXED_TABS],
    activeTabId: 'local-terminal',
  }), []);

  // --- Local terminal management ---
  const addLocalTerminal = useCallback((leafId: string) => {
    localTermCounter.current++;
    const newId = `local-term-${localTermCounter.current}`;
    setExtraLocalTerminals(prev => [...prev, newId]);
    setLayout(prev => updateLeaf(prev, leafId, l => ({
      ...l,
      tabIds: [...l.tabIds, newId],
      activeTabId: newId,
    })));
    setExpanded(true);
  }, [setExpanded]);

  const closeLocalTerminal = useCallback((tabId: string) => {
    destroyTerminalSession(tabId);
    setExtraLocalTerminals(prev => prev.filter(id => id !== tabId));
    setLayout(prev => {
      const result = removeTabFromTree(prev, tabId);
      return result || makeDefaultLeaf();
    });
  }, [makeDefaultLeaf]);

  // --- Sync terminal additions/removals into layout tree ---
  const prevTermIds = useRef<string[]>([]);
  useEffect(() => {
    const currentTermIds = terminals.map(t => t.id);
    const prevIds = prevTermIds.current;

    const added = currentTermIds.filter(id => !prevIds.includes(id));
    const removed = prevIds.filter(id => !currentTermIds.includes(id));

    if (added.length > 0 || removed.length > 0) {
      setLayout(prev => {
        let tree: LayoutNode | null = prev;

        // Remove tabs for closed terminals
        for (const tabId of removed) {
          if (tree) tree = removeTabFromTree(tree, tabId);
        }

        // Add new terminals to the first leaf
        if (tree) {
          for (const tabId of added) {
            tree = addTabToFirstLeaf(tree, tabId);
          }
        }

        // If tree collapsed to null, reset
        if (!tree) tree = makeDefaultLeaf();

        return tree;
      });
    }

    prevTermIds.current = currentTermIds;
  }, [terminals, makeDefaultLeaf]);

  // --- Sync boot log tab additions/removals into layout tree ---
  const prevBootLogSlices = useRef<string[]>([]);
  useEffect(() => {
    const currentIds = openBootLogSlices.map(sn => `boot:${sn}`);
    const prevIds = prevBootLogSlices.current.map(sn => `boot:${sn}`);

    const added = currentIds.filter(id => !prevIds.includes(id));
    const removed = prevIds.filter(id => !currentIds.includes(id));

    if (added.length > 0 || removed.length > 0) {
      setLayout(prev => {
        let tree: LayoutNode | null = prev;
        for (const tabId of removed) {
          if (tree) tree = removeTabFromTree(tree, tabId);
        }
        if (tree) {
          for (const tabId of added) {
            tree = addTabToFirstLeaf(tree, tabId);
          }
        }
        if (!tree) tree = makeDefaultLeaf();

        // Activate the most recently added boot log tab
        if (added.length > 0) {
          const lastAdded = added[added.length - 1];
          const leaf = findLeafByTab(tree, lastAdded);
          if (leaf) {
            tree = updateLeaf(tree, leaf.id, l => ({ ...l, activeTabId: lastAdded }));
          }
        }

        return tree;
      });
    }

    prevBootLogSlices.current = [...openBootLogSlices];
  }, [openBootLogSlices, makeDefaultLeaf]);

  // --- Sync excluded tabs (tabs moved to side panel) ---
  const prevExcludeTabIds = useRef<string[]>([]);
  useEffect(() => {
    const nowExcluded = excludeTabIds.filter(id => !prevExcludeTabIds.current.includes(id));
    const nowIncluded = prevExcludeTabIds.current.filter(id => !excludeTabIds.includes(id));
    if (nowExcluded.length > 0 || nowIncluded.length > 0) {
      setLayout(prev => {
        let tree: LayoutNode | null = prev;
        for (const tabId of nowExcluded) {
          if (tree) tree = removeTabFromTree(tree, tabId);
        }
        for (const tabId of nowIncluded) {
          if (tree) tree = addTabToFirstLeaf(tree, tabId);
        }
        return tree || makeDefaultLeaf();
      });
    }
    prevExcludeTabIds.current = [...excludeTabIds];
  }, [excludeTabIds, makeDefaultLeaf]);

  // --- activateTab helper ---
  const activateTab = useCallback((tabId: string) => {
    setLayout(prev => {
      const leaf = findLeafByTab(prev, tabId);
      if (!leaf || leaf.activeTabId === tabId) return prev;
      return updateLeaf(prev, leaf.id, l => ({ ...l, activeTabId: tabId }));
    });
  }, []);

  // --- Auto-switch effects ---

  const prevTermCount = useRef(terminals.length);
  useEffect(() => {
    if (terminals.length > prevTermCount.current) {
      const newest = terminals[terminals.length - 1];
      activateTab(newest.id);
      setExpanded(true);
    }
    prevTermCount.current = terminals.length;
  }, [terminals.length, setExpanded, activateTab, terminals]);

  const prevErrorCount = useRef(errors.length);
  useEffect(() => {
    if (errors.length > prevErrorCount.current) {
      activateTab('errors');
    }
    prevErrorCount.current = errors.length;
  }, [errors.length, activateTab]);

  const prevSliceErrorCount = useRef(sliceErrors.length);
  const prevBootErrorCount = useRef(bootConfigErrors.length);
  useEffect(() => {
    if (sliceErrors.length > 0 && prevSliceErrorCount.current === 0) {
      activateTab('slice-errors');
      setExpanded(true);
    }
    prevSliceErrorCount.current = sliceErrors.length;
  }, [sliceErrors.length, setExpanded, activateTab]);
  useEffect(() => {
    if (bootConfigErrors.length > 0 && prevBootErrorCount.current === 0) {
      activateTab('slice-errors');
      setExpanded(true);
    }
    prevBootErrorCount.current = bootConfigErrors.length;
  }, [bootConfigErrors.length, setExpanded, activateTab]);

  const prevRecipeRunning = useRef(recipeRunning);
  useEffect(() => {
    if (recipeRunning && !prevRecipeRunning.current) {
      activateTab('recipes');
      setExpanded(true);
    }
    prevRecipeRunning.current = recipeRunning;
  }, [recipeRunning, setExpanded, activateTab]);

  const anyBootRunning = Object.values(sliceBootRunning).some(Boolean);

  // Auto-open boot log tab when boot starts for a slice
  const prevSliceBootRunning = useRef<Record<string, boolean>>({});
  useEffect(() => {
    for (const [sn, running] of Object.entries(sliceBootRunning)) {
      if (running && !prevSliceBootRunning.current[sn]) {
        onOpenBootLog(sn);
        activateTab(`boot:${sn}`);
        setExpanded(true);
      }
    }
    prevSliceBootRunning.current = { ...sliceBootRunning };
  }, [sliceBootRunning, setExpanded, activateTab, onOpenBootLog]);

  // Auto-scroll recipe console
  const recipeConsoleEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const leaves = collectAllLeaves(layout);
    const recipesActive = leaves.some(l => l.activeTabId === 'recipes');
    if (recipesActive) {
      recipeConsoleEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [recipeConsole, layout]);

  // Auto-scroll boot config console (scrolls to bottom of active boot log)
  const bootConsoleEndRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const allBootLines = Object.values(sliceBootLogs).flat();
  useEffect(() => {
    const leaves = collectAllLeaves(layout);
    for (const leaf of leaves) {
      if (leaf.activeTabId.startsWith('boot:')) {
        const sn = leaf.activeTabId.slice(5);
        const ref = bootConsoleEndRefs.current.get(sn);
        ref?.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }, [allBootLines.length, layout]);

  // If active tab was closed, fix it
  useEffect(() => {
    setLayout(prev => {
      const leaves = collectAllLeaves(prev);
      let changed = false;
      let tree = prev;
      for (const leaf of leaves) {
        if (!allTabIds.includes(leaf.activeTabId)) {
          changed = true;
          tree = updateLeaf(tree, leaf.id, l => ({
            ...l,
            activeTabId: l.tabIds[0] || 'validation',
          }));
        }
      }
      return changed ? tree : prev;
    });
  }, [allTabIds]);

  // --- Height resize ---
  const draggingRef = useRef(false);
  const startYRef = useRef(0);
  const startHeightRef = useRef(0);

  const handleHeightDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    startYRef.current = e.clientY;
    startHeightRef.current = panelHeight;

    const onMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = startYRef.current - ev.clientY;
      const newHeight = Math.max(100, Math.min(window.innerHeight * 0.8, startHeightRef.current + delta));
      setPanelHeight(newHeight);
    };
    const onUp = () => {
      draggingRef.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
  }, [panelHeight, setPanelHeight]);

  // --- Split divider resize ---
  const handleSplitDividerStart = useCallback((e: React.MouseEvent, splitId: string, dividerIndex: number, direction: SplitDirection, containerEl: HTMLElement) => {
    e.preventDefault();
    const startPos = direction === 'horizontal' ? e.clientX : e.clientY;
    const containerSize = direction === 'horizontal' ? containerEl.offsetWidth : containerEl.offsetHeight;

    // Read current sizes from the layout
    let startSizes: number[] = [];
    const findSplit = (node: LayoutNode): SplitNode | null => {
      if (node.type === 'split') {
        if (node.id === splitId) return node;
        for (const child of node.children) {
          const found = findSplit(child);
          if (found) return found;
        }
      }
      return null;
    };
    // We need current layout — use a ref trick
    const splitNode = findSplit(layout);
    if (!splitNode) return;
    startSizes = [...splitNode.sizes];

    const onMove = (ev: MouseEvent) => {
      const currentPos = direction === 'horizontal' ? ev.clientX : ev.clientY;
      const delta = currentPos - startPos;
      const deltaPct = (delta / containerSize) * 100;

      const newSizes = [...startSizes];
      const minSize = 15; // minimum 15% per pane
      newSizes[dividerIndex] = Math.max(minSize, startSizes[dividerIndex] + deltaPct);
      newSizes[dividerIndex + 1] = Math.max(minSize, startSizes[dividerIndex + 1] - deltaPct);

      // Validate minimums
      if (newSizes[dividerIndex] < minSize || newSizes[dividerIndex + 1] < minSize) return;

      setLayout(prev => updateSplitSizes(prev, splitId, newSizes));
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
  }, [layout]);

  // --- Tab drag handlers ---
  const handleTabDragStart = useCallback((e: React.DragEvent, tabId: string, leafId: string) => {
    const dragData: ConsoleDragData = { tabId, sourcePanel: panelId, sourceLeafId: leafId };
    e.dataTransfer.setData(CONSOLE_DRAG_TYPE, JSON.stringify(dragData));
    e.dataTransfer.setData('text/plain', tabId);
    e.dataTransfer.effectAllowed = 'move';
    setDragState({ tabId, sourceLeafId: leafId, sourcePanel: panelId, dropTarget: null, targetLeafId: null });
  }, [panelId]);

  const handleTabDragEnd = useCallback(() => {
    setDragState(null);
  }, []);

  const handleLeafDragOver = useCallback((e: React.DragEvent, leafId: string) => {
    const isConsoleDrag = dragState || e.dataTransfer.types.includes(CONSOLE_DRAG_TYPE);
    if (!isConsoleDrag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const target = computeDropZone(e, e.currentTarget.getBoundingClientRect());
    if (dragState && !dragState.external) {
      setDragState(prev => prev ? { ...prev, dropTarget: target, targetLeafId: leafId } : null);
    } else {
      setDragState({ tabId: '', sourceLeafId: '', sourcePanel: '', dropTarget: target, targetLeafId: leafId, external: true });
    }
  }, [dragState]);

  const handleLeafDragLeave = useCallback(() => {
    setDragState(prev => {
      if (!prev) return null;
      if (prev.external) return null;
      return { ...prev, dropTarget: null, targetLeafId: null };
    });
  }, []);

  const handleLeafDrop = useCallback((e: React.DragEvent, targetLeafId: string) => {
    e.preventDefault();
    const dropTarget = dragState?.dropTarget || 'center';

    // Check for cross-panel drop
    const rawData = e.dataTransfer.getData(CONSOLE_DRAG_TYPE);
    if (rawData) {
      try {
        const data: ConsoleDragData = JSON.parse(rawData);
        if (data.sourcePanel !== panelId) {
          // Tab arriving from another panel
          setLayout(prev => addTabToLeafAtPosition(prev, data.tabId, targetLeafId, dropTarget));
          onReceiveExternalTab?.(data.tabId, data.sourcePanel);
          setDragState(null);
          return;
        }
      } catch { /* ignore parse errors */ }
    }

    // Internal drop
    if (!dragState || dragState.external) {
      setDragState(null);
      return;
    }

    const { tabId, sourceLeafId } = dragState;
    setDragState(null);
    if (!dropTarget) return;

    setLayout(prev => {
      const sourceLeaf = findLeaf(prev, sourceLeafId);
      if (!sourceLeaf) return prev;

      if (dropTarget === 'center') {
        if (sourceLeafId === targetLeafId) return prev;
        let tree: LayoutNode | null = removeTabFromTree(prev, tabId);
        if (!tree) tree = makeDefaultLeaf();
        tree = updateLeaf(tree, targetLeafId, l => ({
          ...l,
          tabIds: [...l.tabIds, tabId],
          activeTabId: tabId,
        }));
        return tree;
      }

      if (sourceLeaf.tabIds.length <= 1) return prev;

      const direction: SplitDirection = (dropTarget === 'left' || dropTarget === 'right') ? 'horizontal' : 'vertical';
      const position: 'before' | 'after' = (dropTarget === 'left' || dropTarget === 'top') ? 'before' : 'after';

      let tree: LayoutNode | null = removeTabFromTree(prev, tabId);
      if (!tree) tree = makeDefaultLeaf();

      const newLeaf: LeafNode = {
        type: 'leaf',
        id: nextNodeId(),
        tabIds: [tabId],
        activeTabId: tabId,
      };

      tree = splitLeaf(tree, targetLeafId, direction, position, newLeaf);
      return tree;
    });
  }, [dragState, makeDefaultLeaf, panelId, onReceiveExternalTab]);

  // --- Tab label/badge/content helpers ---
  function getTabLabel(tabId: string): string {
    switch (tabId) {
      case 'slice-errors': return 'Slice Errors';
      case 'errors': return 'Errors';
      case 'validation': return 'Validation';
      case 'log': return 'Log';
      case 'recipes': return 'Recipes';
      case 'local-terminal': return 'Local';
      default: {
        if (tabId.startsWith('boot:')) return tabId.slice(5);
        if (tabId.startsWith('local-term-')) return `Local ${tabId.slice(11)}`;
        const term = terminals.find(t => t.id === tabId);
        return term ? term.label : tabId;
      }
    }
  }

  function getTabBadge(tabId: string): React.ReactNode {
    switch (tabId) {
      case 'slice-errors':
        return totalSliceIssues > 0 ? <span className="bp-tab-badge error">{totalSliceIssues}</span> : null;
      case 'errors':
        return apiErrorCount > 0 ? <span className="bp-tab-badge error">{apiErrorCount}</span> : null;
      case 'validation':
        return (
          <>
            {!validationValid && <span className="bp-tab-indicator error" />}
            {validationValid && validationIssues.length === 0 && <span className="bp-tab-indicator ok" />}
            {validationValid && warnCount > 0 && <span className="bp-tab-indicator warn" />}
          </>
        );
      case 'recipes':
        return (
          <>
            {recipeRunning && <span className="bp-tab-indicator warn" />}
            {!recipeRunning && recipeConsole.length > 0 && <span className="bp-tab-indicator ok" />}
          </>
        );
      default: {
        if (tabId.startsWith('boot:')) {
          const sn = tabId.slice(5);
          const running = !!sliceBootRunning[sn];
          const lines = sliceBootLogs[sn] || [];
          return (
            <>
              {running && <span className="bp-tab-indicator warn" />}
              {!running && lines.length > 0 && <span className="bp-tab-indicator ok" />}
            </>
          );
        }
        return null;
      }
    }
  }

  function getTabHelpId(tabId: string): string | undefined {
    switch (tabId) {
      case 'errors': return 'bottom.errors';
      case 'validation': return 'bottom.validation';
      case 'log': return 'bottom.log';
      case 'local-terminal': return 'bottom.local-terminal';
      default: return undefined;
    }
  }

  function getTabTitle(tabId: string): string {
    switch (tabId) {
      case 'slice-errors': return 'Slice provisioning errors and boot config errors';
      case 'errors': return 'API and operation error log';
      case 'validation': return 'Slice validation results — errors, warnings, and remedies';
      case 'log': return 'Application event log with timestamps';
      case 'recipes': return 'Recipe execution output';
      case 'local-terminal': return 'Shell terminal on the backend container';
      default: {
        if (tabId.startsWith('boot:')) return `Boot config output for ${tabId.slice(5)}`;
        if (tabId.startsWith('local-term-')) return 'Shell terminal on the backend container';
        if (terminals.find(t => t.id === tabId)) return 'SSH terminal to this VM';
        return '';
      }
    }
  }

  function isTabCloseable(tabId: string): boolean {
    return !!terminals.find(t => t.id === tabId) || tabId.startsWith('boot:') || tabId.startsWith('local-term-');
  }

  function renderTabContent(tabId: string, isActive: boolean): React.ReactNode {
    switch (tabId) {
      case 'slice-errors':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <SliceErrorsView errors={sliceErrors} bootConfigErrors={bootConfigErrors} onClearBootConfigErrors={onClearBootConfigErrors} />
          </div>
        );
      case 'errors':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <div className="bp-errors-list">
              <div className="bp-errors-header">
                <span>{errors.length} error{errors.length !== 1 ? 's' : ''}</span>
                {errors.length > 0 && (
                  <button className="bp-errors-clear" onClick={onClearErrors} title="Clear all entries from this tab">Clear All</button>
                )}
              </div>
              {errors.length === 0 && (
                <div className="bp-validation-empty">No errors.</div>
              )}
              {errors.map((msg, i) => (
                <div key={i} className="bp-error-entry">
                  <span className="bp-error-message">{msg}</span>
                </div>
              ))}
            </div>
          </div>
        );
      case 'validation':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <ValidationView issues={validationIssues} valid={validationValid} sliceState={sliceState} dirty={dirty} />
          </div>
        );
      case 'log':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <React.Suspense fallback={null}><LogView /></React.Suspense>
          </div>
        );
      case 'recipes':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            <RecipeConsoleView
              lines={recipeConsole}
              running={recipeRunning}
              onClear={onClearRecipeConsole}
              endRef={recipeConsoleEndRef}
            />
          </div>
        );
      case 'local-terminal':
        return (
          <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
            {containerTermActive && <React.Suspense fallback={null}><TerminalHost sessionId="local-terminal" type="local" /></React.Suspense>}
          </div>
        );
      default: {
        if (tabId.startsWith('local-term-')) {
          return (
            <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
              <React.Suspense fallback={null}><TerminalHost sessionId={tabId} type="local" /></React.Suspense>
            </div>
          );
        }
        if (tabId.startsWith('boot:')) {
          const sn = tabId.slice(5);
          const lines = sliceBootLogs[sn] || [];
          const running = !!sliceBootRunning[sn];
          return (
            <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
              <SingleSliceBootLogView
                sliceName={sn}
                lines={lines}
                running={running}
                onClear={() => onClearSliceBootLog(sn)}
                endRef={(el: HTMLDivElement | null) => {
                  if (el) bootConsoleEndRefs.current.set(sn, el);
                  else bootConsoleEndRefs.current.delete(sn);
                }}
              />
            </div>
          );
        }
        const term = terminals.find(t => t.id === tabId);
        if (term) {
          return (
            <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
              <React.Suspense fallback={null}><TerminalHost sessionId={tabId} type="ssh" sliceName={term.sliceName} nodeName={term.nodeName} managementIp={term.managementIp} /></React.Suspense>
            </div>
          );
        }
        return null;
      }
    }
  }

  // --- Recursive layout renderer ---
  const splitContainerRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  function renderLayoutNode(node: LayoutNode): React.ReactNode {
    if (node.type === 'leaf') {
      return renderLeafPane(node);
    }

    const isHorizontal = node.direction === 'horizontal';

    return (
      <div
        key={node.id}
        className={`bp-split bp-split-${node.direction}`}
        ref={(el) => { if (el) splitContainerRefs.current.set(node.id, el); }}
        style={{ display: 'flex', flexDirection: isHorizontal ? 'row' : 'column', flex: 1, overflow: 'hidden' }}
      >
        {node.children.map((child, i) => (
          <React.Fragment key={child.id}>
            {i > 0 && (
              <div
                className={`bp-split-divider bp-split-divider-${node.direction}`}
                onMouseDown={(e) => {
                  const container = splitContainerRefs.current.get(node.id);
                  if (container) handleSplitDividerStart(e, node.id, i - 1, node.direction, container);
                }}
              />
            )}
            <div style={{ [isHorizontal ? 'width' : 'height']: `${node.sizes[i]}%`, display: 'flex', overflow: 'hidden', minWidth: 0, minHeight: 0 }}>
              {renderLayoutNode(child)}
            </div>
          </React.Fragment>
        ))}
      </div>
    );
  }

  function renderLeafPane(leaf: LeafNode): React.ReactNode {
    return (
      <div
        key={leaf.id}
        className="bp-pane"
        onDragOver={(e) => handleLeafDragOver(e, leaf.id)}
        onDragLeave={handleLeafDragLeave}
        onDrop={(e) => handleLeafDrop(e, leaf.id)}
      >
        {/* Drop indicator overlay */}
        {dragState && dragState.targetLeafId === leaf.id && dragState.dropTarget && (
          <div className={`bp-drop-indicator bp-drop-${dragState.dropTarget}`} />
        )}
        {/* Tab bar */}
        <div className="bottom-panel-tabs">
          {leaf.tabIds.map((tabId) => {
            // SSH terminal tab — render as individual tab
            const term = terminals.find(t => t.id === tabId);
            if (term) {
              return (
                <button
                  key={tabId}
                  className={`bp-tab bp-tab-container ${leaf.activeTabId === tabId ? 'active' : ''} ${dragState?.tabId === tabId ? 'dragging' : ''}`}
                  draggable
                  onDragStart={(e) => handleTabDragStart(e, tabId, leaf.id)}
                  onDragEnd={handleTabDragEnd}
                  onClick={() => activateTab(tabId)}
                  title={getTabTitle(tabId)}
                >
                  {getTabLabel(tabId)}
                  <span
                    className="bp-tab-close"
                    onClick={(e) => { e.stopPropagation(); destroyTerminalSession(tabId); onCloseTerminal(tabId); }}
                  >✕</span>
                </button>
              );
            }

            // Non-terminal tab — render normally
            const isTermTab = isTabCloseable(tabId);
            const isLocalTerm = tabId === 'local-terminal';
            return (
              <button
                key={tabId}
                className={`bp-tab ${leaf.activeTabId === tabId ? 'active' : ''} ${isLocalTerm ? 'bp-tab-container' : ''} ${dragState?.tabId === tabId ? 'dragging' : ''}`}
                draggable
                onDragStart={(e) => handleTabDragStart(e, tabId, leaf.id)}
                onDragEnd={handleTabDragEnd}
                onClick={() => {
                  activateTab(tabId);
                  if (isLocalTerm) {
                    setContainerTermActive(true);
                  }
                }}
                data-help-id={getTabHelpId(tabId)}
                title={getTabTitle(tabId)}
              >
                {getTabLabel(tabId)}
                {getTabBadge(tabId)}
                {isTermTab && (
                  <span
                    className="bp-tab-close"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (tabId.startsWith('boot:')) onCloseBootLog(tabId.slice(5));
                      else if (tabId.startsWith('local-term-')) closeLocalTerminal(tabId);
                      else { destroyTerminalSession(tabId); onCloseTerminal(tabId); }
                    }}
                  >
                    ✕
                  </span>
                )}
              </button>
            );
          })}
          <button
            className="bp-tab bp-add-local-btn"
            onClick={() => addLocalTerminal(leaf.id)}
            title="New local terminal"
          >
            +
          </button>
        </div>
        {/* Content area */}
        <div className="bottom-panel-content">
          {leaf.tabIds.map((tabId) => (
            <React.Fragment key={tabId}>
              {renderTabContent(tabId, leaf.activeTabId === tabId)}
            </React.Fragment>
          ))}
        </div>
      </div>
    );
  }

  // --- Collapsed view ---
  if (!expanded) {
    return (
      <div className="bottom-panel-collapsed">
        <span className="bottom-panel-collapsed-label" onClick={() => setExpanded(true)} title="Expand the console panel">
          ▲ Console
          {totalSliceIssues > 0 && <span className="bottom-panel-badge error">{totalSliceIssues} slice issue{totalSliceIssues !== 1 ? 's' : ''}</span>}
          {apiErrorCount > 0 && <span className="bottom-panel-badge error">{apiErrorCount} error{apiErrorCount !== 1 ? 's' : ''}</span>}
          <span className={`bottom-panel-badge ${validationErrorCount > 0 ? 'warn' : 'ok'}`}>{validationErrorCount} validation</span>
          {warnCount > 0 && <span className="bottom-panel-badge warn">{warnCount} warning{warnCount !== 1 ? 's' : ''}</span>}
          {termCount > 0 && <span className="bottom-panel-badge">{termCount} terminal{termCount !== 1 ? 's' : ''}</span>}
          {(containerTermActive || extraLocalTerminals.length > 0) && (
            <span className="bottom-panel-badge">
              {extraLocalTerminals.length > 0 ? `${1 + extraLocalTerminals.length} local` : 'local'}
            </span>
          )}
          {recipeRunning && <span className="bottom-panel-badge warn">recipe running</span>}
          {anyBootRunning && <span className="bottom-panel-badge warn">boot config running</span>}
        </span>
        <span className="bottom-panel-collapsed-actions">
          {showWidthToggle && onToggleFullWidth && (
            <button
              className="bp-width-toggle"
              onClick={(e) => { e.stopPropagation(); onToggleFullWidth(); }}
              title="Toggle console between full width and panel-constrained width"
            >
              <span className={`bp-width-icon ${fullWidth ? 'full' : 'narrow'}`} />
            </button>
          )}
        </span>
      </div>
    );
  }

  // --- Expanded view with recursive layout ---
  return (
    <div className="bottom-panel" style={{ height: panelHeight }}>
      <div className="bp-resize-handle" onMouseDown={handleHeightDragStart} />
      {/* Global controls row */}
      <div className="bp-global-controls">
        <div className="bp-tab-spacer" />
        {showWidthToggle && onToggleFullWidth && (
          <button
            className="bp-width-toggle"
            onClick={onToggleFullWidth}
            title="Toggle console between full width and panel-constrained width"
          >
            <span className={`bp-width-icon ${fullWidth ? 'full' : 'narrow'}`} />
          </button>
        )}
        <button className="bp-collapse-btn" onClick={() => setExpanded(false)} title="Expand or collapse the console panel">▼</button>
      </div>
      {/* Recursive layout */}
      <div className="bp-panes-row">
        {renderLayoutNode(layout)}
      </div>
    </div>
  );
});

// --- Recipe Console View ---
export function RecipeConsoleView({ lines, running, onClear, endRef }: { lines: RecipeConsoleLine[]; running: boolean; onClear: () => void; endRef: React.RefObject<HTMLDivElement> }) {
  if (lines.length === 0) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-empty">No recipe output. Apply a recipe from the Artifacts panel to see execution output here.</div>
      </div>
    );
  }

  return (
    <div className="bp-recipe-console">
      <div className="bp-recipe-header">
        <span>{running ? 'Recipe running...' : 'Recipe complete'}</span>
        {!running && (
          <button className="bp-errors-clear" onClick={onClear} title="Clear all entries from this tab">Clear</button>
        )}
        {running && <span className="bp-recipe-pulse" />}
      </div>
      <div className="bp-recipe-body">
        {lines.map((line, i) => (
          <div key={i} className={`bp-recipe-line bp-recipe-${line.type}`}>
            {line.type === 'step'   && <span className="bp-recipe-icon">{'\u25B6'}</span>}
            {line.type === 'output' && <span className="bp-recipe-icon">{' '}</span>}
            {line.type === 'error'  && <span className="bp-recipe-icon">{'\u2716'}</span>}
            <span>{line.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}

// --- Per-slice Boot Config Log Lines ---
function BootLogLines({ lines }: { lines: BootConsoleLine[] }) {
  return (
    <>
      {lines.map((line, i) => (
        <div key={i} className={`bp-recipe-line bp-recipe-${line.type}`}>
          {line.type === 'build'    && <span className="bp-recipe-icon">{'\u2692'}</span>}
          {line.type === 'node'     && <span className="bp-recipe-icon">{'\u25A0'}</span>}
          {line.type === 'step'     && <span className="bp-recipe-icon">{'\u25B6'}</span>}
          {line.type === 'progress' && <span className="bp-recipe-icon">{'\u2713'}</span>}
          {line.type === 'output'   && <span className="bp-recipe-icon">{' '}</span>}
          {line.type === 'error'    && <span className="bp-recipe-icon">{'\u2716'}</span>}
          {line.type === 'deploy'   && <span className="bp-recipe-icon">{'\u25B6'}</span>}
          <span>{line.message}</span>
        </div>
      ))}
    </>
  );
}

// --- Single-Slice Boot Log View ---
export function SingleSliceBootLogView({
  sliceName,
  lines,
  running,
  onClear,
  endRef,
}: {
  sliceName: string;
  lines: BootConsoleLine[];
  running: boolean;
  onClear: () => void;
  endRef: (el: HTMLDivElement | null) => void;
}) {
  if (lines.length === 0 && !running) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-empty">No boot config output for {sliceName}. Submit the slice to see execution output here.</div>
      </div>
    );
  }

  return (
    <div className="bp-recipe-console">
      <div className="bp-recipe-header">
        <span style={{ fontWeight: 600 }}>{sliceName}</span>
        <span style={{ marginLeft: '8px', opacity: 0.7, fontWeight: 'normal' }}>
          {running ? 'running...' : 'complete'}
        </span>
        {running && <span className="bp-recipe-pulse" style={{ marginLeft: '8px' }} />}
        {!running && lines.length > 0 && (
          <button className="bp-errors-clear" style={{ marginLeft: 'auto' }}
            onClick={onClear} title="Clear all entries from this tab">Clear</button>
        )}
      </div>
      <div className="bp-recipe-body" style={{ flex: 1 }}>
        <BootLogLines lines={lines} />
        <div ref={endRef} />
      </div>
    </div>
  );
}

// --- Slice Errors View ---

interface ErrorDiagnosis {
  category: string;
  summary: string;
  remedy: string;
}

function diagnoseError(message: string): ErrorDiagnosis {
  const msg = message.toLowerCase();
  if (msg.includes('could not find image') || msg.includes('image not found')) {
    const match = message.match(/image\s+([\w_]+)/i);
    const imageName = match?.[1] || 'the requested image';
    return {
      category: 'Image Not Found',
      summary: `The image "${imageName}" is not available on the target site.`,
      remedy: 'Change the node image to one available on the target site (e.g. default_ubuntu_22, default_centos_9), or try a different site.',
    };
  }
  if (msg.includes('insufficient resources') || msg.includes('no hosts available')) {
    return {
      category: 'Insufficient Resources',
      summary: 'The target site does not have enough resources to provision this node.',
      remedy: 'Try a different site with more available resources, reduce the node size (cores/RAM/disk), or remove specialized components (GPUs, SmartNICs) that may have limited availability.',
    };
  }
  if (msg.includes('closing reservation due to failure in slice')) {
    return {
      category: 'Cascade Failure',
      summary: 'This resource was closed because another resource in the slice failed.',
      remedy: 'Fix the root-cause failure on the other node/network first, then resubmit.',
    };
  }
  if (msg.includes('predecessor reservation') && msg.includes('terminal state')) {
    return {
      category: 'Dependency Failure',
      summary: 'A network or dependent resource failed because its parent node failed first.',
      remedy: 'Fix the root-cause failure on the parent node, then resubmit.',
    };
  }
  if (msg.includes('expired') || msg.includes('lease')) {
    return {
      category: 'Lease Expired',
      summary: 'The slice lease expired and the resources were reclaimed.',
      remedy: 'Create a new slice. Use a longer lease period or renew the lease before it expires.',
    };
  }
  return {
    category: 'Error',
    summary: message.length > 200 ? message.slice(0, 200) + '...' : message,
    remedy: 'Review the error message for details. You may need to adjust the slice configuration and resubmit.',
  };
}

export function SliceErrorsView({ errors, bootConfigErrors, onClearBootConfigErrors }: { errors: SliceErrorMessage[]; bootConfigErrors: BootConfigError[]; onClearBootConfigErrors?: () => void }) {
  const hasSliceErrors = errors && errors.length > 0;
  const hasBootErrors = bootConfigErrors && bootConfigErrors.length > 0;

  if (!hasSliceErrors && !hasBootErrors) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-ok">No slice errors.</div>
      </div>
    );
  }

  const seen = new Set<string>();
  const diagnosed: Array<{ sliver: string; diagnosis: ErrorDiagnosis; raw: string }> = [];
  if (hasSliceErrors) {
    for (const err of errors) {
      const key = err.message;
      if (seen.has(key)) continue;
      seen.add(key);
      diagnosed.push({ sliver: err.sliver, diagnosis: diagnoseError(err.message), raw: err.message });
    }
  }

  return (
    <div className="bp-validation-container">
      {diagnosed.length > 0 && (
        <>
          <div className="bp-validation-header error">
            Slice Failed — {diagnosed.length} error{diagnosed.length !== 1 ? 's' : ''}
          </div>
          {diagnosed.map((d, i) => (
            <div key={i} className="bp-slice-error-entry">
              <div className="bp-slice-error-category">
                {d.diagnosis.category}
                {d.sliver && <span className="bp-slice-error-sliver"> — {d.sliver}</span>}
              </div>
              <div className="bp-slice-error-summary">{d.diagnosis.summary}</div>
              <div className="bp-slice-error-remedy">
                <strong>Suggested fix:</strong> {d.diagnosis.remedy}
              </div>
            </div>
          ))}
        </>
      )}
      {hasBootErrors && (
        <>
          <div className="bp-validation-header error" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Boot Config — {bootConfigErrors.length} error{bootConfigErrors.length !== 1 ? 's' : ''}</span>
            {onClearBootConfigErrors && (
              <button className="bp-errors-clear" onClick={onClearBootConfigErrors} title="Clear all entries from this tab">Clear</button>
            )}
          </div>
          {bootConfigErrors.map((e, i) => (
            <div key={i} className="bp-slice-error-entry">
              <div className="bp-slice-error-category">
                {e.type === 'network' ? 'Network Config' : e.type === 'upload' ? 'File Upload' : 'Command'}
                <span className="bp-slice-error-sliver"> — {e.node}</span>
              </div>
              <div className="bp-slice-error-summary">{e.detail}</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// --- Validation View ---
export function ValidationView({ issues, valid, sliceState, dirty }: { issues: ValidationIssue[]; valid: boolean; sliceState: string; dirty: boolean }) {
  if (!sliceState) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-empty">
          No slice loaded.
        </div>
      </div>
    );
  }

  if (issues.length === 0 && valid && !dirty) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-info">
          Slice is in state <strong>{sliceState}</strong> — draft is unmodified.
        </div>
      </div>
    );
  }

  if (issues.length === 0 && valid && dirty) {
    return (
      <div className="bp-validation-container">
        <div className="bp-validation-ok">
          ✓ Slice is valid and ready to submit.
        </div>
      </div>
    );
  }

  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');

  return (
    <div className="bp-validation-container">
      {errors.length > 0 && (
        <div className="bp-validation-section">
          <div className="bp-validation-header error">
            ✕ {errors.length} Error{errors.length !== 1 ? 's' : ''} — slice cannot be submitted
          </div>
          {errors.map((issue, i) => (
            <div key={i} className="bp-validation-item error">
              <div className="bp-validation-message">{issue.message}</div>
              <div className="bp-validation-remedy">→ {issue.remedy}</div>
            </div>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="bp-validation-section">
          <div className="bp-validation-header warn">
            ⚠ {warnings.length} Warning{warnings.length !== 1 ? 's' : ''}
          </div>
          {warnings.map((issue, i) => (
            <div key={i} className="bp-validation-item warn">
              <div className="bp-validation-message">{issue.message}</div>
              <div className="bp-validation-remedy">→ {issue.remedy}</div>
            </div>
          ))}
        </div>
      )}
      {valid && (
        <div className="bp-validation-ok" style={{ marginTop: 8 }}>
          ✓ Slice is valid and can be submitted (warnings are non-blocking).
        </div>
      )}
    </div>
  );
}

