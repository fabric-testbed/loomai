'use client';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import '@xterm/xterm/css/xterm.css';
import '../styles/side-console.css';
import type { ValidationIssue, SliceErrorMessage } from '../types/fabric';
import type { TerminalTab, BootConfigError, RecipeConsoleLine, BootConsoleLine } from './BottomPanel';
import { RecipeConsoleView, SingleSliceBootLogView, SliceErrorsView, ValidationView } from './BottomPanel';
import LogView from './LogView';
import TerminalHost from './TerminalHost';
import { destroyTerminalSession } from '../utils/terminalStore';
import {
  type SplitDirection, type SplitNode, type LeafNode, type LayoutNode,
  type DropZone, type DragState, type ConsoleDragData,
  CONSOLE_DRAG_TYPE, nextNodeId,
  findLeaf, findLeafByTab, collectAllLeaves,
  updateLeaf, splitLeaf, removeTabFromTree,
  addTabToFirstLeaf, addTabToLeafAtPosition, updateSplitSizes, computeDropZone,
} from '../utils/consoleLayout';

type DragHandleProps = Record<string, unknown>;

interface SideConsolePanelProps {
  tabIds: string[];
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
  recipeConsole: RecipeConsoleLine[];
  recipeRunning: boolean;
  onClearRecipeConsole: () => void;
  sliceBootLogs: Record<string, BootConsoleLine[]>;
  sliceBootRunning: Record<string, boolean>;
  onClearSliceBootLog: (sliceName: string) => void;
  containerTermActive: boolean;
  // Cross-panel
  onReceiveExternalTab?: (tabId: string, fromPanel: string) => void;
  onTabMovedOut?: (tabId: string) => void;
  // Panel chrome (regular panel system)
  onCollapse: () => void;
  dragHandleProps?: DragHandleProps;
  panelIcon?: string;
}

const PANEL_ID = 'side';

