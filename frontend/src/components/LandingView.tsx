'use client';
import '../styles/landing-view.css';

type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai';

interface LandingViewProps {
  onNavigate: (view: TopView) => void;
  onOpenSettings: () => void;
  listLoaded: boolean;
  onLoadSlices: () => void;
  onStartTour: (tourId: string) => void;
  hasToken?: boolean;
  tokenExpired?: boolean;
  onLogin?: () => void;
}

const QUICK_LINKS: Array<{ view: TopView; icon: string; label: string; desc: string }> = [
  { view: 'infrastructure', icon: '\u25C9', label: 'FABRIC', desc: 'Topology editor, site map, slice management' },
  { view: 'slices', icon: '\u25A6', label: 'Composite Slice', desc: 'Cross-testbed experiments spanning FABRIC and Chameleon' },
  { view: 'artifacts', icon: '\u29C9', label: 'Marketplace', desc: 'Browse, download, and publish weaves and templates' },
  { view: 'jupyter', icon: '\uD83D\uDCD3', label: 'JupyterLab', desc: 'Notebooks with full FABlib access' },
];

export default function LandingView({ onNavigate, onOpenSettings, listLoaded, onLoadSlices, onStartTour, hasToken, tokenExpired, onLogin }: LandingViewProps) {
  return (
    <div className="landing-root">
      <div className="landing-scroll">

        {/* Hero */}
        <section className="landing-hero">
          <div className="landing-logo-wrap">
            <img src="/loomai-horizontal-transparent-light-ink-trimmed.svg" alt="LoomAI" className="landing-logo landing-logo-light" />
            <img src="/loomai-horizontal-transparent-dark-ink-trimmed.svg" alt="LoomAI" className="landing-logo landing-logo-dark" />
          </div>
          <div className="landing-tour-buttons">
            <button className="landing-tour-btn landing-tour-btn-primary" onClick={() => onStartTour('discover-loomai')}>
              Discover LoomAI
            </button>
            <button className="landing-tour-btn landing-tour-btn-secondary" onClick={() => onStartTour('hello-fabric')}>
              Hello, FABRIC
            </button>
          </div>
        </section>

        {/* Login card — shown when not authenticated or token expired */}
        {(hasToken === false || tokenExpired) && onLogin && (
          <section className="landing-section">
            <div className="landing-card landing-card-login">
              <h2 className="landing-card-title">{tokenExpired ? 'Session Expired' : 'Connect to FABRIC'}</h2>
              <p>
                {tokenExpired
                  ? 'Your FABRIC token has expired. Log in again to continue using LoomAI. Your configuration and keys are preserved.'
                  : 'Log in with your FABRIC account to start building experiments. LoomAI will automatically configure your environment, generate SSH keys, and set up your project.'}
              </p>
              <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <button className="landing-login-btn" onClick={onLogin}>
                  {tokenExpired ? 'Re-login to FABRIC' : 'Login to FABRIC'}
                </button>
                {!tokenExpired && (
                  <span style={{ fontSize: 12, color: 'var(--fabric-text-muted)' }}>
                    New to FABRIC?{' '}
                    <a href="https://portal.fabric-testbed.net" target="_blank" rel="noopener noreferrer" style={{ color: '#27aae1', fontWeight: 600, textDecoration: 'none' }}>
                      Create an account
                    </a>
                  </span>
                )}
              </div>
            </div>
          </section>
        )}

        {/* About cards */}
        <section className="landing-about">
          <div className="landing-card landing-card-fabric">
            <h2 className="landing-card-title">About FABRIC</h2>
            <p>
              <a href="https://fabric-testbed.net" target="_blank" rel="noopener noreferrer">FABRIC</a> is
              a global research infrastructure with 35 sites providing programmable networking,
              bare-metal VMs, SmartNICs, GPUs, FPGAs, and high-speed optical links. It connects to
              external facilities including AWS, GCP, Azure, Chameleon, CloudLab, and ACCESS,
              letting you build experiments that span real production infrastructure.
            </p>
          </div>
          <div className="landing-card landing-card-loom">
            <h2 className="landing-card-title">About LoomAI</h2>
            <p>
              LoomAI is a browser-based environment for designing, deploying, and managing
              experiments on FABRIC. Draw topologies in a visual editor, provision with one click,
              run automated weave scripts, and connect to provisioned VMs through built-in terminals.
              Six free AI coding assistants help you write scripts, debug networks, and manage
              slices through natural language. A 65+ command CLI, embedded JupyterLab, and a
              community artifact marketplace round out the toolkit.
            </p>
          </div>
        </section>

        {/* AI Tools highlight */}
        <section className="landing-section">
          <div className="landing-card landing-card-ai">
            <h2 className="landing-card-title">Built-in AI Tools</h2>
            <p>
              LoomAI includes several AI coding assistants, all pre-loaded with FABRIC knowledge.
              Tell them what you want in plain English and they'll write the code, create
              topologies, or troubleshoot your experiments. Free tools use FABRIC AI models;
              add an NRP API key in Settings for more options.
            </p>
            <div className="landing-ai-tools">
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">LoomAI Assistant</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Chat with tool calling: creates slices, queries sites, runs commands</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Aider</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Pair programmer for editing weave scripts and boot configs</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">OpenCode</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Coding assistant with FABRIC-specific agents and skills</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Crush</span>
                <span className="landing-ai-tool-tag free">Free</span>
                <span className="landing-ai-tool-desc">Terminal chat from Charm, works with FABRIC and NRP models</span>
              </div>
              <div className="landing-ai-tool">
                <span className="landing-ai-tool-name">Claude Code</span>
                <span className="landing-ai-tool-tag paid">Paid</span>
                <span className="landing-ai-tool-desc">Anthropic CLI with FABRIC MCP tool integration</span>
              </div>
            </div>
            <p className="landing-ai-note">
              Launch any tool from the AI Tools view. Each one has access to your slices,
              FABRIC resources, and the <code>loomai</code> CLI.
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
                <strong>Log in</strong>
                <p>
                  Click "Login to FABRIC" above. LoomAI will set up your SSH keys, project,
                  and API credentials automatically. Or open <button className="landing-inline-link" onClick={onOpenSettings}>Settings</button> to
                  configure manually.
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">2</span>
              <div>
                <strong>Try the <button className="landing-inline-link" onClick={() => onStartTour('hello-fabric')}>Hello, FABRIC</button> tour</strong>
                <p>
                  Deploy your first slice in under 5 minutes. The tour walks you through downloading
                  a weave from the marketplace, running it, and connecting to your VM.
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">3</span>
              <div>
                <strong>Build your own</strong>
                <p>
                  Open the <button className="landing-inline-link" onClick={() => onNavigate('infrastructure')}>FABRIC</button> view
                  to design topologies with the visual editor, or browse
                  the <button className="landing-inline-link" onClick={() => onNavigate('artifacts')}>Marketplace</button> to
                  start from a community weave.
                </p>
              </div>
            </div>
            <div className="landing-step">
              <span className="landing-step-num">4</span>
              <div>
                <strong>Work with your slice</strong>
                <p>
                  Right-click nodes to SSH in, transfer files with the Storage tab,
                  write notebooks in <button className="landing-inline-link" onClick={() => onNavigate('jupyter')}>JupyterLab</button>,
                  or ask the LoomAI assistant to do it for you.
                </p>
              </div>
            </div>
          </div>
          <p style={{ fontSize: 12, color: 'var(--fabric-text-muted)', marginTop: 12 }}>
            New here? Take the <button className="landing-inline-link" onClick={() => onStartTour('discover-loomai')}>Discover LoomAI</button> tour
            for a quick overview of all features.
          </p>
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
