'use client';
import { useEffect, useRef, useMemo, useState } from 'react';
import { helpSections } from '../data/helpData';
import { tourList, toursBySection } from '../data/tourSteps';
import { assetUrl } from '../utils/assetUrl';
import '../styles/help.css';
import '../styles/guided-tour.css';

/** Lightweight markdown-to-HTML for help descriptions.
 *  Handles: paragraphs, **bold**, `code`, ```code blocks```, [links](url), images, - lists.
 */
function renderMarkdown(md: string): string {
  const escapeHtml = (value: string) =>
    value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const escapeAttr = (value: string) =>
    escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  type ScreenshotCallout = {
    kind: 'arrow' | 'rect' | 'circle';
    label: string;
    x: number;
    y: number;
    width: number;
    height: number;
    labelX: number;
    labelY: number;
    title: string;
  };

  const codeBlockMeta = (language: string, code: string) => {
    const normalized = language.trim().toLowerCase();
    const firstLine = code.trimStart().split('\n')[0]?.trim().toLowerCase() || '';
    const hasApiShape = /\bcurl\b/.test(firstLine) || /\/api\//.test(code) || normalized === 'http' || normalized === 'rest' || normalized === 'api';
    const cliPrefixes = ['loomai', 'kubectl', 'docker', 'npm', 'npx', 'pytest', 'pip', 'cd', 'use', 'show', 'clear', 'eval', 'source', 'exit', 'quit', '?', '/ask', '/model'];
    const hasCliShape = cliPrefixes.some(prefix => firstLine === prefix || firstLine.startsWith(`${prefix} `))
      || ['bash', 'sh', 'shell', 'zsh', 'fish', 'terminal', 'console'].includes(normalized);

    if (hasApiShape) return { kind: 'api', label: 'API example' };
    if (hasCliShape) return { kind: 'cli', label: 'CLI example' };
    if (normalized) return { kind: 'code', label: 'Code example' };
    return { kind: 'code', label: 'Example' };
  };

  const highlightByPattern = (
    value: string,
    pattern: RegExp,
    classNameForMatch: (match: RegExpExecArray) => string,
    transformMatch?: (match: RegExpExecArray) => string,
  ): string => {
    const parts: string[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    pattern.lastIndex = 0;

    while ((match = pattern.exec(value)) !== null) {
      if (match.index > lastIndex) {
        parts.push(escapeHtml(value.slice(lastIndex, match.index)));
      }
      const className = classNameForMatch(match);
      const text = transformMatch ? transformMatch(match) : match[0];
      parts.push(`<span class="${className}">${escapeHtml(text)}</span>`);
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < value.length) {
      parts.push(escapeHtml(value.slice(lastIndex)));
    }
    return parts.join('');
  };

  const highlightShellLine = (line: string): string => {
    const commentIndex = line.search(/(^|\s)#/);
    const commandPart = commentIndex >= 0 ? line.slice(0, commentIndex) : line;
    const commentPart = commentIndex >= 0 ? line.slice(commentIndex) : '';
    const highlighted = highlightByPattern(
      commandPart,
      /https?:\/\/[^\s]+|--?[\w-]+(?:=[^\s]+)?|<[^>\s]+>|"[^"]*"|'[^']*'|(?:^|\s)(loomai|curl|python3?|pip|pytest|npm|npx|docker|kubectl|cd|eval|source|use|show|clear|exit|quit|jq)(?=\s|$)|(?:^|\s)(\/ask|\/model|\?)(?=\s|$)|\b\d+(?:\.\d+)?\b/g,
      (match) => {
        const text = match[0].trimStart();
        if (/^https?:\/\//.test(text)) return 'help-syntax-url';
        if (/^--?/.test(text)) return 'help-syntax-flag';
        if (/^<[^>]+>$/.test(text)) return 'help-syntax-placeholder';
        if (/^["']/.test(text)) return 'help-syntax-string';
        if (/^\/|^\?$/.test(text)) return 'help-syntax-command';
        if (/^\d/.test(text)) return 'help-syntax-number';
        return 'help-syntax-command';
      },
    );
    return `${highlighted}${commentPart ? `<span class="help-syntax-comment">${escapeHtml(commentPart)}</span>` : ''}`;
  };

  const highlightPythonLine = (line: string): string => {
    const commentIndex = line.indexOf('#');
    const codePart = commentIndex >= 0 ? line.slice(0, commentIndex) : line;
    const commentPart = commentIndex >= 0 ? line.slice(commentIndex) : '';
    const highlighted = highlightByPattern(
      codePart,
      /"[^"]*"|'[^']*'|\b(import|from|for|in|if|else|elif|return|def|class|try|except|with|as|raise|print)\b|\b(True|False|None)\b|\b\d+(?:\.\d+)?\b|\b(requests|response|json|get|post|put|delete|raise_for_status)\b/g,
      (match) => {
        const text = match[0];
        if (/^["']/.test(text)) return 'help-syntax-string';
        if (/^(True|False|None)$/.test(text)) return 'help-syntax-constant';
        if (/^\d/.test(text)) return 'help-syntax-number';
        if (/^(requests|response|json|get|post|put|delete|raise_for_status)$/.test(text)) return 'help-syntax-function';
        return 'help-syntax-keyword';
      },
    );
    return `${highlighted}${commentPart ? `<span class="help-syntax-comment">${escapeHtml(commentPart)}</span>` : ''}`;
  };

  const highlightGenericLine = (line: string): string => highlightByPattern(
    line,
    /"[^"]*"|'[^']*'|`[^`]*`|\b(true|false|null|undefined)\b|\b\d+(?:\.\d+)?\b/g,
    (match) => {
      const text = match[0];
      if (/^["'`]/.test(text)) return 'help-syntax-string';
      if (/^(true|false|null|undefined)$/.test(text)) return 'help-syntax-constant';
      return 'help-syntax-number';
    },
  );

  const highlightCode = (language: string, code: string, kind: string): string => {
    const normalized = language.trim().toLowerCase();
    return code
      .replace(/\n$/, '')
      .split('\n')
      .map((line) => {
        if (kind === 'api' || kind === 'cli' || ['bash', 'sh', 'shell', 'zsh', 'fish', 'curl'].includes(normalized)) {
          return highlightShellLine(line);
        }
        if (['python', 'py'].includes(normalized)) {
          return highlightPythonLine(line);
        }
        return highlightGenericLine(line);
      })
      .join('\n');
  };

  const renderCodeBlock = (language: string, code: string): string => {
    const meta = codeBlockMeta(language, code);
    const languageLabel = language.trim() ? `<span class="help-code-language">${escapeHtml(language.trim())}</span>` : '';
    return [
      `<div class="help-code-block help-code-block-${meta.kind}">`,
      '<div class="help-code-header">',
      `<span class="help-code-label">${meta.label}</span>`,
      '<div class="help-code-actions">',
      languageLabel,
      '<button type="button" class="help-code-copy" aria-label="Copy example">Copy</button>',
      '</div>',
      '</div>',
      `<pre><code>${highlightCode(language, code, meta.kind)}</code></pre>`,
      '</div>',
    ].join('');
  };

  const renderInline = (value: string): string => {
    let html = escapeHtml(value);
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    html = html.replace(/(?<!href=")(https?:\/\/[^\s<)]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    return html;
  };

  const parseScreenshotAlt = (rawAlt: string): { caption: string; callouts: ScreenshotCallout[] } => {
    const [captionPart, metaPart = ''] = rawAlt.split(/\s+\|\|\s+/, 2);
    const parsePercent = (value: string): number | null => {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return null;
      return Math.max(0, Math.min(100, parsed));
    };
    const defaultLabelPosition = (x: number, y: number, width: number, height: number) => ({
      x: Math.max(2, Math.min(98, x + width + 4)),
      y: Math.max(2, Math.min(98, y + height / 2)),
    });

    const callouts = metaPart
      .split(';')
      .map(part => part.trim())
      .filter(Boolean)
      .map((part): ScreenshotCallout | null => {
        const match = /^(arrow|rect|circle)\s*=\s*([^:]+):\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*@\s*([0-9.]+)\s*,\s*([0-9.]+))?(?:\s*:\s*(.+))?$/.exec(part);
        if (!match) return null;

        const x = parsePercent(match[3]);
        const y = parsePercent(match[4]);
        const width = parsePercent(match[5]);
        const height = parsePercent(match[6]);
        if (x === null || y === null || width === null || height === null) return null;
        const labelPosition = defaultLabelPosition(x, y, width, height);
        const labelX = match[7] ? parsePercent(match[7]) : labelPosition.x;
        const labelY = match[8] ? parsePercent(match[8]) : labelPosition.y;
        if (labelX === null || labelY === null) return null;

        return {
          kind: match[1] as 'arrow' | 'rect' | 'circle',
          label: match[2].trim(),
          x,
          y,
          width: Math.max(1, Math.min(100 - x, width)),
          height: Math.max(1, Math.min(100 - y, height)),
          labelX,
          labelY,
          title: (match[9] || '').trim(),
        };
      })
      .filter((callout): callout is ScreenshotCallout => Boolean(callout));

    return {
      caption: captionPart.trim(),
      callouts,
    };
  };

  const hashString = (value: string): string => {
    let hash = 0;
    for (let i = 0; i < value.length; i += 1) {
      hash = ((hash << 5) - hash) + value.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash).toString(36);
  };

  const renderScreenshotCallout = (callout: ScreenshotCallout, index: number, imageId: string): string => {
    const targetStyle = [
      `left: ${callout.x}%`,
      `top: ${callout.y}%`,
      `width: ${callout.width}%`,
      `height: ${callout.height}%`,
    ].join('; ');
    const markerStyle = [
      `left: ${callout.labelX}%`,
      `top: ${callout.labelY}%`,
    ].join('; ');
    const targetX = callout.x + callout.width / 2;
    const targetY = callout.y + callout.height / 2;
    const markerId = `help-arrow-${imageId}-${index}`;
    const title = callout.title ? ` title="${escapeAttr(callout.title)}"` : '';
    const target = callout.kind === 'arrow'
      ? ''
      : `<span class="help-screenshot-target help-screenshot-target-${callout.kind}" style="${targetStyle}"></span>`;

    return [
      `<span class="help-screenshot-callout" aria-hidden="true"${title}>`,
      '<svg class="help-screenshot-arrow" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">',
      '<defs>',
      `<marker id="${markerId}" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">`,
      '<path d="M0,0 L6,3 L0,6 Z" class="help-screenshot-arrowhead" />',
      '</marker>',
      '</defs>',
      `<line class="help-screenshot-arrow-line" x1="${callout.labelX}" y1="${callout.labelY}" x2="${targetX}" y2="${targetY}" marker-end="url(#${markerId})" />`,
      '</svg>',
      target,
      `<span class="help-screenshot-marker" style="${markerStyle}">${escapeHtml(callout.label)}</span>`,
      '</span>',
    ].join('');
  };

  const renderImageBlock = (alt: string, path: string): string => {
    const normalizedPath = path.trim();
    if (!/^\/help-screenshots\/[a-zA-Z0-9._/-]+\.png$/.test(normalizedPath)) {
      return `<p>${renderInline(`![${alt}](${path})`)}</p>`;
    }
    const { caption, callouts } = parseScreenshotAlt(alt);
    const safeAlt = escapeAttr(caption || 'LoomAI screenshot');
    const safeSrc = escapeAttr(assetUrl(normalizedPath));
    const imageId = hashString(normalizedPath);
    return [
      '<figure class="help-screenshot">',
      '<div class="help-screenshot-frame">',
      `<img src="${safeSrc}" alt="${safeAlt}" loading="lazy" decoding="async" />`,
      callouts.map((callout, index) => renderScreenshotCallout(callout, index, imageId)).join(''),
      '</div>',
      `<figcaption>${safeAlt}</figcaption>`,
      '</figure>',
    ].join('');
  };

  const renderTextBlock = (block: string): string => {
    const lines = block.split('\n');
    const parts: string[] = [];
    let paragraph: string[] = [];
    let listItems: string[] = [];
    let listType: 'ul' | 'ol' | null = null;

    const flushParagraph = () => {
      if (paragraph.length > 0) {
        parts.push(`<p>${paragraph.map(renderInline).join('<br/>')}</p>`);
        paragraph = [];
      }
    };

    const flushList = () => {
      if (listType && listItems.length > 0) {
        parts.push(`<${listType}>${listItems.map(item => `<li>${renderInline(item)}</li>`).join('')}</${listType}>`);
        listItems = [];
        listType = null;
      }
    };

    for (const line of lines) {
      const imageMatch = /^\s*!\[([^\]]*)\]\((\/help-screenshots\/[^)\s]+\.png)\)\s*$/.exec(line);
      const bulletMatch = /^\s*[-*]\s+(.+)$/.exec(line);
      const numberedMatch = /^\s*\d+\.\s+(.+)$/.exec(line);

      if (imageMatch) {
        flushParagraph();
        flushList();
        parts.push(renderImageBlock(imageMatch[1], imageMatch[2]));
        continue;
      }

      if (bulletMatch || numberedMatch) {
        flushParagraph();
        const nextType = bulletMatch ? 'ul' : 'ol';
        if (listType && listType !== nextType) flushList();
        listType = nextType;
        listItems.push((bulletMatch || numberedMatch)?.[1] || '');
        continue;
      }

      flushList();
      if (line.trim()) {
        paragraph.push(line);
      }
    }

    flushParagraph();
    flushList();
    return parts.join('');
  };

  return md
    .split(/(```[\w-]*\n[\s\S]*?```)/g)
    .map((part) => {
      const codeMatch = /^```([\w-]*)\n([\s\S]*?)```$/.exec(part);
      if (codeMatch) return renderCodeBlock(codeMatch[1], codeMatch[2]);
      return part
        .split(/\n{2,}/)
        .map(block => block.trim())
        .filter(Boolean)
        .map(renderTextBlock)
        .join('');
    })
    .join('');
}

interface HelpViewProps {
  scrollToSection?: string;
  onClose: () => void;
  onStartTour?: (tourId: string) => void;
}

export default function HelpView({ scrollToSection, onClose, onStartTour }: HelpViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();

  const visibleSections = useMemo(() => {
    if (!normalizedQuery) return helpSections;
    return helpSections
      .map(section => ({
        ...section,
        entries: section.entries.filter(entry =>
          `${section.title} ${entry.label} ${entry.tooltip} ${entry.description}`
            .toLowerCase()
            .includes(normalizedQuery),
        ),
      }))
      .filter(section => section.entries.length > 0);
  }, [normalizedQuery]);

  const visibleEntryCount = useMemo(
    () => visibleSections.reduce((count, section) => count + section.entries.length, 0),
    [visibleSections],
  );
  const showTours = Boolean(onStartTour && !normalizedQuery);

  useEffect(() => {
    if (scrollToSection) {
      // Try entry-level scroll first (e.g. "toolbar.submit" → scroll to that card)
      const entryEl = document.getElementById(`help-entry-${scrollToSection}`);
      if (entryEl) {
        entryEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        entryEl.classList.add('help-entry-highlight');
        setTimeout(() => entryEl.classList.remove('help-entry-highlight'), 2000);
        return;
      }
      // Fall back to section-level scroll
      const sectionId = scrollToSection.split('.')[0];
      const el = sectionRefs.current[sectionId];
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  }, [scrollToSection]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;

    const copyText = async (text: string) => {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }

      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (!copied) throw new Error('Copy failed');
    };

    const handleCopyClick = async (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const button = target?.closest('.help-code-copy') as HTMLButtonElement | null;
      if (!button || !root.contains(button)) return;

      event.preventDefault();
      const codeBlock = button.closest('.help-code-block');
      const code = codeBlock?.querySelector('code')?.textContent || '';
      if (!code) return;

      const originalText = button.textContent || 'Copy';
      try {
        await copyText(code);
        button.textContent = 'Copied';
        button.classList.add('copied');
      } catch {
        button.textContent = 'Copy failed';
        button.classList.add('copy-failed');
      }

      window.setTimeout(() => {
        if (!button.isConnected) return;
        button.textContent = originalText;
        button.classList.remove('copied', 'copy-failed');
      }, 1600);
    };

    root.addEventListener('click', handleCopyClick);
    return () => root.removeEventListener('click', handleCopyClick);
  }, []);

  const handleSidebarClick = (sectionId: string) => {
    const el = sectionRefs.current[sectionId];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="help-view">
      <div className="help-sidebar">
        <div className="help-sidebar-title">Sections</div>
        {showTours && (
          <button
            className="help-sidebar-item"
            onClick={() => handleSidebarClick('guided-tours')}
          >
            Guided Tours
          </button>
        )}
        {visibleSections.map((s) => (
          <button
            key={s.id}
            className="help-sidebar-item"
            onClick={() => handleSidebarClick(s.id)}
          >
            {s.title}
          </button>
        ))}
      </div>
      <div className="help-content" ref={contentRef}>
        <div className="help-header">
          <h2 className="help-title">LoomAI — Help</h2>
          <button className="help-back-btn" onClick={onClose}>
            Back
          </button>
        </div>
        <div className="help-search-row">
          <input
            className="help-search-input"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search help..."
            aria-label="Search help"
          />
          <span className="help-search-count">
            {normalizedQuery ? `${visibleEntryCount} result${visibleEntryCount === 1 ? '' : 's'}` : `${visibleEntryCount} topics`}
          </span>
        </div>

        {/* Guided Tours section */}
        {showTours && (
          <div
            className="help-section"
            ref={(el) => { sectionRefs.current['guided-tours'] = el; }}
          >
            <h3 className="help-section-title">Guided Tours</h3>
            <div className="help-tours-grid">
              {tourList.map((tour) => (
                <div key={tour.id} className="help-tour-card">
                  <div className="help-tour-card-icon">{tour.icon}</div>
                  <div className="help-tour-card-title">{tour.title}</div>
                  <div className="help-tour-card-desc">{tour.description}</div>
                  <button
                    className="help-tour-btn"
                    onClick={() => onStartTour?.(tour.id)}
                  >
                    Start Tour
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {visibleSections.length === 0 && (
          <div className="help-empty-state">
            No help topics match "{query.trim()}".
          </div>
        )}

        {visibleSections.map((section) => {
          const sectionTours = toursBySection[section.id];
          return (
            <div
              key={section.id}
              className="help-section"
              ref={(el) => { sectionRefs.current[section.id] = el; }}
            >
              <h3 className="help-section-title">{section.title}</h3>
              {showTours && sectionTours && sectionTours.length > 0 && (
                <div className="help-inline-tours">
                  {sectionTours.map((tour) => (
                    <button
                      key={tour.id}
                      className="help-inline-tour-btn"
                      onClick={() => onStartTour?.(tour.id)}
                    >
                      {tour.icon} Take the {tour.title} Tour
                    </button>
                  ))}
                </div>
              )}
              {section.entries.map((entry) => (
                <div key={entry.id} className="help-entry-card" id={`help-entry-${entry.id}`}>
                  <h4 className="help-entry-label">{entry.label}</h4>
                  <div className="help-entry-desc" dangerouslySetInnerHTML={{ __html: renderMarkdown(entry.description) }} />
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
