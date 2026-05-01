"""Kubernetes pod lifecycle management for single-user LoomAI instances."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubernetes_asyncio.client import ApiException

from app.config import settings
from app.spawner.pod_template import build_pod_manifest, sanitize_username

logger = logging.getLogger(__name__)

_k8s_initialized = False


async def _ensure_k8s_client() -> None:
    """Initialize the kubernetes_asyncio client (in-cluster or kubeconfig)."""
    global _k8s_initialized
    if _k8s_initialized:
        return
    try:
        k8s_config.load_incluster_config()
        logger.info("Loaded in-cluster K8s config")
    except k8s_config.ConfigException:
        try:
            await k8s_config.load_kube_config()
            logger.info("Loaded kubeconfig")
        except Exception:
            logger.warning("No K8s config available; spawner calls will fail")
    _k8s_initialized = True


async def create_token_secret(username: str, token_data: dict[str, Any]) -> str:
    """Create or update a K8s Secret with FABRIC token data.

    Args:
        username: Hub username.
        token_data: Dict with token fields to store as id_token.json.

    Returns:
        The secret name.
    """
    await _ensure_k8s_client()

    safe_name = sanitize_username(username)
    secret_name = f"loomai-tokens-{safe_name}"
    namespace = settings.K8S_NAMESPACE

    import base64

    # Store id_token and refresh_token as separate secret keys
    secret_data = {}
    id_token = token_data.get("cilogon_id_token", "")
    refresh_token = token_data.get("cilogon_refresh_token", "")
    if id_token:
        secret_data["CILOGON_ID_TOKEN"] = base64.b64encode(id_token.encode()).decode()
    if refresh_token:
        secret_data["CILOGON_REFRESH_TOKEN"] = base64.b64encode(refresh_token.encode()).decode()

    secret = k8s_client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=k8s_client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={
                "app": "loomai",
                "component": "user-tokens",
                "hub.loomai.io/username": safe_name,
            },
        ),
        type="Opaque",
        data=secret_data,
    )

    core_v1 = k8s_client.CoreV1Api()
    try:
        await core_v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        # Exists — replace
        await core_v1.replace_namespaced_secret(
            name=secret_name, namespace=namespace, body=secret
        )
        logger.info("Updated token secret %s", secret_name)
    except ApiException as e:
        if e.status == 404:
            await core_v1.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info("Created token secret %s", secret_name)
        else:
            raise

    return secret_name


async def spawn_user_pod(
    username: str,
    token_secret_name: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Create a pod and headless service for a user.

    Args:
        username: Hub username.
        token_secret_name: K8s Secret name for FABRIC tokens.
        config: Optional overrides (image, cpu_limit, etc.).

    Returns:
        The pod name.
    """
    await _ensure_k8s_client()

    config = config or {}
    safe_name = sanitize_username(username)
    pod_name = f"loomai-{safe_name}"
    namespace = settings.K8S_NAMESPACE

    image = config.get("image", settings.SINGLEUSER_IMAGE)
    resources = {
        "cpu_limit": config.get("cpu_limit", settings.SINGLEUSER_CPU_LIMIT),
        "mem_limit": config.get("mem_limit", settings.SINGLEUSER_MEM_LIMIT),
        "cpu_request": config.get("cpu_request", settings.SINGLEUSER_CPU_REQUEST),
        "mem_request": config.get("mem_request", settings.SINGLEUSER_MEM_REQUEST),
    }
    storage_pvc = config.get("pvc_name", f"loomai-user-{safe_name}")

    pod = build_pod_manifest(
        username=username,
        image=image,
        resources=resources,
        token_secret_name=token_secret_name,
        storage_pvc=storage_pvc,
        extra_env=config.get("extra_env"),
    )

    core_v1 = k8s_client.CoreV1Api()

    # Create pod (delete stale pod first if it exists)
    try:
        await core_v1.create_namespaced_pod(namespace=namespace, body=pod)
        logger.info("Created pod %s", pod_name)
    except ApiException as e:
        if e.status == 409:
            logger.info("Pod %s already exists — deleting and recreating", pod_name)
            try:
                await core_v1.delete_namespaced_pod(
                    name=pod_name, namespace=namespace, grace_period_seconds=0,
                )
                # Wait for pod to be fully removed
                for _ in range(30):
                    try:
                        await core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                        await asyncio.sleep(1)
                    except ApiException as e2:
                        if e2.status == 404:
                            break
                        raise
                await core_v1.create_namespaced_pod(namespace=namespace, body=pod)
                logger.info("Recreated pod %s", pod_name)
            except Exception as e2:
                logger.error("Failed to recreate pod %s: %s", pod_name, e2)
                raise
        else:
            logger.error("Failed to create pod %s: %s", pod_name, e)
            raise

    # Create headless service so CHP can route to it by DNS name
    service = k8s_client.V1Service(
        api_version="v1",
        kind="Service",
        metadata=k8s_client.V1ObjectMeta(
            name=pod_name,
            namespace=namespace,
            labels={
                "app": "loomai",
                "component": "singleuser",
                "hub.loomai.io/username": safe_name,
            },
        ),
        spec=k8s_client.V1ServiceSpec(
            selector={"hub.loomai.io/username": safe_name},
            ports=[
                k8s_client.V1ServicePort(
                    name="http",
                    port=3000,
                    target_port=3000,
                )
            ],
            type="ClusterIP",
        ),
    )

    try:
        await core_v1.create_namespaced_service(namespace=namespace, body=service)
        logger.info("Created service %s", pod_name)
    except ApiException as e:
        if e.status == 409:
            logger.info("Service %s already exists", pod_name)
        else:
            logger.error("Failed to create service %s: %s", pod_name, e)
            raise

    return pod_name


