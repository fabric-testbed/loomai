'use client';
import React from 'react';

export function matchesFilter(filter: string, values: Array<unknown>): boolean {
  const needle = filter.trim().toLowerCase();
  if (!needle) return true;
  return values
    .flatMap((value) => {
      if (Array.isArray(value)) return value;
      return [value];
    })
    .filter((value) => value != null)
    .some((value) => String(value).toLowerCase().includes(needle));
}

export function FilterBox({
  value,
  onChange,
  placeholder,
  resultCount,
  totalCount,
  testId,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  resultCount?: number;
  totalCount?: number;
  testId?: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '0 0 8px' }} data-testid={testId ? `${testId}-wrap` : undefined}>
      <input
        type="search"
        className="chi-form-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ flex: 1, fontSize: 11, padding: '4px 6px' }}
        data-testid={testId}
      />
      {totalCount != null && (
        <span style={{ fontSize: 10, color: 'var(--fabric-text-muted)', whiteSpace: 'nowrap' }}>
          {resultCount ?? totalCount}/{totalCount}
        </span>
      )}
    </div>
  );
}

export type CompactColumn<T> = {
  key: string;
  label: string;
  width?: string;
  render: (item: T) => React.ReactNode;
};

export function CompactResourceTable<T>({
  items,
  columns,
  getKey,
  emptyLabel,
  testId,
  getRowTestId,
  getRowAttributes,
}: {
  items: T[];
  columns: Array<CompactColumn<T>>;
  getKey: (item: T, index: number) => string;
  emptyLabel: string;
  testId?: string;
  getRowTestId?: (item: T, index: number) => string;
  getRowAttributes?: (item: T, index: number) => Record<string, string | number | boolean | undefined>;
}) {
  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--fabric-border)', borderRadius: 6 }} data-testid={testId}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                style={{
                  width: column.width,
                  textAlign: 'left',
                  padding: '5px 6px',
                  borderBottom: '1px solid var(--fabric-border)',
                  color: 'var(--fabric-text-muted)',
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                  background: 'var(--fabric-bg-tint)',
                }}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                style={{ padding: 10, textAlign: 'center', color: 'var(--fabric-text-muted)' }}
              >
                {emptyLabel}
              </td>
            </tr>
          ) : items.map((item, index) => (
            <tr
              key={getKey(item, index)}
              data-testid={getRowTestId?.(item, index)}
              {...(getRowAttributes?.(item, index) || {})}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={{
                    padding: '5px 6px',
                    borderBottom: index === items.length - 1 ? 'none' : '1px solid var(--fabric-border)',
                    verticalAlign: 'middle',
                  }}
                >
                  {column.render(item)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InlineActions({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
      {children}
    </span>
  );
}
