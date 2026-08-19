"""Static validation for LoomAI local artifact directories.

The validator is intentionally read-only and dependency-light.  It checks the
artifact contract that agents commonly get wrong before an artifact is run or
published, without trying to execute user scripts.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Mapping


MARKER_FILES = ("weave.json", "vm-template.json", "recipe.json")
SCRIPT_DIRS = ("tools", "scripts", "node_tools")
ALLOWED_ARG_TYPES = {"string", "number", "boolean", "select"}


@dataclass(frozen=True)
class ArtifactValidationFinding:
    severity: str
    path: str
    message: str
    fix_hint: str
    line: int | None = None
    code: str = ""

    def to_api(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "fix-hint": self.fix_hint,
        }
        if self.line is not None:
            item["line"] = self.line
        if self.code:
            item["code"] = self.code
        return item


def read_artifact_files(artifact_dir: str) -> dict[str, str]:
    """Read validation-relevant files from an artifact directory."""
    files: dict[str, str] = {}
    for filename in MARKER_FILES + ("weave.sh", ".weaveignore"):
        _read_if_file(artifact_dir, filename, files)

    for entry in sorted(os.listdir(artifact_dir)):
        rel = entry
        full = os.path.join(artifact_dir, rel)
        if os.path.isfile(full) and _looks_like_script(rel):
            _read_if_file(artifact_dir, rel, files)

    for directory in SCRIPT_DIRS:
        root = os.path.join(artifact_dir, directory)
        if not os.path.isdir(root):
            continue
        for current_root, _, names in os.walk(root):
            for name in sorted(names):
                full = os.path.join(current_root, name)
                rel = os.path.relpath(full, artifact_dir)
                if _looks_like_script(rel):
                    _read_if_file(artifact_dir, rel, files)
    return files


def validate_artifact_files(
    files: Mapping[str, str],
    *,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an artifact represented as a relative path -> text mapping."""
    normalized = {
        _normalize_rel_path(path): str(content)
        for path, content in files.items()
        if path and content is not None
    }
    findings: list[ArtifactValidationFinding] = []
    parsed: dict[str, Any] = {}

    marker_files = [path for path in MARKER_FILES if path in normalized]
    if not marker_files:
        findings.append(_finding(
            "error",
            ".",
            "Artifact has no recognized marker file.",
            "Add exactly one appropriate marker file: weave.json, vm-template.json, or recipe.json.",
            code="ARTIFACT_MARKER_MISSING",
        ))
    elif len(marker_files) > 1:
        findings.append(_finding(
            "warning",
            ".",
            f"Artifact has multiple marker files: {', '.join(marker_files)}.",
            "Keep only the marker file for the artifact category unless this is an intentional compatibility artifact.",
            code="ARTIFACT_MULTIPLE_MARKERS",
        ))

    for marker in marker_files:
        data = _parse_json(normalized[marker], marker, findings)
        if isinstance(data, dict):
            parsed[marker] = data

    if "weave.json" in normalized:
        _validate_weave_json(parsed.get("weave.json"), normalized, findings)
    if "vm-template.json" in normalized:
        _validate_vm_template_json(parsed.get("vm-template.json"), findings)
    if "recipe.json" in normalized:
        _validate_recipe_json(parsed.get("recipe.json"), findings)

    _validate_scripts(normalized, parsed.get("weave.json"), findings)

    error_count = sum(1 for finding in findings if finding.severity == "error")
    warning_count = sum(1 for finding in findings if finding.severity == "warning")
    artifact_type = _artifact_type(marker_files)
    return {
        "valid": error_count == 0,
        "artifact_type": artifact_type,
        "source": source or {"type": "inline"},
        "checked_files": sorted(normalized.keys()),
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": [finding.to_api() for finding in findings],
    }


def _read_if_file(base: str, rel_path: str, files: dict[str, str]) -> None:
    full = os.path.join(base, rel_path)
    if not os.path.isfile(full):
        return
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            files[_normalize_rel_path(rel_path)] = handle.read()
    except OSError:
        return


def _normalize_rel_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip().lstrip("/")
    return os.path.normpath(cleaned).replace("\\", "/")


def _looks_like_script(path: str) -> bool:
    return path.endswith((".sh", ".py", ".bash"))


