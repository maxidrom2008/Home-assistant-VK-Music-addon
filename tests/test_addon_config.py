from pathlib import Path
import json

import yaml


def test_addon_manifest_uses_persistent_data_and_ingress_only() -> None:
    manifest = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    assert manifest["slug"] == "vk_music_server"
    assert manifest["version"] == "1.0.0-rc.25"
    assert manifest["image"] == "ghcr.io/maxidrom2008/vk-music-server"
    assert manifest["ingress"] is True
    assert manifest["ingress_port"] == 8099
    assert manifest["audio"] is True
    assert manifest["hassio_api"] is True
    assert "aarch64" in manifest["arch"]
    assert "amd64" in manifest["arch"]
    assert "data:rw" in manifest["map"]
    assert "ports" not in manifest


def test_hacs_custom_integration_manifest_is_present() -> None:
    manifest = json.loads(
        Path("custom_components/vk_music_server/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["domain"] == "vk_music_server"
    assert manifest["config_flow"] is True
    assert manifest["version"] == "1.0.0-rc.25"
    assert manifest["issue_tracker"].endswith("/issues")


def test_release_versions_are_synchronized() -> None:
    import json
    import tomllib

    from app.version import VERSION

    app_manifest = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    integration = json.loads(
        Path("custom_components/vk_music_server/manifest.json").read_text(encoding="utf-8")
    )
    web_package = json.loads(
        Path("app/web/package.json").read_text(encoding="utf-8")
    )
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert app_manifest["version"] == VERSION
    assert integration["version"] == VERSION
    assert web_package["version"] == VERSION
    assert project["project"]["version"] == "1.0.0rc25"


def test_app_repository_metadata_is_valid() -> None:
    metadata = yaml.safe_load(Path("repository.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == "VK Music Server"
    assert metadata["url"] == "https://github.com/maxidrom2008/Home-assistant-VK-Music-addon"
    assert metadata["maintainer"]


def test_ci_metadata_normalization_is_safe_for_untrusted_pull_request_values(tmp_path: Path) -> None:
    import os
    import subprocess

    workflow = yaml.safe_load(
        Path(".github/workflows/validate.yml").read_text(encoding="utf-8")
    )
    normalize_step = next(
        step
        for step in workflow["jobs"]["prepare"]["steps"]
        if step.get("name") == "Normalize app metadata"
    )

    script = normalize_step["run"]
    # GitHub expressions must remain environment values, never shell source.
    assert "${{ steps.info.outputs." not in script
    assert "single_line" in script
    assert "jq -er" in script
    assert "set -euo pipefail" in script

    marker = tmp_path / "metadata-command-was-executed"
    output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update(
        {
            "IMAGE": json.dumps("ghcr.io/maxidrom2008/vk-music-server"),
            "VERSION": json.dumps("1.0.0-rc.25"),
            "APP_NAME": json.dumps(f"VK Music\nInjected=1 $(touch {marker})"),
            "APP_DESCRIPTION": json.dumps("Server\r\nInjected=2"),
            "APP_URL": json.dumps("https://github.com/maxidrom2008/Home-assistant-VK-Music-addon"),
            "GITHUB_OUTPUT": str(output),
        }
    )

    subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, text=True)

    assert not marker.exists()
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6
    assert "name=VK Music Injected=1 $(touch " + str(marker) + ")" in lines
    assert "description=Server  Injected=2" in lines
    assert "url=https://github.com/maxidrom2008/Home-assistant-VK-Music-addon" in lines


def test_direct_runtime_dependencies_are_exactly_pinned() -> None:
    from pathlib import Path

    requirements = [
        line.strip()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirements
    assert all("==" in requirement and ">=" not in requirement and "<" not in requirement for requirement in requirements)

    package = json.loads(
        Path("app/web/package.json").read_text(encoding="utf-8")
    )
    for dependency in (*package.get("dependencies", {}).values(), *package.get("devDependencies", {}).values()):
        assert dependency and dependency[0].isdigit()
        assert not dependency.startswith(("^", "~", "*"))


def test_github_actions_are_pinned_to_full_commit_shas() -> None:
    from pathlib import Path

    for workflow_path in (
        Path(".github/workflows/validate.yml"),
        Path(".github/workflows/hassfest.yml"),
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        action_refs = []
        for line in workflow.splitlines():
            stripped = line.strip()
            if stripped.startswith("uses:"):
                action_refs.append(
                    stripped.removeprefix("uses:").split("#", 1)[0].strip()
                )

        assert action_refs, f"No actions found in {workflow_path}"
        for action_ref in action_refs:
            revision = action_ref.rsplit("@", 1)[-1]
            assert len(revision) == 40 and all(
                char in "0123456789abcdef" for char in revision
            ), f"Action is not pinned to an immutable commit SHA: {action_ref}"


def test_pull_request_builds_do_not_receive_publish_credentials() -> None:
    from pathlib import Path

    workflow = yaml.safe_load(
        Path(".github/workflows/validate.yml").read_text(encoding="utf-8")
    )
    publish_build = workflow["jobs"]["build"]
    assert publish_build["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert publish_build["permissions"]["packages"] == "write"
    assert publish_build["permissions"]["id-token"] == "write"

    pull_request_build = workflow["jobs"]["build_validate"]
    assert pull_request_build["if"] == "github.event_name == 'pull_request'"
    assert pull_request_build["permissions"] == {"contents": "read"}
    matrix_arches = {
        item["arch"]: (item["os"], item["platform"])
        for item in pull_request_build["strategy"]["matrix"]["include"]
    }
    assert matrix_arches == {
        "amd64": ("ubuntu-latest", "linux/amd64"),
        "aarch64": ("ubuntu-24.04-arm", "linux/arm64"),
    }
    assert all(
        "container-registry-password" not in str(step.get("with", {}))
        for step in pull_request_build["steps"]
    )


def test_checkout_steps_do_not_persist_github_tokens() -> None:
    from pathlib import Path

    for workflow_path in (
        Path(".github/workflows/validate.yml"),
        Path(".github/workflows/hassfest.yml"),
    ):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    assert step.get("with", {}).get("persist-credentials") is False


def test_python_runtime_lock_covers_direct_dependencies_and_is_used() -> None:
    from pathlib import Path

    direct = {}
    for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            direct[name.split("[", 1)[0].lower().replace("_", "-")] = version

    locked = {}
    lock_lines = [
        line.strip()
        for line in Path("requirements.lock.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lock_lines
    for line in lock_lines:
        name, version = line.split("==", 1)
        locked[name.lower().replace("_", "-")] = version

    assert direct
    assert all(locked.get(name) == version for name, version in direct.items())

    dev_lines = Path("requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "-r requirements.lock.txt" in dev_lines
    assert "pytest==9.2.0" in dev_lines
    assert "requirements.lock.txt" in Path("Dockerfile").read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in Path(
        ".github/workflows/validate.yml"
    ).read_text(encoding="utf-8")

def test_home_assistant_media_player_polls_its_own_selected_output() -> None:
    from pathlib import Path

    source = Path("custom_components/vk_music_server/media_player.py").read_text(encoding="utf-8")
    assert "device = quote(self._output_device, safe=\"\")" in source
    assert "playback/state?output_device={device}" in source
