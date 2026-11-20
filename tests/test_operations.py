"""Testes das operações de conversão e atualização.

Os repositórios upstream são fixtures Git temporárias; a resolução
externa do GitHub (ref → SHA) e o fetch do snapshot são simulados por
fakes que operam somente sobre essas fixtures locais. A exceção é a
suíte de `resolve_remote_ref`, que exercita o `git ls-remote` real
contra repositórios locais para cobrir o destag de tags anotadas.
"""

import contextlib
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from gateway import operations
from gateway.config import load_config, release_url
from gateway.marketplace import upsert_marketplace_entry
from gateway.operations import (
    ConversionInputs,
    OperationError,
    UpdateInputs,
    convert_plugin,
    run_conversion,
    run_update,
    update_plugin,
)

MANIFEST_PATH = ".claude-plugin/plugin.json"
OWNER_REPO = "endersonmenezes/kimi-plugin-gateway"
REPOSITORY_URL = "https://github.com/fixture/plugin"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def make_upstream(
    tmp: Path,
    releases: list[tuple[str, str]],
    *,
    name: str = "fixture-plugin",
    manifest_path: str = MANIFEST_PATH,
    drop_skills_from: int | None = None,
) -> Path:
    """Cria um repositório Git temporário com um commit/tag por release.

    `releases` é uma lista de `(tag, versão_do_manifesto)`; o primeiro
    commit também recebe um branch `base`. Com `drop_skills_from=i`, o
    commit i remove o diretório de skills e o campo do manifesto.
    """
    repo = Path(tmp) / f"upstream-{uuid.uuid4().hex}"
    repo.mkdir()

    def commit_all(message: str) -> None:
        git(repo, "add", "-A")
        git(
            repo,
            "-c", "user.name=Gateway Tests",
            "-c", "user.email=tests@example.com",
            "commit", "-q", "-m", message,
        )

    git(repo, "init", "-q")
    for index, (tag, version) in enumerate(releases):
        manifest = {"name": name, "version": version}
        skills = repo / ".claude" / "skills" / "fixture"
        if drop_skills_from is None or index < drop_skills_from:
            skills.mkdir(parents=True, exist_ok=True)
            (skills / "SKILL.md").write_text(f"# fixture skill {index}\n", encoding="utf-8")
            manifest["skills"] = "./.claude/skills/"
        elif skills.exists():
            shutil.rmtree(repo / ".claude" / "skills")
        target = repo / manifest_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        commit_all(f"release {tag}")
        git(repo, "tag", "-a", "-m", f"release {tag}", tag)
    return repo


class FakeGitHub:
    """Simula a resolução externa do GitHub usando um repositório local."""

    def __init__(self, repo: Path):
        self.repo = Path(repo)
        self.calls: list[tuple] = []

    def resolve(self, repository_url: str, requested_ref: str) -> str:
        self.calls.append(("resolve", repository_url, requested_ref))
        return git(self.repo, "rev-parse", f"{requested_ref}^{{commit}}")

    def fetch(self, repository_url: str, commit: str, destination: Path) -> None:
        self.calls.append(("fetch", repository_url, commit))
        dest = Path(destination)
        subprocess.run(
            ["git", "clone", "--quiet", str(self.repo), str(dest)],
            check=True,
            capture_output=True,
        )
        git(dest, "checkout", "--quiet", "--detach", commit)
        shutil.rmtree(dest / ".git")


@contextlib.contextmanager
def simulated_github(fake: FakeGitHub):
    with mock.patch.object(operations, "resolve_remote_ref", fake.resolve), \
            mock.patch.object(operations, "fetch_upstream_tree", fake.fetch):
        yield


def conversion_inputs(**overrides) -> ConversionInputs:
    values = {
        "repository_url": REPOSITORY_URL,
        "requested_ref": "v1.0.0",
        "plugin_id": None,
        "manifest_path": MANIFEST_PATH,
    }
    values.update(overrides)
    return ConversionInputs(**values)


def update_inputs(**overrides) -> UpdateInputs:
    values = {"plugin_id": "fixture-plugin", "requested_ref": "v1.1.0"}
    values.update(overrides)
    return UpdateInputs(**values)


def make_repo_root(tmp: Path) -> Path:
    root = Path(tmp) / "repo"
    root.mkdir()
    return root


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def marketplace_path(root: Path) -> Path:
    path = root / "marketplace.json"
    write_json(path, {"version": "2", "plugins": []})
    return path