def _artifact_type(marker_files: list[str]) -> str:
    if "weave.json" in marker_files:
        return "weave"
    if "vm-template.json" in marker_files:
        return "vm-template"
    if "recipe.json" in marker_files:
        return "recipe"
    return "unknown"


def _finding(
    severity: str,
    path: str,
    message: str,
    fix_hint: str,
    *,
    line: int | None = None,
    code: str = "",
) -> ArtifactValidationFinding:
    return ArtifactValidationFinding(
        severity=severity,
        path=path,
        message=message,
        fix_hint=fix_hint,
        line=line,
        code=code,
    )


def _parse_json(
    text: str,
    path: str,
    findings: list[ArtifactValidationFinding],
) -> Any:
    try:
        data = json.loads(text)
    except JSONDecodeError as exc:
        findings.append(_finding(
            "error",
            path,
            f"{path} is not valid JSON: {exc.msg}.",
            "Fix the JSON syntax before running or publishing this artifact.",
            line=exc.lineno,
            code="ARTIFACT_JSON_INVALID",
        ))
        return None
    if not isinstance(data, dict):
        findings.append(_finding(
            "error",
            path,
            f"{path} must contain a JSON object.",
            "Replace the top-level value with an object containing artifact metadata.",
            code="ARTIFACT_JSON_OBJECT_REQUIRED",
        ))
        return None
    return data


def _validate_weave_json(
    weave: Any,
    files: Mapping[str, str],
    findings: list[ArtifactValidationFinding],
) -> None:
    if not isinstance(weave, dict):
        return

    for field in ("name", "description", "description_long", "run_script", "log_file"):
        if field in weave and not isinstance(weave[field], str):
            findings.append(_finding(
                "error",
                "weave.json",
                f"`{field}` must be a string.",
                f"Set `{field}` to a JSON string or remove it.",
                line=_json_key_line(files.get("weave.json", ""), field),
                code="WEAVE_FIELD_TYPE",
            ))

    args = weave.get("args")
    if args is not None:
        _validate_args(args, files.get("weave.json", ""), findings)

    nodes = weave.get("nodes")
    networks = weave.get("networks")
    has_topology = isinstance(nodes, list) or isinstance(networks, list)
    if nodes is not None and not isinstance(nodes, list):
        findings.append(_finding(
            "error",
            "weave.json",
            "`nodes` must be an array when present.",
            "Use a JSON array of node objects, or remove `nodes` for a script-driven weave.",
            line=_json_key_line(files.get("weave.json", ""), "nodes"),
            code="WEAVE_NODES_SHAPE",
        ))
    elif isinstance(nodes, list):
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                findings.append(_finding(
                    "error",
                    "weave.json",
                    f"`nodes[{index}]` must be an object.",
                    "Each topology node must be an object with at least a `name` field.",
                    line=_json_key_line(files.get("weave.json", ""), "nodes"),
                    code="WEAVE_NODE_SHAPE",
                ))
                continue
            if not isinstance(node.get("name"), str) or not node.get("name", "").strip():
                findings.append(_finding(
                    "error",
                    "weave.json",
                    f"`nodes[{index}].name` must be a non-empty string.",
                    "Give every topology node a stable name.",
                    line=_json_key_line(files.get("weave.json", ""), "nodes"),
                    code="WEAVE_NODE_NAME",
                ))
            if "components" in node and not isinstance(node["components"], list):
                findings.append(_finding(
                    "error",
                    "weave.json",
                    f"`nodes[{index}].components` must be an array.",
                    "Use a list of component objects, or omit `components`.",
                    line=_json_key_line(files.get("weave.json", ""), "components"),
                    code="WEAVE_NODE_COMPONENTS_SHAPE",
                ))

    if networks is not None and not isinstance(networks, list):
        findings.append(_finding(
            "error",
            "weave.json",
            "`networks` must be an array when present.",
            "Use a JSON array of network objects, or remove `networks` for a script-driven weave.",
            line=_json_key_line(files.get("weave.json", ""), "networks"),
            code="WEAVE_NETWORKS_SHAPE",
        ))
    elif isinstance(networks, list):
        for index, network in enumerate(networks):
            if not isinstance(network, dict):
                findings.append(_finding(
                    "error",
                    "weave.json",
                    f"`networks[{index}]` must be an object.",
                    "Each topology network must be an object with name/type/interfaces fields.",
                    line=_json_key_line(files.get("weave.json", ""), "networks"),
                    code="WEAVE_NETWORK_SHAPE",
                ))
                continue
            if "interfaces" in network and not isinstance(network["interfaces"], list):
                findings.append(_finding(
                    "error",
                    "weave.json",
                    f"`networks[{index}].interfaces` must be an array.",
                    "Use a list of interface names such as node-nic-p1.",
                    line=_json_key_line(files.get("weave.json", ""), "interfaces"),
                    code="WEAVE_NETWORK_INTERFACES_SHAPE",
                ))

    run_script = str(weave.get("run_script") or "weave.sh").strip()
    if run_script:
        _validate_relative_file_ref(
            run_script,
            "weave.json",
            "run_script",
            files.get("weave.json", ""),
            findings,
        )
        if run_script not in files:
            severity = "warning" if has_topology else "error"
            findings.append(_finding(
                severity,
                "weave.json",
                f"`run_script` points to missing file `{run_script}`.",
                "Add the script file or change `run_script` to a file that exists in the artifact root.",
                line=_json_key_line(files.get("weave.json", ""), "run_script"),
                code="WEAVE_RUN_SCRIPT_MISSING",
            ))

    if not has_topology and run_script not in files:
        findings.append(_finding(
            "error",
            "weave.json",
            "Weave has neither declarative topology nor an available run script.",
            "Add `nodes`/`networks` to weave.json, or include the script named by `run_script`.",
            code="WEAVE_NO_TOPOLOGY_OR_SCRIPT",
        ))


