"""Testes das entradas estáveis do marketplace.json."""

import json
import tempfile
import unittest
from pathlib import Path

from gateway.config import GatewayConfig, release_url
from gateway.marketplace import MarketplaceError, upsert_marketplace_entry

OWNER_REPO = "endersonmenezes/kimi-plugin-gateway"


def make_config(**overrides) -> GatewayConfig:
    values = {
        "plugin_id": "fixture-plugin",
        "upstream_url": "https://github.com/fixture/plugin",
        "requested_ref": "v1.0.0",
        "commit": "a" * 40,
        "manifest_path": ".claude-plugin/plugin.json",
        "source_version": "1.0.0",
        "release_revision": 1,
        "remove_paths": (),
    }
    values.update(overrides)
    return GatewayConfig(**values)


def write_marketplace(directory: str, payload) -> Path:
    path = Path(directory) / "marketplace.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


EMPTY = {"version": "2", "plugins": []}


class UpsertMarketplaceEntryTests(unittest.TestCase):
    def test_adds_entry_with_deterministic_url(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            upsert_marketplace_entry(path, config, OWNER_REPO, "Fixture Plugin")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "2")
            self.assertEqual(
                data["plugins"],
                [
                    {
                        "id": "fixture-plugin",
                        "displayName": "Fixture Plugin",
                        "source": release_url(config, OWNER_REPO),
                    }
                ],
            )
            self.assertEqual(
                data["plugins"][0]["source"],
                "https://github.com/endersonmenezes/kimi-plugin-gateway/"
                "releases/download/fixture-plugin-v1.0.0-gateway.1/"
                "fixture-plugin.zip",
            )

    def test_reupsert_is_byte_stable(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            upsert_marketplace_entry(path, config, OWNER_REPO, "Fixture Plugin")
            first = path.read_bytes()
            upsert_marketplace_entry(path, config, OWNER_REPO, "Fixture Plugin")
            second = path.read_bytes()
        self.assertEqual(first, second)

    def test_existing_entry_source_follows_new_revision(self):
        config = make_config(release_revision=2)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            upsert_marketplace_entry(path, make_config(), OWNER_REPO, "Antigo")
            upsert_marketplace_entry(path, config, OWNER_REPO, "Fixture Plugin")
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["plugins"]), 1)
        self.assertEqual(data["plugins"][0]["displayName"], "Fixture Plugin")
        self.assertIn("fixture-plugin-v1.0.0-gateway.2", data["plugins"][0]["source"])

    def test_entries_are_sorted_by_id(self):
        other = make_config(plugin_id="aaa-outro")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            upsert_marketplace_entry(path, make_config(), OWNER_REPO, "B")
            upsert_marketplace_entry(path, other, OWNER_REPO, "A")
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["id"] for entry in data["plugins"]], ["aaa-outro", "fixture-plugin"]
        )

    def test_unknown_entry_fields_are_preserved(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(
                tmp,
                {
                    "version": "2",
                    "plugins": [
                        {"id": "fixture-plugin", "source": "antiga",
                         "notas": "revisão humana"}
                    ],
                },
            )
            upsert_marketplace_entry(path, config, OWNER_REPO, "Fixture Plugin")
            entry = json.loads(path.read_text(encoding="utf-8"))["plugins"][0]
        self.assertEqual(entry["notas"], "revisão humana")
        self.assertIn("gateway.1", entry["source"])

    def test_missing_file_is_rejected(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MarketplaceError) as ctx:
                upsert_marketplace_entry(
                    Path(tmp) / "marketplace.json", config, OWNER_REPO, "Fixture"
                )
        self.assertIn("marketplace.json", str(ctx.exception))

    def test_invalid_documents_are_rejected(self):
        config = make_config()
        variants = [
            "[1, 2]",
            json.dumps({"version": "2"}),
            json.dumps({"version": "2", "plugins": {}}),
            json.dumps({"version": "2", "plugins": ["texto"]}),
            json.dumps(
                {
                    "version": "2",
                    "plugins": [
                        {"id": "fixture-plugin", "source": "a"},
                        {"id": "fixture-plugin", "source": "b"},
                    ],
                }
            ),
        ]
        for content in variants:
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "marketplace.json"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(MarketplaceError):
                        upsert_marketplace_entry(
                            path, config, OWNER_REPO, "Fixture Plugin"
                        )

    def test_invalid_owner_repo_is_rejected(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            with self.assertRaises(ValueError):
                upsert_marketplace_entry(path, config, "sem-barra", "Fixture")

    def test_empty_display_name_is_rejected(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_marketplace(tmp, EMPTY)
            for name in ("", "   "):
                with self.subTest(name=name):
                    with self.assertRaises(MarketplaceError):
                        upsert_marketplace_entry(path, config, OWNER_REPO, name)


if __name__ == "__main__":
    unittest.main()
