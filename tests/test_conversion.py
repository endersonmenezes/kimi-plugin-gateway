"""Testes da conversão determinística de manifests Claude em manifests Kimi."""

import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from gateway.conversion import (
    ConversionError,
    ConversionResult,
    convert_manifest,
    write_kimi_manifest,
)

FIXTURE = Path(__file__).parent / "fixtures" / "claude-basic"
MANIFEST_PATH = ".claude-plugin/plugin.json"


def copy_upstream(tmp: str) -> Path:
    upstream = Path(tmp) / f"upstream-{uuid.uuid4().hex}"
    shutil.copytree(FIXTURE, upstream)
    return upstream


def load_fixture_manifest() -> dict:
    text = (FIXTURE / MANIFEST_PATH).read_text(encoding="utf-8")
    return json.loads(text)


def write_upstream_manifest(upstream: Path, payload: dict) -> None:
    target = upstream / MANIFEST_PATH
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def convert_variant(tmp: str, payload: dict, plugin_id=None) -> ConversionResult:
    upstream = copy_upstream(tmp)
    write_upstream_manifest(upstream, payload)
    return convert_manifest(upstream, MANIFEST_PATH, plugin_id=plugin_id)


class ConvertManifestTests(unittest.TestCase):
    def test_converts_impeccable_essential_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_manifest(copy_upstream(tmp), MANIFEST_PATH)
        self.assertIsInstance(result, ConversionResult)
        self.assertEqual(result.source_version, "4.10.0")
        self.assertEqual(
            result.manifest,
            {
                "name": "impeccable",
                "version": "4.10.0",
                "description": (
                    "Design fluency for frontend development. 1 skill with 24 "
                    "commands (/impeccable polish, /impeccable audit, "
                    "/impeccable critique, etc.) and curated anti-pattern "
                    "detection."
                ),
                "author": {
                    "name": "Paul Bakaus",
                    "email": "paul@paulbakaus.com",
                },
                "homepage": "https://impeccable.style",
                "skills": ["./upstream/.claude/skills/"],
                "commands": ["./upstream/.claude/commands/"],
                "agents": ["./upstream/.claude/agents/"],
            },
        )

    def test_report_lists_converted_discovered_and_ignored_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_manifest(copy_upstream(tmp), MANIFEST_PATH)
        report = result.report
        self.assertTrue(
            any("convertido: skills declarado" in e
                and "./upstream/.claude/skills/" in e for e in report)
        )
        self.assertTrue(
            any("convertido: commands descoberto em .claude/commands"
                in e and "./upstream/.claude/commands/" in e for e in report)
        )
        self.assertTrue(
            any("convertido: agents descoberto em .claude/agents"
                in e and "./upstream/.claude/agents/" in e for e in report)
        )
        self.assertTrue(any("revisão: commands" in e for e in report))
        self.assertTrue(any("revisão: agents" in e for e in report))
        self.assertTrue(any("'repository'" in e and "ignorado" in e
                            for e in report))
        self.assertFalse(any("pendência" in e for e in report))
        self.assertFalse(any("campo desconhecido" in e for e in report))

    def test_plugin_id_override_replaces_manifest_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_variant(tmp, load_fixture_manifest(),
                                     plugin_id="custom-id")
        self.assertEqual(result.manifest["name"], "custom-id")
        self.assertEqual(result.source_version, "4.10.0")

    def test_invalid_plugin_id_override_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError):
                convert_variant(tmp, load_fixture_manifest(),
                                plugin_id="../escape")

    def test_missing_name_requires_plugin_id(self):
        payload = load_fixture_manifest()
        del payload["name"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError) as ctx:
                convert_variant(tmp, payload)
            result = convert_variant(tmp, payload, plugin_id="fallback-id")
        self.assertIn("name", str(ctx.exception))
        self.assertEqual(result.manifest["name"], "fallback-id")

    def test_declared_capability_paths_support_string_and_list(self):
        payload = load_fixture_manifest()
        payload["commands"] = ["./.claude/commands/"]
        payload["agents"] = "./.claude/agents"
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_variant(tmp, payload)
        self.assertEqual(result.manifest["commands"],
                         ["./upstream/.claude/commands/"])
        self.assertEqual(result.manifest["agents"],
                         ["./upstream/.claude/agents/"])

    def test_conversion_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream = copy_upstream(tmp)
            first = convert_manifest(upstream, MANIFEST_PATH)
            second = convert_manifest(upstream, MANIFEST_PATH)
        self.assertEqual(first.manifest, second.manifest)
        self.assertEqual(first.report, second.report)
        self.assertEqual(first.source_version, second.source_version)


