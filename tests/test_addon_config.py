from pathlib import Path
import json

import yaml


def test_addon_manifest_uses_persistent_data_and_ingress_only() -> None:
    manifest = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    assert manifest["slug"] == "vk_music_server"
    assert manifest["version"] == "1.0.0-rc.13"
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
    assert manifest["version"] == "1.0.0-rc.13"
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
    assert project["project"]["version"] == "1.0.0rc13"


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
            "VERSION": json.dumps("1.0.0-rc.13"),
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
