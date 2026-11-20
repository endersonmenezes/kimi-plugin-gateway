"""Testes dos pacotes autocontidos: ZIP por plugin com SHA-256 estável.

O pacote tem o manifesto e a proveniência na raiz, cópia real de
upstream/ com overlays aplicados e sem `.git`. A fixture inclui um
script-marca upstream que prova que nenhuma etapa executa código do
upstream.
"""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

from gateway import operations
from gateway.operations import ConversionInputs, run_conversion
from gateway.package import PackageResult, build_package
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
    from gateway.conversion import convert_manifest, write_kimi_manifest

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


def zip_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def zip_bytes(zip_path: Path, name: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name)


def make_crafted_zip(tmp: Path, extra_names: list[str]) -> Path:
    """ZIP mínimo válido (raiz completa) com entradas extras nomeadas."""
    zip_path = tmp / "crafted.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("kimi.plugin.json",
                    json.dumps({"name": "crafted", "version": "1.0.0"}))
        zf.writestr("gateway-source.json", json.dumps({
            "id": "crafted",
            "upstream": {
                "url": REPOSITORY_URL,
                "requestedRef": "v1.0.0",
                "commit": "a" * 40,
                "sourceVersion": "1.0.0",
            },
            "releaseRevision": 1,
            "tag": "crafted-v1.0.0-gateway.1",
        }))
        for name in extra_names:
            zf.writestr(name, "conteúdo\n")
    return zip_path


class ZipNameSafetyTests(unittest.TestCase):
    def test_zip_sem_nomes_maliciosos_passa_no_gate(self):
        from gateway.package import _validate_zip

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = make_crafted_zip(Path(tmp), ["upstream/arquivo.txt"])
            self.assertEqual(_validate_zip(zip_path), [])

    def test_traversal_e_absoluto_em_forma_de_backslash_sao_rejeitados(self):
        from gateway.package import _validate_zip

        malicious = (
            "sub\\..\\evil.txt",
            "..\\evil.txt",
            "C:\\evil.txt",
            "\\\\server\\share\\evil.txt",
            "a/../b.txt",
            "/abs/evil.txt",
        )
        for name in malicious:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    zip_path = make_crafted_zip(Path(tmp), [name])
                    with self.assertRaises(ValidationError) as ctx:
                        _validate_zip(zip_path)
                self.assertIn("inseguro", str(ctx.exception))


class PackageLayoutTests(unittest.TestCase):
    def test_manifesto_e_proveniencia_na_raiz_do_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            result = build_package(plugin_dir, tmp / "dist")
            names = zip_names(result.zip_path)
            self.assertIn("kimi.plugin.json", names)
            self.assertIn("gateway-source.json", names)
            self.assertIn("upstream/.claude-plugin/plugin.json", names)
            provenance = json.loads(zip_bytes(result.zip_path, "gateway-source.json"))
            self.assertEqual(provenance["id"], "fixture-plugin")
            self.assertEqual(
                provenance["upstream"],
                {
                    "url": REPOSITORY_URL,
                    "requestedRef": "v1.0.0",
                    "commit": COMMIT,
                    "sourceVersion": "4.10.0",
                },
            )
            self.assertEqual(
                provenance["tag"], "fixture-plugin-v4.10.0-gateway.1"
            )

    def test_zip_contem_skills_reais_dentro_de_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            result = build_package(plugin_dir, tmp / "dist")
            skill = "upstream/.claude/skills/impeccable/SKILL.md"
            self.assertEqual(
                zip_bytes(result.zip_path, skill),
                (FIXTURE / ".claude" / "skills" / "impeccable" / "SKILL.md")
                .read_bytes(),
            )

    def test_zip_nao_contem_git_nem_overlays_nem_gateway_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            git_dir = plugin_dir / "upstream" / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            overlay = plugin_dir / "overlays" / "docs" / "extra.md"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("# extra\n", encoding="utf-8")
            result = build_package(plugin_dir, tmp / "dist")
            names = zip_names(result.zip_path)
            self.assertNotIn("gateway.json", names)
            self.assertFalse(any(n.startswith("overlays/") for n in names))
            self.assertFalse(any(".git" in n.split("/") for n in names))
            self.assertIn("upstream/docs/extra.md", names)
            # o diretório de origem permanece intacto para a revisão humana
            self.assertTrue((plugin_dir / "upstream" / ".git" / "HEAD").is_file())
            self.assertTrue(overlay.is_file())


