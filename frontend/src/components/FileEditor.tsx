'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightSpecialChars, drawSelection, highlightActiveLine, rectangularSelection, crosshairCursor } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { defaultKeymap, indentWithTab, history, historyKeymap } from '@codemirror/commands';
import { syntaxHighlighting, defaultHighlightStyle, indentOnInput, bracketMatching, foldGutter, foldKeymap } from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete';
import { oneDark } from '@codemirror/theme-one-dark';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';
import { css } from '@codemirror/lang-css';
import { html } from '@codemirror/lang-html';
import { yaml } from '@codemirror/lang-yaml';
import { xml } from '@codemirror/lang-xml';
import * as api from '../api/client';
import '../styles/file-editor.css';

interface VmContext {
  sliceName: string;
  nodeName: string;
}

interface FileEditorProps {
  filePath: string;
  onClose: () => void;
  dark?: boolean;
  /** If set, reads/writes via VM SSH instead of container storage. */
  vmContext?: VmContext;
}

const TEXT_EXTENSIONS = new Set([
  'txt', 'py', 'js', 'ts', 'tsx', 'jsx', 'json', 'md', 'css', 'html', 'htm',
  'xml', 'yaml', 'yml', 'sh', 'bash', 'zsh', 'cfg', 'conf', 'ini', 'env',
  'toml', 'csv', 'log', 'sql', 'r', 'java', 'c', 'cpp', 'h', 'hpp', 'go',
  'rs', 'rb', 'php', 'pl', 'lua', 'makefile', 'dockerfile', 'gitignore',
  'properties', 'rc', 'service', 'timer', 'desktop', 'rules', 'ipynb',
]);

export function isTextFile(name: string): boolean {
  const lower = name.toLowerCase();
  // Files with no extension but known names
  if (['makefile', 'dockerfile', 'readme', 'license', 'changelog'].includes(lower)) return true;
  const ext = lower.split('.').pop() || '';
  return TEXT_EXTENSIONS.has(ext);
}

const BINARY_EXTENSIONS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'webp', 'svg', 'tiff', 'tif',
  'mp3', 'mp4', 'wav', 'avi', 'mkv', 'mov', 'flac', 'ogg', 'webm',
  'zip', 'gz', 'tar', 'bz2', 'xz', 'zst', '7z', 'rar',
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt',
  'exe', 'dll', 'so', 'dylib', 'bin', 'o', 'a', 'class', 'pyc', 'pyo',
  'whl', 'egg', 'deb', 'rpm', 'iso', 'img', 'dmg',
  'sqlite', 'db', 'sqlite3',
  'woff', 'woff2', 'ttf', 'otf', 'eot',
]);

export function isLikelyBinary(name: string): boolean {
  const lower = name.toLowerCase();
  const ext = lower.split('.').pop() || '';
  return BINARY_EXTENSIONS.has(ext);
}

function getLanguageExtension(filename: string) {
  const ext = filename.toLowerCase().split('.').pop() || '';
  switch (ext) {
    case 'py': return python();
    case 'js': case 'jsx': return javascript();
    case 'ts': case 'tsx': return javascript({ typescript: true, jsx: ext.endsWith('x') });
    case 'json': case 'ipynb': return json();
    case 'md': case 'markdown': return markdown();
    case 'css': return css();
    case 'html': case 'htm': return html();
    case 'xml': case 'svg': return xml();
    case 'yaml': case 'yml': return yaml();
    default: return [];
  }
}

export default function FileEditor({ filePath, onClose, dark, vmContext }: FileEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [modified, setModified] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const originalContent = useRef('');

  const filename = filePath.split('/').pop() || filePath;

  const handleSave = useCallback(async () => {
    if (!viewRef.current) return;
    const content = viewRef.current.state.doc.toString();
    setSaving(true);
    setError('');
    try {
      if (vmContext) {
        await api.writeVmFileContent(vmContext.sliceName, vmContext.nodeName, filePath, content);
      } else {
        await api.writeFileContent(filePath, content);
      }
      originalContent.current = content;
      setModified(false);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }, [filePath, vmContext]);

  // Load file content and create editor
  useEffect(() => {
    if (!containerRef.current) return;
    let destroyed = false;

    (async () => {
      setLoading(true);
      setError('');
      try {
        const resp = vmContext
          ? await api.readVmFileContent(vmContext.sliceName, vmContext.nodeName, filePath)
          : await api.readFileContent(filePath);
        const content = resp.content;
        if (destroyed) return;
        originalContent.current = content;

        const langExt = getLanguageExtension(filename);

        const extensions = [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightSpecialChars(),
          history(),
          foldGutter(),
          drawSelection(),
          indentOnInput(),
          bracketMatching(),
          closeBrackets(),
          highlightActiveLine(),
          highlightSelectionMatches(),
          rectangularSelection(),
          crosshairCursor(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          keymap.of([
            ...closeBracketsKeymap,
            ...defaultKeymap,
            ...searchKeymap,
            ...historyKeymap,
            ...foldKeymap,
            indentWithTab,
          ]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              const current = update.state.doc.toString();
              setModified(current !== originalContent.current);
            }
          }),
          // Ctrl/Cmd+S to save
          keymap.of([{
            key: 'Mod-s',
            run: () => {
              // Trigger save via DOM event since we can't call handleSave directly
              containerRef.current?.dispatchEvent(new CustomEvent('editor-save'));
              return true;
            },
          }]),
          EditorView.lineWrapping,
          ...(dark ? [oneDark] : []),
          ...(Array.isArray(langExt) ? langExt : [langExt]),
        ];

        const state = EditorState.create({ doc: content, extensions });
        const view = new EditorView({ state, parent: containerRef.current! });
        viewRef.current = view;
        setModified(false);
      } catch (e: any) {
        setError(e.message);
      } finally {
        if (!destroyed) setLoading(false);
      }
    })();

    return () => {
      destroyed = true;
      viewRef.current?.destroy();
      viewRef.current = null;
    };
  }, [filePath, filename, dark, vmContext]);

  // Listen for Ctrl+S custom event
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = () => handleSave();
    el.addEventListener('editor-save', handler);
    return () => el.removeEventListener('editor-save', handler);
  }, [handleSave]);

  return (
    <div className="file-editor">
      <div className="fe-header">
        <div className="fe-filename" title={filePath}>
          {filename}
          {modified && <span className="fe-modified-dot" title="Unsaved changes" />}
        </div>
        <div className="fe-actions">
          {error && <span className="fe-error">{error}</span>}
          {savedFlash && <span className="fe-saved">Saved</span>}
          <button
            className="primary"
            onClick={handleSave}
            disabled={saving || !modified}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
      <div className="fe-editor-container" ref={containerRef}>
        {loading && <div className="fe-loading">Loading...</div>}
      </div>
    </div>
  );
}
