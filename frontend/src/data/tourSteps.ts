export type TourRequiredView = 'main' | 'settings' | 'map' | 'files' | 'slivers' | 'ai' | 'libraries' | 'client' | 'jupyter' | 'landing' | 'fabric' | 'chameleon';

export interface TourStep {
  id: string;
  title: string;
  content: string;
  targetSelector: string;
  requiredView: TourRequiredView;
  tooltipPosition: 'top' | 'bottom' | 'left' | 'right';
  /** Key into tourContext to check for step completion */
  completionCheck?: string;
  /** Label shown when the step is complete */
  completionLabel?: string;
  /** Label shown when the step is pending */
  pendingLabel?: string;
  /** Optional image URL displayed above the content text */
  imageUrl?: string;
  /** Alt text for the image */
  imageAlt?: string;
}

export interface TourDef {
  id: string;
  title: string;
  description: string;
  icon: string;
  autoStart: boolean;
  helpSections: string[];
  steps: TourStep[];
}

// ════════════════════════════════════════════════════════════════════
// 1. DISCOVER LOOMAI — Visual overview / sales pitch
// ════════════════════════════════════════════════════════════════════

const discoverLoomai: TourDef = {
  id: 'discover-loomai',
  title: 'Discover LoomAI',
  description: 'A visual tour of LoomAI\u2019s capabilities \u2014 see how AI-powered tools, visual editors, and automated workflows come together to build experiments on FABRIC.',
  icon: '\u2728',
  autoStart: false,
  helpSections: ['overview', 'fabric-view', 'chameleon-view', 'cli'],
  steps: [
    {
      id: 'dl-welcome',
      title: 'Welcome to LoomAI',
      content:
        'LoomAI is FABRIC\u2019s AI-powered loom for weaving custom network fabrics.\n\nFABRIC is a global research infrastructure with 35 sites offering programmable networking, bare-metal VMs, GPUs, FPGAs, SmartNICs, and high-speed optical links. LoomAI gives you a visual, browser-based sandbox to design, deploy, and manage experiments \u2014 aided by embedded AI coding assistants.\n\nLoomAI provides dedicated views for FABRIC and Chameleon Cloud testbeds, a powerful `loomai` CLI with 65+ commands, and six AI tools for natural language experiment management.\n\nLet\u2019s take a quick look at what LoomAI can do.',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
    },
    {
      id: 'dl-topology',
      title: 'Visual Slice Design',
      content:
        'Design experiment topologies with an interactive graph editor. Drag to add VM nodes, connect them with L2/L3 networks, attach GPUs and SmartNICs, and configure boot scripts \u2014 all visually.\n\n\u2022 Six graph layout algorithms for clear topology views\n\u2022 Automatic site and host placement based on real-time resource availability\n\u2022 Site co-location groups (@group tags) for multi-site experiments\n\u2022 One-click submit to provision on FABRIC\n\u2022 Export topology diagrams as PNG for publications',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-topology.svg',
      imageAlt: 'LoomAI topology editor showing a multi-node slice with graph view and editor panel',
    },
    {
      id: 'dl-infrastructure',
      title: 'Explore FABRIC Infrastructure',
      content:
        'An interactive geographic map shows all 35 FABRIC sites worldwide with real-time resource availability, backbone network links, and live site metrics.\n\n\u2022 Click any site to see available cores, RAM, disk, GPUs, FPGAs, and SmartNICs\n\u2022 View backbone link bandwidth between sites\n\u2022 Live CPU load and dataplane traffic metrics\n\u2022 Per-host resource availability for precise placement\n\u2022 Connect to external facilities: AWS, GCP, Azure, Chameleon, CloudLab, ACCESS',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-map.svg',
      imageAlt: 'Geographic map showing FABRIC sites worldwide with resource availability',
    },
    {
      id: 'dl-ai-tools',
      title: 'AI-Powered Development',
      content:
        'Six AI coding assistants are embedded directly into LoomAI, each pre-configured with FABRIC domain knowledge and direct access to testbed operations:\n\n\u2022 LoomAI \u2014 Chat-based FABRIC assistant with tool calling and multi-conversation support\n\u2022 Aider \u2014 AI pair programming for editing deployment scripts\n\u2022 OpenCode \u2014 Full-featured coding assistant with FABRIC-specific skills and agents\n\u2022 Crush \u2014 Elegant terminal AI from Charm with FABRIC and NRP model support\n\u2022 Deep Agents \u2014 LangChain coding agent with planning, memory, and skills\n\u2022 Claude Code \u2014 Anthropic\u2019s CLI with deep FABRIC MCP integration\n\nPlus Jupyter AI integrated into JupyterLab for notebook-based AI assistance.\n\nFree tools use FABRIC AI (ai.fabric-testbed.net). Use natural language to create topologies, generate scripts, debug networking, and automate experiment workflows.',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-ai-tools.svg',
      imageAlt: 'AI Tools launcher showing available coding assistants',
    },
    {
      id: 'dl-artifacts',
      title: 'Artifact Marketplace',
      content:
        'Share and discover reusable experiment building blocks through the FABRIC Artifact Manager marketplace.\n\n\u2022 Browse community-published weaves, VM templates, recipes, and notebooks\n\u2022 Download artifacts with one click \u2014 version tracking notifies you of updates\n\u2022 Publish your own artifacts with visibility controls (public, project, or private)\n\u2022 Fork and build on community contributions with provenance tracking\n\u2022 Manage versions, tags, authors, and descriptions',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-artifacts.svg',
      imageAlt: 'Artifact marketplace showing community-published weaves and templates',
    },
    {
      id: 'dl-weave-experiments',
      title: 'Automated Weave Experiments',
      content:
        'Weaves are the heart of LoomAI \u2014 reusable experiment packages that automate the full lifecycle:\n\n1. \uD83D\uDCD0 Define topology, boot configuration, and run scripts in a weave\n2. \uD83D\uDE80 One-click Deploy provisions infrastructure, configures networking, and installs software\n3. \u2699\uFE0F Run scripts execute your experiment autonomously for up to 30 minutes\n4. \uD83D\uDCCA Build Log streams real-time progress with milestone tracking\n\nUse AI tools to write weave.sh scripts that orchestrate multi-slice experiments, collect data, and manage their own lifecycle \u2014 all under AI control.',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-weave-deploy.svg',
      imageAlt: 'Weave deploy pipeline showing automated provisioning and build log output',
    },
    {
      id: 'dl-jupyter',
      title: 'Interactive Development',
      content:
        'A complete development environment is built into LoomAI:\n\n\u2022 Embedded JupyterLab for interactive notebooks with full Python + FABlib access\n\u2022 SSH terminals to every provisioned VM \u2014 right-click a node to connect\n\u2022 Local shell on the backend container for FABlib CLI and debugging\n\u2022 Dual-panel file manager for transferring files between storage and VMs\n\u2022 Boot configuration editor for post-provisioning automation',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
      imageUrl: '/tours/overview-jupyter.svg',
      imageAlt: 'JupyterLab embedded view with notebook and terminal access',
    },
    {
      id: 'dl-fabric-view',
      title: 'Dedicated Testbed Views',
      content:
        'LoomAI provides dedicated, branded views for each testbed:\n\n\u2022 **FABRIC View** \u2014 A complete FABRIC-only slice editor with sub-tabs: Topology, Table, Map, Storage, Apps, Slices, Browse, and Facility Ports. Everything you need to manage FABRIC experiments in one place.\n\n\u2022 **Chameleon View** \u2014 Manage Chameleon Cloud leases and bare-metal instances. Configure Chameleon credentials in Settings to enable this view.\n\n\u2022 **Composite Slice** \u2014 Build experiments that may span multiple testbeds with a unified editor.',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
    },
    {
      id: 'dl-cli',
      title: 'Command-Line Interface',
      content:
        'The `loomai` CLI provides full FABRIC management from the terminal with 20 command groups and 65+ subcommands.\n\n\u2022 Interactive shell with tab completion, context selection, and AI assistant\n\u2022 One-shot commands for scripting and automation\n\u2022 JSON/YAML output for piping and processing\n\u2022 SSH, exec, and file transfer to slice VMs\n\u2022 Weave management, artifact publishing, and more\n\nAccess it from the Local Terminal tab or any terminal in the container.',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
    },
    {
      id: 'dl-get-started',
      title: 'Ready to Build?',
      content:
        'LoomAI gives you everything you need to design, deploy, and manage research experiments on FABRIC \u2014 from visual topology design to AI-powered automation.\n\nTo get started:\n\u2022 Take the Hello FABRIC tour to configure your credentials\n\u2022 Or jump straight in \u2014 click "+ New" in the toolbar to create your first slice\n\u2022 Visit the Help page for detailed documentation on every feature\n\nHappy experimenting!',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 2. HELLO FABRIC — Run the Hello FABRIC weave
// ════════════════════════════════════════════════════════════════════

const helloFabric: TourDef = {
  id: 'hello-fabric',
  title: 'Hello, FABRIC',
  description: 'Deploy your first slice by running the Hello FABRIC weave \u2014 one-click provisioning to verify your setup.',
  icon: '\u{1F44B}',
  autoStart: false,
  helpSections: ['templates', 'bottom'],
  steps: [
    {
      id: 'hf-intro',
      title: 'Hello, FABRIC!',
      content:
        'In this tour you\'ll deploy your first FABRIC slice by running the "Hello FABRIC" weave. This is the fastest way to verify your credentials and see LoomAI in action.\n\nThe weave will create a single Ubuntu VM, wait for it to provision, and configure SSH access \u2014 all automatically.',
      targetSelector: '.title-bar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'hf-open-marketplace',
      title: 'Step 1: Open the Marketplace',
      content:
        'First, let\'s get the Hello FABRIC weave from the community marketplace.\n\nSwitch to the Artifacts view using the View selector in the title bar, then click the "Community Marketplace" tab.',
      targetSelector: '[data-help-id="libraries.marketplace"]',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'hf-search',
      title: 'Step 2: Search for "Hello"',
      content:
        'Type "Hello" in the search bar above. The artifact list will filter as you type.',
      targetSelector: '.tv-mp-toolbar',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'hf-filter',
      title: 'Step 3: Filter by Weave',
      content:
        'Click the "Weave" button highlighted above to narrow results to weave artifacts only. You should see the "Hello FABRIC" weave appear in the results below.',
      targetSelector: '[data-tour-id="mp-filter-weave"]',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'hf-get',
      title: 'Step 4: Download the Weave',
      content:
        'Find the "Hello FABRIC" card below and click its "Get" button to download it to your local artifacts. You should see a confirmation message.',
      targetSelector: '.title-bar',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'hf-back-to-main',
      title: 'Step 5: Return to the Editor',
      content:
        'Great! The Hello FABRIC weave is now in your local artifacts. Switch back to the Topology view using the View selector in the title bar.\n\nYou\'ll see the Hello FABRIC weave in the Weaves tab of the side panel on the right.',
      targetSelector: '.template-panel',
      requiredView: 'main',
      tooltipPosition: 'left',
    },
    {
      id: 'hf-run-weave',
      title: 'Step 6: Run the Weave',
      content:
        'Find "Hello FABRIC" in the Weaves tab and click the \u25B6 Run button (or use the \u22EF menu \u2192 Run). You\'ll be prompted for a slice name \u2014 the default "hello-fabric" works fine.\n\nThe weave.sh script will:\n1. Create the slice with a single Ubuntu VM\n2. Submit it to FABRIC\n3. Wait for provisioning (this takes 2\u20135 minutes)\n4. Run post-boot configuration\n5. Report the management IP and SSH command',
      targetSelector: '.template-panel',
      requiredView: 'main',
      tooltipPosition: 'left',
    },
    {
      id: 'hf-watch-log',
      title: 'Watch the Build Log',
      content:
        'The console at the bottom will open a "run:Hello FABRIC" tab showing the script output in real-time.\n\nYou\'ll see progress milestones as the slice provisions. Wait until you see a success message with the VM\'s IP address.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'hf-ssh',
      title: 'Connect to Your VM',
      content:
        'Once the slice is provisioned (state: StableOK), you can SSH into it:\n\n\u2022 Right-click the node in the topology graph \u2192 "Open Terminal"\n\u2022 Or use the Local Terminal tab to run SSH commands manually\n\nCongratulations \u2014 you\'ve deployed your first FABRIC slice!',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'hf-done',
      title: 'What\'s Next?',
      content:
        'You\'ve verified that your credentials work and deployed a slice. Here\'s what to explore next:\n\n\u2022 Try "Build Your First Slice" tour to learn manual slice creation\n\u2022 Explore the Map view to see all FABRIC sites\n\u2022 Browse the Community Marketplace for more weaves\n\u2022 Launch an AI Tool to build experiments with natural language\n\nWhen you\'re done, delete the hello-fabric slice from the toolbar to free resources.',
      targetSelector: '[data-help-id="titlebar.help"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// Exports
// ════════════════════════════════════════════════════════════════════

export const tours: Record<string, TourDef> = {
  'discover-loomai': discoverLoomai,
  'hello-fabric': helloFabric,
};

export const tourList: TourDef[] = [
  discoverLoomai,
  helloFabric,
];

/** Reverse lookup: help section id → tours that cover that section */
export const toursBySection: Record<string, TourDef[]> = {};
for (const tour of tourList) {
  for (const sectionId of tour.helpSections) {
    if (!toursBySection[sectionId]) {
      toursBySection[sectionId] = [];
    }
    toursBySection[sectionId].push(tour);
  }
}
