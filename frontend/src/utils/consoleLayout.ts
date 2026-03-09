/**
 * Shared layout tree types and manipulation functions for the split-pane
 * console system. Used by both BottomPanel and SideConsolePanel.
 */

export type SplitDirection = 'horizontal' | 'vertical';

export interface SplitNode {
  type: 'split';
  id: string;
  direction: SplitDirection;
  children: LayoutNode[];
  sizes: number[];
}

export interface LeafNode {
  type: 'leaf';
  id: string;
  tabIds: string[];
  activeTabId: string;
}

export type LayoutNode = SplitNode | LeafNode;
export type DropZone = 'left' | 'right' | 'top' | 'bottom' | 'center';

export interface DragState {
  tabId: string;
  sourceLeafId: string;
  sourcePanel: string; // 'bottom' | 'side'
  dropTarget: DropZone | null;
  targetLeafId: string | null;
  external?: boolean; // true when drag originated from another panel
}

/** Drag data format for cross-panel DnD (serialized to dataTransfer) */
export interface ConsoleDragData {
  tabId: string;
  sourcePanel: string;
  sourceLeafId: string;
}

export const CONSOLE_DRAG_TYPE = 'application/console-tab';

let nodeIdCounter = 0;
export function nextNodeId(): string {
  return `node-${++nodeIdCounter}`;
}

export function findLeaf(root: LayoutNode, id: string): LeafNode | null {
  if (root.type === 'leaf') return root.id === id ? root : null;
  for (const child of root.children) {
    const found = findLeaf(child, id);
    if (found) return found;
  }
  return null;
}

export function findLeafByTab(root: LayoutNode, tabId: string): LeafNode | null {
  if (root.type === 'leaf') return root.tabIds.includes(tabId) ? root : null;
  for (const child of root.children) {
    const found = findLeafByTab(child, tabId);
    if (found) return found;
  }
  return null;
}

export function collectAllLeaves(root: LayoutNode): LeafNode[] {
  if (root.type === 'leaf') return [root];
  const leaves: LeafNode[] = [];
  for (const child of root.children) {
    leaves.push(...collectAllLeaves(child));
  }
  return leaves;
}

export function collectAllTabIds(root: LayoutNode): string[] {
  return collectAllLeaves(root).flatMap((l) => l.tabIds);
}

export function updateLeaf(
  root: LayoutNode,
  leafId: string,
  updater: (leaf: LeafNode) => LeafNode,
): LayoutNode {
  if (root.type === 'leaf') {
    return root.id === leafId ? updater(root) : root;
  }
  return {
    ...root,
    children: root.children.map((child) => updateLeaf(child, leafId, updater)),
  };
}

export function removeLeaf(root: LayoutNode, leafId: string): LayoutNode | null {
  if (root.type === 'leaf') {
    return root.id === leafId ? null : root;
  }
  const newChildren: LayoutNode[] = [];
  const newSizes: number[] = [];
  for (let i = 0; i < root.children.length; i++) {
    const result = removeLeaf(root.children[i], leafId);
    if (result === null) {
      // removed
    } else {
      newChildren.push(result);
      newSizes.push(root.sizes[i]);
    }
  }
  if (newChildren.length === 0) return null;
  if (newChildren.length === 1) return newChildren[0];
  const totalRemaining = newSizes.reduce((a, b) => a + b, 0);
  const adjustedSizes = newSizes.map((s) => (s / totalRemaining) * 100);
  return { ...root, children: newChildren, sizes: adjustedSizes };
}

