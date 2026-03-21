name: reports
description: Query FABRIC usage statistics, project activity, and resource utilization via Reports API
---
Query the FABRIC Reports API for usage statistics and analytics.

**Important:** The `fabric-reports` MCP tools require **FABRIC staff or admin
permissions**. Regular users cannot access them. If a regular user asks for
usage stats, collect data from their slices using FABlib tools instead
(`fabric_list_slices`, `fabric_get_slice`, `fabric_slice_ssh`).

**For staff/admins — use the `fabric-reports` MCP tools:**

### Slices
- `query-slices` — Search slices by state, project, user, date range
  - Filter by: `state`, `project_uuid`, `user_id`, `start_date`, `end_date`
  - Returns: slice name, state, created, expires, node count

### Slivers (individual resources)
- `query-slivers` — Search slivers by site, slice, component type
  - Filter by: `site`, `slice_id`, `component_type`, `state`
  - Returns: sliver details, host, site, resource allocation

### Projects
- `query-projects` — List projects with activity metrics
- `query-project-memberships` — Who belongs to which projects

### Users
- `query-users` — Search users by name, email, or ID
- `query-user-memberships` — User's project memberships and roles

### Sites
- `query-sites` — Site information and status

### Common Queries
- "How many active slices do I have?" → `query-slices` with user filter + state=Active
- "What's running at STAR?" → `query-slivers` with site=STAR
- "Who's in my project?" → `query-project-memberships` with project UUID
- "Show my resource usage this month" → `query-slivers` with date range

**Present results** as formatted tables. Summarize totals (slice count, node count,
resource hours). If no results, check: correct project selected? token valid?
date range reasonable?
