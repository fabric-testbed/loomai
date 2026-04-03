'use client';
import React from 'react';
import TestbedViewShell, { COMPOSITE_THEME } from './TestbedViewShell';
import type { Tab } from './TestbedViewShell';

export type CompositeSubView = 'slices' | 'topology' | 'storage' | 'map' | 'apps' | 'calendar';

interface CompositeViewProps {
  subView: CompositeSubView;
  onSubViewChange: (sv: CompositeSubView) => void;
  toolbarContent?: React.ReactNode;
  children: React.ReactNode;
}

const TABS: Tab[] = [
  { id: 'slices', label: 'Slices' },
  { id: 'topology', label: 'Topology' },
  { id: 'storage', label: 'Storage' },
  { id: 'map', label: 'Map' },
  { id: 'apps', label: 'Apps' },
  { id: 'calendar', label: 'Calendar' },
];

export default React.memo(function CompositeView({
  subView, onSubViewChange, toolbarContent, children,
}: CompositeViewProps) {
  return (
    <TestbedViewShell
      theme={COMPOSITE_THEME}
      tabs={TABS}
      activeTab={subView}
      onTabChange={(id) => onSubViewChange(id as CompositeSubView)}
      toolbarContent={toolbarContent}
    >
      {children}
    </TestbedViewShell>
  );
});
