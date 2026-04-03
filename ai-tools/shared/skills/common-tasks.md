name: common-tasks
description: Step-by-step recipes for frequent FABRIC operations
---
Quick recipes for the most common FABRIC tasks. Use `loomai` CLI commands
or the equivalent tool calls.

## Create and Deploy a Simple Slice

```bash
loomai slices create my-exp
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai slices submit my-exp --wait --timeout 600
loomai slices slivers my-exp    # Verify nodes are Active
loomai ssh my-exp node1 -- hostname
```

## Create a Multi-Node Cluster with Networking

```bash
loomai slices create cluster
loomai nodes add cluster node1 --site RENC --cores 4 --ram 16 --disk 50
loomai nodes add cluster node2 --site RENC --cores 4 --ram 16 --disk 50
loomai components add cluster node1 nic1 --model NIC_Basic
loomai components add cluster node2 nic1 --model NIC_Basic
loomai networks add cluster net1 --type L2Bridge -i node1-nic1-p1,node2-nic1-p1
loomai slices validate cluster
loomai slices submit cluster --wait
```

## Deploy a GPU Experiment

```bash
loomai sites find --gpu GPU_RTX6000          # Find GPU sites
loomai slices create gpu-exp
loomai nodes add gpu-exp gpu-node --site RENC --cores 8 --ram 32 --disk 100
loomai components add gpu-exp gpu-node gpu1 --model GPU_RTX6000
loomai slices submit gpu-exp --wait
loomai ssh gpu-exp gpu-node -- "nvidia-smi"   # Verify GPU
```

## Install Software on All Nodes

```bash
loomai exec my-exp "sudo apt-get update -qq" --all --parallel
loomai exec my-exp "sudo apt-get install -y -qq docker.io" --all --parallel
loomai exec my-exp "docker --version" --all   # Verify
```

## Upload Files to All Nodes

```bash
loomai scp my-exp ./setup.sh /tmp/setup.sh --all --parallel
loomai exec my-exp "bash /tmp/setup.sh" --all --parallel
```

## Collect Data from All Nodes

```bash
# Download from each node (serial — files go to different local paths)
loomai ssh my-exp node1 -- "cat /tmp/results.csv" > node1-results.csv
loomai ssh my-exp node2 -- "cat /tmp/results.csv" > node2-results.csv
```

## Run a Weave Experiment

```bash
loomai weaves list                                          # Browse
loomai weaves run Hello_FABRIC --args SLICE_NAME=my-hello   # Start
loomai weaves runs --status running                         # Check
loomai weaves logs <run-id> --follow                        # Watch output
```

## Find Available Resources

```bash
loomai sites list --available                     # All active sites
loomai sites find --cores 8 --ram 32              # Specific requirements
loomai sites find --gpu GPU_RTX6000               # GPU sites
loomai sites hosts RENC                           # Per-host at a site
loomai images                                     # VM images
loomai component-models                           # Hardware models
```

## Manage Slice Lifecycle

```bash
loomai slices renew my-exp --days 7               # Extend lease
loomai slices refresh my-exp                      # Force refresh from FABRIC
loomai slices clone my-exp --new-name my-exp-v2   # Clone
loomai slices export my-exp -o slice.json         # Export topology
loomai slices delete my-exp --force               # Delete
```

## Browse and Get Marketplace Artifacts

```bash
loomai artifacts list --remote                    # Browse all
loomai artifacts search "iperf" --tags networking # Search
loomai artifacts show <uuid>                      # Details
loomai artifacts get <uuid> --name My_Weave       # Download
```

## Publish a Weave

```bash
loomai artifacts publish My_Weave \
  --title "My Experiment" \
  --description "A network benchmarking weave" \
  --tags networking,benchmark
```

## Delete All Dead Slices

```bash
loomai slices list --state Dead                   # See what's dead
loomai slices delete <name> --force               # Delete each one
```