def _validate_args(
    args: Any,
    weave_json_text: str,
    findings: list[ArtifactValidationFinding],
) -> None:
    if not isinstance(args, list):
        findings.append(_finding(
            "error",
            "weave.json",
            "`args` must be an array of argument definition objects.",
            "Use `args: [{\"name\": \"SLICE_NAME\", \"type\": \"string\", \"default\": \"my-slice\"}]`.",
            line=_json_key_line(weave_json_text, "args"),
            code="WEAVE_ARGS_SHAPE",
        ))
        return

    seen: set[str] = set()
    for index, arg in enumerate(args):
        if not isinstance(arg, dict):
            findings.append(_finding(
                "error",
                "weave.json",
                f"`args[{index}]` must be an object.",
                "Each argument entry must be an object with name/type/default metadata.",
                line=_json_key_line(weave_json_text, "args"),
                code="WEAVE_ARG_ITEM_SHAPE",
            ))
            continue
        name = arg.get("name")
        if not isinstance(name, str) or not name.strip():
            findings.append(_finding(
                "error",
                "weave.json",
                f"`args[{index}].name` must be a non-empty string.",
                "Set an environment-variable style name such as SLICE_NAME.",
                line=_json_key_line(weave_json_text, "name", occurrence=index + 1),
                code="WEAVE_ARG_NAME_MISSING",
            ))
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            findings.append(_finding(
                "error",
                "weave.json",
                f"`args[{index}].name` is not a valid environment variable name: {name!r}.",
                "Use letters, numbers, and underscores, starting with a letter or underscore.",
                line=_json_key_line(weave_json_text, name),
                code="WEAVE_ARG_NAME_INVALID",
            ))
        if name in seen:
            findings.append(_finding(
                "error",
                "weave.json",
                f"`args` defines duplicate argument `{name}`.",
                "Keep one definition for each environment variable.",
                line=_json_key_line(weave_json_text, name),
                code="WEAVE_ARG_DUPLICATE",
            ))
        seen.add(name)

        arg_type = arg.get("type")
        if arg_type is not None and arg_type not in ALLOWED_ARG_TYPES:
            findings.append(_finding(
                "warning",
                "weave.json",
                f"`args[{index}].type` has uncommon value {arg_type!r}.",
                "Use one of: string, number, boolean, select.",
                line=_json_key_line(weave_json_text, "type", occurrence=index + 1),
                code="WEAVE_ARG_TYPE_UNKNOWN",
            ))
        if "required" in arg and not isinstance(arg["required"], bool):
            findings.append(_finding(
                "error",
                "weave.json",
                f"`args[{index}].required` must be boolean.",
                "Use true or false, not a string.",
                line=_json_key_line(weave_json_text, "required", occurrence=index + 1),
                code="WEAVE_ARG_REQUIRED_TYPE",
            ))
        if "default" not in arg:
            findings.append(_finding(
                "warning",
                "weave.json",
                f"`args[{index}]` has no default value.",
                "Provide a useful default so the Run dialog can be executed immediately.",
                line=_json_key_line(weave_json_text, "name", occurrence=index + 1),
                code="WEAVE_ARG_DEFAULT_MISSING",
            ))


