'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { installToolStream, type InstallStreamEvent } from '../api/client';
import '../styles/tool-install-overlay.css';

interface ToolInstallOverlayProps {
  toolId: string;
  onComplete: () => void;
  onError: (message: string) => void;
}

const INSTALL_STEPS: Record<string, string[]> = {
  jupyterlab: [
    'Preparing environment...',
    'Creating virtual environment...',
    'Downloading JupyterLab packages...',
    'Installing dependencies...',
    'Configuring JupyterLab...',
    'Finalizing...',
  ],
  opencode: [
    'Preparing environment...',
    'Setting up npm prefix...',
    'Downloading OpenCode packages...',
    'Installing dependencies...',
    'Configuring workspace...',
    'Finalizing...',
  ],
  aider: [
    'Preparing environment...',
    'Creating virtual environment...',
    'Downloading Aider packages...',
    'Installing dependencies...',
    'Configuring Streamlit...',
    'Finalizing...',
  ],
  default: [
    'Preparing environment...',
    'Downloading packages...',
    'Installing dependencies...',
    'Configuring...',
    'Finalizing...',
  ],
};

export default function ToolInstallOverlay({ toolId, onComplete, onError }: ToolInstallOverlayProps) {
  const [displayName, setDisplayName] = useState(toolId);
  const [sizeEstimate, setSizeEstimate] = useState('');
  const [currentStep, setCurrentStep] = useState(0);
  const [outputLines, setOutputLines] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const stepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const steps = INSTALL_STEPS[toolId] || INSTALL_STEPS.default;

  // Auto-scroll the output log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [outputLines]);

  const runInstall = useCallback(async () => {
    // Advance steps on a timer (visual progress)
    let step = 0;
    stepTimerRef.current = setInterval(() => {
      step = Math.min(step + 1, steps.length - 1);
      setCurrentStep(step);
    }, 3000);

    try {
      const result = await installToolStream(toolId, (event: InstallStreamEvent) => {
        if (event.type === 'start') {
          if (event.display_name) setDisplayName(event.display_name);
          if (event.size_estimate) setSizeEstimate(event.size_estimate);
        } else if (event.type === 'output' && event.message) {
          setOutputLines(prev => {
            const next = [...prev, event.message!];
            // Keep last 200 lines to avoid unbounded growth
            return next.length > 200 ? next.slice(-200) : next;
          });
        } else if (event.type === 'error') {
          setOutputLines(prev => [...prev, `Error: ${event.message || 'Unknown error'}`]);
        }
      });

      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
      setCurrentStep(steps.length); // Mark all done

      if (result.status === 'installed' || result.status === 'already_installed') {
        setDone(true);
        // Brief pause to show completion before closing
        setTimeout(() => onComplete(), 800);
      } else {
        onError(`Failed to install ${displayName}. Please try again.`);
      }
    } catch (e: any) {
      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
      onError(e.message || `Failed to install ${displayName}`);
    }
  }, [toolId, steps, displayName, onComplete, onError]);

  useEffect(() => {
    runInstall();
    return () => {
      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="tool-install-overlay">
      <div className="tool-install-modal">
        <div className="tool-install-spinner" />
        <h4>Installing {displayName}</h4>
        {sizeEstimate && <div className="tool-install-size">{sizeEstimate}</div>}

        <div className="tool-install-steps">
          {steps.map((msg, i) => (
            <div
              key={i}
              className={`tool-install-step${i < currentStep ? ' done' : i === currentStep ? ' active' : ''}${done ? ' done' : ''}`}
            >
              <span className="tool-install-step-icon">
                {(i < currentStep || done) ? '\u2713' : i === currentStep ? '\u25CF' : '\u25CB'}
              </span>
              {msg}
            </div>
          ))}
        </div>

        <div className="tool-install-log" ref={logRef}>
          {outputLines.map((line, i) => (
            <div key={i} className="tool-install-log-line">{line}</div>
          ))}
        </div>

        {done && (
          <div className="tool-install-done">Installation complete — launching...</div>
        )}
      </div>
    </div>
  );
}
