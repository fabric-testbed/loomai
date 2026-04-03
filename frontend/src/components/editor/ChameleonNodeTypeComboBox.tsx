import { useState, useRef, useEffect, useMemo } from 'react';
import type { ChameleonNodeTypeDetail } from '../../types/chameleon';
import '../../styles/chi-combo.css';

interface ChameleonNodeTypeComboBoxProps {
  nodeTypes: ChameleonNodeTypeDetail[];
  value: string;
  onSelect: (nodeType: string) => void;
  disabled?: boolean;
  compact?: boolean;
}

export default function ChameleonNodeTypeComboBox({ nodeTypes, value, onSelect, disabled, compact }: ChameleonNodeTypeComboBoxProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [availableOnly, setAvailableOnly] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const lf = filter.toLowerCase();
    return nodeTypes.filter(nt => {
      if (availableOnly && nt.reservable <= 0) return false;
      if (!lf) return true;
      return nt.node_type.toLowerCase().includes(lf)
        || (nt.cpu_model || '').toLowerCase().includes(lf)
        || (nt.gpu || '').toLowerCase().includes(lf)
        || (nt.cpu_arch || '').toLowerCase().includes(lf);
    });
  }, [nodeTypes, filter, availableOnly]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setFilter('');
      }
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [open]);

  const selected = nodeTypes.find(nt => nt.node_type === value);
  const specsStr = (nt: ChameleonNodeTypeDetail) => {
    const parts: string[] = [];
    if (nt.cpu_count) parts.push(`${nt.cpu_count}c`);
    if (nt.ram_gb) parts.push(`${nt.ram_gb}GB`);
    if (nt.gpu) parts.push(nt.gpu);
    return parts.length > 0 ? parts.join(', ') : '';
  };

  return (
    <div className={`chi-combo${compact ? ' chi-combo-compact' : ''}`} ref={dropdownRef}>
      <div
        className={`chi-combo-input${disabled ? ' chi-combo-disabled' : ''}`}
        onClick={() => {
          if (disabled) return;
          setOpen(true);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        {open ? (
          <input
            ref={inputRef}
            className="chi-combo-filter"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Search node types..."
            onKeyDown={e => {
              if (e.key === 'Escape') { setOpen(false); setFilter(''); }
            }}
          />
        ) : (
          <span className="chi-combo-display">
            <span className="chi-combo-name">{value || 'Select node type'}</span>
            {selected && (
              <span className={`chi-combo-badge ${selected.reservable > 0 ? 'chi-combo-badge-avail' : 'chi-combo-badge-unavail'}`}>
                {selected.reservable} avail / {selected.total}
              </span>
            )}
          </span>
        )}
        <span className="chi-combo-arrow">{open ? '\u25B2' : '\u25BC'}</span>
      </div>

      {open && (
        <div className="chi-combo-dropdown">
          <label className="chi-combo-avail-toggle">
            <input type="checkbox" checked={availableOnly} onChange={e => setAvailableOnly(e.target.checked)} />
            Available only
          </label>
          {filtered.length === 0 ? (
            <div className="chi-combo-empty">No matches</div>
          ) : (
            filtered.map(nt => {
              const specs = specsStr(nt);
              const isUnavail = nt.reservable <= 0;
              return (
                <div
                  key={nt.node_type}
                  className={`chi-combo-option${nt.node_type === value ? ' selected' : ''}${isUnavail ? ' chi-combo-dim' : ''}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onSelect(nt.node_type);
                    setOpen(false);
                    setFilter('');
                  }}
                >
                  <div className="chi-combo-opt-info">
                    <span className="chi-combo-opt-name">{nt.node_type}</span>
                    {specs && <span className="chi-combo-opt-desc">{specs}</span>}
                  </div>
                  <span className={`chi-combo-badge ${isUnavail ? 'chi-combo-badge-unavail' : 'chi-combo-badge-avail'}`}>
                    {nt.reservable} avail / {nt.total}
                  </span>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