export default function SideConsolePanel({
  tabIds, terminals, onCloseTerminal, validationIssues, validationValid,
  sliceState, dirty, errors, onClearErrors, sliceErrors, bootConfigErrors,
  onClearBootConfigErrors, recipeConsole, recipeRunning, onClearRecipeConsole,
  sliceBootLogs, sliceBootRunning, onClearSliceBootLog, containerTermActive,
  onReceiveExternalTab, onTabMovedOut, onCollapse, dragHandleProps, panelIcon,
}: SideConsolePanelProps) {

  // --- Layout tree state ---
  const [layout, setLayout] = useState<LayoutNode>(() => ({
    type: 'leaf',
    id: nextNodeId(),
    tabIds: [],
    activeTabId: '',
  }));
  const [dragState, setDragState] = useState<DragState | null>(null);

  // --- Sync tabIds prop into layout tree ---
  const prevTabIds = useRef<string[]>([]);
  useEffect(() => {
    const added = tabIds.filter(id => !prevTabIds.current.includes(id));
    const removed = prevTabIds.current.filter(id => !tabIds.includes(id));

    if (added.length > 0 || removed.length > 0) {
      setLayout(prev => {
        let tree: LayoutNode | null = prev;
        for (const tabId of removed) {
          if (tree) tree = removeTabFromTree(tree, tabId);
        }
        for (const tabId of added) {
          // Only add if not already in the tree (might have been added by drop handler)
          if (tree && !findLeafByTab(tree, tabId)) {
            tree = addTabToFirstLeaf(tree, tabId);
          }
        }
        if (!tree) {
          return { type: 'leaf', id: nextNodeId(), tabIds: [], activeTabId: '' };
        }
        return tree;
      });
    }
    prevTabIds.current = [...tabIds];
  }, [tabIds]);

  // --- activateTab ---
  const activateTab = useCallback((tabId: string) => {
    setLayout(prev => {
      const leaf = findLeafByTab(prev, tabId);
      if (!leaf || leaf.activeTabId === tabId) return prev;
      return updateLeaf(prev, leaf.id, l => ({ ...l, activeTabId: tabId }));
    });
  }, []);

  // --- Split divider resize ---
  const splitContainerRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const handleSplitDividerStart = useCallback((e: React.MouseEvent, splitId: string, dividerIndex: number, direction: SplitDirection, containerEl: HTMLElement) => {
    e.preventDefault();
    const startPos = direction === 'horizontal' ? e.clientX : e.clientY;
    const containerSize = direction === 'horizontal' ? containerEl.offsetWidth : containerEl.offsetHeight;

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
    const splitNode = findSplit(layout);
    if (!splitNode) return;
    startSizes = [...splitNode.sizes];

    const onMove = (ev: MouseEvent) => {
      const currentPos = direction === 'horizontal' ? ev.clientX : ev.clientY;
      const delta = currentPos - startPos;
      const deltaPct = (delta / containerSize) * 100;
      const newSizes = [...startSizes];
      const minSize = 15;
      newSizes[dividerIndex] = Math.max(minSize, startSizes[dividerIndex] + deltaPct);
      newSizes[dividerIndex + 1] = Math.max(minSize, startSizes[dividerIndex + 1] - deltaPct);
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
    const dragData: ConsoleDragData = { tabId, sourcePanel: PANEL_ID, sourceLeafId: leafId };
    e.dataTransfer.setData(CONSOLE_DRAG_TYPE, JSON.stringify(dragData));
    e.dataTransfer.setData('text/plain', tabId);
    e.dataTransfer.effectAllowed = 'move';
    setDragState({ tabId, sourceLeafId: leafId, sourcePanel: PANEL_ID, dropTarget: null, targetLeafId: null });
  }, []);

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

    const rawData = e.dataTransfer.getData(CONSOLE_DRAG_TYPE);
    if (rawData) {
      try {
        const data: ConsoleDragData = JSON.parse(rawData);
        if (data.sourcePanel !== PANEL_ID) {
          setLayout(prev => addTabToLeafAtPosition(prev, data.tabId, targetLeafId, dropTarget));
          onReceiveExternalTab?.(data.tabId, data.sourcePanel);
          setDragState(null);
          return;
        }
      } catch { /* ignore */ }
    }

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
        if (!tree) return { type: 'leaf', id: nextNodeId(), tabIds: [], activeTabId: '' };
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
      if (!tree) return { type: 'leaf', id: nextNodeId(), tabIds: [], activeTabId: '' };

      const newLeaf: LeafNode = { type: 'leaf', id: nextNodeId(), tabIds: [tabId], activeTabId: tabId };
      tree = splitLeaf(tree, targetLeafId, direction, position, newLeaf);
      return tree;
    });
  }, [dragState, onReceiveExternalTab]);


  // --- Tab helpers ---
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

  function isTabCloseable(tabId: string): boolean {
    // All tabs in the side panel are closeable (sends them back to bottom panel)
    return true;
  }

  // --- Scroll refs for auto-scroll ---
  const recipeConsoleEndRef = useRef<HTMLDivElement>(null);
  const bootConsoleEndRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // --- Tab content rendering ---
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
                  <button className="bp-errors-clear" onClick={onClearErrors} title="Clear all entries">Clear All</button>
                )}
              </div>
              {errors.length === 0 && <div className="bp-validation-empty">No errors.</div>}
              {errors.map((msg, i) => (
                <div key={i} className="bp-error-entry"><span className="bp-error-message">{msg}</span></div>
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
            <LogView />
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
            {containerTermActive && <TerminalHost sessionId="local-terminal" type="local" />}
          </div>
        );
      default: {
        if (tabId.startsWith('local-term-')) {
          return (
            <div style={{ display: isActive ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
              <TerminalHost sessionId={tabId} type="local" />
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
              <TerminalHost sessionId={tabId} type="ssh" sliceName={term.sliceName} nodeName={term.nodeName} managementIp={term.managementIp} />
            </div>
          );
        }
        return null;
      }
    }
  }

  // --- Layout rendering ---
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
    if (leaf.tabIds.length === 0) {
      return (
        <div
          key={leaf.id}
          className="bp-pane"
          onDragOver={(e) => handleLeafDragOver(e, leaf.id)}
          onDragLeave={handleLeafDragLeave}
          onDrop={(e) => handleLeafDrop(e, leaf.id)}
        >
          {dragState && dragState.targetLeafId === leaf.id && dragState.dropTarget && (
            <div className={`bp-drop-indicator bp-drop-${dragState.dropTarget}`} />
          )}
          <div className="side-console-empty">
            Drag console tabs here from the bottom panel
          </div>
        </div>
      );
    }

    return (
      <div
        key={leaf.id}
        className="bp-pane"
        onDragOver={(e) => handleLeafDragOver(e, leaf.id)}
        onDragLeave={handleLeafDragLeave}
        onDrop={(e) => handleLeafDrop(e, leaf.id)}
      >
        {dragState && dragState.targetLeafId === leaf.id && dragState.dropTarget && (
          <div className={`bp-drop-indicator bp-drop-${dragState.dropTarget}`} />
        )}
        <div className="bottom-panel-tabs">
          {leaf.tabIds.map((tabId) => (
            <button
              key={tabId}
              className={`bp-tab ${leaf.activeTabId === tabId ? 'active' : ''} ${dragState?.tabId === tabId ? 'dragging' : ''}`}
              draggable
              onDragStart={(e) => handleTabDragStart(e, tabId, leaf.id)}
              onDragEnd={handleTabDragEnd}
              onClick={() => activateTab(tabId)}
            >
              {getTabLabel(tabId)}
              {isTabCloseable(tabId) && (
                <span
                  className="bp-tab-close"
                  onClick={(e) => {
                    e.stopPropagation();
                    // Close = move back to bottom panel
                    if (tabId.startsWith('local-term-') || terminals.find(t => t.id === tabId)) {
                      // Terminal tabs: just move back to bottom
                      onTabMovedOut?.(tabId);
                    } else {
                      // Fixed tabs: move back to bottom
                      onTabMovedOut?.(tabId);
                    }
                  }}
                >
                  ✕
                </span>
              )}
            </button>
          ))}
        </div>
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

  // --- Regular panel view ---
  return (
    <div className="side-console-panel">
      <div className="side-console-header" {...(dragHandleProps || {})}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span className="panel-drag-handle">{'\u283F'}</span>
          Console
        </span>
        <button
          className="collapse-btn"
          onClick={(e) => { e.stopPropagation(); onCollapse(); }}
          title="Close panel"
        >
          {'\u2715'}
        </button>
      </div>
      <div className="side-console-panes">
        {renderLayoutNode(layout)}
      </div>
    </div>
  );
}
