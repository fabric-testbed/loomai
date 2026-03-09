name: init-project
description: Initialize a new project directory with standard structure
---
Create a new project directory with a standard structure for FABRIC experiments.

1. **Ask or infer** the project name and type (if not specified in the user's message).

2. **Create the project structure**:
   ```
   <project-name>/
     README.md              # Project description and instructions
     requirements.txt       # Python dependencies (if needed)
     scripts/               # Automation and setup scripts
     data/                  # Data files and results
     notebooks/             # Jupyter notebooks (if applicable)
   ```

3. **Write README.md** with:
   - Project title and description
   - Prerequisites (FABRIC account, project membership)
   - Quick start instructions
   - File structure description

4. **Verify**: List the created directory structure.

Create at `/home/fabric/work/<project-name>/`.
