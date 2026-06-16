'use client';

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import '../styles/in-app-select.css';

type SelectValue = string | number | readonly string[];

interface ParsedOption {
  value: string;
  label: string;
  disabled: boolean;
  title?: string;
  group?: string;
}

type ParsedItem =
  | { type: 'group'; label: string }
  | { type: 'option'; option: ParsedOption };

type OptionElementProps = {
  children?: React.ReactNode;
  disabled?: boolean;
  label?: string;
  title?: string;
  value?: string | number;
};

type OptGroupElementProps = {
  children?: React.ReactNode;
  disabled?: boolean;
  label?: string;
};

type InAppSelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children' | 'size'> & {
  children?: React.ReactNode;
};

function nodeText(node: React.ReactNode): string {
  return React.Children.toArray(node).map((child) => {
    if (typeof child === 'string' || typeof child === 'number') return String(child);
    if (React.isValidElement<OptionElementProps>(child)) return nodeText(child.props.children);
    return '';
  }).join('');
}

function parseOption(
  child: React.ReactElement<OptionElementProps>,
  group?: string,
  groupDisabled = false,
): ParsedOption {
  const label = child.props.label ?? nodeText(child.props.children).trim();
  return {
    value: child.props.value == null ? label : String(child.props.value),
    label,
    disabled: groupDisabled || Boolean(child.props.disabled),
    title: child.props.title,
    group,
  };
}

function parseItems(children: React.ReactNode): { items: ParsedItem[]; options: ParsedOption[] } {
  const items: ParsedItem[] = [];
  const options: ParsedOption[] = [];

  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;

    if (child.type === React.Fragment) {
      const parsed = parseItems((child.props as { children?: React.ReactNode }).children);
      items.push(...parsed.items);
      options.push(...parsed.options);
      return;
    }

    if (child.type === 'optgroup') {
      const props = child.props as OptGroupElementProps;
      const groupLabel = props.label ?? '';
      if (groupLabel) items.push({ type: 'group', label: groupLabel });
      React.Children.forEach(props.children, (optionChild) => {
        if (!React.isValidElement<OptionElementProps>(optionChild) || optionChild.type !== 'option') return;
        const option = parseOption(optionChild, groupLabel, Boolean(props.disabled));
        options.push(option);
        items.push({ type: 'option', option });
      });
      return;
    }

    if (child.type === 'option') {
      const option = parseOption(child as React.ReactElement<OptionElementProps>);
      options.push(option);
      items.push({ type: 'option', option });
    }
  });

  return { items, options };
}

function toValueArray(value: SelectValue | undefined, defaultValue: SelectValue | undefined, multiple?: boolean): string[] {
  const raw = value ?? defaultValue ?? (multiple ? [] : '');
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === 'number') return [String(raw)];
  if (typeof raw === 'string') return raw ? [raw] : [];
  return [];
}

function firstEnabledIndex(items: ParsedItem[]): number {
  return items.findIndex((item) => item.type === 'option' && !item.option.disabled);
}