class OverlayAndRemovalPackagingTests(unittest.TestCase):
    def test_overlay_aplicado_no_zip_sem_tocar_o_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            skill = plugin_dir / "overlays" / ".claude" / "skills" / "impeccable"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# versão humana\n", encoding="utf-8")
            result = build_package(plugin_dir, tmp / "dist")
            packaged = zip_bytes(
                result.zip_path, "upstream/.claude/skills/impeccable/SKILL.md"
            )
            self.assertEqual(packaged.decode(), "# versão humana\n")
            original = plugin_dir / "upstream" / ".claude" / "skills" / "impeccable" / "SKILL.md"
            self.assertEqual(
                original.read_text(encoding="utf-8"),
                (FIXTURE / ".claude" / "skills" / "impeccable" / "SKILL.md")
                .read_text(encoding="utf-8"),
            )
            self.assertFalse(any("redundante" in w for w in result.warnings))

    def test_overlay_sem_alvo_gera_aviso_no_resultado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            overlay = plugin_dir / "overlays" / "docs" / "extra.md"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("# extra\n", encoding="utf-8")
            result = build_package(plugin_dir, tmp / "dist")
            self.assertIn("upstream/docs/extra.md", zip_names(result.zip_path))
            self.assertTrue(any("docs/extra.md" in w for w in result.warnings))

    def test_remocao_declarada_reflita_no_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            legacy = plugin_dir / "upstream" / "bin"
            legacy.mkdir()
            (legacy / "legacy.sh").write_text("# legado\n", encoding="utf-8")
            gateway = read_json(plugin_dir / "gateway.json")
            gateway["overlays"] = {"remove": ["bin/legacy.sh"]}
            write_json(plugin_dir / "gateway.json", gateway)
            result = build_package(plugin_dir, tmp / "dist")
            self.assertNotIn("upstream/bin/legacy.sh", zip_names(result.zip_path))
            self.assertTrue(
                (plugin_dir / "upstream" / "bin" / "legacy.sh").is_file()
            )
            self.assertTrue(any("bin/legacy.sh" in w for w in result.warnings))


