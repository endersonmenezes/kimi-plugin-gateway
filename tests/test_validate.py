"""Testes da validação de adaptações e de pacotes autocontidos.

Erros levantam ValidationError; diagnósticos não bloqueantes voltam na
lista de avisos. Hooks/MCP nunca são ativados automaticamente e qualquer
presença deles no manifesto Kimi falha a validação.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gateway.config import release_tag
from gateway.conversion import convert_manifest, write_kimi_manifest
from gateway.overlays import apply_overlays
from gateway.package import provenance_payload, write_provenance
from gateway.validate import ValidationError, validate_plugin

FIXTURE = Path(__file__).parent / "fixtures" / "claude-basic"
MANIFEST_PATH = ".claude-plugin/plugin.json"
REPOSITORY_URL = "https://github.com/fixture/plugin"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def make_plugin(tmp: Path, plugin_id: str = "fixture-plugin") -> Path:
    """Monta plugins/<id>/ fiel ao que a conversão produziria."""
    plugin_dir = tmp / "plugins" / plugin_id
    upstream = plugin_dir / "upstream"
    shutil.copytree(FIXTURE, upstream)
    (plugin_dir / "overlays").mkdir(parents=True)
    converted = convert_manifest(upstream, MANIFEST_PATH, plugin_id=plugin_id)
    write_kimi_manifest(plugin_dir / "kimi.plugin.json", converted.manifest)
    write_json(plugin_dir / "gateway.json", {
        "id": plugin_id,
        "upstream": {
            "url": REPOSITORY_URL,
            "requestedRef": "v1.0.0",
            "commit": COMMIT,
            "manifest": MANIFEST_PATH,
            "sourceVersion": converted.source_version,
        },
        "releaseRevision": 1,
    })
    return plugin_dir


def make_packaged(plugin_dir: Path, tmp: Path) -> Path:
    """Replica o staging do pacote: overlays aplicados + proveniência."""
    from gateway.config import load_config

    config = load_config(plugin_dir / "gateway.json")
    staging = tmp / "staging"
    apply_overlays(plugin_dir / "upstream", plugin_dir / "overlays",
                   staging / "upstream", config.remove_paths)
    write_provenance(staging / "gateway-source.json", config)
    shutil.copyfile(plugin_dir / "kimi.plugin.json",
                    staging / "kimi.plugin.json")
    return staging


class ValidPluginTests(unittest.TestCase):
    def test_plugin_valido_retorna_sem_diagnosticos(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            self.assertEqual(validate_plugin(plugin_dir), [])

    def test_diretorio_inexistente_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationError):
                validate_plugin(Path(tmp) / "ausente")

    def test_upstream_ausente_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            shutil.rmtree(plugin_dir / "upstream")
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)


class ManifestValidationTests(unittest.TestCase):
    def test_manifesto_ausente_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "kimi.plugin.json").unlink()
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)

    def test_manifesto_invalido_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "kimi.plugin.json").write_text("{quebrado", encoding="utf-8")
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)

    def test_caminho_inexistente_no_manifesto_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["skills"] = ["./upstream/nope/"]
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn("nope", str(ctx.exception))

    def test_caminho_fora_de_upstream_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            (plugin_dir / "fora").mkdir()
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["skills"] = ["./fora/"]
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn("upstream", str(ctx.exception))

    def test_traversal_no_caminho_do_manifesto_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "escape").mkdir()
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["skills"] = ["./upstream/../escape/"]
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn("upstream", str(ctx.exception))

    def test_versao_invalida_no_manifesto_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["version"] = "1.0;echo"
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)


class HooksMcpValidationTests(unittest.TestCase):
    def test_hooks_no_manifesto_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["hooks"] = {"SessionStart": "../escape.sh"}
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn("hooks", str(ctx.exception))

    def test_mcp_no_manifesto_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["mcpServers"] = {"docs": {"command": "/bin/evil"}}
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn("mcpServers", str(ctx.exception))


class UpstreamSafetyValidationTests(unittest.TestCase):
    def test_git_dentro_de_upstream_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            git_dir = plugin_dir / "upstream" / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn(".git", str(ctx.exception))

    def test_gitlink_do_submodulo_em_upstream_e_permitido(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "upstream" / ".git").write_text(
                "gitdir: ../../../.git/modules/plugins/impeccable/upstream\n",
                encoding="utf-8",
            )
            validate_plugin(plugin_dir)

    def test_arquivo_git_sem_gitdir_em_upstream_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "upstream" / ".git").write_text(
                "conteúdo estranho\n", encoding="utf-8"
            )
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn(".git", str(ctx.exception))

    def test_arquivo_git_fora_de_upstream_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            nested = plugin_dir / "upstream" / ".claude"
            (nested / ".git").write_text(
                "gitdir: ../../../.git/modules/outro\n", encoding="utf-8"
            )
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(plugin_dir)
            self.assertIn(".git", str(ctx.exception))

    def test_symlink_escapando_de_upstream_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            outside = tmp / "fora"
            outside.mkdir()
            skills = plugin_dir / "upstream" / ".claude" / "skills"
            shutil.rmtree(skills)
            skills.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)


class GatewayFilesValidationTests(unittest.TestCase):
    def test_gateway_json_invalido_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            (plugin_dir / "gateway.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)

    def test_versao_divergente_do_manifesto_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["version"] = "9.9.9"
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            warnings = validate_plugin(plugin_dir)
            self.assertTrue(any("9.9.9" in w and "sourceVersion" in w for w in warnings))

    def test_overlay_sem_alvo_avisa_sem_bloquear(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            overlay = plugin_dir / "overlays" / "docs" / "extra.md"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("# extra\n", encoding="utf-8")
            warnings = validate_plugin(plugin_dir)
            self.assertTrue(any("docs/extra.md" in w for w in warnings))

    def test_overlay_redundante_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            skill = plugin_dir / "overlays" / ".claude" / "skills" / "impeccable"
            skill.mkdir(parents=True)
            original = plugin_dir / "upstream" / ".claude" / "skills" / "impeccable" / "SKILL.md"
            (skill / "SKILL.md").write_bytes(original.read_bytes())
            warnings = validate_plugin(plugin_dir)
            self.assertTrue(any("redundante" in w for w in warnings))

    def test_overlay_com_symlink_para_fora_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            outside = tmp / "fora.md"
            outside.write_text("fora\n", encoding="utf-8")
            (plugin_dir / "overlays" / "link.md").symlink_to(outside)
            with self.assertRaises(ValidationError):
                validate_plugin(plugin_dir)

    def test_remove_path_inexistente_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            gateway = read_json(plugin_dir / "gateway.json")
            gateway["overlays"] = {"remove": ["nope.txt"]}
            write_json(plugin_dir / "gateway.json", gateway)
            warnings = validate_plugin(plugin_dir)
            self.assertTrue(any("nope.txt" in w for w in warnings))

    def test_diretorio_overlays_ausente_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = make_plugin(Path(tmp))
            shutil.rmtree(plugin_dir / "overlays")
            warnings = validate_plugin(plugin_dir)
            self.assertTrue(any("overlays" in w for w in warnings))


class PackagedValidationTests(unittest.TestCase):
    def test_pacote_sem_proveniencia_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            staging = tmp / "staging"
            shutil.copytree(plugin_dir / "upstream", staging / "upstream")
            shutil.copyfile(plugin_dir / "kimi.plugin.json",
                            staging / "kimi.plugin.json")
            with self.assertRaises(ValidationError) as ctx:
                validate_plugin(staging, packaged=True)
            self.assertIn("gateway-source", str(ctx.exception))

    def test_pacote_com_proveniencia_valida(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            staging = make_packaged(plugin_dir, tmp)
            self.assertEqual(validate_plugin(staging, packaged=True), [])

    def test_proveniencia_com_id_divergente_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            staging = make_packaged(plugin_dir, tmp)
            source = read_json(staging / "gateway-source.json")
            source["id"] = "outro-plugin"
            write_json(staging / "gateway-source.json", source)
            with self.assertRaises(ValidationError):
                validate_plugin(staging, packaged=True)

    def test_hooks_no_pacote_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            staging = make_packaged(plugin_dir, tmp)
            manifest = read_json(staging / "kimi.plugin.json")
            manifest["mcpServers"] = {"docs": {"url": "https://example.com/mcp"}}
            write_json(staging / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError):
                validate_plugin(staging, packaged=True)


class ProvenanceTests(unittest.TestCase):
    def test_provenance_payload_registra_origem_e_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            from gateway.config import load_config

            config = load_config(plugin_dir / "gateway.json")
            payload = provenance_payload(config)
            self.assertEqual(payload["id"], "fixture-plugin")
            self.assertEqual(payload["upstream"]["url"], REPOSITORY_URL)
            self.assertEqual(payload["upstream"]["commit"], COMMIT)
            self.assertEqual(payload["upstream"]["sourceVersion"], "4.10.0")
            self.assertEqual(payload["releaseRevision"], 1)
            self.assertEqual(payload["tag"], release_tag(config))
            target = tmp / "gateway-source.json"
            write_provenance(target, config)
            self.assertEqual(read_json(target), payload)


if __name__ == "__main__":
    unittest.main()
