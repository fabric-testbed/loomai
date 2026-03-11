'use client';
import { Suspense, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import TerminalCompanionView from '../../components/TerminalCompanionView';
import AIChatPanel from '../../components/AIChatPanel';
import '../../styles/ai-chat-panel.css';

const TOOL_TITLES: Record<string, string> = {
  claude: 'Claude Code',
  crush: 'Crush',
  loomai: 'LoomAI Chat',
};

function PopoutContent() {
  const params = useSearchParams();
  const tool = params.get('tool') ?? '';

  // Redirect iframe-based tools to their direct URLs
  useEffect(() => {
    if (tool === 'opencode' || tool === 'aider') {
      const port = tool === 'opencode' ? 9198 : 9197;
      window.location.replace(`http://${window.location.hostname}:${port}`);
    }
  }, [tool]);

  // Set document title
  useEffect(() => {
    const title = TOOL_TITLES[tool] || tool;
    if (title) document.title = `${title} — LoomAI`;
  }, [tool]);

  if (tool === 'opencode' || tool === 'aider') {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#888' }}>Redirecting...</div>;
  }

  if (tool === 'claude' || tool === 'crush') {
    return (
      <div style={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
        <TerminalCompanionView toolId={tool} />
      </div>
    );
  }

  if (tool === 'loomai') {
    return (
      <div style={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
        <AIChatPanel onCollapse={() => {}} fullScreen persistId="loomai-popout" />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#888' }}>
      Unknown tool: {tool || '(none)'}. Use ?tool=claude, crush, loomai, opencode, or aider.
    </div>
  );
}

export default function PopoutPage() {
  return (
    <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#888' }}>Loading...</div>}>
      <PopoutContent />
    </Suspense>
  );
}
