"""Testes da seleção de plugins para release a partir do diff de um push.

O cenário usa repositórios Git temporários: alterações em documentação,
scripts e workflows não geram release; mudanças sob `plugins/<id>/`
selecionam exatamente aquele id, ordenado e sem duplicatas. Push inicial
(SHA anterior zerado) difere contra a árvore vazia e branch excluída
(SHA posterior zerado) seleciona nada.
"""

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gateway.cli import INPUT_ERROR_EXIT, main
from gateway.release import ReleaseError, changed_plugins

ZERO_SHA = "0" * 40
NONZERO = "0123456789abcdef0123456789abcdef01234567"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def make_repo(tmp: Path) -> Path:
    repo = tmp / "gateway-repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "gateway-test@example.com")
    git(repo, "config", "user.name", "Gateway Test")
    return repo


def commit_file(repo: Path, rel: str, content: str = "conteúdo\n") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "--", rel)
    git(repo, "commit", "-q", "-m", f"altera {rel}")
    return git(repo, "rev-parse", "HEAD")


def add_gitlink(repo: Path, rel: str) -> str:
    """Cria uma entrada de submódulo (gitlink) sem clone externo."""
    git(repo, "update-index", "--add", "--cacheinfo",
        f"160000,{NONZERO},{rel}")
    git(repo, "commit", "-q", "-m", f"adiciona {rel}")
    return git(repo, "rev-parse", "HEAD")


def write_event(tmp: Path, payload: dict) -> Path:
    path = Path(tmp) / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class ChangedPluginsSelectionTests(unittest.TestCase):
    def test_alteracao_somente_em_docs_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md", "docs\n")
            last = commit_file(repo, "docs/guia.md", "guia\n")
            self.assertEqual(changed_plugins(repo, first, last), [])

    def test_alteracao_em_scripts_e_workflows_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, ".github/workflows/release.yml", "on: push\n")
            last = commit_file(repo, "scripts/gateway/release.py", "código\n")
            self.assertEqual(changed_plugins(repo, first, last), [])

    def test_alteracao_isolada_em_um_plugin_retorna_apenas_esse_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md")
            last = commit_file(
                repo, "plugins/alpha/upstream/skill/SKILL.md", "skill\n"
            )
            self.assertEqual(changed_plugins(repo, first, last), ["alpha"])

    def test_alteracoes_em_dois_plugins_retornam_dois_ids_ordenados(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md")
            commit_file(repo, "plugins/beta/kimi.plugin.json", "{}\n")
            last = commit_file(repo, "plugins/alpha/gateway.json", "{}\n")
            self.assertEqual(changed_plugins(repo, first, last),
                             ["alpha", "beta"])

    def test_varios_commits_no_mesmo_plugin_nao_duplicam_o_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md")
            commit_file(repo, "plugins/alpha/gateway.json", "v1\n")
            commit_file(repo, "plugins/alpha/kimi.plugin.json", "v1\n")
            last = commit_file(
                repo, "plugins/alpha/overlays/nota.md", "overlay\n"
            )
            self.assertEqual(changed_plugins(repo, first, last), ["alpha"])

    def test_caminhos_fora_de_plugins_sao_ignorados_mesmo_com_prefixo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md")
            last = commit_file(repo, "plugins.txt", "não é plugin\n")
            self.assertEqual(changed_plugins(repo, first, last), [])

    def test_gitlink_de_submodulo_em_plugins_conta_como_mudanca_do_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            first = commit_file(repo, "README.md")
            last = add_gitlink(repo, "plugins/gamma")
            self.assertEqual(changed_plugins(repo, first, last), ["gamma"])

    def test_push_inicial_com_before_zerado_seleciona_plugins_presentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            commit_file(repo, "README.md")
            commit_file(repo, "plugins/alpha/gateway.json", "{}\n")
            after = commit_file(repo, "plugins/beta/gateway.json", "{}\n")
            self.assertEqual(changed_plugins(repo, ZERO_SHA, after),
                             ["alpha", "beta"])

    def test_push_inicial_sem_nenhum_plugin_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            after = commit_file(repo, "README.md")
            self.assertEqual(changed_plugins(repo, ZERO_SHA, after), [])

    def test_branch_excluida_com_after_zerado_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            before = commit_file(repo, "plugins/alpha/gateway.json", "{}\n")
            self.assertEqual(changed_plugins(repo, before, ZERO_SHA), [])

    def test_sha_invalido_rejeitado_antes_de_qualquer_chamada_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            after = commit_file(repo, "README.md")
            for bad in ("abc", "G" * 40, "", "main", "-" * 40):
                with self.subTest(before=bad):
                    with self.assertRaises(ReleaseError):
                        changed_plugins(repo, bad, after)
            for bad in ("xyz", "1" * 39, "refs/heads/main"):
                with self.subTest(after=bad):
                    with self.assertRaises(ReleaseError):
                        changed_plugins(repo, ZERO_SHA, bad)

    def test_repositorio_invalido_produz_erro_explicito(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "nao-e-repo"
            root.mkdir()
            with self.assertRaises(ReleaseError):
                changed_plugins(root, ZERO_SHA, NONZERO)


@unittest.skipIf(shutil.which("git") is None, "git não disponível")
class ChangedPluginsCliTests(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_changed_plugins_emite_json_com_ids_ordenados(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = make_repo(tmp)
            first = commit_file(repo, "README.md")
            commit_file(repo, "plugins/beta/gateway.json", "{}\n")
            last = commit_file(repo, "plugins/alpha/gateway.json", "{}\n")
            event = write_event(tmp, {"before": first, "after": last})

            code, out, _ = self.run_cli([
                "changed-plugins", "--event-path", str(event),
                "--repo-root", str(repo),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), {"plugins": ["alpha", "beta"]})

    def test_changed_plugins_sem_alteracao_emite_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = make_repo(tmp)
            first = commit_file(repo, "README.md")
            last = commit_file(repo, "docs/guia.md", "guia\n")
            event = write_event(tmp, {"before": first, "after": last})

            code, out, _ = self.run_cli([
                "changed-plugins", "--event-path", str(event),
                "--repo-root", str(repo),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), {"plugins": []})

    def test_evento_inexistente_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_cli([
                "changed-plugins", "--event-path",
                str(Path(tmp) / "faltando.json"), "--repo-root", tmp,
            ])

            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("evento", err)

    def test_evento_sem_before_ou_after_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = make_repo(tmp)
            after = commit_file(repo, "README.md")
            event = write_event(tmp, {"after": after})

            code, _, err = self.run_cli([
                "changed-plugins", "--event-path", str(event),
                "--repo-root", str(repo),
            ])

            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("before", err)


if __name__ == "__main__":
    unittest.main()
