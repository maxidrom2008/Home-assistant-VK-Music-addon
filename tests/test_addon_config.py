from pathlib import Path

import yaml


def test_addon_manifest_uses_persistent_data_and_ingress_only() -> None:
    manifest = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    assert manifest["slug"] == "vk_music_server"
    assert manifest["version"] == "0.1.2"
    assert manifest["ingress"] is True
    assert manifest["ingress_port"] == 8099
    assert manifest["audio"] is True
    assert "aarch64" in manifest["arch"]
    assert "amd64" in manifest["arch"]
    assert "data:rw" in manifest["map"]
    assert "ports" not in manifest
