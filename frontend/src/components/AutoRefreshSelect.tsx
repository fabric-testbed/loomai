'use client';
import InAppSelect from './InAppSelect';
import React from 'react';

const REFRESH_INTERVALS = [
  { value: 0, label: 'Never' },
  { value: 15000, label: '15s' },
  { value: 30000, label: '30s' },
  { value: 60000, label: '1m' },
  { value: 120000, label: '2m' },
  { value: 300000, label: '5m' },
];

export default function AutoRefreshSelect({
  value,
  onChange,
  className,
  title,
  'data-help-id': dataHelpId,
}: {
  value: number;
  onChange: (value: number) => void;
  className: string;
  title: string;
  'data-help-id'?: string;
}) {
  return (
    <InAppSelect
      className={className}
      data-help-id={dataHelpId}
      value={value}
      onChange={(e) => onChange(parseInt(e.target.value, 10))}
      title={title}
      style={{ minWidth: 60, cursor: 'pointer' }}
    >
      {REFRESH_INTERVALS.map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </InAppSelect>
  );
}
