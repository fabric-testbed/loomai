import { useState, useRef, useEffect } from 'react';
import type { SliceData, SliceErrorMessage } from '../../types/fabric';

export interface SliverOption {
  key: string;       // e.g. "node:node1", "net:net1", "fp:port1"
  name: string;
  type: string;      // display badge: "VM", "L2Bridge", "IPv4", "FP"
  group: string;     // "Nodes (VMs)" | "Networks" | "Facility Ports"
  hasFailed: boolean;
}

interface SliverComboBoxProps {
  sliceData: SliceData | null;
  selectedSliverKey: string;
  onSelect: (key: string) => void;
  errorMessages?: SliceErrorMessage[];
}

function buildOptions(sliceData: SliceData | null, errorMessages?: SliceErrorMessage[]): SliverOption[] {
  if (!sliceData) return [];
  const failedNames = new Set<string>();
  if (errorMessages) {
    for (const err of errorMessages) {
      if (err.sliver) failedNames.add(err.sliver);
    }
  }
  const options: SliverOption[] = [];

  for (const node of sliceData.nodes) {
    options.push({
      key: `node:${node.name}`,
      name: node.name,
      type: 'VM',
      group: 'Nodes (VMs)',
      hasFailed: failedNames.has(node.name),
    });
  }
  for (const net of sliceData.networks) {
    options.push({
      key: `net:${net.name}`,
      name: net.name,
      type: net.type,
      group: 'Networks',
      hasFailed: failedNames.has(net.name),
    });
  }
  for (const fp of (sliceData.facility_ports ?? [])) {
    options.push({
      key: `fp:${fp.name}`,
      name: fp.name,
      type: 'FP',
      group: 'Facility Ports',
      hasFailed: failedNames.has(fp.name),
    });
  }
  return options;
}

export default function SliverComboBox({ sliceData, selectedSliverKey, onSelect, errorMessages }: SliverComboBoxProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const allOptions = buildOptions(sliceData, errorMessages);
  const filtered = filter
    ? allOptions.filter((o) => o.name.toLowerCase().includes(filter.toLowerCase()))
    : allOptions;

  const selectedOption = allOptions.find((o) => o.key === selectedSliverKey);

  // Group filtered options
  const groups: Record<string, SliverOption[]> = {};
  for (const opt of filtered) {
    if (!groups[opt.group]) groups[opt.group] = [];
    groups[opt.group].push(opt);
  }

  // Close dropdown on outside click
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
    <div className="sliver-combo" ref={dropdownRef}>
      <div
        className="sliver-combo-input"
        onClick={() => {
          setOpen(true);
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        {open ? (
          <input
            ref={inputRef}
            className="sliver-combo-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Type to filter..."
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setOpen(false);
                setFilter('');
              }
            }}
          />
        ) : (
          <span className="sliver-combo-display">
            {selectedOption ? (
              <>
                <span className="sliver-combo-name">{selectedOption.name}</span>
                {selectedOption.hasFailed && <span className="sliver-badge sliver-badge-failed">Failed</span>}
                <span className={`sliver-badge sliver-badge-${selectedOption.type === 'VM' ? 'vm' : selectedOption.type === 'FP' ? 'fp' : 'net'}`}>
                  {selectedOption.type}
                </span>
              </>
            ) : (
              <span className="sliver-combo-placeholder">Select sliver...</span>
            )}
          </span>
        )}
        <span className="sliver-combo-arrow">{open ? '\u25B2' : '\u25BC'}</span>
      </div>

      {open && (
        <div className="sliver-combo-dropdown">
          {filtered.length === 0 ? (
            <div className="sliver-combo-empty">
              {allOptions.length === 0 ? '(empty slice)' : 'No matches'}
            </div>
          ) : (
            Object.entries(groups).map(([group, opts]) => (
              <div key={group}>
                <div className="sliver-combo-group">{group}</div>
                {opts.map((opt) => (
                  <div
                    key={opt.key}
                    className={`sliver-combo-option ${opt.key === selectedSliverKey ? 'selected' : ''} ${opt.hasFailed ? 'failed' : ''}`}
                    onClick={() => {
                      onSelect(opt.key);
                      setOpen(false);
                      setFilter('');
                    }}
                  >
                    <span className="sliver-combo-opt-name">{opt.name}</span>
                    {opt.hasFailed && <span className="sliver-badge sliver-badge-failed">Failed</span>}
                    <span className={`sliver-badge sliver-badge-${opt.type === 'VM' ? 'vm' : opt.type === 'FP' ? 'fp' : 'net'}`}>
                      {opt.type}
                    </span>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
