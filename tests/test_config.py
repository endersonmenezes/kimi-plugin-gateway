"""Testes do schema de gateway.json, ids, versões, tags e URLs de release."""

import json
import tempfile
import unittest
from pathlib import Path

from gateway.config import (
    ConfigError,
    GatewayConfig,
    load_config,
    release_tag,
    release_url,
    validate_plugin_id,
    validate_source_version,
)


def make_config(**overrides):
    values = {
        "plugin_id": "impeccable",
        "upstream_url": "https://github.com/pbakaus/impeccable",
        "requested_ref": "v4.10.0",
        "commit": "a" * 40,
        "manifest_path": ".claude-plugin/plugin.json",
        "source_version": "4.10.0",
        "release_revision": 1,
        "remove_paths": (),
    }
    values.update(overrides)
    return GatewayConfig(**values)


def write_gateway_json(directory, payload):
    path = Path(directory) / "gateway.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


VALID_PAYLOAD = {
    "id": "impeccable",
    "upstream": {
        "url": "https://github.com/pbakaus/impeccable",
        "requestedRef": "v4.10.0",
        "commit": "b" * 40,
        "manifest": ".claude-plugin/plugin.json",
        "sourceVersion": "4.10.0",
    },
    "releaseRevision": 1,
}


class GatewayConfigTests(unittest.TestCase):
    def test_release_tag_format(self):
        config = make_config()
        self.assertEqual(release_tag(config), "impeccable-v4.10.0-gateway.1")

    def test_release_tag_uses_source_version_not_ref(self):
        config = make_config(requested_ref="main")
        self.assertEqual(release_tag(config), "impeccable-v4.10.0-gateway.1")

    def test_release_url(self):
        config = make_config()
        self.assertEqual(
            release_url(config, "endersonmenezes/kimi-plugin-gateway"),
            "https://github.com/endersonmenezes/kimi-plugin-gateway/"
            "releases/download/impeccable-v4.10.0-gateway.1/impeccable.zip",
        )

    def test_release_tag_rejects_missing_version(self):
        with self.assertRaises(ConfigError):
            release_tag(make_config(source_version=""))

    def test_release_tag_rejects_unsafe_version_characters(self):
        for version in ("4.10.0;rm -rf /", "4 10 0", "v4.10.0/../x", "-1.0"):
            with self.subTest(version=version):
                with self.assertRaises(ConfigError):
                    release_tag(make_config(source_version=version))


class ValidateSourceVersionTests(unittest.TestCase):
    def test_accepts_semver_like_versions(self):
        for version in ("4.10.0", "1.0.0-beta.2", "2026.11"):
            with self.subTest(version=version):
                self.assertEqual(validate_source_version(version), version)

    def test_rejects_missing_or_invalid_version(self):
        for version in ("", "   ", "4.10.0;echo", "a b", "../1.0"):
            with self.subTest(version=version):
                with self.assertRaises(ConfigError):
                    validate_source_version(version)


class ValidatePluginIdTests(unittest.TestCase):
    def test_config_validates_plugin_id(self):
        self.assertEqual(validate_plugin_id("impeccable"), "impeccable")
        with self.assertRaises(ConfigError):
            validate_plugin_id("../escape")


class LoadConfigTests(unittest.TestCase):
    def test_load_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gateway_json(tmp, VALID_PAYLOAD)
            config = load_config(path)
        self.assertEqual(config.plugin_id, "impeccable")
        self.assertEqual(
            config.upstream_url, "https://github.com/pbakaus/impeccable"
        )
        self.assertEqual(config.requested_ref, "v4.10.0")
        self.assertEqual(config.commit, "b" * 40)
        self.assertEqual(config.manifest_path, ".claude-plugin/plugin.json")
        self.assertEqual(config.source_version, "4.10.0")
        self.assertEqual(config.release_revision, 1)
        self.assertEqual(config.remove_paths, [])

    def test_load_config_with_remove_paths(self):
        payload = dict(VALID_PAYLOAD)
        payload["overlays"] = {"remove": [".claude/hooks", "bin/tool.sh"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gateway_json(tmp, payload)
            config = load_config(path)
        self.assertEqual(config.remove_paths, [".claude/hooks", "bin/tool.sh"])

    def test_missing_file_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_config(Path(tmp) / "gateway.json")
        self.assertIn("gateway.json", str(ctx.exception))

    def test_invalid_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gateway.json"
            path.write_text("{não é json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_missing_required_fields_are_rejected(self):
        for key in ("id", "upstream", "releaseRevision"):
            with self.subTest(missing=key):
                payload = {k: v for k, v in VALID_PAYLOAD.items() if k != key}
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_gateway_json(tmp, payload)
                    with self.assertRaises(ConfigError):
                        load_config(path)

    def test_invalid_values_are_rejected(self):
        variants = [
            {**VALID_PAYLOAD, "id": "id inválido"},
            {**VALID_PAYLOAD, "releaseRevision": 0},
            {
                **VALID_PAYLOAD,
                "upstream": {
                    **VALID_PAYLOAD["upstream"],
                    "url": "https://example.com/x/y",
                },
            },
            {
                **VALID_PAYLOAD,
                "upstream": {**VALID_PAYLOAD["upstream"], "sourceVersion": ""},
            },
            {
                **VALID_PAYLOAD,
                "upstream": {**VALID_PAYLOAD["upstream"], "commit": "abc123"},
            },
            {
                **VALID_PAYLOAD,
                "overlays": {"remove": ["../escape"]},
            },
        ]
        for payload in variants:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_gateway_json(tmp, payload)
                    with self.assertRaises(ConfigError):
                        load_config(path)


if __name__ == "__main__":
    unittest.main()
