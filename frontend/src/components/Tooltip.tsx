'use client';
import { useState, useRef, useCallback, useLayoutEffect, type ReactNode } from 'react';
import '../styles/tooltip.css';

interface TooltipProps {
  text: string;
  children: ReactNode;
  delay?: number;
}

export default function Tooltip({ text, children, delay = 400 }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [adjusted, setAdjusted] = useState({ x: 0, y: 0 });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const show = useCallback((e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPos({ x: rect.left + rect.width / 2, y: rect.bottom + 6 });
    setAdjusted({ x: 0, y: 0 });
    timerRef.current = setTimeout(() => setVisible(true), delay);
  }, [delay]);

  const hide = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setVisible(false);
  }, []);

  // After the popup renders, check if it overflows the viewport and nudge it
  useLayoutEffect(() => {
    if (!visible || !popupRef.current) return;
    const el = popupRef.current;
    const rect = el.getBoundingClientRect();
    const pad = 8;
    let dx = 0;
    let dy = 0;

    // Horizontal clamping
    if (rect.left < pad) {
      dx = pad - rect.left;
    } else if (rect.right > window.innerWidth - pad) {
      dx = window.innerWidth - pad - rect.right;
    }

    // If tooltip goes below viewport, flip it above the trigger
    if (rect.bottom > window.innerHeight - pad) {
      const wrapperRect = wrapperRef.current?.getBoundingClientRect();
      if (wrapperRect) {
        dy = wrapperRect.top - 6 - rect.height - pos.y;
      }
    }

    if (dx !== 0 || dy !== 0) {
      setAdjusted({ x: dx, y: dy });
    }
  }, [visible, pos]);

  return (
    <span className="tooltip-wrapper" ref={wrapperRef} onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {visible && (
        <div
          ref={popupRef}
          className="tooltip-popup"
          style={{
            left: pos.x + adjusted.x,
            top: pos.y + adjusted.y,
            transform: 'translateX(-50%)',
          }}
        >
          {text}
        </div>
      )}
    </span>
  );
}
