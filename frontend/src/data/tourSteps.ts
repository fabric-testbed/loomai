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
  description: 'Set up your FABRIC credentials, learn the workspace layout, and get ready to create slices.',
  icon: '\u{1F680}',
  autoStart: false,
  helpSections: [],
  steps: [
    {
      id: 'welcome',
      title: 'Welcome to LoomAI',
      content:
        'This tour will walk you through setting up your FABRIC account step by step. You\'ll configure your token, SSH keys, and project \u2014 then you\'ll be ready to create slices.\n\nEach setup step lets you do the work right here. Complete it and the tour will detect it automatically.',
      targetSelector: '.title-bar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
    },
    {
      id: 'configure-token',
      title: 'Step 1: Upload Your Token',
      content:
        'Upload your FABRIC identity token now. Click "Login via FABRIC Portal" to sign in and get a fresh token, or drag-and-drop your token JSON file onto the upload area.\n\nThe token identifies you and determines which projects you can access. It expires periodically and can be refreshed from the portal.',
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
        'Upload your FABRIC bastion private key. This key authenticates you through the bastion host (jump server) to reach your slice VMs via SSH.\n\nYou can download your bastion key from the FABRIC Portal under "Manage SSH Keys". Click the upload button or drag-and-drop the key file.',
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
        'Generate or upload SSH key pairs for slice access. Click "Add Key Set" then "Generate" to create a new pair automatically \u2014 this is the easiest option.\n\nSlice keys let you SSH into provisioned VMs. You can have multiple named key sets for different slices.',
      targetSelector: '[data-tour-id="slice-keys"]',
      requiredView: 'settings',
      tooltipPosition: 'right',
      completionCheck: 'has_slice_key',
      completionLabel: 'Slice key configured',
      pendingLabel: 'Generate or upload a slice key, or skip for now',
    },
    {
      id: 'close-settings',
      title: 'Step 4: Save & Close',
      content:
        'Check that the status indicators above are green, then click "Save & Close" to apply your configuration.\n\nIf any steps are incomplete, you can always return to Settings later from the gear icon in the title bar.',
      targetSelector: '.status-banner',
      requiredView: 'settings',
      tooltipPosition: 'bottom',
      completionCheck: 'configured',
      completionLabel: 'All credentials configured',
      pendingLabel: 'Complete the steps above, or skip for now',
    },
    {
      id: 'toolbar-intro',
      title: 'The Toolbar',
      content:
        'This is your main workspace. The toolbar has everything for managing slices.\n\nTry it now: click "Load Slices" to fetch your existing slices from FABRIC.',
      targetSelector: '.toolbar',
      requiredView: 'main',
      tooltipPosition: 'bottom',
      completionCheck: 'has_slices',
      completionLabel: 'Slices loaded',
      pendingLabel: 'Click "Load Slices" to fetch your slices, or skip',
    },
    {
      id: 'load-template',
      title: 'Artifacts Panel',
      content:
        'The Artifacts panel has weaves (pre-built topologies), VM templates, recipes, and notebooks.\n\nTry it now: click "Load" on any weave to create a draft slice from it. This gives you a topology to explore in the editor.',
      targetSelector: '.template-panel',
      requiredView: 'main',
      tooltipPosition: 'left',
      completionCheck: 'slice_loaded',
      completionLabel: 'Slice loaded in editor',
      pendingLabel: 'Load a weave or click "+ New" in the toolbar, or skip',
    },
    {
      id: 'edit-node',
      title: 'Editor Panel',
      content:
        'The Editor panel lets you modify the selected node, network, or component. Change the site, adjust cores/RAM/disk, pick an OS image, or add hardware components.\n\nTry it now: click any node in the graph to select it for editing.',
      targetSelector: '.editor-panel',
      requiredView: 'main',
      tooltipPosition: 'right',
      completionCheck: 'node_selected',
      completionLabel: 'Node selected',
      pendingLabel: 'Click a node in the graph to select it, or skip',
    },
    {
      id: 'console-panel',
      title: 'Console Panel',
      content:
        'The console at the bottom shows errors, validation results, logs, and terminal sessions.\n\nAfter provisioning, right-click any node in the graph and select "Open Terminal" for an SSH session. Drag the top edge to resize.',
      targetSelector: '.bottom-panel',
      requiredView: 'main',
      tooltipPosition: 'top',
    },
    {
      id: 'done',
      title: 'You\'re All Set!',
      content:
        'You now know the basics of LoomAI. Here\'s what to try next:\n\n\u2022 Load a weave and click Submit to provision a slice\n\u2022 Explore the Map view to see FABRIC sites worldwide\n\u2022 Try the AI Tools to create slices with natural language\n\u2022 Right-click elements for context menus\n\u2022 Hover over any label for a tooltip\n\nFind more tours on the Help page or restart this one from the landing page.',
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
        'LoomAI is the built-in FABRIC-aware chat assistant. It can execute FABRIC operations using tool calling.\n\nTry asking it:\n\u2022 "Create a 2-node slice with an L2 bridge at RENC"\n\u2022 "What sites have GPUs available?"\n\u2022 "Show me my active slices"\n\u2022 "Help me write a boot script to install Docker"\n\nThe assistant streams responses and shows expandable tool call cards when it executes FABRIC operations.',
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
        'Aider, OpenCode, Crush, and Claude Code run in a split-pane view with the tool on the left and a container file browser on the right.\n\nUse them to:\n\u2022 Write deployment scripts and boot configs\n\u2022 Create weave artifacts (slice.json + deploy.sh + run.sh)\n\u2022 Debug networking and configuration issues\n\u2022 Generate FABlib Python code for custom experiments\n\nAll tools have access to your workspace files and FABRIC domain knowledge.',
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
      title: 'Local Artifacts',
      content:
        'The Artifacts view has three tabs: My Artifacts, Published, and Community Marketplace.\n\nThe My Artifacts tab shows artifacts on your machine, organized by category. These include any you\'ve created or downloaded from the marketplace.\n\nEach card shows the artifact name, description, and action buttons.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-marketplace',
      title: 'Marketplace',
      content:
        'The Community Marketplace tab lets you browse artifacts published by the FABRIC community.\n\n\u2022 Search by name or description\n\u2022 Filter by category (Weave, VM Template, Recipe, Notebook)\n\u2022 Filter by tags or author\n\u2022 Sort by popularity, newest, or alphabetically\n\nClick "Get" to download an artifact to your local library.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-weave-types',
      title: 'Understanding Weaves',
      content:
        'A weave can contain any combination of:\n\n\u2022 slice.json \u2014 Topology definition (nodes, networks, boot configs)\n\u2022 deploy.sh \u2014 Deployment script that runs after provisioning\n\u2022 run.sh \u2014 Autonomous experiment script\n\nAction buttons appear based on what the weave contains:\n\u2022 Load/Deploy require slice.json\n\u2022 Deploy also requires deploy.sh\n\u2022 Run requires run.sh\n\u2022 JupyterLab opens the folder for editing',
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
        'To create a weave from an existing slice:\n\n1. Build your topology in the editor\n2. Click "Save as Template" in the toolbar\n3. The weave captures all nodes, networks, site groups, and boot configs\n\nFor a deployable weave, use an AI tool to add a deploy.sh script:\n1. Open the weave folder in JupyterLab\n2. Write deploy.sh with your post-provisioning commands\n3. The weave now has a Deploy button\n\nFor autonomous experiments, add a run.sh script.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-publish',
      title: 'Publishing Artifacts',
      content:
        'Share your artifacts with the FABRIC community:\n\n1. Find your artifact in the My Artifacts tab\n2. Click "Publish" to open the publish dialog\n3. Set visibility (public or project-only), add tags, and write a description\n4. Published artifacts appear in the Community Marketplace for others to use\n\nYou can manage your published artifacts from the Published tab \u2014 update descriptions, add new versions, or unpublish.',
      targetSelector: '.libraries-view',
      requiredView: 'libraries',
      tooltipPosition: 'bottom',
    },
    {
      id: 'aw-side-panel',
      title: 'Artifacts Side Panel',
      content:
        'Back in the Topology view, the Artifacts side panel gives quick access to your library.\n\nThe four tabs (Weaves, VM, Recipes, Notebooks) let you:\n\u2022 Load weaves into the editor\n\u2022 Deploy weaves with one click\n\u2022 Add VM templates to the current slice\n\u2022 Apply recipes to provisioned nodes\n\u2022 Star favorite recipes for the context menu',
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
        'LoomAI includes a full JupyterLab environment running on the backend container. Use it for:\n\n\u2022 Interactive FABlib experiments\n\u2022 Data analysis and visualization\n\u2022 Editing artifact scripts (deploy.sh, run.sh)\n\u2022 Running Jupyter notebooks from the Artifacts library\n\nJupyterLab auto-starts when you first access it and syncs with your app theme.',
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
        'Try it now: go to the Artifacts side panel (in topology view) and click "JupyterLab" on any weave, VM template, or recipe card. This opens that artifact\'s folder directly in JupyterLab.\n\nThis is the easiest way to:\n\u2022 Edit deploy.sh or run.sh scripts\n\u2022 Modify slice.json topology files\n\u2022 Update boot configuration commands\n\u2022 Write and test Jupyter notebooks before publishing\n\nChanges are saved directly to your artifact storage.',
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
// Exports
// ════════════════════════════════════════════════════════════════════

export const tours: Record<string, TourDef> = {
  'getting-started': gettingStarted,
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
  gettingStarted,
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
