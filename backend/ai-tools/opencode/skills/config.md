name: config
description: View and manage FABRIC configuration (project, token, settings)
---
Help the user view and manage their FABRIC configuration.

## Available Tools

- `fabric_get_config` — Show all current settings from fabric_rc
- `fabric_set_config(key, value)` — Set a single config value
- `fabric_load_rc(path)` — Load all settings from a fabric_rc file
- `fabric_list_projects` — List projects from the user's token
- `fabric_set_project(project)` — Set the active project (by name or UUID)

## Common Operations

### View current config
Call `fabric_get_config` to show all settings.

### Change project
1. Call `fabric_list_projects` to see available projects
2. If multiple projects, ask the user which one to use
3. Call `fabric_set_project` with the project name or UUID

### Set token path
Call `fabric_set_config("FABRIC_TOKEN_LOCATION", "/path/to/id_token.json")`

### Load from fabric_rc file
Call `fabric_load_rc("/path/to/fabric_rc")` to import all settings.

### Common settings
| Key | Description |
|-----|-------------|
| `FABRIC_PROJECT_ID` | Active project UUID |
| `FABRIC_TOKEN_LOCATION` | Path to id_token.json |
| `FABRIC_BASTION_HOST` | Bastion hostname |
| `FABRIC_BASTION_USERNAME` | Bastion login username |
| `FABRIC_BASTION_KEY_LOCATION` | Path to bastion SSH key |
| `FABRIC_SLICE_PRIVATE_KEY_FILE` | Slice SSH private key |
| `FABRIC_SLICE_PUBLIC_KEY_FILE` | Slice SSH public key |
| `FABRIC_LOG_LEVEL` | Logging level (INFO, DEBUG, etc.) |
| `FABRIC_AVOID` | Comma-separated sites to avoid |
| `FABRIC_AI_API_KEY` | AI service API key |

Default config directory: `/home/fabric/work/fabric_config/`
Token location: `~/.tokens.json` (primary) or `fabric_config/id_token.json` (FABlib fallback).
Settings are stored in fabric_rc and loaded at startup.
Changes take effect immediately (FABlib is reinitialized).
