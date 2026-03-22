export type TourRequiredView = 'main' | 'settings' | 'map' | 'files' | 'slivers' | 'ai' | 'libraries' | 'client' | 'jupyter' | 'landing';

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
// 1. GETTING STARTED — Interactive setup wizard
// ════════════════════════════════════════════════════════════════════

const gettingStarted: TourDef = {
  id: 'getting-started',
  title: 'Getting Started',
  description: 'Set up your FABRIC credentials, AI tools, and workspace \u2014 by the end, LoomAI will be fully configured and ready to use.',
  icon: '\u{1F680}',
  autoStart: false,
  helpSections: ['settings'],
  steps: [
    {
      id: 'welcome',
      title: 'Welcome to LoomAI',
      content:
        'This tour will walk you through configuring LoomAI step by step. You\'ll set up your FABRIC credentials, SSH keys, project, and AI tools.\n\nEach step lets you do the work right here. Complete it and the tour detects it automatically. When you\'re done, LoomAI will be fully configured and ready to use.',
      targetSelector: '.title-bar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'configure-token',
      title: 'Step 1: Upload Your Token',
      content:
        'Upload your FABRIC identity token. Click "Login via FABRIC Portal" to sign in and get a fresh token, or drag-and-drop your token JSON file onto the upload area.\n\nThe token identifies you and determines which projects you can access. It expires periodically \u2014 refresh it from the portal when needed.',
      targetSelector: '[data-tour-id="token"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'has_token',
      completionLabel: 'Token uploaded',
      pendingLabel: 'Upload your token to continue, or skip for now',
    },
    {
      id: 'configure-bastion',
      title: 'Step 2: Upload Bastion Key',
      content:
        'Upload your FABRIC bastion private key. This key authenticates you through the bastion host (jump server) to reach your slice VMs via SSH.\n\nDownload your bastion key from the FABRIC Portal under "Manage SSH Keys". Click the "Upload Bastion Key" button or drag-and-drop the key file.',
      targetSelector: '[data-tour-id="bastion-key"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'has_bastion_key',
      completionLabel: 'Bastion key uploaded',
      pendingLabel: 'Upload your bastion key, or skip for now',
    },
    {
      id: 'configure-slice-keys',
      title: 'Step 3: Set Up Slice Keys',
      content:
        'Generate or upload SSH key pairs for slice access. Click "Add Key Set" then "Generate" to create a new pair automatically \u2014 this is the easiest option.\n\nSlice keys let you SSH into provisioned VMs. You can manage multiple named key sets for different slices.',
      targetSelector: '[data-tour-id="slice-keys"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'has_slice_key',
      completionLabel: 'Slice key configured',
      pendingLabel: 'Generate or upload a slice key, or skip for now',
    },
    {
      id: 'configure-project',
      title: 'Step 4: Verify Your Project',
      content:
        'Your active FABRIC project was auto-selected from your token. Verify this is the project you want to work with, or select a different one from the dropdown.\n\nEach project has its own resource quotas, slice namespaces, and member permissions. You can switch projects anytime from the title bar.',
      targetSelector: '[data-help-id="settings.project"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'configured',
      completionLabel: 'Project selected',
      pendingLabel: 'Verify or change your project, or skip for now',
    },
    {
      id: 'open-advanced',
      title: 'Step 5: Open Advanced Settings',
      content:
        'Click "Show Advanced Settings" below to reveal AI tool configuration and other advanced options.',
      targetSelector: '.advanced-toggle',
      requiredView: 'settings',
      tooltipPosition: 'right',
    },
    {
      id: 'configure-ai-key',
      title: 'Step 6: Set Up AI Tools',
      content:
        'Enter your FABRIC AI API key to unlock the built-in AI coding assistants (Aider, OpenCode, Crush, and the LoomAI chat). These are free to use with your FABRIC account.\n\nGet your API key from the FABRIC portal at https://portal.fabric-testbed.net \u2014 look for "AI Services" or "API Keys" in your account settings.\n\nOptionally, add an NRP API key from https://nrp.ai for access to additional models.',
      targetSelector: '[data-tour-id="ai-api-key"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'has_ai_api_key',
      completionLabel: 'AI API key configured',
      pendingLabel: 'Enter your AI API key, or skip for now',
    },
    {
      id: 'close-settings',
      title: 'Step 7: Save & Close',
      content:
        'Check that the status indicators show green dots for Token, Bastion Key, Slice Keys, and Project. Then click "Save & Close" to apply your configuration.\n\nYou can always return to Settings later from the gear icon in the title bar.',
      targetSelector: '[data-tour-id="save-close"]',
      requiredView: 'settings',
      tooltipPosition: 'bottom',
      completionCheck: 'configured',
      completionLabel: 'All credentials configured',
      pendingLabel: 'Complete the steps above, or skip for now',
    },
    {
      id: 'done',
      title: 'You\'re All Set!',
      content:
        'LoomAI is configured and ready to use! Here are two recommended next tours:\n\n\u2022 Hello, FABRIC \u2014 Run the Hello FABRIC weave to deploy your first slice with one click. A great way to verify everything works.\n\n\u2022 Build Your First Slice \u2014 Manually create a single-node slice, submit it, and SSH into it. Learn the core workflow.\n\nStart either tour from the Help page (click the ? in the title bar) or from the landing page.',
      targetSelector: '[data-help-id="titlebar.help"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 2. TOPOLOGY EDITOR — Building slice topologies
// ════════════════════════════════════════════════════════════════════

const topologyEditor: TourDef = {
  id: 'topology-editor',
  title: 'Topology Editor',
  description: 'Learn how to add nodes, components, and networks to build your slice topology.',
  icon: '\u270E',
  autoStart: false,
  helpSections: ['editor', 'topology'],
  steps: [
    {
      id: 'te-intro',
      title: 'Topology Editor Overview',
      content:
        'The topology editor lets you visually build your slice. The Cytoscape.js graph shows nodes (VMs), components (NICs, GPUs), and networks.\n\n\u2022 Click an element to select it\n\u2022 Right-click for context menus\n\u2022 Box-select or Shift-click for multi-selection\n\u2022 Scroll to zoom, drag to pan',
      targetSelector: '.cytoscape-container',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'te-create-slice',
      title: 'Create a Draft Slice',
      content:
        'First, you need a slice to work with.\n\nTry it now: click "+ New" in the toolbar to create a new draft slice. Or load a weave from the Artifacts panel on the right.',
      targetSelector: '[data-help-id="toolbar.new"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'slice_loaded',
      completionLabel: 'Slice ready',
      pendingLabel: 'Click "+ New" or load a weave to create a slice',
    },
    {
      id: 'te-add-node',
      title: 'Adding Nodes',
      content:
        'Each VM node represents a virtual machine on a FABRIC site.\n\nTry it now: click the "+" button in the Editor panel to add a new VM node. Each node starts with default settings that you can customize.',
      targetSelector: '[data-help-id="editor.add-button"]',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'has_nodes',
      completionLabel: 'Node added',
      pendingLabel: 'Add a node using the + button, or skip',
    },
    {
      id: 'te-node-props',
      title: 'Node Properties',
      content:
        'Select a node to edit its properties: site, host, cores, RAM, disk, and OS image.\n\nTry it now: click your node in the graph to select it. The editor will show its properties.\n\nThe Site dropdown shows feasibility indicators (\u2713/\u26A0) and available resources.',
      targetSelector: '.editor-panel',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'node_selected',
      completionLabel: 'Node selected \u2014 you can edit its properties now',
      pendingLabel: 'Click a node in the graph to select it',
    },
    {
      id: 'te-components',
      title: 'Hardware Components',
      content:
        'Switch to the Components tab to attach NICs, GPUs, FPGAs, or SmartNICs to a node.\n\nTry it now: with a node selected, click the Components tab and add a NIC_Basic. This creates a network interface you can connect to networks.\n\n\u2022 NIC_Basic \u2014 Shared virtual NIC (available everywhere)\n\u2022 NIC_ConnectX_5/6/7 \u2014 Dedicated SmartNICs\n\u2022 GPU_TeslaT4, GPU_A30 \u2014 GPU accelerators',
      targetSelector: '[data-help-id="editor.devices-tab"]',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'has_components',
      completionLabel: 'Component added',
      pendingLabel: 'Add a NIC or other component to your node, or skip',
    },
    {
      id: 'te-networks',
      title: 'Creating Networks',
      content:
        'Networks connect interfaces across nodes.\n\nTry it now: add a second node, give both nodes NICs, then select the interfaces and create a network. Or click the + button and choose "Add Network".\n\n\u2022 L2Bridge \u2014 Multi-point bridge at one site\n\u2022 L2STS \u2014 Site-to-site link\n\u2022 L2PTP \u2014 Point-to-point link\n\u2022 IPv4Ext \u2014 External internet',
      targetSelector: '[data-help-id="editor.network-tab"]',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'has_networks',
      completionLabel: 'Network created',
      pendingLabel: 'Create a network to connect your nodes, or skip',
    },
    {
      id: 'te-boot-config',
      title: 'Boot Configuration',
      content:
        'The Boot Config tab lets you define post-provisioning actions for each node:\n\n\u2022 File Uploads \u2014 Transfer files from storage to the VM\n\u2022 Network Config \u2014 Set up interface IPs (static or DHCP)\n\u2022 Shell Commands \u2014 Install packages, start services\n\nBoot configs run automatically after the VM is provisioned. You can re-run them anytime with the Execute button.',
      targetSelector: '[data-help-id="editor.boot-config"]',
      requiredView: 'main',
      tooltipPosition: 'right',
    },
    {
      id: 'te-layout',
      title: 'Graph Layout',
      content:
        'Use the layout selector to rearrange the topology graph. Choose from Dagre (hierarchical), Cola (force-directed), Breadth-First, Grid, Concentric, or CoSE (physics-based).\n\nClick "Fit" to zoom to fit all elements, or "Save PNG" to export the graph as an image.',
      targetSelector: '[data-help-id="topology.layout"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'te-context-menu',
      title: 'Context Menu & Submit',
      content:
        'Right-click any node for quick actions: Open Terminal, Save as VM Template, Apply Recipe, Delete.\n\nWhen your topology is ready, click Submit in the toolbar. The system will:\n1. Refresh resource availability\n2. Resolve site assignments\n3. Validate the topology\n4. Submit to FABRIC for provisioning',
      targetSelector: '[data-help-id="toolbar.submit"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 3. AI TOOLS — Using AI assistants to create and manage slices
// ════════════════════════════════════════════════════════════════════

const aiTools: TourDef = {
  id: 'ai-tools',
  title: 'AI Tools & LoomAI',
  description: 'Use AI assistants to create slices, write scripts, and manage experiments with natural language.',
  icon: '\u{1F916}',
  autoStart: false,
  helpSections: ['ai-chat', 'ai-companion'],
  steps: [
    {
      id: 'ai-intro',
      title: 'AI-Powered Development',
      content:
        'LoomAI embeds multiple AI coding assistants directly into your workflow. They can create slice topologies, write deployment scripts, troubleshoot issues, and manage experiments \u2014 all through natural language.\n\nLet\'s explore the AI Tools view.',
      targetSelector: '[data-help-id="titlebar.view"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'ai-launcher',
      title: 'AI Tools Launcher',
      content:
        'The AI Tools view shows available assistants as cards. Each has different strengths:\n\n\u2022 LoomAI \u2014 Chat-based FABRIC assistant with tool calling\n\u2022 Aider \u2014 AI pair programmer for editing files\n\u2022 OpenCode \u2014 Coding assistant with FABRIC skills\n\u2022 Crush \u2014 Terminal AI from Charm\n\u2022 Claude Code \u2014 Anthropic\'s advanced CLI (paid)\n\nTry it now: click on one of the tool cards to launch it.',
      targetSelector: '.ai-companion-view',
      requiredView: 'ai',
      tooltipPosition: 'bottom',
      completionCheck: 'ai_tool_selected',
      completionLabel: 'AI tool selected',
      pendingLabel: 'Click a tool card to launch it, or skip',
    },
    {
      id: 'ai-loomai',
      title: 'LoomAI Chat',
      content:
        'LoomAI is the FABRIC-aware chat assistant. It can execute FABRIC operations using tool calling.\n\nTry asking it:\n\u2022 "Create a 2-node slice with an L2 bridge at RENC"\n\u2022 "What sites have GPUs available?"\n\u2022 "Show me my active slices"\n\u2022 "Help me write a boot script to install Docker"\n\nThe assistant streams responses and shows expandable tool call cards when it executes FABRIC operations.',
      targetSelector: '.ai-companion-view',
      requiredView: 'ai',
      tooltipPosition: 'bottom',
    },
    {
      id: 'ai-model-agent',
      title: 'Models & Agent Personas',
      content:
        'When using LoomAI, you can choose:\n\n\u2022 Model \u2014 Which LLM to use (different speed/capability tradeoffs)\n\u2022 Agent Persona \u2014 Specialization that tailors the assistant:\n  \u2013 Network Architect (topology design)\n  \u2013 Troubleshooter (diagnosing issues)\n  \u2013 Experiment Designer (planning experiments)\n  \u2013 Template Builder (creating weaves)\n  \u2013 DevOps Engineer (automation)\n\nEach persona has a system prompt guiding the AI toward relevant expertise.',
      targetSelector: '.ai-companion-view',
      requiredView: 'ai',
      tooltipPosition: 'bottom',
    },
    {
      id: 'ai-coding-tools',
      title: 'AI Coding Assistants',
      content:
        'Aider, OpenCode, Crush, and Claude Code run in a split-pane view with the tool on the left and a container file browser on the right.\n\nUse them to:\n\u2022 Write deployment scripts and boot configs\n\u2022 Create weave artifacts (weave.json defines the topology, weave.sh runs it, output goes to weave.log)\n\u2022 Debug networking and configuration issues\n\u2022 Generate FABlib Python code for custom experiments\n\nAll tools have access to your workspace files and FABRIC domain knowledge.',
      targetSelector: '.ai-companion-view',
      requiredView: 'ai',
      tooltipPosition: 'bottom',
    },
    {
      id: 'ai-example',
      title: 'Example: Create a Slice with AI',
      content:
        'Here\'s a typical workflow using LoomAI:\n\n1. Open LoomAI from the AI Tools launcher\n2. Ask: "Create a 2-node iPerf bandwidth test with Ubuntu 24.04 at RENC and TACC"\n3. The AI creates the slice topology using tool calls\n4. Review the topology in the Topology editor\n5. Submit the slice\n6. Ask the AI to troubleshoot if anything goes wrong\n\nYou can also use AI to write complex boot scripts, create weave artifacts, or analyze experiment results.',
      targetSelector: '.ai-companion-view',
      requiredView: 'ai',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 4. ARTIFACTS & WEAVES — Managing reusable experiment building blocks
// ════════════════════════════════════════════════════════════════════

const artifactsWeaves: TourDef = {
  id: 'artifacts-weaves',
  title: 'Artifacts & Weaves',
  description: 'Create, manage, and publish reusable experiment templates, scripts, and notebooks.',
  icon: '\u{1F4E6}',
  autoStart: false,
  helpSections: ['templates', 'vm-templates', 'libraries'],
  steps: [
    {
      id: 'aw-intro',
      title: 'The Artifact System',
      content:
        'Artifacts are reusable building blocks for experiments. They come in four types:\n\n\u2022 Weaves \u2014 Slice topologies with optional deploy/run scripts\n\u2022 VM Templates \u2014 Pre-configured single-node setups\n\u2022 Recipes \u2014 Software installation scripts for provisioned VMs\n\u2022 Notebooks \u2014 Jupyter notebooks for interactive experiments\n\nLet\'s explore the Artifacts view.',
      targetSelector: '[data-help-id="titlebar.view"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-local',
      title: 'My Artifacts',
      content:
        'The Artifacts view has three tabs: My Artifacts, Published (by me), and Community Marketplace.\n\nThe My Artifacts tab shows artifacts on your machine. Each card displays:\n\u2022 Name and description\n\u2022 Remote status badge \u2014 Linked (connected to marketplace), Update Available (newer version exists), Local Only, or Remote Deleted\n\u2022 Action buttons \u2014 Open, Publish, Edit, Delete\n\nArtifacts downloaded from the marketplace automatically track their remote version, so you\'ll see an "Update available" notification when a newer version is published.',
      targetSelector: '[data-help-id="libraries.my-artifacts"]',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-marketplace',
      title: 'Community Marketplace',
      content:
        'The Community Marketplace tab connects to the FABRIC Artifact Manager (artifacts.fabric-testbed.net) and lets you browse artifacts published by the community.\n\n\u2022 Search by name or description\n\u2022 Filter by category (Weave, VM Template, Recipe, Notebook)\n\u2022 Filter by tags or author\n\u2022 Sort by popularity, newest, or alphabetically\n\u2022 Toggle grid vs table view\n\nClick "Get" to download an artifact. For multi-version artifacts, a version picker lets you choose which version to install. Downloaded artifacts show an "Installed" badge.',
      targetSelector: '[data-help-id="libraries.marketplace"]',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-weave-types',
      title: 'Understanding Weaves',
      content:
        'A weave is defined by weave.json and can contain:\n\n\u2022 weave.json \u2014 Topology definition (nodes, networks, boot configs) \u2014 required marker file\n\u2022 weave.sh \u2014 Run script for the weave (output goes to weave.log)\n\n Action buttons appear based on what the weave contains:\n\u2022 Load/Deploy require weave.json\n\u2022 Run requires weave.sh (or a run_script in weave_config)\n\u2022 JupyterLab opens the folder for editing',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-load-weave',
      title: 'Load a Weave',
      content:
        'Try it now: find a weave in the My Artifacts tab and click "Load" to create a draft slice from it.\n\nThe weave\'s topology will appear in the editor with all nodes, networks, and boot configs pre-configured. You can modify anything before submitting.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
      completionCheck: 'slice_loaded',
      completionLabel: 'Weave loaded into editor',
      pendingLabel: 'Click "Load" on a weave to try it, or skip',
    },
    {
      id: 'aw-create-weave',
      title: 'Creating a Weave',
      content:
        'To create a weave from an existing slice:\n\n1. Build your topology in the editor\n2. Click "Save as Weave" in the toolbar\n3. The weave captures all nodes, networks, site groups, and boot configs as weave.json\n\nTo make the weave runnable, use an AI tool to add a weave.sh script:\n1. Open the weave folder in JupyterLab\n2. Write weave.sh with your experiment commands\n3. The weave now has a Run button (output goes to weave.log)',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-publish',
      title: 'Publishing Artifacts',
      content:
        'Share your artifacts with the FABRIC community:\n\n1. Find your artifact in the My Artifacts tab and click "Publish"\n2. Fill in the publish dialog:\n   \u2022 Title and short description (shown on cards)\n   \u2022 Long description (detailed documentation)\n   \u2022 Visibility: author-only, project, or public\n   \u2022 Project association and author credits\n   \u2022 Tags for categorization\n3. Choose an action: New (first publish), Update (new version), or Fork (based on someone else\'s artifact)\n\nManage published artifacts from the Published tab \u2014 edit metadata, add versions, change visibility.',
      targetSelector: '[data-help-id="libraries.publish"]',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-versions',
      title: 'Version Tracking',
      content:
        'LoomAI tracks which version of each marketplace artifact you have installed.\n\n\u2022 When a newer version is published, a teal "Update available" badge appears on your local copy\n\u2022 Click "Get" on the marketplace version to update\n\u2022 Use "Reset" to revert to the originally downloaded version\n\u2022 The detail panel shows your installed version number and the latest available version\n\nThis helps you keep your experiment templates current with community improvements.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-side-panel',
      title: 'Artifacts Side Panel',
      content:
        'Back in the Topology view, the Artifacts side panel gives quick access to your artifacts.\n\nThe four tabs (Weaves, VM, Recipes, Notebooks) let you:\n\u2022 Load weaves into the editor\n\u2022 Deploy weaves with one click\n\u2022 Add VM templates to the current slice\n\u2022 Apply recipes to provisioned nodes\n\u2022 Star favorite recipes for the context menu',
      targetSelector: '.template-panel',
      requiredView: 'main',
      tooltipPosition: 'left',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 5. MAP & RESOURCES — Exploring FABRIC infrastructure
// ════════════════════════════════════════════════════════════════════

const mapResources: TourDef = {
  id: 'map-resources',
  title: 'Map & Resources',
  description: 'Explore FABRIC sites worldwide, check resource availability, and understand the backbone network.',
  icon: '\u{1F30D}',
  autoStart: false,
  helpSections: ['map'],
  steps: [
    {
      id: 'mr-intro',
      title: 'Load Resource Data',
      content:
        'Before exploring the map, you need to load site and resource data from FABRIC.\n\nTry it now: click "Refresh Resources" in the toolbar. This fetches all FABRIC sites, their available resources, and backbone link information.',
      targetSelector: '[data-help-id="toolbar.refresh-resources"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'resources_loaded',
      completionLabel: 'Resources loaded',
      pendingLabel: 'Click "Refresh Resources" to load site data, or skip',
    },
    {
      id: 'mr-sites',
      title: 'FABRIC Sites',
      content:
        'Each marker represents a FABRIC site. Try it now: click a site marker on the map to see its details.\n\nThe Detail panel will show:\n\u2022 Available resources (cores, RAM, disk)\n\u2022 Component inventory (GPUs, SmartNICs, FPGAs)\n\u2022 Live metrics (CPU load, network throughput)\n\u2022 Per-host resource breakdown\n\nSite colors indicate utilization levels \u2014 green means plenty of capacity.',
      targetSelector: '.geo-view',
      requiredView: 'map',
      tooltipPosition: 'top',
    },
    {
      id: 'mr-links',
      title: 'Backbone Links',
      content:
        'Lines between sites represent the FABRIC backbone network \u2014 high-speed optical connections that enable cross-site experiments.\n\nTry it now: click a link line to see bandwidth capacity and utilization in both directions. Use the toggle buttons to show/hide infrastructure links and slice connections independently.',
      targetSelector: '.geo-view',
      requiredView: 'map',
      tooltipPosition: 'top',
    },
    {
      id: 'mr-site-mapping',
      title: 'Site Resolution',
      content:
        'When building slices, the site resolver automatically places nodes on sites with available resources.\n\nIn the Editor panel, the Site Mapping view shows how @group tags map to concrete sites. Use "Auto-Assign" to re-resolve with fresh data, or manually override any assignment.\n\nOn submit, all sites are re-resolved with force-refreshed availability data.',
      targetSelector: '.editor-panel',
      requiredView: 'main',
      tooltipPosition: 'right',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 6. TABLE VIEW & BULK OPERATIONS — Managing many slices
// ════════════════════════════════════════════════════════════════════

const tableViewOps: TourDef = {
  id: 'table-view',
  title: 'Table View & Bulk Ops',
  description: 'Use the table view to manage multiple slices with filtering, sorting, and bulk delete.',
  icon: '\u{1F4CA}',
  autoStart: false,
  helpSections: ['sliver'],
  steps: [
    {
      id: 'tv-load',
      title: 'Load Your Slices',
      content:
        'The Table view shows all your slices in an expandable table. But first, you need slices to view.\n\nTry it now: click "Load Slices" in the toolbar to fetch your slices from FABRIC. If you already have slices loaded, you\'re good to go.',
      targetSelector: '[data-help-id="toolbar.load"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'has_slices',
      completionLabel: 'Slices loaded',
      pendingLabel: 'Click "Load Slices" to fetch your slices, or skip',
    },
    {
      id: 'tv-intro',
      title: 'Table View',
      content:
        'Each slice row shows its name, state (as a color-coded badge), lease expiration, and resource counts.\n\nTry it now: click the arrow on a slice row to expand it and see its individual nodes and networks.',
      targetSelector: '.all-slivers-view',
      requiredView: 'slivers',
      tooltipPosition: 'bottom',
    },
    {
      id: 'tv-filter',
      title: 'Filtering & Sorting',
      content:
        'Try it now: type something in the filter bar to search across slice names, states, sites, and images. The filter count shows how many slices match.\n\nClick any column header to sort \u2014 by name, state, lease end, node count, or network count. Click again to reverse the sort direction.',
      targetSelector: '.sliver-action-bar',
      requiredView: 'slivers',
      tooltipPosition: 'bottom',
    },
    {
      id: 'tv-select-all',
      title: 'Select All & Bulk Delete',
      content:
        'Use Select All with the filter for powerful bulk operations:\n\n1. Type a filter (e.g., "test-" to find test slices)\n2. Click "Select All" to select all matching slices\n3. Click "Delete" to remove them in one operation\n\nYou can also use the header checkbox to toggle all filtered slices, or individual checkboxes for fine-tuned selection.',
      targetSelector: '.sliver-action-bar',
      requiredView: 'slivers',
      tooltipPosition: 'bottom',
    },
    {
      id: 'tv-state-badges',
      title: 'State Badges',
      content:
        'Slice states are shown as color-coded badges:\n\n\u2022 StableOK / ModifyOK \u2014 Green (healthy)\n\u2022 StableError / ModifyError \u2014 Red (errors)\n\u2022 Active \u2014 Blue (in use)\n\u2022 Configuring / Allocating \u2014 Blue (provisioning)\n\u2022 Nascent / Draft \u2014 Gray (new)\n\u2022 Closing \u2014 Orange (tearing down)\n\u2022 Dead \u2014 Dark gray (deleted)\n\nDouble-click any slice row to open it in the topology editor.',
      targetSelector: '.all-slivers-view',
      requiredView: 'slivers',
      tooltipPosition: 'bottom',
    },
    {
      id: 'tv-context',
      title: 'Context Menu',
      content:
        'Try it now: right-click a slice or node row to see the context menu with quick actions:\n\n\u2022 Open in Editor \u2014 Switch to topology view with this slice\n\u2022 Open Build Log \u2014 View deploy/boot output\n\u2022 Open Terminal \u2014 SSH into a provisioned VM\n\u2022 Save as VM Template \u2014 Capture a node\'s configuration\n\u2022 Apply Recipe \u2014 Install software on a running VM\n\u2022 Delete \u2014 Remove the slice from FABRIC',
      targetSelector: '.all-slivers-view',
      requiredView: 'slivers',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 7. WEB APPS — Accessing services running on slice VMs
// ════════════════════════════════════════════════════════════════════

const webApps: TourDef = {
  id: 'web-apps',
  title: 'My Web Apps',
  description: 'Access web services running on your slice VMs through secure tunnels.',
  icon: '\u{1F310}',
  autoStart: false,
  helpSections: [],
  steps: [
    {
      id: 'wa-intro',
      title: 'My Web Apps',
      content:
        'The Web Apps view lets you access web services running inside your slice VMs directly in the browser.\n\nThis works by creating a secure tunnel through the FABRIC bastion host to a port on your VM. You can access Jupyter servers, web dashboards, monitoring UIs, or any HTTP service.',
      targetSelector: '[data-help-id="titlebar.view"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'wa-load-slices',
      title: 'Load Slices First',
      content:
        'To connect to a web app, you need a provisioned slice with running VMs.\n\nTry it now: click "Load Slices" if you haven\'t already. You\'ll need at least one slice in StableOK state with a web service running on it.',
      targetSelector: '[data-help-id="toolbar.load"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'has_slices',
      completionLabel: 'Slices loaded',
      pendingLabel: 'Load your slices to continue, or skip',
    },
    {
      id: 'wa-setup',
      title: 'Setting Up a Tunnel',
      content:
        'Try it now: set up a web app tunnel:\n\n1. Select a slice from the dropdown\n2. Select a node (must have a management IP \u2014 i.e., be provisioned)\n3. Enter the port number your service is running on (e.g., 8888 for Jupyter, 3000 for Grafana, 9090 for Prometheus)\n4. Click Connect\n\nThe tunnel takes a few seconds to establish. Once connected, the web app appears in an embedded frame.',
      targetSelector: '.client-view',
      requiredView: 'client',
      tooltipPosition: 'bottom',
    },
    {
      id: 'wa-example',
      title: 'Example: Monitoring Stack',
      content:
        'A common use case: deploy a Prometheus + Grafana weave, then access the dashboards:\n\n1. Deploy the "Prometheus & Grafana Stack" weave\n2. Wait for it to reach StableOK\n3. Open My Web Apps, select the slice\n4. Connect to port 3000 on the Grafana node\n5. Browse your monitoring dashboards in the browser\n\nYou can have multiple tunnels active simultaneously to different nodes and ports.',
      targetSelector: '.client-view',
      requiredView: 'client',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 8. JUPYTERLAB — Interactive notebook environment
// ════════════════════════════════════════════════════════════════════

const jupyterLab: TourDef = {
  id: 'jupyter-lab',
  title: 'JupyterLab',
  description: 'Use the embedded JupyterLab environment for interactive experiments and artifact editing.',
  icon: '\u{1F4D3}',
  autoStart: false,
  helpSections: [],
  steps: [
    {
      id: 'jl-intro',
      title: 'Embedded JupyterLab',
      content:
        'LoomAI includes a full JupyterLab environment running on the backend container. Use it for:\n\n\u2022 Interactive FABlib experiments\n\u2022 Data analysis and visualization\n\u2022 Editing weave scripts (weave.sh)\n\u2022 Running Jupyter notebooks from the Artifacts view\n\nJupyterLab auto-starts when you first access it and syncs with your app theme.',
      targetSelector: '[data-help-id="titlebar.view"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'jl-view',
      title: 'The JupyterLab View',
      content:
        'Try it now: you\'re looking at the JupyterLab view. The JupyterLab server starts automatically on first access.\n\nControl buttons at the top:\n\u2022 Refresh \u2014 Reload the JupyterLab frame\n\u2022 Restart \u2014 Stop and relaunch the JupyterLab server\n\nThe file browser shows your workspace files, including artifacts, slice data, and configuration. Files persist across sessions.',
      targetSelector: '.jupyter-view',
      requiredView: 'jupyter',
      tooltipPosition: 'bottom',
    },
    {
      id: 'jl-artifacts',
      title: 'Editing Artifacts in JupyterLab',
      content:
        'Try it now: go to the Artifacts side panel (in topology view) and click "JupyterLab" on any weave, VM template, or recipe card. This opens that artifact\'s folder directly in JupyterLab.\n\nThis is the easiest way to:\n\u2022 Edit weave.sh run scripts\n\u2022 Modify weave.json topology files\n\u2022 Update boot configuration commands\n\u2022 Write and test Jupyter notebooks before publishing\n\nChanges are saved directly to your artifact storage.',
      targetSelector: '.template-panel',
      requiredView: 'main',
      tooltipPosition: 'left',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 9. CONSOLE & TERMINALS — Debugging and SSH access
// ════════════════════════════════════════════════════════════════════

const consoleTerminals: TourDef = {
  id: 'console-terminals',
  title: 'Console & Terminals',
  description: 'Use the console for logs, validation, deploy output, and SSH sessions to your VMs.',
  icon: '\u{1F5B5}',
  autoStart: false,
  helpSections: ['bottom'],
  steps: [
    {
      id: 'ct-overview',
      title: 'Console Panel',
      content:
        'The console at the bottom organizes different output types into tabs. Try it now: drag the top edge of the console to resize it.\n\nTabs include fixed tabs (Errors, Validation, Log, Local Terminal) and dynamic tabs created by operations (Build Logs, Run Scripts, Recipe output, SSH sessions).',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'ct-validation',
      title: 'Validation',
      content:
        'Try it now: if you have a slice loaded, click the "Validation" tab to see real-time checks.\n\n\u2022 Errors (red) \u2014 Block submission (e.g., missing sites, invalid configs)\n\u2022 Warnings (yellow) \u2014 Advisory issues (e.g., large resource requests)\n\nEach issue includes a description and a suggested remedy. Load or create a slice to see validation in action.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
      completionCheck: 'slice_loaded',
      completionLabel: 'Slice loaded \u2014 check the Validation tab',
      pendingLabel: 'Load a slice to see validation results, or skip',
    },
    {
      id: 'ct-errors',
      title: 'Errors Tab',
      content:
        'The Errors tab collects API and operation failures with timestamps. It\'s where you look first when something goes wrong.\n\nClick "Clear" to dismiss old errors. Errors also appear briefly in the status bar at the bottom of the screen.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'ct-build-log',
      title: 'Build Log & Run Scripts',
      content:
        'When you Deploy a weave, a Build Log tab streams the full pipeline output: template loading, submission, provisioning, and boot config execution.\n\nWhen you Run a weave script, a separate tab labeled "run:<name>" streams the autonomous script output for up to 30 minutes.\n\nLines with "### PROGRESS:" appear as progress milestones.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'ct-local-terminal',
      title: 'Local Terminal',
      content:
        'Try it now: click the "Local" tab to open a shell on the backend container. You can:\n\n\u2022 Run FABlib Python commands\n\u2022 Troubleshoot SSH connections\n\u2022 Check FABRIC configuration files\n\u2022 Run custom scripts\n\nThe terminal runs as the application user with access to your FABRIC credentials.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'ct-ssh',
      title: 'SSH Node Terminals',
      content:
        'After provisioning a slice, right-click any node in the graph and select "Open Terminal" to start an SSH session.\n\nEach node gets its own tab in the console. SSH connections route through the FABRIC bastion host via WebSocket. You can have multiple terminal tabs open to different nodes simultaneously.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 10. FILE MANAGER — Transferring files between container and VMs
// ════════════════════════════════════════════════════════════════════

const fileManager: TourDef = {
  id: 'file-manager',
  title: 'File Manager',
  description: 'Transfer files between container storage and slice VMs using the dual-panel file manager.',
  icon: '\u{1F4C1}',
  autoStart: false,
  helpSections: ['files'],
  steps: [
    {
      id: 'fm-intro',
      title: 'Dual-Panel File Manager',
      content:
        'The Storage view provides a dual-panel file manager for moving files between your container storage and slice VMs.\n\n\u2022 Left panel \u2014 Container storage (local backend files)\n\u2022 Right panel \u2014 VM files via SFTP (select a provisioned node)\n\u2022 Center buttons \u2014 Transfer files between panels',
      targetSelector: '[data-help-id="titlebar.view"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'fm-container',
      title: 'Container Storage',
      content:
        'Try it now: the left panel shows files stored on the backend container. You can:\n\n\u2022 Upload files from your computer (drag-and-drop or file picker)\n\u2022 Create folders to organize files\n\u2022 Double-click text files to edit them inline\n\u2022 Download files to your computer\n\nFiles here persist as long as the container is running. Use them in boot configurations for automated VM setup.',
      targetSelector: '.file-transfer-view',
      requiredView: 'files',
      tooltipPosition: 'top',
    },
    {
      id: 'fm-vm',
      title: 'VM File Access',
      content:
        'Try it now: if you have a provisioned slice, connect the right panel to a VM:\n\n1. Select a slice from the dropdown\n2. Select a node (must have a management IP)\n3. Browse, upload, download, rename, and delete files on the VM\n\nUse the transfer buttons in the center to copy files between panels. You can also drag and drop files across panels.',
      targetSelector: '.file-transfer-view',
      requiredView: 'files',
      tooltipPosition: 'top',
      completionCheck: 'has_slices',
      completionLabel: 'Slices available for file access',
      pendingLabel: 'Load slices to connect to a VM, or skip',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 11. HELLO FABRIC — Run the Hello FABRIC weave
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
// 12. BUILD YOUR FIRST SLICE — Manual single-node creation
// ════════════════════════════════════════════════════════════════════

const buildFirstSlice: TourDef = {
  id: 'build-first-slice',
  title: 'Build Your First Slice',
  description: 'Manually create a single-node slice, submit it to FABRIC, and SSH into it \u2014 learn the core workflow.',
  icon: '\u{1F9F1}',
  autoStart: false,
  helpSections: ['toolbar', 'editor', 'topology'],
  steps: [
    {
      id: 'bfs-intro',
      title: 'Build Your First Slice',
      content:
        'In this tour you\'ll manually create a slice with one VM, submit it to FABRIC, and SSH into it. This teaches the core slice-building workflow that you\'ll use for more complex experiments.',
      targetSelector: '.title-bar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'bfs-new-slice',
      title: 'Step 1: Create a New Slice',
      content:
        'Click "+ New" in the toolbar to create a new draft slice. Enter a name like "my-first-slice" and press Enter.\n\nA draft slice is local until you submit it to FABRIC.',
      targetSelector: '[data-help-id="toolbar.new"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'slice_loaded',
      completionLabel: 'Slice created',
      pendingLabel: 'Click "+ New" to create a slice, or skip',
    },
    {
      id: 'bfs-add-node',
      title: 'Step 2: Add a VM Node',
      content:
        'In the Editor panel on the left, click the "+" button to add a new element, then select "VM Node".\n\nConfigure the node:\n\u2022 Name: any unique name (e.g., "node1")\n\u2022 Site: leave as "auto" for automatic placement\n\u2022 Cores: 2, RAM: 8 GB, Disk: 10 GB\n\u2022 Image: default_ubuntu_22 (recommended)\n\nClick "Add Node" to add it to the slice.',
      targetSelector: '.editor-panel',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'has_nodes',
      completionLabel: 'Node added',
      pendingLabel: 'Add a VM node using the + button, or skip',
    },
    {
      id: 'bfs-review',
      title: 'Step 3: Review the Topology',
      content:
        'Your node appears in the topology graph. Click it to see its properties in the Editor panel.\n\nThe Validation tab in the console should show a green checkmark \u2014 meaning your slice is valid and ready to submit.\n\nIf you see warnings about site availability, the auto-assign resolver will handle placement when you submit.',
      targetSelector: '[data-help-id="topology.graph"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'bfs-submit',
      title: 'Step 4: Submit to FABRIC',
      content:
        'Click "Submit" in the toolbar to provision the slice on FABRIC.\n\nThe system will:\n1. Refresh resource availability from all FABRIC sites\n2. Assign your node to a site with available resources\n3. Submit the slice for provisioning\n\nProvisioning takes 2\u20135 minutes. Auto-refresh will poll for status updates automatically.',
      targetSelector: '[data-help-id="toolbar.submit"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'bfs-wait',
      title: 'Step 5: Wait for Provisioning',
      content:
        'The slice state will progress: Nascent \u2192 Configuring \u2192 StableOK.\n\nWhile waiting, you can:\n\u2022 Watch the slice state badge in the toolbar\n\u2022 Check the Validation and Errors tabs in the console\n\u2022 Explore the Map view to see where your node was placed\n\nOnce the state shows StableOK (green), your VM is ready.',
      targetSelector: '.toolbar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'bfs-ssh',
      title: 'Step 6: SSH into Your VM',
      content:
        'Right-click the node in the topology graph and select "Open Terminal". This opens an SSH session to your VM in the console panel.\n\nYou\'re now connected to a FABRIC VM! Try running:\n\u2022 hostname \u2014 see the VM\'s name\n\u2022 ip addr \u2014 see network interfaces\n\u2022 uname -a \u2014 see the kernel version',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'bfs-done',
      title: 'Congratulations!',
      content:
        'You\'ve built and deployed a FABRIC slice from scratch. You now know the core workflow: create \u2192 add nodes \u2192 submit \u2192 connect.\n\nNext steps:\n\u2022 Add more nodes and networks to build multi-node topologies\n\u2022 Attach GPUs, SmartNICs, or FPGAs via the Components tab\n\u2022 Set up boot scripts to automate VM configuration\n\u2022 Save your topology as a weave for reuse\n\nWhen done, delete the slice from the toolbar to free resources.\n\nMore tours available from the Help page \u2014 click ? in the title bar.',
      targetSelector: '[data-help-id="titlebar.help"]',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// 13. DISCOVER LOOMAI — Visual overview / sales pitch
// ════════════════════════════════════════════════════════════════════

const discoverLoomai: TourDef = {
  id: 'discover-loomai',
  title: 'Discover LoomAI',
  description: 'A visual tour of LoomAI\u2019s capabilities \u2014 see how AI-powered tools, visual editors, and automated workflows come together to build experiments on FABRIC.',
  icon: '\u2728',
  autoStart: false,
  helpSections: ['overview'],
  steps: [
    {
      id: 'dl-welcome',
      title: 'Welcome to LoomAI',
      content:
        'LoomAI is FABRIC\u2019s AI-powered loom for weaving custom network fabrics.\n\nFABRIC is a global research infrastructure with 35 sites offering programmable networking, bare-metal VMs, GPUs, FPGAs, SmartNICs, and high-speed optical links. LoomAI gives you a visual, browser-based sandbox to design, deploy, and manage experiments \u2014 aided by embedded AI coding assistants.\n\nLet\u2019s take a quick look at what LoomAI can do.',
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
        'Four AI coding assistants are embedded directly into LoomAI, each pre-configured with FABRIC domain knowledge and direct access to testbed operations:\n\n\u2022 Aider \u2014 AI pair programming for editing deployment scripts\n\u2022 OpenCode \u2014 Full-featured coding assistant with FABRIC-specific skills and agents\n\u2022 Crush \u2014 Elegant terminal AI from Charm with FABRIC and NRP model support\n\u2022 Claude Code \u2014 Anthropic\u2019s CLI with deep FABRIC MCP integration\n\nFree tools use FABRIC AI (ai.fabric-testbed.net). Use natural language to create topologies, generate scripts, debug networking, and automate experiment workflows.',
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
      id: 'dl-get-started',
      title: 'Ready to Build?',
      content:
        'LoomAI gives you everything you need to design, deploy, and manage research experiments on FABRIC \u2014 from visual topology design to AI-powered automation.\n\nTo get started:\n\u2022 Take the Getting Started tour to configure your credentials\n\u2022 Or jump straight in \u2014 click "+ New" in the toolbar to create your first slice\n\u2022 Visit the Help page for detailed documentation on every feature\n\nHappy experimenting!',
      targetSelector: '_fullscreen',
      requiredView: 'landing',
      tooltipPosition: 'bottom',
    },
  ],
};

// ════════════════════════════════════════════════════════════════════
// Exports
// ════════════════════════════════════════════════════════════════════

export const tours: Record<string, TourDef> = {
  'discover-loomai': discoverLoomai,
  'getting-started': gettingStarted,
  'hello-fabric': helloFabric,
  'build-first-slice': buildFirstSlice,
  'topology-editor': topologyEditor,
  'ai-tools': aiTools,
  'artifacts-weaves': artifactsWeaves,
  'map-resources': mapResources,
  'table-view': tableViewOps,
  'web-apps': webApps,
  'jupyter-lab': jupyterLab,
  'console-terminals': consoleTerminals,
  'file-manager': fileManager,
};

export const tourList: TourDef[] = [
  discoverLoomai,
  gettingStarted,
  helloFabric,
  buildFirstSlice,
  topologyEditor,
  aiTools,
  artifactsWeaves,
  mapResources,
  tableViewOps,
  webApps,
  jupyterLab,
  consoleTerminals,
  fileManager,
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
