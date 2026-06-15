'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import '../styles/app-dialog.css';

type DialogTone = 'default' | 'danger';
type DialogKind = 'alert' | 'confirm' | 'prompt';

type DialogOptions = {
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  defaultValue?: string;
  placeholder?: string;
  tone?: DialogTone;
};

type DialogRequest<T = unknown> = DialogOptions & {
  id: number;
  kind: DialogKind;
  message: string;
  resolve: (value: T) => void;
};

type DialogController = {
  show: <T>(request: Omit<DialogRequest<T>, 'id' | 'resolve'>) => Promise<T>;
};

let controller: DialogController | null = null;
let nextDialogId = 1;

function nativeFallback<T>(kind: DialogKind, message: string, options: DialogOptions): Promise<T> {
  console.warn(`[app-dialog] Dialog requested before provider mounted: ${message}`, options);
  if (kind === 'alert') {
    return Promise.resolve(undefined as T);
  }
  if (kind === 'confirm') {
    return Promise.resolve(false as T);
  }
  return Promise.resolve(null as T);
}

function requestDialog<T>(kind: DialogKind, message: string, options: DialogOptions = {}): Promise<T> {
  if (!controller) return nativeFallback<T>(kind, message, options);
  return controller.show<T>({ kind, message, ...options });
}

export function alertDialog(message: string, options?: DialogOptions): Promise<void> {
  return requestDialog<void>('alert', message, options);
}

export function confirmDialog(message: string, options?: DialogOptions): Promise<boolean> {
  return requestDialog<boolean>('confirm', message, options);
}

export function promptDialog(message: string, options?: DialogOptions): Promise<string | null> {
  return requestDialog<string | null>('prompt', message, options);
}

export function AppDialogProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState<DialogRequest | null>(null);
  const [promptValue, setPromptValue] = useState('');
  const activeRef = useRef<DialogRequest | null>(null);
  const queueRef = useRef<DialogRequest[]>([]);

  const showNext = useCallback(() => {
    const next = queueRef.current.shift() || null;
    activeRef.current = next;
    setActive(next);
    setPromptValue(next?.defaultValue || '');
  }, []);

  const show = useCallback(<T,>(request: Omit<DialogRequest<T>, 'id' | 'resolve'>) => (
    new Promise<T>((resolve) => {
      const item = { ...request, id: nextDialogId++, resolve } as DialogRequest<T>;
      if (activeRef.current) {
        queueRef.current.push(item as DialogRequest);
        return;
      }
      activeRef.current = item as DialogRequest;
      setActive(item as DialogRequest);
      setPromptValue(item.defaultValue || '');
    })
  ), []);

  useEffect(() => {
    controller = { show };
    return () => {
      if (controller?.show === show) controller = null;
    };
  }, [show]);

  const close = useCallback((value: unknown) => {
    const current = activeRef.current;
    if (!current) return;
    activeRef.current = null;
    setPromptValue('');
    if (queueRef.current.length > 0) {
      showNext();
    } else {
      setActive(null);
    }
    current.resolve(value);
  }, [showNext]);

  useEffect(() => {
    if (!active) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close(active.kind === 'confirm' ? false : active.kind === 'prompt' ? null : undefined);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [active, close]);

  const dialog = active && typeof document !== 'undefined' ? createPortal(
    <div
      className="app-dialog-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget) return;
        close(active.kind === 'confirm' ? false : active.kind === 'prompt' ? null : undefined);
      }}
    >
      <div
        className={`app-dialog app-dialog-${active.tone || 'default'}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`app-dialog-title-${active.id}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="app-dialog-header">
          <h2 id={`app-dialog-title-${active.id}`}>
            {active.title || (active.kind === 'confirm' ? 'Confirm Action' : active.kind === 'prompt' ? 'Input Required' : 'Notice')}
          </h2>
        </div>
        <div className="app-dialog-body">
          {active.message.split('\n').map((line, index) => (
            <p key={index}>{line || '\u00a0'}</p>
          ))}
          {active.kind === 'prompt' && (
            <input
              className="app-dialog-input"
              value={promptValue}
              placeholder={active.placeholder}
              autoFocus
              onChange={(event) => setPromptValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') close(promptValue);
              }}
            />
          )}
        </div>
        <div className="app-dialog-actions">
          {active.kind !== 'alert' && (
            <button className="app-dialog-button app-dialog-button-secondary" onClick={() => close(active.kind === 'confirm' ? false : null)}>
              {active.cancelLabel || 'Cancel'}
            </button>
          )}
          <button
            className={`app-dialog-button app-dialog-button-primary ${active.tone === 'danger' ? 'app-dialog-button-danger' : ''}`}
            onClick={() => close(active.kind === 'prompt' ? promptValue : active.kind === 'confirm' ? true : undefined)}
            autoFocus={active.kind !== 'prompt'}
          >
            {active.confirmLabel || (active.kind === 'alert' ? 'OK' : 'Confirm')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <>
      {children}
      {dialog}
    </>
  );
}
