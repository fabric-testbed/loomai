import { useState, useRef, useEffect, useMemo } from 'react';
import type { ChameleonImage } from '../../types/chameleon';
import '../../styles/chi-combo.css';

interface ChameleonImageComboBoxProps {
  images: ChameleonImage[];
  value: string;  // image ID (or legacy name)
  onSelect: (imageId: string) => void;
  disabled?: boolean;
  compact?: boolean;
}

export default function ChameleonImageComboBox({ images, value, onSelect, disabled, compact }: ChameleonImageComboBoxProps) {
  // Resolve display name from ID (or use value as-is if it's a name)
  const displayName = useMemo(() => {
    const byId = images.find(img => img.id === value);
    if (byId) return byId.name;
    const byName = images.find(img => img.name === value);
    if (byName) return byName.name;
    return value || 'Select image';
  }, [images, value]);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!filter) return images;
    const lf = filter.toLowerCase();
    return images.filter(img => img.name.toLowerCase().includes(lf));
  }, [images, filter]);

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
            placeholder="Search images..."
            onKeyDown={e => {
              if (e.key === 'Escape') { setOpen(false); setFilter(''); }
            }}
          />
        ) : (
          <span className="chi-combo-display">
            <span className="chi-combo-name">{displayName}</span>
            <span className="chi-combo-badge chi-combo-badge-img">IMG</span>
          </span>
        )}
        <span className="chi-combo-arrow">{open ? '\u25B2' : '\u25BC'}</span>
      </div>

      {open && (
        <div className="chi-combo-dropdown">
          {filtered.length === 0 ? (
            <div className="chi-combo-empty">No matches</div>
          ) : (
            filtered.map(img => (
              <div
                key={img.id}
                className={`chi-combo-option${(img.id === value || img.name === value) ? ' selected' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onSelect(img.id);
                  setOpen(false);
                  setFilter('');
                }}
              >
                <span className="chi-combo-opt-name">{img.name}</span>
                {img.size_mb && <span className="chi-combo-opt-size">{img.size_mb} MB</span>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
