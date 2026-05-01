"""Kubernetes PVC management for user storage."""

from __future__ import annotations

import logging

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import ApiException

from app.config import settings
from app.spawner.kubespawner import _ensure_k8s_client
from app.spawner.pod_template import sanitize_username

logger = logging.getLogger(__name__)


async def ensure_user_pvc(
    username: str,
    capacity: str | None = None,
    storage_class: str | None = None,
) -> str:
    """Create a PVC for the user if it doesn't already exist.

    Args:
        username: Hub username (FABRIC UUID).
        capacity: Storage capacity (e.g. "10Gi"). Defaults to settings.
        storage_class: K8s storage class name. Defaults to settings.

    Returns:
        The PVC name.
    """
    await _ensure_k8s_client()

    safe_name = sanitize_username(username)
    pvc_name = f"loomai-user-{safe_name}"
    namespace = settings.K8S_NAMESPACE
    capacity = capacity or settings.SINGLEUSER_STORAGE_CAPACITY
    storage_class = storage_class or settings.SINGLEUSER_STORAGE_CLASS or None

    core_v1 = k8s_client.CoreV1Api()

    # Check if PVC already exists
    try:
        await core_v1.read_namespaced_persistent_volume_claim(
            name=pvc_name, namespace=namespace
        )
        logger.info("PVC %s already exists", pvc_name)
        return pvc_name
    except ApiException as e:
        if e.status != 404:
            logger.error("Error checking PVC %s: %s", pvc_name, e)
            raise

    # Create PVC
    pvc_manifest = k8s_client.V1PersistentVolumeClaim(
        api_version="v1",
        kind="PersistentVolumeClaim",
        metadata=k8s_client.V1ObjectMeta(
            name=pvc_name,
            namespace=namespace,
            labels={
                "app": "loomai",
                "component": "user-storage",
                "hub.loomai.io/username": safe_name,
            },
        ),
        spec=k8s_client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=k8s_client.V1VolumeResourceRequirements(
                requests={"storage": capacity},
            ),
            storage_class_name=storage_class,
        ),
    )

    try:
        await core_v1.create_namespaced_persistent_volume_claim(
            namespace=namespace, body=pvc_manifest
        )
        logger.info("Created PVC %s (%s, class=%s)", pvc_name, capacity, storage_class)
    except ApiException as e:
        if e.status == 409:
            logger.info("PVC %s was created concurrently", pvc_name)
        else:
            logger.error("Failed to create PVC %s: %s", pvc_name, e)
            raise

    return pvc_name