def _validate_vm_template_json(data: Any, findings: list[ArtifactValidationFinding]) -> None:
    if not isinstance(data, dict):
        return
    if "name" in data and not isinstance(data["name"], str):
        findings.append(_finding(
            "error",
            "vm-template.json",
            "`name` must be a string.",
            "Set `name` to the VM template display name.",
            code="VM_TEMPLATE_NAME_TYPE",
        ))
    if "image" in data and not isinstance(data["image"], str):
        findings.append(_finding(
            "error",
            "vm-template.json",
            "`image` must be a string.",
            "Set `image` to a FABRIC image id such as default_ubuntu_22.",
            code="VM_TEMPLATE_IMAGE_TYPE",
        ))
    if "boot_config" in data and not isinstance(data["boot_config"], dict):
        findings.append(_finding(
            "error",
            "vm-template.json",
            "`boot_config` must be an object.",
            "Use a boot_config object with uploads/commands/network arrays.",
            code="VM_TEMPLATE_BOOT_CONFIG_SHAPE",
        ))
    if "variants" in data and not isinstance(data["variants"], dict):
        findings.append(_finding(
            "error",
            "vm-template.json",
            "`variants` must be an object.",
            "Use an object keyed by image id for multi-variant templates.",
            code="VM_TEMPLATE_VARIANTS_SHAPE",
        ))
    if "components" in data and not isinstance(data["components"], list):
        findings.append(_finding(
            "error",
            "vm-template.json",
            "`components` must be an array.",
            "Use a list of component objects or omit `components`.",
            code="VM_TEMPLATE_COMPONENTS_SHAPE",
        ))
    if "image" not in data and "variants" not in data:
        findings.append(_finding(
            "warning",
            "vm-template.json",
            "VM template does not define `image` or `variants`.",
            "Add a default image or variant map so the template can be applied to a node.",
            code="VM_TEMPLATE_IMAGE_MISSING",
        ))


def _validate_recipe_json(data: Any, findings: list[ArtifactValidationFinding]) -> None:
    if not isinstance(data, dict):
        return
    if "name" in data and not isinstance(data["name"], str):
        findings.append(_finding(
            "error",
            "recipe.json",
            "`name` must be a string.",
            "Set `name` to the recipe display name.",
            code="RECIPE_NAME_TYPE",
        ))
    if "image_patterns" in data and not isinstance(data["image_patterns"], dict):
        findings.append(_finding(
            "error",
            "recipe.json",
            "`image_patterns` must be an object.",
            "Map image-name fragments to script filenames.",
            code="RECIPE_IMAGE_PATTERNS_SHAPE",
        ))
    steps = data.get("steps")
    if steps is None:
        findings.append(_finding(
            "warning",
            "recipe.json",
            "Recipe does not define `steps`.",
            "Add a `steps` array describing upload and execute actions.",
            code="RECIPE_STEPS_MISSING",
        ))
        return
    if not isinstance(steps, list):
        findings.append(_finding(
            "error",
            "recipe.json",
            "`steps` must be an array.",
            "Use an array of step objects.",
            code="RECIPE_STEPS_SHAPE",
        ))
        return
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            findings.append(_finding(
                "error",
                "recipe.json",
                f"`steps[{index}]` must be an object.",
                "Each recipe step must be an object with a `type` field.",
                code="RECIPE_STEP_SHAPE",
            ))
        elif not isinstance(step.get("type"), str) or not step.get("type", "").strip():
            findings.append(_finding(
                "error",
                "recipe.json",
                f"`steps[{index}].type` must be a non-empty string.",
                "Set the step type, for example `upload_scripts` or `execute`.",
                code="RECIPE_STEP_TYPE_MISSING",
            ))


