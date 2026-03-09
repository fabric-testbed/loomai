'use client';
import '../styles/slices-view.css';

type SlicesSubView = 'topology' | 'table' | 'storage' | 'map' | 'apps';

interface SlicesViewProps {
  subView: SlicesSubView;
  onSubViewChange: (sv: SlicesSubView) => void;
  children: React.ReactNode;  // The active sub-view content is passed as children
}

const SUB_VIEWS: Array<{ key: SlicesSubView; label: string }> = [
  { key: 'topology', label: 'Topology' },
  { key: 'table', label: 'Table' },
  { key: 'storage', label: 'Storage' },
  { key: 'map', label: 'Map' },
  { key: 'apps', label: 'Apps' },
];

export default function SlicesView({ subView, onSubViewChange, children }: SlicesViewProps) {
  return (
    <div className="slices-view">
      <div className="slices-subtabs">
        {SUB_VIEWS.map((sv) => (
          <button
            key={sv.key}
            className={`slices-subtab ${subView === sv.key ? 'active' : ''}`}
            onClick={() => onSubViewChange(sv.key)}
          >
            {sv.label}
          </button>
        ))}
      </div>
      <div className="slices-content">
        {children}
      </div>
    </div>
  );
}
