name: eval-ai-tools
description: Evaluate, fix, or create AI skills, agents, and configuration for all three AI tools
---
Manage the AI tool configuration for all three tools in this environment:
OpenCode (skills, agents), Aider (.aider.conf.yml), and Claude Code (CLAUDE.md).

**Parse the user's intent from their arguments:**
- No args or "evaluate" → **Evaluate** (report only)
- "fix" or "fix <name>" → **Fix** (evaluate then edit files)
- "create <name>" → **Create** (write a new skill or agent)
- "aider" → focus on Aider config
- "claude" or "claude-code" → focus on Claude Code config

## Evaluate

1. **Inventory** all assets across all three tools:
   ```bash
   echo "=== OpenCode Skills ===" && ls /home/fabric/work/.opencode/skills/
   echo "=== OpenCode Agents ===" && ls /home/fabric/work/.opencode/agent-prompts/
   echo "=== Aider ===" && cat /home/fabric/work/.aider.conf.yml 2>/dev/null || echo "NOT FOUND"
   echo "=== Claude Code ===" && cat /home/fabric/work/CLAUDE.md 2>/dev/null || echo "NOT FOUND"
   echo "=== Shared Context ===" && wc -l /home/fabric/work/AGENTS.md
   ```

2. **Read every file** in scope. Note name, description, line count, tools referenced.

3. **Score** each on tool-specific criteria:
   - **OpenCode skills**: trigger clarity, tool awareness, error handling, token efficiency
   - **OpenCode agents**: persona clarity, domain depth, tool listings, workflow structure
   - **Aider config**: read files set, ignore patterns, behavior flags, no MCP refs
   - **Claude Code**: FABlib tool references, container paths, workflow patterns, conciseness
   Rate: Strong / Adequate / Weak.

4. **Find gaps** — common FABRIC tasks with no coverage:
   modify slice, renew lease, boot config, facility ports,
   clone/export, multi-site coordination, experiment analysis.

5. **Report** — summary table + prioritized recommendations.

## Fix

1. Run the **Evaluate** steps above.
2. For each Weak or broken asset, edit the file directly:
   - OpenCode skills: `/home/fabric/work/.opencode/skills/<name>/SKILL.md`
   - OpenCode agents: `/home/fabric/work/.opencode/agent-prompts/<name>.md`
   - Aider config: `/home/fabric/work/.aider.conf.yml`
   - Claude Code: `/home/fabric/work/CLAUDE.md`
3. Follow these rules:
   - OpenCode skills: 30–60 lines, reference AGENTS.md for domain knowledge
   - OpenCode agents: 40–120 lines, clear persona, list tools, structured workflow
   - Aider: no MCP references (not supported), context via `read:` files only
   - Claude Code: under 95 lines, reference AGENTS.md, list FABlib tools (not MCP fabric-api)
   - Never break frontmatter format
4. Re-read each modified file to confirm correctness.
5. Report changes with before/after summary.

## Create

1. Determine type: OpenCode skill, OpenCode agent, or config enhancement.
2. Read existing assets to avoid overlap.
3. Write the file following the standards above.
4. Verify by re-reading.
5. Report the new file and integration notes.