export function splitLeaf(
  root: LayoutNode,
  leafId: string,
  direction: SplitDirection,
  position: 'before' | 'after',
  newLeaf: LeafNode,
): LayoutNode {
  if (root.type === 'leaf') {
    if (root.id !== leafId) return root;
    const children = position === 'before' ? [newLeaf, root] : [root, newLeaf];
    return {
      type: 'split',
      id: nextNodeId(),
      direction,
      children,
      sizes: [50, 50],
    };
  }
  const childIndex = root.children.findIndex((c) => c.type === 'leaf' && c.id === leafId);
  if (childIndex !== -1 && root.direction === direction) {
    const newChildren = [...root.children];
    const newSizes = [...root.sizes];
    const insertIndex = position === 'before' ? childIndex : childIndex + 1;
    const splitSize = newSizes[childIndex] / 2;
    newSizes[childIndex] = splitSize;
    newChildren.splice(insertIndex, 0, newLeaf);
    newSizes.splice(insertIndex, 0, splitSize);
    return { ...root, children: newChildren, sizes: newSizes };
  }
  return {
    ...root,
    children: root.children.map((child) =>
      splitLeaf(child, leafId, direction, position, newLeaf),
    ),
  };
}

export function removeTabFromTree(root: LayoutNode, tabId: string): LayoutNode | null {
  if (root.type === 'leaf') {
    if (!root.tabIds.includes(tabId)) return root;
    const newTabIds = root.tabIds.filter((t) => t !== tabId);
    if (newTabIds.length === 0) return null;
    return {
      ...root,
      tabIds: newTabIds,
      activeTabId: newTabIds.includes(root.activeTabId) ? root.activeTabId : newTabIds[0],
    };
  }
  const newChildren: LayoutNode[] = [];
  const newSizes: number[] = [];
  for (let i = 0; i < root.children.length; i++) {
    const result = removeTabFromTree(root.children[i], tabId);
    if (result === null) {
      // child was removed
    } else {
      newChildren.push(result);
      newSizes.push(root.sizes[i]);
    }
  }
  if (newChildren.length === 0) return null;
  if (newChildren.length === 1) return newChildren[0];
  const totalRemaining = newSizes.reduce((a, b) => a + b, 0);
  const adjustedSizes = newSizes.map((s) => (s / totalRemaining) * 100);
  return { ...root, children: newChildren, sizes: adjustedSizes };
}

export function addTabToFirstLeaf(root: LayoutNode, tabId: string): LayoutNode {
  if (root.type === 'leaf') {
    return { ...root, tabIds: [...root.tabIds, tabId] };
  }
  return {
    ...root,
    children: [addTabToFirstLeaf(root.children[0], tabId), ...root.children.slice(1)],
  };
}

export function addTabToLeafAtPosition(
  root: LayoutNode,
  tabId: string,
  targetLeafId: string,
  dropZone: DropZone,
): LayoutNode {
  if (dropZone === 'center') {
    return updateLeaf(root, targetLeafId, (l) => ({
      ...l,
      tabIds: [...l.tabIds, tabId],
      activeTabId: tabId,
    }));
  }
  const direction: SplitDirection =
    dropZone === 'left' || dropZone === 'right' ? 'horizontal' : 'vertical';
  const position: 'before' | 'after' =
    dropZone === 'left' || dropZone === 'top' ? 'before' : 'after';
  const newLeaf: LeafNode = {
    type: 'leaf',
    id: nextNodeId(),
    tabIds: [tabId],
    activeTabId: tabId,
  };
  return splitLeaf(root, targetLeafId, direction, position, newLeaf);
}

export function updateSplitSizes(
  root: LayoutNode,
  splitId: string,
  sizes: number[],
): LayoutNode {
  if (root.type === 'leaf') return root;
  if (root.id === splitId) return { ...root, sizes };
  return {
    ...root,
    children: root.children.map((child) => updateSplitSizes(child, splitId, sizes)),
  };
}

/** Compute the drop zone from cursor position within a rectangle */
export function computeDropZone(
  e: React.DragEvent,
  rect: DOMRect,
): DropZone {
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const edgeX = Math.min(60, rect.width * 0.25);
  const edgeY = Math.min(60, rect.height * 0.25);

  if (x < edgeX) return 'left';
  if (x > rect.width - edgeX) return 'right';
  if (y < edgeY) return 'top';
  if (y > rect.height - edgeY) return 'bottom';
  return 'center';
}
