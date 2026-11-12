from pathlib import Path
import json

import yaml


def test_addon_manifest_uses_persistent_data_and_ingress_only() -> None:
    manifest = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    assert manifest["slug"] == "vk_music_server"
    assert manifest["version"] == "1.0.0-rc.11"
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
    assert manifest["version"] == "1.0.0-rc.11"
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
    assert project["project"]["version"] == "1.0.0rc11"


def test_app_repository_metadata_is_valid() -> None:
    metadata = yaml.safe_load(Path("repository.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == "VK Music Server"
    assert metadata["url"] == "https://github.com/maxidrom2008/Home-assistant-VK-Music-addon"
    assert metadata["maintainer"]
