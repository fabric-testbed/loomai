name: jupyter
description: Create a Jupyter notebook for FABRIC experiments (saves as artifact)
---
Create a Jupyter notebook (.ipynb) for FABRIC experiments. Notebooks saved
as artifacts appear in the WebUI Libraries panel and can be opened in JupyterLab.

1. **Understand the goal**: What experiment or analysis? What should the notebook demonstrate?

2. **Create the artifact directory**:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   mkdir -p "$ARTIFACTS_DIR/<Notebook_Name>"
   ```

3. **Create the notebook** with:
   - Title and description in a markdown cell
   - Import cells (FABlib, pandas, matplotlib, etc.)
   - Step-by-step cells with markdown explanations
   - Code cells for slice creation, data collection, analysis
   - Cleanup cell at the end (delete slice)

4. **Notebook JSON structure** (.ipynb format):
   ```json
   {
     "cells": [
       {
         "cell_type": "markdown",
         "metadata": {},
         "source": ["# Title\n", "Description"]
       },
       {
         "cell_type": "code",
         "metadata": {},
         "source": ["from fabrictestbed_extensions.fablib.fablib import FablibManager\n", "fablib = FablibManager()"],
         "execution_count": null,
         "outputs": []
       }
     ],
     "metadata": {
       "kernelspec": {
         "display_name": "Python 3",
         "language": "python",
         "name": "python3"
       },
       "language_info": {
         "name": "python",
         "version": "3.11.0"
       }
     },
     "nbformat": 4,
     "nbformat_minor": 5
   }
   ```

5. **Optional metadata.json** for display name and description:
   ```json
   {
     "name": "My Experiment Notebook",
     "description": "Measures bandwidth across FABRIC sites",
     "order": 99
   }
   ```

6. **Save** the `.ipynb` file to `$ARTIFACTS_DIR/<Notebook_Name>/`.
   The notebook appears in the WebUI Libraries panel immediately.

7. **Open in JupyterLab**: Start JupyterLab via
   `curl -X POST http://localhost:8000/api/jupyter/start`, then open at
   `/jupyter/lab/tree/my_artifacts/<Notebook_Name>`.

**Common FABlib patterns for notebooks:**
```python
# Create and submit a slice
slice = fablib.new_slice(name="experiment")
node = slice.add_node(name="n1", site="STAR", cores=4, ram=16, disk=50)
slice.submit()
slice.wait_ssh(progress=True)

# Run experiment
stdout, stderr = node.execute("iperf3 -s -D")

# Collect results
node.download_file("~/results.csv", "results.csv")

# Cleanup
slice.delete()
```
