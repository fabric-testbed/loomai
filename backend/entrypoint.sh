#!/bin/bash
# Entrypoint script for the LoomAI backend container.
# If FABLIB_BRANCH env var is set at runtime and differs from the branch
# baked into the image, reinstall fabrictestbed-extensions from that branch.

if [ -n "$FABLIB_BRANCH" ] && [ "$FABLIB_BRANCH" != "$FABLIB_BRANCH_BUILD" ]; then
    echo "==> Runtime FABlib branch override: $FABLIB_BRANCH (image was built with: $FABLIB_BRANCH_BUILD)"
    pip install --no-cache-dir --force-reinstall \
        "fabrictestbed-extensions @ git+https://github.com/fabric-testbed/fabrictestbed-extensions.git@${FABLIB_BRANCH}"
fi

exec "$@"