class PackageDeterminismTests(unittest.TestCase):
    def test_checksum_estavel_entre_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            first = build_package(plugin_dir, tmp / "dist-a")
            second = build_package(plugin_dir, tmp / "dist-b")
            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(
                first.zip_path.read_bytes(), second.zip_path.read_bytes()
            )
            self.assertEqual(
                first.sha256,
                hashlib.sha256(first.zip_path.read_bytes()).hexdigest(),
            )

    def test_dois_plugins_produzem_arquivos_separados(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            alpha = make_plugin(tmp, "plugin-alpha")
            beta = make_plugin(tmp, "plugin-beta")
            result_a = build_package(alpha, tmp / "dist")
            result_b = build_package(beta, tmp / "dist")
            self.assertEqual(result_a.zip_path.name, "plugin-alpha.zip")
            self.assertEqual(result_b.zip_path.name, "plugin-beta.zip")
            self.assertNotEqual(result_a.sha256, result_b.sha256)
            manifest_a = json.loads(zip_bytes(result_a.zip_path, "kimi.plugin.json"))
            manifest_b = json.loads(zip_bytes(result_b.zip_path, "kimi.plugin.json"))
            self.assertEqual(manifest_a["name"], "plugin-alpha")
            self.assertEqual(manifest_b["name"], "plugin-beta")


class PackageFailureTests(unittest.TestCase):
    def test_build_falha_quando_validacao_do_staging_falha(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["skills"] = ["./upstream/nope/"]
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError):
                build_package(plugin_dir, tmp / "dist")

    def test_build_falha_sem_gateway_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            (plugin_dir / "gateway.json").unlink()
            with self.assertRaises(ValidationError):
                build_package(plugin_dir, tmp / "dist")

    def test_build_falha_com_hooks_no_manifesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            manifest = read_json(plugin_dir / "kimi.plugin.json")
            manifest["hooks"] = {"SessionStart": "echo pwned"}
            write_json(plugin_dir / "kimi.plugin.json", manifest)
            with self.assertRaises(ValidationError):
                build_package(plugin_dir, tmp / "dist")

    def test_resultado_traz_caminho_sha256_e_avisos(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plugin_dir = make_plugin(tmp)
            overlay = plugin_dir / "overlays" / "docs" / "extra.md"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("# extra\n", encoding="utf-8")
            result = build_package(plugin_dir, tmp / "dist")
            self.assertIsInstance(result, PackageResult)
            self.assertEqual(result.plugin_id, "fixture-plugin")
            self.assertTrue(result.zip_path.is_file())
            self.assertEqual(len(result.sha256), 64)
            self.assertTrue(any("docs/extra.md" in w for w in result.warnings))


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class FakeGitHub:
    """Simula a resolução externa do GitHub usando um repositório local."""

    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def resolve(self, repository_url: str, requested_ref: str) -> str:
        return git(self.repo, "rev-parse", f"{requested_ref}^{{commit}}")

    def fetch(self, repository_url: str, commit: str, destination: Path) -> None:
        dest = Path(destination)
        subprocess.run(
            ["git", "clone", "--quiet", str(self.repo), str(dest)],
            check=True,
            capture_output=True,
        )
        git(dest, "checkout", "--quiet", "--detach", commit)
        shutil.rmtree(dest / ".git")


def make_upstream_repo(tmp: Path) -> Path:
    repo = tmp / f"upstream-{uuid.uuid4().hex}"
    shutil.copytree(FIXTURE, repo)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(
        repo,
        "-c", "user.name=Gateway Tests",
        "-c", "user.email=tests@example.com",
        "commit", "-q", "-m", "fixture com script-marca",
    )
    git(repo, "tag", "-a", "-m", "release v4.10.0", "v4.10.0")
    return repo


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class MarkerScriptTests(unittest.TestCase):
    def test_script_marca_nunca_executa_em_conversao_validacao_e_pacote(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = make_upstream_repo(tmp)
            root = tmp / "repo"
            root.mkdir()
            fake = FakeGitHub(repo)
            with mock.patch.object(operations, "resolve_remote_ref", fake.resolve), \
                    mock.patch.object(operations, "fetch_upstream_tree", fake.fetch):
                result = run_conversion(
                    root,
                    ConversionInputs(
                        repository_url=REPOSITORY_URL,
                        requested_ref="v4.10.0",
                        plugin_id="marcador",
                        manifest_path=MANIFEST_PATH,
                    ),
                )
            plugin_dir = result.plugin_dir
            script = plugin_dir / "upstream" / ".claude" / "skills" / "impeccable" / "probe.sh"
            self.assertTrue(script.is_file())

            warnings = validate_plugin(plugin_dir)
            self.assertIsInstance(warnings, list)
            package = build_package(plugin_dir, tmp / "dist")

            with zipfile.ZipFile(package.zip_path) as zf:
                names = zf.namelist()
                extract_dir = tmp / "extraido"
                extract_dir.mkdir()
                zf.extractall(extract_dir)

            # o script foi copiado de verdade para o pacote...
            self.assertIn("upstream/.claude/skills/impeccable/probe.sh", names)
            self.assertTrue(
                (extract_dir / "upstream" / ".claude" / "skills" / "impeccable" / "probe.sh")
                .is_file()
            )
            # ...mas a marca nunca foi criada: nada upstream executou
            self.assertEqual(list(tmp.rglob("MARCA-EXECUTADO.txt")), [])


if __name__ == "__main__":
    unittest.main()
