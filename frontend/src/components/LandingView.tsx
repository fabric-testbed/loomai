'use client';
import '../styles/landing-view.css';

type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai';

interface LandingViewProps {
  onNavigate: (view: TopView) => void;
  onOpenSettings: () => void;
  listLoaded: boolean;
  onLoadSlices: () => void;
  onStartTour: () => void;
}

const QUICK_LINKS: Array<{ view: TopView; icon: string; label: string; desc: string }> = [
  { view: 'slices', icon: '\u25A6', label: 'Slices', desc: 'Build, monitor, and manage slice topologies' },
  { view: 'artifacts', icon: '\u29C9', label: 'Artifacts', desc: 'Templates, recipes, and notebooks' },
  { view: 'infrastructure', icon: '\u25C9', label: 'Infrastructure', desc: 'FABRIC testbed resources and availability' },
  { view: 'jupyter', icon: '\uD83D\uDCD3', label: 'JupyterLab', desc: 'Interactive notebooks' },
];

export default function LandingView({ onNavigate, onOpenSettings, listLoaded, onLoadSlices, onStartTour }: LandingViewProps) {
  return (
    <div className="landing-root">
      <div className="landing-scroll">

        {/* Hero */}
        <section className="landing-hero">
          <h1 className="landing-hero-title">
            Welcome to <span className="landing-brand">LoomAI</span>
          </h1>
          <p className="landing-hero-subtitle">
            FABRIC's loom for weaving custom network fabrics &mdash; aided by AI
          </p>
          <button className="landing-tour-btn" onClick={onStartTour}>
            Take the Guided Tour
          </button>
        </section>

        {/* About cards */}
        <section className="landing-about">
          <div className="landing-card landing-card-fabric">
            <h2 className="landing-card-title">About FABRIC</h2>
            <p>
              <a href="https://fabric-testbed.net" target="_blank" rel="noopener noreferrer">FABRIC</a> is
              a unique, large-scale research infrastructure with 35 globally distributed sites providing
              programmable networking, compute, and storage resources. Researchers deploy custom
              topologies with bare-metal VMs, SmartNICs, GPUs, FPGAs, and high-speed optical links
              to run networking and distributed systems experiments that aren't possible on
              traditional infrastructure.
            </p>
          </div>
          <div className="landing-card landing-card-loom">
            <h2 className="landing-card-title">About LoomAI</h2>
            <p>
              LoomAI is an AI-assisted sandbox for building experiments and prototyping research
              infrastructure on FABRIC. Design topologies visually, deploy with one click, and
              iterate toward production using in-network programmability and connections to
              external facilities &mdash; computing centers, campuses, public clouds, ACCESS,
              and other NSF testbeds.
            </p>
          </div>
        </section>

        {/* AI Tools highlight */}
        <section className="landing-section">
          <div className="landing-card landing-card-ai">
            <h2 className="landing-card-title">AI-Powered Development</h2>
            <p>
              LoomAI embeds multiple AI coding assistants directly into your workflow. Use them to
              quickly create slice topologies, write deployment scripts, troubleshoot networking
              issues, and manage experiments &mdash; all through natural language conversation.
            </p>
            <div className="landing-ai-tools">
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Aider</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">AI pair programmer for editing files and writing FABRIC scripts</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">OpenCode</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Full-featured coding assistant with FABRIC-specific skills and agents</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Crush</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Terminal AI assistant from Charm with FABRIC and NRP LLM support</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Deep Agents</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">LangChain coding agent with planning, memory, and skills</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Claude Code</span>
                <span className="landing-ai-tool-tag paid">Paid</span>
                <span className="landing-ai-tool-desc">Anthropic's CLI with deep FABRIC integration via MCP tools</span>
              </div>
            </div>
            <p className="landing-ai-note">
              All tools come pre-configured with FABRIC domain knowledge, FABlib API context, and
              direct access to testbed operations. Launch them from
              the AI Tools section in the View selector.
            </p>
          </div>
        </section>

        {/* Quick links */}
        <section className="landing-section">
          <h2 className="landing-section-title">Quick Links</h2>
          <div className="landing-grid">
            {QUICK_LINKS.map((link) => (
              <button
                key={link.view}
                className="landing-tile"
                onClick={() => onNavigate(link.view)}
              >
                <span className="landing-tile-icon">{link.icon}</span>
                <span className="landing-tile-label">{link.label}</span>
                <span className="landing-tile-desc">{link.desc}</span>
              </button>
            ))}
          </div>
        </section>

        {/* Getting started */}
        <section className="landing-section">
          <h2 className="landing-section-title">Getting Started</h2>
          <div className="landing-steps">
            <div className="landing-step">
              <span className="landing-step-num">1</span>
              <div>
                <strong>Configure your account</strong>
                <p>
                  Open <button className="landing-inline-link" onClick={onOpenSettings}>Settings</button> to
                  paste your FABRIC token and set up SSH keys. You'll need a bastion key (from
                  the <a href="https://portal.fabric-testbed.net" target="_blank" rel="noopener noreferrer">FABRIC Portal</a>)
                  and a slice key (auto-generated or uploaded).
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">2</span>
              <div>
                <strong>Load your slices</strong>
                <p>
                  {listLoaded
                    ? 'Your slices are loaded. Select one from the toolbar or create a new draft.'
                    : <>Click <button className="landing-inline-link" onClick={onLoadSlices}>Load Slices</button> to fetch your existing slices from FABRIC, or create a new draft from the Topology editor.</>
                  }
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">3</span>
              <div>
                <strong>Build a topology</strong>
                <p>
                  Open <button className="landing-inline-link" onClick={() => onNavigate('slices')}>Slices</button> to
                  add VMs, configure components and networks, then submit your slice to FABRIC.
                  Or browse <button className="landing-inline-link" onClick={() => onNavigate('artifacts')}>Artifacts</button> to
                  start from a pre-built template.
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">4</span>
              <div>
                <strong>Use your slice</strong>
                <p>
                  Once provisioned, right-click nodes to open SSH terminals, transfer files
                  via <button className="landing-inline-link" onClick={() => onNavigate('slices')}>Slices &gt; Storage</button>,
                  or run experiments
                  in <button className="landing-inline-link" onClick={() => onNavigate('jupyter')}>JupyterLab</button>.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* External links */}
        <section className="landing-section">
          <h2 className="landing-section-title">Resources</h2>
          <div className="landing-links">
            <a href="https://fabric-testbed.net" target="_blank" rel="noopener noreferrer" className="landing-ext-link">
              FABRIC Testbed
              <span className="landing-ext-arrow">{'\u2197'}</span>
            </a>
            <a href="https://portal.fabric-testbed.net" target="_blank" rel="noopener noreferrer" className="landing-ext-link">
              FABRIC Portal
              <span className="landing-ext-arrow">{'\u2197'}</span>
            </a>
            <a href="https://learn.fabric-testbed.net" target="_blank" rel="noopener noreferrer" className="landing-ext-link">
              Knowledge Base
              <span className="landing-ext-arrow">{'\u2197'}</span>
            </a>
            <a href="https://artifacts.fabric-testbed.net" target="_blank" rel="noopener noreferrer" className="landing-ext-link">
              Artifact Manager
              <span className="landing-ext-arrow">{'\u2197'}</span>
            </a>
          </div>
        </section>

      </div>
    </div>
  );
}
