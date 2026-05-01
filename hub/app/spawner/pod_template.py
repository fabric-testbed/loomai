"""Build Kubernetes pod manifests for single-user LoomAI pods."""

from __future__ import annotations

import re
from typing import Any

from kubernetes_asyncio.client import (
    V1Container,
    V1ContainerPort,
    V1EnvVar,
    V1EnvVarSource,
    V1HTTPGetAction,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1Probe,
    V1ResourceRequirements,
    V1SecretKeySelector,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
    V1PersistentVolumeClaimVolumeSource,
)

from app.config import settings


def sanitize_username(username: str) -> str:
    """Sanitize a username for use in K8s resource names.

    K8s names must be lowercase alphanumeric, hyphens, dots — max 63 chars.
    """
    safe = re.sub(r"[^a-z0-9\-]", "-", username.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe[:63]


def build_pod_manifest(
    username: str,
    image: str,
    resources: dict[str, str],
    token_secret_name: str,
    storage_pvc: str,
    extra_env: dict[str, str] | None = None,
) -> V1Pod:
    """Build a V1Pod manifest for a single-user LoomAI instance.

    Args:
        username: Hub username (FABRIC UUID).
        image: Container image to run.
        resources: Dict with cpu_limit, mem_limit, cpu_request, mem_request.
        token_secret_name: Name of the K8s Secret holding CILogon tokens.
        storage_pvc: Name of the PVC for user storage.
        extra_env: Additional environment variables.

    Returns:
        V1Pod object ready to create.
    """
    safe_name = sanitize_username(username)
    pod_name = f"loomai-{safe_name}"

    labels = {
        "app": "loomai",
        "component": "singleuser",
        "hub.loomai.io/username": safe_name,
    }

    # Base path for sub-path routing (CHP routes /user/{username}/ to this pod)
    base_path = f"/user/{safe_name}"

    # Environment variables
    env_vars = [
        V1EnvVar(name="FABRIC_CREDMGR_HOST", value=f"https://{settings.FABRIC_CM_HOST}"),
        V1EnvVar(name="FABRIC_ORCHESTRATOR_HOST", value=f"https://{settings.FABRIC_ORCHESTRATOR_HOST}"),
        V1EnvVar(name="FABRIC_CORE_API_HOST", value=settings.FABRIC_CORE_API_HOST),
        V1EnvVar(name="FABRIC_BASTION_HOST", value=settings.FABRIC_BASTION_HOST),
        V1EnvVar(name="FABRIC_CONFIG_DIR", value="/home/fabric/work/fabric_config"),
        V1EnvVar(name="FABRIC_TOKEN_LOCATION", value="/home/fabric/work/fabric_config/id_token.json"),
        V1EnvVar(name="LOOMAI_BASE_PATH", value=base_path),
        # CILogon tokens injected from K8s Secret
        V1EnvVar(
            name="CILOGON_ID_TOKEN",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=token_secret_name,
                    key="CILOGON_ID_TOKEN",
                    optional=True,
                ),
            ),
        ),
        V1EnvVar(
            name="CILOGON_REFRESH_TOKEN",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=token_secret_name,
                    key="CILOGON_REFRESH_TOKEN",
                    optional=True,
                ),
            ),
        ),
    ]
    if extra_env:
        for k, v in extra_env.items():
            env_vars.append(V1EnvVar(name=k, value=v))

    # Volume mounts — only the user storage PVC
    volume_mounts = [
        V1VolumeMount(
            name="user-storage",
            mount_path="/home/fabric/work",
        ),
    ]

    # Volumes
    volumes = [
        V1Volume(
            name="user-storage",
            persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                claim_name=storage_pvc,
            ),
        ),
    ]

    # Readiness probe — check backend directly on port 8000
    readiness_probe = V1Probe(
        http_get=V1HTTPGetAction(
            path="/api/health",
            port=8000,
        ),
        initial_delay_seconds=10,
        period_seconds=5,
        timeout_seconds=3,
        failure_threshold=30,
    )

    # Container — expose port 3000 (nginx serves frontend + proxies /api to backend)
    container = V1Container(
        name="loomai",
        image=image,
        ports=[V1ContainerPort(container_port=3000, name="http")],
        env=env_vars,
        volume_mounts=volume_mounts,
        readiness_probe=readiness_probe,
        security_context=V1SecurityContext(
            allow_privilege_escalation=settings.SINGLEUSER_ALLOW_PRIVILEGE_ESCALATION,
        ),
        resources=V1ResourceRequirements(
            requests={
                "cpu": resources.get("cpu_request", settings.SINGLEUSER_CPU_REQUEST),
                "memory": resources.get("mem_request", settings.SINGLEUSER_MEM_REQUEST),
            },
            limits={
                "cpu": resources.get("cpu_limit", settings.SINGLEUSER_CPU_LIMIT),
                "memory": resources.get("mem_limit", settings.SINGLEUSER_MEM_LIMIT),
            },
        ),
    )

    pod = V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=V1ObjectMeta(
            name=pod_name,
            namespace=settings.K8S_NAMESPACE,
            labels=labels,
        ),
        spec=V1PodSpec(
            containers=[container],
            volumes=volumes,
            restart_policy="Never",
            automount_service_account_token=False,
        ),
    )

    return pod