def _validate_relative_file_ref(
    value: str,
    path: str,
    field: str,
    source_text: str,
    findings: list[ArtifactValidationFinding],
) -> None:
    if os.path.isabs(value) or ".." in value.split("/"):
        findings.append(_finding(
            "error",
            path,
            f"`{field}` must be a relative file path inside the artifact directory.",
            "Use a simple relative filename such as weave.sh.",
            line=_json_key_line(source_text, field),
            code="ARTIFACT_UNSAFE_PATH",
        ))


def _validate_scripts(
    files: Mapping[str, str],
    weave: Any,
    findings: list[ArtifactValidationFinding],
) -> None:
    run_script = ""
    if isinstance(weave, dict):
        run_script = str(weave.get("run_script") or "weave.sh").strip()

    for path, text in files.items():
        if not _looks_like_script(path):
            continue
        if path.endswith((".sh", ".bash")):
            is_weave_entrypoint = path == run_script or path == "weave.sh"
            _validate_shell_script(path, text, findings, is_weave_entrypoint=is_weave_entrypoint)
        _validate_results_paths(path, text, findings)


def _validate_shell_script(
    path: str,
    text: str,
    findings: list[ArtifactValidationFinding],
    *,
    is_weave_entrypoint: bool,
) -> None:
    has_set_e = bool(re.search(r"^\s*set\s+-[^#\n]*e", text, re.MULTILINE))
    has_guarded_failures = bool(re.search(r"^\s*if\s+!\s+", text, re.MULTILINE))
    has_cleanup_trap = "trap " in text and "SIGTERM" in text

    if not has_set_e and not (is_weave_entrypoint and has_guarded_failures and has_cleanup_trap):
        findings.append(_finding(
            "warning",
            path,
            f"{path} does not enable `set -e` or explicit guarded failure handling.",
            "Add `set -e` for simple setup scripts, or use explicit `if ! command; then ...; exit 1` guards with a cleanup trap for weave.sh.",
            line=_first_non_comment_line(text),
            code="SCRIPT_SET_E_MISSING",
        ))

    if is_weave_entrypoint and "### PROGRESS:" not in text:
        findings.append(_finding(
            "warning",
            path,
            f"{path} has no `### PROGRESS:` status messages.",
            "Print `### PROGRESS: ...` lines so the WebUI and agents can track run progress.",
            line=_first_non_comment_line(text),
            code="SCRIPT_PROGRESS_MARKER_MISSING",
        ))


def _validate_results_paths(
    path: str,
    text: str,
    findings: list[ArtifactValidationFinding],
) -> None:
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "results/" in stripped or "results" in stripped and "mkdir" in stripped:
            continue
        if re.search(r"(^|[^A-Za-z0-9_./-])(result|output|outputs)/", stripped):
            findings.append(_finding(
                "warning",
                path,
                "Script appears to write experiment output outside `results/`.",
                "Write collected benchmark or experiment outputs under `results/` so cleanup, publishing, and evaluators can find them.",
                line=line_no,
                code="SCRIPT_RESULTS_PATH_CONVENTION",
            ))
            continue
        if re.search(r">\s*(?:\./)?(?:iperf|ping|throughput|metrics|result)[A-Za-z0-9_.-]*\.(?:csv|json|txt)", stripped):
            findings.append(_finding(
                "warning",
                path,
                "Script redirects result-like output to the artifact root.",
                "Redirect outputs to `results/<name>` and create the directory before writing.",
                line=line_no,
                code="SCRIPT_RESULTS_PATH_CONVENTION",
            ))


def _json_key_line(text: str, key: str, *, occurrence: int = 1) -> int | None:
    if not text:
        return None
    pattern = re.compile(rf'"{re.escape(key)}"\s*:')
    seen = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            seen += 1
            if seen >= occurrence:
                return line_no
    if key and key not in {"args", "nodes", "networks", "components", "interfaces"}:
        for line_no, line in enumerate(text.splitlines(), start=1):
            if key in line:
                return line_no
    return None


def _first_non_comment_line(text: str) -> int | None:
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return line_no
    return None
