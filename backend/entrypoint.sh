#!/bin/bash
# Entrypoint script for the LoomAI backend container.
# If FABLIB_BRANCH env var is set at runtime and differs from the branch
# baked into the image, reinstall fabrictestbed-extensions from that branch.

if [ -n "$FABLIB_BRANCH" ] && [ "$FABLIB_BRANCH" != "$FABLIB_BRANCH_BUILD" ]; then
    echo "==> Runtime FABlib branch override: $FABLIB_BRANCH (image was built with: $FABLIB_BRANCH_BUILD)"
    pip install --no-cache-dir --force-reinstall \
        "fabrictestbed-extensions @ git+https://github.com/fabric-testbed/fabrictestbed-extensions.git@${FABLIB_BRANCH}"
fi

# Start JupyterLab as a background daemon so it's available with the
# container (frontend opens /jupyter/lab in a new tab — no on-demand start).
JUPYTER_PORT="${LOOMAI_JUPYTER_PORT:-8889}"
JUPYTER_WORKDIR="${FABRIC_STORAGE_DIR:-/home/fabric/work}"
JUPYTER_BASE_URL="${LOOMAI_BASE_PATH:+${LOOMAI_BASE_PATH}}/jupyter/"
mkdir -p "$JUPYTER_WORKDIR" 2>/dev/null || true
echo "==> Starting JupyterLab on :${JUPYTER_PORT} (base_url=${JUPYTER_BASE_URL}, root=${JUPYTER_WORKDIR})"
(
    cd "$JUPYTER_WORKDIR" && exec jupyter lab \
        --no-browser \
        --ip=0.0.0.0 \
        --port="$JUPYTER_PORT" \
        --ServerApp.token= \
        --ServerApp.password= \
        --ServerApp.disable_check_xsrf=True \
        --ServerApp.allow_origin='*' \
        --ServerApp.allow_remote_access=True \
        --ServerApp.base_url="$JUPYTER_BASE_URL" \
        --ServerApp.root_dir="$JUPYTER_WORKDIR" \
        --ServerApp.terminado_settings="{'shell_command': ['/bin/bash']}" \
        >/tmp/jupyterlab.log 2>&1
) &

exec "$@"
