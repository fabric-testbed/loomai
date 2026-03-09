'use client';
import AIChatPanel from './AIChatPanel';
import '../styles/ai-chat-panel.css';

interface LoomAIChatViewProps {
  visible?: boolean;
}

export default function LoomAIChatView({ visible = true }: LoomAIChatViewProps) {
  return (
    <div className="loomai-fullscreen-view" style={{ display: visible ? undefined : 'none' }}>
      <AIChatPanel onCollapse={() => {}} fullScreen persistId="loomai-fullscreen" />
    </div>
  );
}
