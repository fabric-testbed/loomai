# Create a Tutorial Notebook

Create a Jupyter notebook tutorial for a FABRIC weave artifact, using consistent
FABRIC branding that works in both JupyterLab light and dark mode.

## Input

The user provides: $ARGUMENTS (what the tutorial should teach, and which weave it belongs to)

## Process

1. **Identify the target weave** — find the artifact directory under `/home/fabric/work/my_artifacts/`.
   Read `weave.json` and any Python scripts to understand what the weave does.

2. **Plan the notebook cells** — design a logical flow:
   - What concepts need explaining?
   - What code cells demonstrate the weave's features?
   - What "What just happened?" explanations are needed?

3. **Write the `.ipynb` file** in the weave's artifact directory.

## FABRIC Branding Standards

All tutorial notebooks MUST use these exact styles for visual consistency.

### Official FABRIC Colors
- **Primary Blue:** `#3182CE`
- **Dark Blue:** `#2B6CB0`
- **Header Blue:** `#2358a1`
- **Link Blue:** `#5798bc`
- **Font:** Roboto, sans-serif
- **Logo:** `https://learn.fabric-testbed.net/wp-content/uploads/2023/10/2019_NRIG_Fabric-dark-text-right.png`

### Dark/Light Mode Rules
- **NEVER** use hardcoded light-mode background colors like `#e3f2fd`, `#f0f7ff`, `white`, etc.
- **NEVER** use hardcoded text colors like `#333`, `#595959`, `black` on markdown content (use default/inherited text color)
- **OK** to use `color: #3182CE` on headings — this FABRIC blue is readable on both dark and light backgrounds
- **OK** to use `color: white` ONLY inside dark gradient containers
- For callout/info boxes: use **border-only** styling (no background color)
- For the title banner: the dark gradient background works in both modes

### Required Cell Structure

Every tutorial notebook follows this structure:

#### Cell 1: Title Banner (markdown)
```html
<div style="background: linear-gradient(135deg, #2B6CB0 0%, #3182CE 100%); padding: 30px; border-radius: 10px; color: white; margin-bottom: 20px;">
<img src="https://learn.fabric-testbed.net/wp-content/uploads/2023/10/2019_NRIG_Fabric-dark-text-right.png" alt="FABRIC" style="height: 40px; filter: brightness(0) invert(1); margin-bottom: 12px;" />
<h1 style="color: white; margin: 0; font-family: Roboto, sans-serif;">TITLE HERE</h1>
<p style="font-size: 1.1em; margin: 10px 0 0 0; opacity: 0.9; font-family: Roboto, sans-serif;">Subtitle description here &mdash; powered by LoomAI</p>
</div>

Brief intro paragraph.

> **Prerequisite:** Deploy the **WEAVE NAME** weave first by clicking
> **Run** in the LoomAI Artifacts panel. This notebook assumes the slice
> is already in the `StableOK` state.
```

#### Cell 2+: Concept Explanations (markdown)
Standard markdown — no special styling needed. Use `##` headings.

#### Step Cells: Section Headers (markdown)
```html
<h2 style="color: #3182CE; font-family: Roboto, sans-serif;">Step N: Title</h2>

Explanation text here using standard markdown.
```

#### Code Cells
Standard Python code cells. Always include:
- A brief comment explaining what the code does
- Print output so the user sees results

#### "What Just Happened?" Cells (markdown)
Standard `### What Just Happened?` heading followed by a numbered list explanation.
No special styling — use default markdown.

#### Final Cell: Next Steps (markdown)
```html
---

<div style="border: 2px solid #3182CE; border-left: 5px solid #3182CE; padding: 20px; border-radius: 8px;">

<h2 style="color: #3182CE; margin-top: 0; font-family: Roboto, sans-serif;">Next Steps</h2>

Bullet list of suggestions...

</div>
```

## Common Code Patterns

### Import FABlib
```python
from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()
```

### Get a slice
```python
my_slice = fablib.get_slice(name=slice_name)
```

### Run command on a node
```python
stdout, stderr = node.execute('command here')
print(stdout)
```

### List nodes
```python
for node in my_slice.get_nodes():
    print(f"Node: {node.get_name()}, Site: {node.get_site()}")
```

## Reference

Study the canonical example at:
`/home/fabric/work/my_artifacts/Hello_FABRIC/hello_fabric.ipynb`

## Verification

After creating the notebook:
1. Validate JSON: `python3 -c "import json; json.load(open('FILENAME.ipynb'))"`
2. Check for hardcoded light-mode colors — there should be NONE
3. Confirm no `background:` on any div except the title gradient banner
4. Read back the file to verify it's complete
