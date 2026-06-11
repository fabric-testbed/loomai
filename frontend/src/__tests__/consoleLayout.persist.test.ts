import { describe, it, expect, beforeEach } from 'vitest';
import {
  isValidLayout, reserveNodeIds, loadPersistedLayout, nextNodeId,
  type LayoutNode, type LeafNode,
} from '../utils/consoleLayout';

const leaf = (id: string, tabIds: string[]): LeafNode => ({
  type: 'leaf', id, tabIds, activeTabId: tabIds[0] ?? '',
});

describe('isValidLayout', () => {
  it('accepts a well-formed leaf', () => {
    expect(isValidLayout(leaf('node-1', ['errors', 'local-terminal']))).toBe(true);
  });

  it('accepts a well-formed split', () => {
    const tree: LayoutNode = {
      type: 'split', id: 'node-3', direction: 'horizontal',
      children: [leaf('node-1', ['a']), leaf('node-2', ['b'])], sizes: [50, 50],
    };
    expect(isValidLayout(tree)).toBe(true);
  });

  it('rejects junk', () => {
    expect(isValidLayout(null)).toBe(false);
    expect(isValidLayout({})).toBe(false);
    expect(isValidLayout({ type: 'leaf', id: 1, tabIds: [] })).toBe(false);
    expect(isValidLayout({ type: 'leaf', id: 'x', tabIds: [1] })).toBe(false);
    expect(isValidLayout({ type: 'split', id: 'x', direction: 'horizontal', children: [], sizes: [] })).toBe(false);
  });
});

describe('reserveNodeIds', () => {
  it('advances the counter past restored ids so new nodes do not collide', () => {
    const restored = leaf('node-42', ['a']);
    reserveNodeIds(restored);
    const fresh = nextNodeId();
    expect(fresh).toBe('node-43');
  });
});

describe('loadPersistedLayout', () => {
  beforeEach(() => localStorage.clear());

  it('falls back to a default leaf holding the given tabs when nothing stored', () => {
    const tree = loadPersistedLayout('side', ['errors', 'log']) as LeafNode;
    expect(tree.type).toBe('leaf');
    expect(tree.tabIds).toEqual(['errors', 'log']);
    expect(tree.activeTabId).toBe('errors');
  });

  it('restores a valid persisted split tree, preserving tab positions', () => {
    const tree: LayoutNode = {
      type: 'split', id: 'node-9', direction: 'vertical',
      children: [leaf('node-7', ['local-terminal']), leaf('node-8', ['term-2'])], sizes: [60, 40],
    };
    localStorage.setItem('fabric-console-layout-bottom', JSON.stringify(tree));
    const restored = loadPersistedLayout('bottom', ['local-terminal']);
    expect(restored).toEqual(tree);
    // counter advanced past node-9 so freshly created nodes won't reuse an id
    const fresh = nextNodeId();
    expect(parseInt(fresh.replace('node-', ''), 10)).toBeGreaterThan(9);
  });

  it('ignores corrupt storage and falls back to default', () => {
    localStorage.setItem('fabric-console-layout-bottom', '{not json');
    const tree = loadPersistedLayout('bottom', ['errors']) as LeafNode;
    expect(tree.tabIds).toEqual(['errors']);
  });

  it('ignores structurally-invalid stored layout', () => {
    localStorage.setItem('fabric-console-layout-bottom', JSON.stringify({ type: 'leaf', id: 5 }));
    const tree = loadPersistedLayout('bottom', ['errors']) as LeafNode;
    expect(tree.tabIds).toEqual(['errors']);
  });
});