async def stop_user_pod(username: str) -> None:
    """Delete the pod and service for a user.

    Args:
        username: Hub username.
    """
    await _ensure_k8s_client()

    safe_name = sanitize_username(username)
    pod_name = f"loomai-{safe_name}"
    namespace = settings.K8S_NAMESPACE

    core_v1 = k8s_client.CoreV1Api()

    # Delete pod
    try:
        await core_v1.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            grace_period_seconds=30,
        )
        logger.info("Deleted pod %s", pod_name)
    except ApiException as e:
        if e.status == 404:
            logger.info("Pod %s already gone", pod_name)
        else:
            logger.error("Failed to delete pod %s: %s", pod_name, e)
            raise

    # Delete service
    try:
        await core_v1.delete_namespaced_service(name=pod_name, namespace=namespace)
        logger.info("Deleted service %s", pod_name)
    except ApiException as e:
        if e.status == 404:
            logger.info("Service %s already gone", pod_name)
        else:
            logger.error("Failed to delete service %s: %s", pod_name, e)


async def get_pod_status(username: str) -> dict[str, Any]:
    """Get the current status of a user's pod.

    Args:
        username: Hub username.

    Returns:
        Dict with phase, ready, message, and pod_ip.
    """
    await _ensure_k8s_client()

    safe_name = sanitize_username(username)
    pod_name = f"loomai-{safe_name}"
    namespace = settings.K8S_NAMESPACE

    core_v1 = k8s_client.CoreV1Api()

    try:
        pod = await core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            return {"phase": "NotFound", "ready": False, "message": "Pod not found", "pod_ip": None}
        raise

    phase = pod.status.phase if pod.status else "Unknown"
    ready = False
    if pod.status and pod.status.conditions:
        for cond in pod.status.conditions:
            if cond.type == "Ready" and cond.status == "True":
                ready = True
                break

    pod_ip = pod.status.pod_ip if pod.status else None
    message = ""
    if pod.status and pod.status.container_statuses:
        cs = pod.status.container_statuses[0]
        if cs.state and cs.state.waiting:
            message = cs.state.waiting.reason or ""
        elif cs.state and cs.state.terminated:
            message = cs.state.terminated.reason or ""

    return {
        "phase": phase,
        "ready": ready,
        "message": message,
        "pod_ip": pod_ip,
    }


async def wait_for_pod_ready(username: str, timeout: int | None = None) -> bool:
    """Poll until the user's pod is ready or timeout.

    Args:
        username: Hub username.
        timeout: Seconds to wait. Defaults to settings.SINGLEUSER_START_TIMEOUT.

    Returns:
        True if pod became ready, False if timed out.
    """
    timeout = timeout or settings.SINGLEUSER_START_TIMEOUT
    elapsed = 0
    interval = 3

    while elapsed < timeout:
        status = await get_pod_status(username)
        if status["ready"]:
            return True
        if status["phase"] in ("Failed", "Unknown"):
            logger.error("Pod for %s entered %s: %s", username, status["phase"], status["message"])
            return False
        await asyncio.sleep(interval)
        elapsed += interval

    logger.warning("Timeout waiting for pod %s after %ds", username, timeout)
    return False