DANGEROUS_REFS = (
    "",
    "-x",
    "--upload-pack=/evil",
    "a..b",
    "v1.0^{}",
    "foo bar",
    "x@{y}",
    "*.lock",
    "refs/heads/x:y",
)


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class ResolveRemoteRefTests(unittest.TestCase):
    """Resolução real de refs: tags anotadas destagam para o commit.

    Regressão do caso `skill-v4.10.0` do Impeccable: um `ls-remote`
    filtrado omite a linha `^{}` e devolvia o SHA do objeto tag.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "upstream"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "arquivo.txt").write_text("conteúdo\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(
            self.repo,
            "-c", "user.name=Gateway Tests",
            "-c", "user.email=tests@example.com",
            "commit", "-q", "-m", "base",
        )
        self.commit = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "config", "tag.gpgSign", "false")
        git(self.repo, "tag", "-a", "-m", "release anotada", "v-anotada")
        self.tag_object = git(self.repo, "rev-parse", "v-anotada^{tag}")
        git(self.repo, "tag", "v-leve")
        git(self.repo, "branch", "ramo")

    def tearDown(self):
        self._tmp.cleanup()

    def resolve(self, ref: str) -> str:
        return operations.resolve_remote_ref(str(self.repo), ref)

    def test_tag_anotada_resolve_no_commit_destag(self):
        resolved = self.resolve("v-anotada")
        self.assertEqual(resolved, self.commit)
        self.assertNotEqual(resolved, self.tag_object)
        self.assertTrue(resolved.isalnum() and len(resolved) == 40)

    def test_tag_leve_resolve_no_commit(self):
        self.assertEqual(self.resolve("v-leve"), self.commit)

    def test_branch_resolve_no_commit(self):
        self.assertEqual(self.resolve("ramo"), self.commit)

    def test_sha_completo_e_aceito_diretamente(self):
        self.assertEqual(self.resolve(self.commit), self.commit)

    def test_ref_inexistente_e_erro(self):
        with self.assertRaises(OperationError):
            self.resolve("nao-existe")


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class ConvertOperationTests(unittest.TestCase):
    def test_convert_creates_plugin_files_and_marketplace_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            sha = fake.resolve(REPOSITORY_URL, "v1.0.0")
            with simulated_github(fake):
                result = run_conversion(
                    root, conversion_inputs(plugin_id="fixture-plugin")
                )

            self.assertEqual(result.plugin_dir, root / "plugins" / "fixture-plugin")
            self.assertEqual(result.plugin_id, "fixture-plugin")
            self.assertEqual(result.commit, sha)
            self.assertEqual(result.tag, "fixture-plugin-v1.0.0-gateway.1")
            plugin_dir = result.plugin_dir
            self.assertTrue((plugin_dir / "gateway.json").is_file())
            self.assertTrue((plugin_dir / "kimi.plugin.json").is_file())
            self.assertTrue((plugin_dir / "overlays").is_dir())
            self.assertFalse((plugin_dir / "upstream" / ".git").exists())
            self.assertTrue((plugin_dir / "upstream" / MANIFEST_PATH).is_file())

            config = load_config(plugin_dir / "gateway.json")
            self.assertEqual(config.upstream_url, REPOSITORY_URL)
            self.assertEqual(config.requested_ref, "v1.0.0")
            self.assertEqual(config.commit, sha)
            self.assertEqual(config.source_version, "1.0.0")
            self.assertEqual(config.release_revision, 1)

            manifest = read_json(plugin_dir / "kimi.plugin.json")
            self.assertEqual(manifest["name"], "fixture-plugin")
            self.assertEqual(manifest["version"], "1.0.0")
            self.assertEqual(manifest["skills"], ["./upstream/.claude/skills/"])

            marketplace = marketplace_path(root)
            upsert_marketplace_entry(
                marketplace, config, OWNER_REPO, "Fixture Plugin"
            )
            data = read_json(marketplace)
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
            self.assertTrue(any("convertido: skills" in e for e in result.report))
            self.assertTrue(any("tag de release" in e for e in result.report))

    def test_convert_plugin_returns_plugin_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            root = make_repo_root(tmp)
            with simulated_github(FakeGitHub(upstream)):
                plugin_dir = convert_plugin(
                    root, conversion_inputs(plugin_id="fixture-plugin")
                )
            self.assertEqual(plugin_dir, root / "plugins" / "fixture-plugin")
            self.assertTrue((plugin_dir / "gateway.json").is_file())

    def test_convert_uses_manifest_name_when_plugin_id_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            root = make_repo_root(tmp)
            with simulated_github(FakeGitHub(upstream)):
                result = run_conversion(root, conversion_inputs())
            self.assertEqual(result.plugin_id, "fixture-plugin")
            self.assertTrue(
                (root / "plugins" / "fixture-plugin" / "gateway.json").is_file()
            )

    def test_convert_supports_custom_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(
                tmp, [("v1.0.0", "1.0.0")], manifest_path="plugin.json"
            )
            root = make_repo_root(tmp)
            with simulated_github(FakeGitHub(upstream)):
                result = run_conversion(
                    root, conversion_inputs(manifest_path="plugin.json")
                )
            config = load_config(root / "plugins" / result.plugin_id / "gateway.json")
            self.assertEqual(config.manifest_path, "plugin.json")

    def test_convert_rejects_duplicate_id_without_touching_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            with simulated_github(fake):
                run_conversion(root, conversion_inputs(plugin_id="fixture-plugin"))
                fake.calls.clear()
                with self.assertRaises(OperationError) as ctx:
                    run_conversion(
                        root, conversion_inputs(plugin_id="fixture-plugin")
                    )
        self.assertIn("fixture-plugin", str(ctx.exception))
        self.assertEqual(fake.calls, [])

    def test_convert_rejects_dangerous_refs_before_any_git_call(self):
        for ref in DANGEROUS_REFS:
            with self.subTest(ref=ref):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp = Path(tmp)
                    upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
                    fake = FakeGitHub(upstream)
                    root = make_repo_root(tmp)
                    with simulated_github(fake):
                        with self.assertRaises((OperationError, ValueError)):
                            run_conversion(
                                root, conversion_inputs(requested_ref=ref)
                            )
                    self.assertEqual(fake.calls, [])

    def test_convert_rejects_invalid_repository_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            with simulated_github(fake):
                with self.assertRaises(ValueError):
                    run_conversion(
                        root,
                        conversion_inputs(
                            repository_url="https://example.com/x/y"
                        ),
                    )
            self.assertEqual(fake.calls, [])

    def test_convert_result_report_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp, [("v1.0.0", "1.0.0")])
            root = make_repo_root(tmp)
            with simulated_github(FakeGitHub(upstream)):
                first = run_conversion(root, conversion_inputs())
            shutil.rmtree(root / "plugins")
            with simulated_github(FakeGitHub(upstream)):
                second = run_conversion(root, conversion_inputs())
        self.assertEqual(first.report, second.report)
        self.assertEqual(first.tag, second.tag)


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class UpdateOperationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.upstream = make_upstream(
            tmp, [("v1.0.0", "1.0.0"), ("v1.1.0", "1.1.0")]
        )
        self.fake = FakeGitHub(self.upstream)
        self.root = make_repo_root(tmp)
        with simulated_github(self.fake):
            self.initial = run_conversion(
                self.root, conversion_inputs(plugin_id="fixture-plugin")
            )
        self.plugin_dir = self.initial.plugin_dir
        self.first_sha = self.initial.commit

    def tearDown(self):
        self._tmp.cleanup()

    def update(self, ref: str):
        with simulated_github(self.fake):
            return run_update(self.root, update_inputs(requested_ref=ref))

    def test_update_moves_ref_commit_and_version(self):
        result = self.update("v1.1.0")
        config = load_config(self.plugin_dir / "gateway.json")
        self.assertEqual(config.requested_ref, "v1.1.0")
        self.assertNotEqual(config.commit, self.first_sha)
        self.assertEqual(config.commit, result.commit)
        self.assertEqual(config.source_version, "1.1.0")
        self.assertEqual(config.release_revision, 1)
        self.assertEqual(result.tag, "fixture-plugin-v1.1.0-gateway.1")
        manifest = read_json(self.plugin_dir / "kimi.plugin.json")
        self.assertEqual(manifest["version"], "1.1.0")
        self.assertTrue(
            (self.plugin_dir / "upstream" / MANIFEST_PATH).is_file()
        )

    def test_update_never_changes_the_registered_url(self):
        self.update("v1.1.0")
        config = load_config(self.plugin_dir / "gateway.json")
        self.assertEqual(config.upstream_url, REPOSITORY_URL)

    def test_update_preserves_human_fields_and_overlays(self):
        kimi_path = self.plugin_dir / "kimi.plugin.json"
        manifest = read_json(kimi_path)
        manifest["description"] = "edição humana preservada"
        manifest["customNote"] = "campo humano"
        write_json(kimi_path, manifest)

        gateway_path = self.plugin_dir / "gateway.json"
        gateway = read_json(gateway_path)
        gateway["overlays"] = {"remove": ["bin/legacy.sh"]}
        write_json(gateway_path, gateway)

        overlay = self.plugin_dir / "overlays" / ".claude" / "skills" / "fixture"
        overlay.mkdir(parents=True)
        (overlay / "SKILL.md").write_text("# overlay humano\n", encoding="utf-8")

        self.update("v1.1.0")

        updated = read_json(kimi_path)
        self.assertEqual(updated["description"], "edição humana preservada")
        self.assertEqual(updated["customNote"], "campo humano")
        self.assertEqual(updated["version"], "1.1.0")
        self.assertEqual(
            (overlay / "SKILL.md").read_text(encoding="utf-8"), "# overlay humano\n"
        )
        config = load_config(gateway_path)
        self.assertEqual(config.remove_paths, ["bin/legacy.sh"])

    def test_update_resets_revision_when_version_changes(self):
        self.update("v1.1.0")
        config = load_config(self.plugin_dir / "gateway.json")
        self.assertEqual(config.release_revision, 1)

    def test_update_increments_revision_when_version_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(
                tmp, [("v1.0.0", "1.0.0"), ("v1.0.1", "1.0.0")]
            )
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            with simulated_github(fake):
                run_conversion(root, conversion_inputs(plugin_id="fixture-plugin"))
                result = run_update(root, update_inputs(requested_ref="v1.0.1"))
            config = load_config(root / "plugins" / "fixture-plugin" / "gateway.json")
            self.assertEqual(config.requested_ref, "v1.0.1")
            self.assertEqual(config.source_version, "1.0.0")
            self.assertEqual(config.release_revision, 2)
            self.assertEqual(result.tag, "fixture-plugin-v1.0.0-gateway.2")

    def test_update_to_same_commit_is_a_noop(self):
        result = self.update("v1.0.0")
        config = load_config(self.plugin_dir / "gateway.json")
        self.assertEqual(config.commit, self.first_sha)
        self.assertEqual(config.release_revision, 1)
        self.assertTrue(any("sem mudanças" in e for e in result.report))

    def test_update_reports_capability_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(
                tmp,
                [("v1.0.0", "1.0.0"), ("v2.0.0", "2.0.0")],
                drop_skills_from=1,
            )
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            with simulated_github(fake):
                run_conversion(root, conversion_inputs(plugin_id="fixture-plugin"))
                result = run_update(root, update_inputs(requested_ref="v2.0.0"))
            self.assertTrue(
                any("removida" in e and "skills" in e for e in result.report)
            )

    def test_update_keeps_overlay_when_target_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(
                tmp,
                [("v1.0.0", "1.0.0"), ("v2.0.0", "2.0.0")],
                drop_skills_from=1,
            )
            fake = FakeGitHub(upstream)
            root = make_repo_root(tmp)
            with simulated_github(fake):
                initial = run_conversion(
                    root, conversion_inputs(plugin_id="fixture-plugin")
                )
            overlay = initial.plugin_dir / "overlays" / ".claude" / "skills" / "fixture"
            overlay.mkdir(parents=True)
            (overlay / "SKILL.md").write_text("# overlay humano\n", encoding="utf-8")
            with simulated_github(fake):
                result = run_update(root, update_inputs(requested_ref="v2.0.0"))
            self.assertTrue((overlay / "SKILL.md").is_file())
            self.assertTrue(
                any("afetado" in e and ".claude/skills" in e for e in result.report)
            )

    def test_update_unknown_plugin_fails(self):
        with simulated_github(self.fake):
            with self.assertRaises(OperationError):
                run_update(
                    self.root, update_inputs(plugin_id="plugin-inexistente")
                )

    def test_update_rejects_dangerous_refs_before_any_git_call(self):
        for ref in DANGEROUS_REFS:
            with self.subTest(ref=ref):
                self.fake.calls.clear()
                with simulated_github(self.fake):
                    with self.assertRaises((OperationError, ValueError)):
                        run_update(self.root, update_inputs(requested_ref=ref))
                self.assertEqual(self.fake.calls, [])

    def test_update_plugin_returns_plugin_dir(self):
        with simulated_github(self.fake):
            plugin_dir = update_plugin(self.root, update_inputs())
        self.assertEqual(plugin_dir, self.root / "plugins" / "fixture-plugin")
        config = load_config(plugin_dir / "gateway.json")
        self.assertEqual(config.source_version, "1.1.0")

    def test_update_marketplace_entry_uses_new_deterministic_url(self):
        self.update("v1.1.0")
        config = load_config(self.plugin_dir / "gateway.json")
        marketplace = marketplace_path(self.root)
        upsert_marketplace_entry(marketplace, config, OWNER_REPO, "Fixture Plugin")
        data = read_json(marketplace)
        self.assertEqual(
            data["plugins"][0]["source"], release_url(config, OWNER_REPO)
        )
        self.assertIn("fixture-plugin-v1.1.0-gateway.1", data["plugins"][0]["source"])


if __name__ == "__main__":
    unittest.main()
