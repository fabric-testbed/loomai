'use client';
import { useState, useEffect, useLayoutEffect, useCallback, useRef } from 'react';
import type { TourStep } from '../data/tourSteps';
import '../styles/guided-tour.css';

export interface GuidedTourProps {
  active: boolean;
  steps: TourStep[];
  step: number;
  onStepChange: (step: number) => void;
  onDismiss: () => void;       // permanent dismiss (sets localStorage for getting-started)
  onClose: () => void;         // close without permanent dismiss
  onOpenSettings: () => void;
  onCloseSettings: () => void;
  settingsOpen: boolean;
  onSwitchView: (view: any) => void;
  currentView: string;
  /** Context values for completion checks — keys match TourStep.completionCheck */
  tourContext: Record<string, boolean>;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PADDING = 8;

export default function GuidedTour({
  active,
  steps,
  step,
  onStepChange,
  onDismiss,
  onClose,
  onOpenSettings,
  onCloseSettings,
  settingsOpen,
  onSwitchView,
  currentView,
  tourContext,
}: GuidedTourProps) {
  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const [centered, setCentered] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const tooltipRef = useRef<HTMLDivElement>(null);

  const currentStep = steps[step];
  const isFirst = step === 0;
  const isLast = step === steps.length - 1;

  // Check if the current step has a completion requirement and whether it's met
  const completionCheck = currentStep?.completionCheck;
  const isStepComplete = completionCheck ? (tourContext[completionCheck] ?? false) : undefined;
  const isFullscreen = currentStep?.targetSelector === '_fullscreen';

  // Measure target element position, scrolling it into view first
  const measure = useCallback(() => {
    if (!currentStep) return;
    const el = document.querySelector(currentStep.targetSelector);
    if (el) {
      // Scroll element to center of viewport so it's clearly visible
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Wait for scroll animation to finish before measuring
      setTimeout(() => {
        const r = el.getBoundingClientRect();
        setTargetRect({
          top: r.top - PADDING,
          left: r.left - PADDING,
          width: r.width + PADDING * 2,
          height: r.height + PADDING * 2,
        });
        setCentered(false);
      }, 400);
    } else {
      setTargetRect(null);
      setCentered(true);
    }
  }, [currentStep]);

  // Handle view transitions when step changes
  useEffect(() => {
    if (!active || !currentStep) return;
    const rv = currentStep.requiredView;
    if (rv === 'settings') {
      if (!settingsOpen) onOpenSettings();
    } else {
      if (settingsOpen) onCloseSettings();
      // Map requiredView to the new top-level view
      const viewMap: Record<string, string> = {
        main: 'slices',
        map: 'slices',
        files: 'slices',
        slivers: 'slices',
        ai: 'ai',
        libraries: 'artifacts',
        client: 'slices',
        jupyter: 'jupyter',
        landing: 'landing',
      };
      const targetView = viewMap[rv] || 'slices';
      if (currentView !== targetView) onSwitchView(targetView as any);
    }
  }, [active, step]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-measure after step change (delay for DOM to settle)
  useLayoutEffect(() => {
    if (!active) return;
    // Immediate measure + delayed re-measure for transitions
    measure();
    timerRef.current = setTimeout(measure, 350);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [active, step, measure]);

  // ResizeObserver for window changes
  useEffect(() => {
    if (!active) return;
    const handleResize = () => measure();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [active, measure]);

  const handleNext = () => {
    if (isLast) {
      onDismiss();
    } else {
      onStepChange(step + 1);
    }
  };

  const handleBack = () => {
    if (!isFirst) {
      onStepChange(step - 1);
    }
  };

  if (!active || !currentStep) return null;

  // Compute tooltip position relative to spotlight, clamped to viewport
  const tooltipStyle: React.CSSProperties = {};
  let arrowClass = '';
  const arrowStyle: React.CSSProperties = {};

  if (centered || !targetRect) {
    // Centered fallback
  } else {
    const pos = currentStep.tooltipPosition;
    const tooltipWidth = 360;
    // Use actual tooltip height if available, else estimate
    const tooltipHeight = tooltipRef.current?.offsetHeight ?? 220;
    const gap = 16;
    const margin = 8; // minimum distance from viewport edge
    const vh = window.innerHeight;
    const vw = window.innerWidth;

    // Center of the target element (used to aim the arrow)
    const targetCenterX = targetRect.left + targetRect.width / 2;
    const targetCenterY = targetRect.top + targetRect.height / 2;

    if (pos === 'bottom') {
      tooltipStyle.top = targetRect.top + targetRect.height + gap;
      tooltipStyle.left = Math.max(margin, Math.min(targetRect.left, vw - tooltipWidth - margin));
      arrowClass = 'arrow-top';
      // Flip to top if it would overflow bottom
      if ((tooltipStyle.top as number) + tooltipHeight > vh - margin) {
        tooltipStyle.top = targetRect.top - tooltipHeight - gap;
        arrowClass = 'arrow-bottom';
      }
    } else if (pos === 'top') {
      tooltipStyle.top = targetRect.top - tooltipHeight - gap;
      tooltipStyle.left = Math.max(margin, Math.min(targetRect.left, vw - tooltipWidth - margin));
      arrowClass = 'arrow-bottom';
      // Flip to bottom if it would overflow top
      if ((tooltipStyle.top as number) < margin) {
        tooltipStyle.top = targetRect.top + targetRect.height + gap;
        arrowClass = 'arrow-top';
      }
    } else if (pos === 'right') {
      tooltipStyle.top = targetRect.top;
      tooltipStyle.left = targetRect.left + targetRect.width + gap;
      arrowClass = 'arrow-left';
      // Flip to left if it would overflow right
      if ((tooltipStyle.left as number) + tooltipWidth > vw - margin) {
        tooltipStyle.left = targetRect.left - tooltipWidth - gap;
        arrowClass = 'arrow-right';
      }
    } else if (pos === 'left') {
      tooltipStyle.top = targetRect.top;
      tooltipStyle.left = targetRect.left - tooltipWidth - gap;
      arrowClass = 'arrow-right';
      // Flip to right if it would overflow left
      if ((tooltipStyle.left as number) < margin) {
        tooltipStyle.left = targetRect.left + targetRect.width + gap;
        arrowClass = 'arrow-left';
      }
    }

    // Final vertical clamp: ensure tooltip is fully within viewport
    if (tooltipStyle.top != null) {
      if ((tooltipStyle.top as number) + tooltipHeight > vh - margin) {
        tooltipStyle.top = vh - tooltipHeight - margin;
      }
      if ((tooltipStyle.top as number) < margin) {
        tooltipStyle.top = margin;
      }
    }

    // Position arrow to point at target center, clamped within tooltip bounds
    const arrowSize = 12;
    const arrowMargin = 16; // min distance from tooltip edge
    const tooltipLeft = tooltipStyle.left as number;
    const tooltipTop = tooltipStyle.top as number;

    if (arrowClass === 'arrow-top' || arrowClass === 'arrow-bottom') {
      // Horizontal arrow: position along x-axis to point at target center
      const arrowLeft = Math.max(arrowMargin, Math.min(
        targetCenterX - tooltipLeft - arrowSize / 2,
        tooltipWidth - arrowMargin - arrowSize,
      ));
      arrowStyle.left = arrowLeft;
    } else if (arrowClass === 'arrow-left' || arrowClass === 'arrow-right') {
      // Vertical arrow: position along y-axis to point at target center
      const arrowTop = Math.max(arrowMargin, Math.min(
        targetCenterY - tooltipTop - arrowSize / 2,
        tooltipHeight - arrowMargin - arrowSize,
      ));
      arrowStyle.top = arrowTop;
    }
  }

  // Determine Next button label based on completion state
  const nextLabel = isLast
    ? 'Done'
    : (completionCheck && !isStepComplete)
      ? 'Skip'
      : 'Next';

  return (
    <>
      {/* Spotlight overlay */}
      {targetRect && !centered && (
        <div
          className="tour-spotlight"
          style={{
            top: targetRect.top,
            left: targetRect.left,
            width: targetRect.width,
            height: targetRect.height,
          }}
        />
      )}

      {/* Darkened backdrop when centered (no target) */}
      {centered && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.55)',
            zIndex: 9998,
          }}
        />
      )}

      {/* Tooltip card */}
      <div
        ref={tooltipRef}
        className={`tour-tooltip ${centered ? 'centered' : ''} ${isFullscreen ? 'tour-tooltip-fullscreen' : ''}`}
        style={centered ? undefined : tooltipStyle}
      >
        {arrowClass && !centered && (
          <div className={`tour-arrow ${arrowClass}`} style={arrowStyle} />
        )}
        <h3 className="tour-tooltip-title">{currentStep.title}</h3>
        {currentStep.imageUrl && (
          <img
            className="tour-tooltip-image"
            src={currentStep.imageUrl}
            alt={currentStep.imageAlt || currentStep.title}
          />
        )}
        <p className="tour-tooltip-content">{currentStep.content}</p>

        {/* Completion indicator for interactive steps */}
        {completionCheck && (
          <div className={`tour-completion ${isStepComplete ? 'complete' : 'pending'}`}>
            <span className="tour-completion-icon">{isStepComplete ? '\u2713' : '\u25CB'}</span>
            <span className="tour-completion-label">
              {isStepComplete
                ? (currentStep.completionLabel || 'Complete')
                : (currentStep.pendingLabel || 'Complete this step or skip')}
            </span>
          </div>
        )}

        <div className="tour-step-indicator">
          Step {step + 1} of {steps.length}
        </div>
        <div className="tour-nav">
          {!isFirst && (
            <button className="tour-btn" onClick={handleBack}>
              Back
            </button>
          )}
          <button
            className={`tour-btn ${(completionCheck && !isStepComplete) ? '' : 'primary'}`}
            onClick={handleNext}
          >
            {nextLabel}
          </button>
          <button className="tour-btn skip" onClick={onClose}>
            Exit Tour
          </button>
        </div>
      </div>
    </>
  );
}