class CapabilityHandlingTests(unittest.TestCase):
    def test_unknown_fields_are_reported_not_copied(self):
        payload = load_fixture_manifest()
        payload["telemetry"] = {"endpoint": "https://example.com"}
        payload["customFlag"] = True
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_variant(tmp, payload)
        self.assertNotIn("telemetry", result.manifest)
        self.assertNotIn("customFlag", result.manifest)
        self.assertTrue(any("campo desconhecido 'telemetry'" in e
                            for e in result.report))
        self.assertTrue(any("campo desconhecido 'customFlag'" in e
                            for e in result.report))

    def test_hooks_and_mcp_become_pending_never_converted(self):
        payload = load_fixture_manifest()
        payload["hooks"] = [{"event": "SessionStart", "command": "echo pwned"}]
        payload["mcpServers"] = {"docs": {"url": "https://example.com/mcp"}}
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_variant(tmp, payload)
        self.assertNotIn("hooks", result.manifest)
        self.assertNotIn("mcpServers", result.manifest)
        self.assertTrue(any("pendência: 'hooks'" in e for e in result.report))
        self.assertTrue(any("pendência: 'mcpServers'" in e
                            for e in result.report))

    def test_empty_declared_capability_list_is_reported(self):
        payload = load_fixture_manifest()
        payload["commands"] = []
        with tempfile.TemporaryDirectory() as tmp:
            result = convert_variant(tmp, payload)
        self.assertNotIn("commands", result.manifest)
        self.assertTrue(any("'commands' declarado com lista vazia" in e
                            for e in result.report))


class VersionHandlingTests(unittest.TestCase):
    def test_missing_version_fails(self):
        payload = load_fixture_manifest()
        del payload["version"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError) as ctx:
                convert_variant(tmp, payload)
        self.assertIn("version", str(ctx.exception))

    def test_invalid_version_values_fail(self):
        for bad in ("", "   ", "4.10.0;echo", "4 10 0", 4):
            with self.subTest(version=bad):
                payload = load_fixture_manifest()
                payload["version"] = bad
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ConversionError):
                        convert_variant(tmp, payload)


class PathSafetyTests(unittest.TestCase):
    def test_manifest_path_must_stay_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError):
                convert_manifest(copy_upstream(tmp), "../plugin.json")

    def test_declared_path_escaping_upstream_is_rejected(self):
        payload = load_fixture_manifest()
        payload["skills"] = "../outside/skills"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError) as ctx:
                convert_variant(tmp, payload)
        self.assertIn("..", str(ctx.exception))

    def test_declared_path_must_exist(self):
        payload = load_fixture_manifest()
        payload["skills"] = "./nope"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError) as ctx:
                convert_variant(tmp, payload)
        self.assertIn("./nope", str(ctx.exception))

    def test_non_string_capability_path_is_rejected(self):
        payload = load_fixture_manifest()
        payload["skills"] = [123]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConversionError):
                convert_variant(tmp, payload)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream = copy_upstream(tmp)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            skills = upstream / ".claude" / "skills"
            shutil.rmtree(skills)
            skills.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ConversionError):
                convert_manifest(upstream, MANIFEST_PATH)


class ManifestFileErrorTests(unittest.TestCase):
    def test_missing_manifest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream = Path(tmp) / "upstream"
            upstream.mkdir()
            with self.assertRaises(ConversionError) as ctx:
                convert_manifest(upstream, MANIFEST_PATH)
        self.assertIn(MANIFEST_PATH, str(ctx.exception))

    def test_manifest_must_be_valid_json_object(self):
        for content in ("[1, 2]", "{quebrado", '"texto"'):
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as tmp:
                    upstream = copy_upstream(tmp)
                    (upstream / MANIFEST_PATH).write_text(
                        content, encoding="utf-8"
                    )
                    with self.assertRaises(ConversionError):
                        convert_manifest(upstream, MANIFEST_PATH)


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class SourceVersionFromManifestTests(unittest.TestCase):
    def test_branch_and_tag_same_content_same_source_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            upstream = copy_upstream(tmp)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", "-C", str(upstream), *args],
                    check=True,
                    capture_output=True,
                )

            git("init", "-q")
            git("add", "-A")
            git("-c", "user.name=Gateway Tests",
                "-c", "user.email=tests@example.com",
                "commit", "-q", "-m", "fixture")
            git("tag", "-a", "-m", "ref de teste", "v9.9.9")
            git("checkout", "-q", "-b", "relatorio-manual")

            versions = []
            for ref in ("v9.9.9", "relatorio-manual"):
                git("checkout", "-q", ref)
                result = convert_manifest(upstream, MANIFEST_PATH)
                versions.append(result.source_version)

        self.assertEqual(versions, ["4.10.0", "4.10.0"])


class WriteKimiManifestTests(unittest.TestCase):
    def test_writes_sorted_stable_utf8_json(self):
        manifest = {
            "version": "4.10.0",
            "name": "impeccable",
            "description": "Acentuação preservada: fluência",
            "skills": ["./upstream/.claude/skills/"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a" / "kimi.plugin.json"
            second = Path(tmp) / "b" / "kimi.plugin.json"
            write_kimi_manifest(first, manifest)
            write_kimi_manifest(second, manifest)
            write_kimi_manifest(first, manifest)
            text_a = first.read_text(encoding="utf-8")
            text_b = second.read_text(encoding="utf-8")

        self.assertEqual(text_a, text_b)
        self.assertEqual(text_a, text_a.strip() + "\n")
        self.assertEqual(json.loads(text_a), manifest)
        self.assertIn("Acentuação", text_a)
        positions = [text_a.index(f'"{key}"') for key in sorted(manifest)]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
