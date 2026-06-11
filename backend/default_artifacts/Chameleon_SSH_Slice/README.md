# Chameleon SSH Slice

This weave creates a LoomAI Chameleon slice record, deploys one Chameleon bare-metal node, and associates a floating IP so you can SSH directly to it. It uses Chameleon OpenStack APIs directly for the resources: Keystone, Blazar, Nova, and Neutron.

As resources are created, their OpenStack IDs are attached to the Chameleon slice record with the LoomAI Chameleon slice API. That makes the lease, instance, and floating IP visible and manageable from the slice view.

The helper talks to the LoomAI backend through `LOOMAI_API_URL` or `LOOMAI_URL`
when set, otherwise it defaults to `http://localhost:8000/api`. If this weave is
run outside the backend container, set the URL for that network namespace:
`http://127.0.0.1:8000` on the Docker host, `http://backend:8000` from another
docker-compose service, or the published backend URL in a remote environment.

Defaults:

- Site: `auto` (tries common bare-metal Chameleon sites)
- Node type: `auto` (tries `compute_cascadelake_r` first, then other common compute pools)
- Image: `CC-Ubuntu22.04`
- SSH user: `cc`
- Lease duration: `4` hours

When the weave is ready, the build log prints:

```bash
ssh cc@<floating-ip>
```

Click Stop in LoomAI to release the floating IP, delete the instance, delete the lease, remove the slice record, and remove the local state.
