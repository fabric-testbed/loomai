'use client';
import { useState, useEffect } from 'react';
import { helpEntryMap } from '../data/helpData';

interface HelpContextMenuProps {
  onOpenHelp: (section: string) => void;
}

interface MenuState {
  x: number;
  y: number;
  helpId: string;
  label: string;
}

export default function HelpContextMenu({ onOpenHelp }: HelpContextMenuProps) {
  const [menu, setMenu] = useState<MenuState | null>(null);

  useEffect(() => {
    const handleContextMenu = (e: MouseEvent) => {
      // Walk up the DOM to find the nearest data-help-id attribute
      let el = e.target as HTMLElement | null;
      let helpId: string | null = null;
      while (el) {
        helpId = el.getAttribute('data-help-id');
        if (helpId) break;
        // Stop at the cytoscape container — graph has its own context menu
        if (el.classList.contains('cytoscape-container')) return;
        el = el.parentElement;
      }

      if (!helpId) return;

      const entry = helpEntryMap[helpId];
      if (!entry) return;

      e.preventDefault();
      setMenu({ x: e.clientX, y: e.clientY, helpId, label: entry.label });
    };

    const handleClick = () => setMenu(null);
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null); };

    document.addEventListener('contextmenu', handleContextMenu);
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('contextmenu', handleContextMenu);
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, []);

  if (!menu) return null;

  return (
    <div
      className="graph-context-menu"
      style={{ left: menu.x, top: menu.y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <button
        className="graph-context-menu-item"
        onClick={() => {
          onOpenHelp(menu.helpId);
          setMenu(null);
        }}
      >
        ? Help: {menu.label}
      </button>
    </div>
  );
}
