import { useState, useRef, useEffect } from 'react';

export type AddSliverType = 'node' | 'l2network' | 'l3network' | 'facility-port';

interface AddSliverMenuProps {
  onSelect: (type: AddSliverType) => void;
}

const options: { type: AddSliverType; label: string; desc: string }[] = [
  { type: 'node', label: 'VM Node', desc: 'Virtual machine with configurable resources' },
  { type: 'l2network', label: 'Network (L2)', desc: 'Layer 2 Ethernet network (Bridge, STS, PTP)' },
  { type: 'l3network', label: 'Network (L3)', desc: 'Layer 3 IP-routed network (IPv4, IPv6)' },
  { type: 'facility-port', label: 'Facility Port', desc: 'External network connection via VLAN' },
];

export default function AddSliverMenu({ onSelect }: AddSliverMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <div className="add-sliver-wrapper" ref={menuRef}>
      <button
        className="add-sliver-btn"
        onClick={() => setOpen(!open)}
        title="Add a new sliver"
      >
        +
      </button>
      {open && (
        <div className="add-sliver-menu">
          {options.map((opt) => (
            <button
              key={opt.type}
              className="add-sliver-item"
              onClick={() => {
                onSelect(opt.type);
                setOpen(false);
              }}
              title={opt.desc}
            >
              <span className="add-sliver-label">{opt.label}</span>
              <span className="add-sliver-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