export default function InAppSelect(props: InAppSelectProps) {
  const {
    children,
    className,
    defaultValue,
    disabled,
    id,
    multiple,
    name,
    onChange,
    required,
    style,
    title,
    value,
    ...rest
  } = props;
  const restAttrs = rest as Record<string, unknown>;
  const ariaLabel = restAttrs['aria-label'] as string | undefined;
  const dataTestId = restAttrs['data-testid'] as string | undefined;
  const dataAttrs = Object.fromEntries(
    Object.entries(restAttrs).filter(([key]) => key.startsWith('data-') && key !== 'data-testid'),
  ) as Record<string, string | number | boolean | undefined>;

  const listboxId = useId();
  const triggerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [internalValue, setInternalValue] = useState<SelectValue | undefined>(defaultValue as SelectValue | undefined);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});
  const controlled = value !== undefined;
  const selectedValues = toValueArray(controlled ? value as SelectValue : internalValue, defaultValue as SelectValue | undefined, multiple);
  const selectedSet = useMemo(() => new Set(selectedValues), [selectedValues]);
  const { items, options } = useMemo(() => parseItems(children), [children]);
  const selectedOptions = useMemo(
    () => options.filter((option) => selectedSet.has(option.value)),
    [options, selectedSet],
  );

  const displayLabel = useMemo(() => {
    if (multiple) {
      if (selectedOptions.length === 0) return 'Select...';
      if (selectedOptions.length === 1) return selectedOptions[0].label;
      return `${selectedOptions.length} selected`;
    }
    if (selectedOptions[0]) return selectedOptions[0].label;
    const selected = options.find((option) => option.value === selectedValues[0]);
    if (selected) return selected.label;
    return options[0]?.label || 'Select...';
  }, [multiple, options, selectedOptions, selectedValues]);

  const filteredItems = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;

    const next: ParsedItem[] = [];
    let pendingGroup: string | null = null;
    for (const item of items) {
      if (item.type === 'group') {
        pendingGroup = item.label;
        continue;
      }
      const searchableText = [
        item.option.label,
        item.option.value,
        item.option.title || '',
        item.option.group || '',
      ].join(' ').toLowerCase();
      if (!searchableText.includes(q)) continue;
      if (pendingGroup) {
        next.push({ type: 'group', label: pendingGroup });
        pendingGroup = null;
      }
      next.push(item);
    }
    return next;
  }, [filter, items]);

  const updateMenuPosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const margin = 8;
    const gap = 4;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.max(rect.width, 180);
    const below = viewportHeight - rect.bottom - margin;
    const above = rect.top - margin;
    const placeBelow = below >= 160 || below >= above;
    const maxHeight = Math.max(120, Math.min(320, (placeBelow ? below : above) - gap));
    const left = Math.min(Math.max(margin, rect.left), Math.max(margin, viewportWidth - width - margin));
    const top = placeBelow ? rect.bottom + gap : Math.max(margin, rect.top - maxHeight - gap);
    setMenuStyle({ left, top, width, maxHeight });
  }, []);

  const setOpenWithPosition = useCallback((nextOpen: boolean) => {
    if (disabled) return;
    setOpen(nextOpen);
    if (nextOpen) {
      const selectedIndex = filteredItems.findIndex((item) => item.type === 'option' && selectedSet.has(item.option.value) && !item.option.disabled);
      setActiveIndex(selectedIndex >= 0 ? selectedIndex : firstEnabledIndex(filteredItems));
      requestAnimationFrame(updateMenuPosition);
      requestAnimationFrame(() => filterRef.current?.focus());
    } else {
      setFilter('');
    }
  }, [disabled, filteredItems, selectedSet, updateMenuPosition]);

  const emitChange = useCallback((nextValue: string | string[]) => {
    if (!controlled) setInternalValue(nextValue);
    const values = Array.isArray(nextValue) ? nextValue : [nextValue];
    const nextSelected = options.filter((option) => values.includes(option.value));
    const target = {
      id,
      multiple: Boolean(multiple),
      name,
      selectedOptions: nextSelected.map((option) => ({ value: option.value, label: option.label, text: option.label })),
      value: Array.isArray(nextValue) ? (nextValue[0] ?? '') : nextValue,
    } as unknown as HTMLSelectElement;
    onChange?.({
      currentTarget: target,
      target,
    } as React.ChangeEvent<HTMLSelectElement>);
  }, [controlled, id, multiple, name, onChange, options]);

  const chooseOption = useCallback((option: ParsedOption) => {
    if (option.disabled) return;
    if (multiple) {
      const nextValues = selectedSet.has(option.value)
        ? selectedValues.filter((selected) => selected !== option.value)
        : [...selectedValues, option.value];
      emitChange(nextValues);
      return;
    }
    emitChange(option.value);
    setOpen(false);
    setFilter('');
  }, [emitChange, multiple, selectedSet, selectedValues]);

  const moveActive = useCallback((direction: 1 | -1) => {
    if (filteredItems.length === 0) return;
    let next = activeIndex;
    for (let attempt = 0; attempt < filteredItems.length; attempt += 1) {
      next = (next + direction + filteredItems.length) % filteredItems.length;
      const item = filteredItems[next];
      if (item.type === 'option' && !item.option.disabled) {
        setActiveIndex(next);
        return;
      }
    }
  }, [activeIndex, filteredItems]);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return undefined;
    updateMenuPosition();
    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
      setFilter('');
    };
    document.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('resize', updateMenuPosition);
    window.addEventListener('scroll', updateMenuPosition, true);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('resize', updateMenuPosition);
      window.removeEventListener('scroll', updateMenuPosition, true);
    };
  }, [open, updateMenuPosition]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = filteredItems.findIndex((item) => item.type === 'option' && selectedSet.has(item.option.value) && !item.option.disabled);
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : firstEnabledIndex(filteredItems));
  }, [filter, filteredItems, open, selectedSet]);

  const nativeValueProps = controlled
    ? { value: value as React.SelectHTMLAttributes<HTMLSelectElement>['value'] }
    : { value: (multiple ? selectedValues : (selectedValues[0] ?? '')) as React.SelectHTMLAttributes<HTMLSelectElement>['value'] };

  const menu = open && mounted ? createPortal(
    <div
      ref={menuRef}
      id={listboxId}
      className="in-app-select-menu"
      role="listbox"
      aria-multiselectable={multiple || undefined}
      style={menuStyle}
    >
      {filteredItems.map((item, index) => {
        if (item.type === 'group') {
          return <div key={`group-${item.label}-${index}`} className="in-app-select-group">{item.label}</div>;
        }
        const { option } = item;
        const selected = selectedSet.has(option.value);
        return (
          <div
            key={`${option.group || 'root'}-${option.value}-${index}`}
            role="option"
            aria-selected={selected}
            aria-disabled={option.disabled || undefined}
            title={option.title}
            className={[
              'in-app-select-option',
              selected ? 'selected' : '',
              activeIndex === index ? 'active' : '',
              option.disabled ? 'disabled' : '',
              multiple ? 'multiple' : '',
            ].filter(Boolean).join(' ')}
            onMouseEnter={() => !option.disabled && setActiveIndex(index)}
            onClick={() => chooseOption(option)}
          >
            {multiple && <span className="in-app-select-check" aria-hidden="true" />}
            <span className="in-app-select-option-label">{option.label}</span>
          </div>
        );
      })}
      {filteredItems.length === 0 && <div className="in-app-select-empty">{filter ? 'No matches' : 'No options'}</div>}
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <div
        ref={triggerRef}
        className={['in-app-select', className || '', disabled ? 'disabled' : '', multiple ? 'multiple' : '', open ? 'open' : ''].filter(Boolean).join(' ')}
        style={style}
        role="button"
        aria-controls={open ? listboxId : undefined}
        aria-disabled={disabled || undefined}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel || title || 'Select option'}
        tabIndex={disabled ? -1 : 0}
        title={title}
        onClick={() => setOpenWithPosition(!open)}
        onKeyDown={(event) => {
          if (disabled) return;
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (!open) setOpenWithPosition(true);
            else moveActive(1);
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (!open) setOpenWithPosition(true);
            else moveActive(-1);
          } else if (event.key === 'Home') {
            event.preventDefault();
            setActiveIndex(firstEnabledIndex(filteredItems));
          } else if (event.key === 'End') {
            event.preventDefault();
            for (let index = filteredItems.length - 1; index >= 0; index -= 1) {
              const item = filteredItems[index];
              if (item.type === 'option' && !item.option.disabled) {
                setActiveIndex(index);
                break;
              }
            }
          } else if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (!open) {
              setOpenWithPosition(true);
              return;
            }
            const item = filteredItems[activeIndex];
            if (item?.type === 'option') chooseOption(item.option);
          } else if (event.key === 'Escape') {
            event.preventDefault();
            setOpen(false);
            setFilter('');
          } else if (event.key === 'Tab') {
            setOpen(false);
            setFilter('');
          }
        }}
        {...dataAttrs}
      >
        {open ? (
          <input
            ref={filterRef}
            className="in-app-select-filter"
            value={filter}
            placeholder={displayLabel}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => setFilter(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveActive(1);
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveActive(-1);
              } else if (event.key === 'Enter') {
                event.preventDefault();
                const item = filteredItems[activeIndex];
                if (item?.type === 'option') chooseOption(item.option);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                setOpen(false);
                setFilter('');
              } else if (event.key === 'Tab') {
                setOpen(false);
                setFilter('');
              }
            }}
          />
        ) : (
          <span className="in-app-select-value">{displayLabel}</span>
        )}
        <span className="in-app-select-caret" aria-hidden="true">{open ? '\u25B2' : '\u25BC'}</span>
      </div>
      <select
        id={id}
        name={name}
        className={['in-app-select-native', className || ''].filter(Boolean).join(' ')}
        data-testid={dataTestId}
        disabled={disabled}
        multiple={multiple}
        onChange={onChange}
        required={required}
        tabIndex={-1}
        title={title}
        {...nativeValueProps}
      >
        {children}
      </select>
      {menu}
    </>
  );
}
