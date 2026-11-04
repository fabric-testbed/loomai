'use client';

import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

/**
 * The one way to render a modal dialog.
 *
 * CLAUDE.md requires every modal to be a centered viewport popup: portaled to
 * document.body, with the positioning as inline styles (CSS classes can be
 * overridden or fail to load), z-index 99999 (above title-bar dropdowns at
 * 9999), and a scrollable box capped at 80vh. This component is that rule.
 *
 * `overlayClassName` / `className` keep each caller's existing CSS for colors,
 * padding and width; the inline styles here only own positioning, stacking
 * and overflow. Escape and a backdrop click call `onClose`; omit `onClose`
 * for a dialog that must not be dismissed (e.g. a progress overlay).
 */
export interface ModalProps {
  onClose?: () => void;
  children: React.ReactNode;
  /** Class for the dialog box (e.g. "toolbar-modal"). */
  className?: string;
  /** Class for the backdrop (e.g. "toolbar-modal-overlay"). */
  overlayClassName?: string;
  /** Extra inline styles for the dialog box (merged after the defaults). */
  style?: React.CSSProperties;
  'data-testid'?: string;
  /** data-testid for the dialog box itself (the overlay gets `data-testid`). */
  boxTestId?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
}

const OVERLAY_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(0,0,0,0.5)',
  zIndex: 99999,
};

const BOX_STYLE: React.CSSProperties = {
  maxHeight: '80vh',
  overflowY: 'auto',
};

export function Modal({
  onClose,
  children,
  className,
  overlayClassName,
  style,
  'data-testid': testId,
  boxTestId,
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
}: ModalProps) {
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    // Move focus into the dialog so keyboard users land on it and Escape
    // works without a click first; only if nothing inside is focused yet.
    const box = boxRef.current;
    if (box && !box.contains(document.activeElement)) box.focus();
  }, []);

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className={overlayClassName}
      style={OVERLAY_STYLE}
      onClick={onClose}
      data-testid={testId}
    >
      <div
        ref={boxRef}
        className={className}
        style={{ ...BOX_STYLE, ...style }}
        role="dialog"
        aria-modal="true"
        data-testid={boxTestId}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

export default Modal;
