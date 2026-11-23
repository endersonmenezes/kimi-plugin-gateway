"""Testes estáticos dos workflows IssueOps, validação, release e governança.

Os arquivos YAML são lidos como texto (sem parser externo) e conferem:
- disparos (`issues: opened` com rótulo, `workflow_dispatch`, PRs, push em
  `main`); permissões mínimas por workflow;
- ausência de interpolação `${{ ... }}` nos blocos `run` (campos de Issue
  chegam somente como caminho de evento via `--issue-event`);
- evento da Issue materializado no mesmo job que roda o CLI (`RUNNER_TEMP`
  não é compartilhado entre jobs: o caminho nunca vem de
  `needs.prepare.outputs.event-path` e o job do CLI refaz `gh issue view`);
- checkout recursivo em todos os jobs que tocam em plugins;
- proibição de force-push; releases somente após `main` ou dispatch
  autorizado; criação de release sem flags de substituição e com
  verificação prévia de tag/asset existente;
- Issue Forms com os títulos exatos dos campos que o CLI espera;
- CODEOWNERS apontando para o mantenedor.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB = REPO_ROOT / ".github"
WORKFLOWS = GITHUB / "workflows"
TEMPLATES = GITHUB / "ISSUE_TEMPLATE"

ISSUEOPS_WORKFLOWS = ("convert-plugin.yml", "update-plugin.yml")

FORBIDDEN_SCOPES = ("id-token", "actions:", "packages:",
                    "deployments:", "pages:")

CONVERT_FIELD_TITLES = (
    "Public GitHub repository URL",
    "Source tag, branch, or commit",
    "Desired Gateway plugin ID (optional)",
    "Claude manifest path",
    "Adaptation notes (optional)",
)
UPDATE_FIELD_TITLES = (
    "Gateway plugin ID",
    "Source tag, branch, or commit",
    "Update reason (optional)",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_blocks(text: str) -> list[str]:
    """Extrai os blocos `run:` de um workflow YAML como texto puro."""
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if re.match(r"^run:\s*[|>]", stripped):
            indent = len(lines[i]) - len(lines[i].lstrip())
            i += 1
            block: list[str] = []
            while i < len(lines):
                line = lines[i]
                if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                    break
                block.append(line)
                i += 1
            blocks.append("\n".join(block))
        elif stripped.startswith("run:"):
            blocks.append(stripped[len("run:"):].strip())
            i += 1
        else:
            i += 1
    return blocks


class WorkflowFilesExistenceTests(unittest.TestCase):
    def test_arquivos_obrigatorios_existem(self):
        expected = [
            WORKFLOWS / name for name in (
                "convert-plugin.yml", "update-plugin.yml",
                "validate.yml", "release.yml",
            )
        ] + [
            TEMPLATES / name
            for name in ("convert-plugin.yml", "update-plugin.yml")
        ] + [GITHUB / "CODEOWNERS"]
        for path in expected:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"ausente: {path}")


class IssueOpsWorkflowStaticTests(unittest.TestCase):
    """Garantias comuns aos workflows de conversão e atualização."""

    label_by_workflow = {
        "convert-plugin.yml": "conversion",
        "update-plugin.yml": "update",
    }

    def setUp(self):
        self.texts = {
            name: read(WORKFLOWS / name) for name in ISSUEOPS_WORKFLOWS
        }

    def test_disparado_por_issue_aberta_com_rotulo_e_dispatch(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn("issues:", text)
                self.assertIn("opened", text)
                self.assertIn("workflow_dispatch:", text)
                self.assertIn("issue-number", text)
                self.assertIn(self.label_by_workflow[name], text)

    def test_permissoes_minimas_sem_escopos_perigosos(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                for scope in FORBIDDEN_SCOPES:
                    self.assertNotIn(scope, text)
                self.assertIn("contents: write", text)
                self.assertIn("pull-requests: write", text)
                self.assertIn("issues: write", text)

    def test_blocos_run_sem_interpolacao_de_contexto(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                blocks = run_blocks(text)
                self.assertTrue(blocks, "nenhum bloco run encontrado")
                for block in blocks:
                    self.assertNotIn("${{", block)
                    self.assertNotIn("github.event.issue", block)

    def test_cli_recebe_apenas_o_caminho_do_evento(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn('--issue-event "$EVENT_PATH"', text)
                self.assertNotIn("--repository-url", text)
                self.assertNotIn("--ref ", text)
                for line in text.splitlines():
                    if "--plugin-id" in line:
                        self.assertIn(
                            '--plugin-id "$PLUGIN_ID"', line,
                            "--plugin-id só pode vir da saída validada do CLI",
                        )

    def test_evento_da_issue_e_materializado_no_job_que_roda_o_cli(self):
        """RUNNER_TEMP é por runner: o evento não pode cruzar jobs via
        output; o job do CLI refaz `gh issue view` e grava o arquivo
        localmente antes de chamar `--issue-event`."""
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("needs.prepare.outputs.event-path", text)
                self.assertIn('gh issue view "$ISSUE_NUMBER"', text)
                self.assertIn("issue-event.json", text)
                self.assertIn("steps.issue-event.outputs.event-path", text)

    def test_checkout_recursivo_em_todos_os_jobs(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                checkouts = text.count("uses: actions/checkout@")
                recursive = text.count("submodules: recursive")
                self.assertGreaterEqual(checkouts, 1)
                self.assertEqual(checkouts, recursive)

    def test_sem_force_push_e_sem_publicacao_de_release(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("--force", text)
                self.assertIn("git push", text)
                self.assertNotIn("gh release", text)

    def test_concorrencia_serializada_por_id(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn("concurrency:", text)
                self.assertIn("cancel-in-progress: false", text)

    def test_branch_deterministica_pr_e_comentario_de_erro(self):
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertIn("issueops/issue-", text)
                self.assertIn("gh pr create", text)
                self.assertIn("if: failure()", text)
                self.assertIn("gh issue comment", text)


class ValidateWorkflowStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = read(WORKFLOWS / "validate.yml")

    def test_disparado_em_prs_sem_publicar_nada(self):
        self.assertIn("pull_request:", self.text)
        self.assertNotIn("issues:", self.text)
        self.assertNotIn("push:", self.text)
        self.assertNotIn("gh release", self.text)
        self.assertNotIn("gh pr create", self.text)

    def test_permissoes_somente_leitura(self):
        self.assertIn("contents: read", self.text)
        for scope in FORBIDDEN_SCOPES + ("write",):
            self.assertNotIn(scope, self.text)

    def test_checkout_recursivo_e_run_sem_interpolacao(self):
        checkouts = self.text.count("uses: actions/checkout@")
        self.assertEqual(checkouts,
                         self.text.count("submodules: recursive"))
        self.assertGreaterEqual(checkouts, 1)
        for block in run_blocks(self.text):
            self.assertNotIn("${{", block)

    def test_roda_suite_completa_e_valida_e_empacota_sem_publicar(self):
        self.assertIn("unittest discover -s tests", self.text)
        self.assertIn("-m gateway validate", self.text)
        self.assertIn("-m gateway package", self.text)


class ReleaseWorkflowStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = read(WORKFLOWS / "release.yml")

    def test_disparo_somente_apos_main_ou_dispatch_autorizado(self):
        self.assertIn("push:", self.text)
        self.assertIn("branches: [main]", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("plugin-id", self.text)
        self.assertNotIn("pull_request", self.text)
        self.assertNotIn("issues:", self.text)

    def test_permissoes_minimas_de_release(self):
        for scope in FORBIDDEN_SCOPES:
            self.assertNotIn(scope, self.text)
        self.assertIn("contents: write", self.text)
        self.assertNotIn("pull-requests: write", self.text)
        self.assertNotIn("issues: write", self.text)

    def test_checkout_recursivo_e_run_sem_interpolacao(self):
        checkouts = self.text.count("uses: actions/checkout@")
        self.assertEqual(checkouts,
                         self.text.count("submodules: recursive"))
        self.assertGreaterEqual(checkouts, 1)
        for block in run_blocks(self.text):
            self.assertNotIn("${{", block)

    def test_usa_changed_plugins_para_a_matrix(self):
        self.assertIn("changed-plugins", self.text)
        self.assertIn('--event-path "$EVENT_PATH"', self.text)
        self.assertIn("--repo-root", self.text)
        self.assertIn("fail-fast: false", self.text)
        self.assertIn("fromJSON(", self.text)

    def test_verificacao_previa_de_tag_e_asset_existente(self):
        self.assertIn("gh release view", self.text)
        self.assertIn("ls-remote --tags", self.text)
        self.assertIn("immutab", self.text)

    def test_release_e_upload_sem_flags_de_substituicao(self):
        self.assertIn("gh release create", self.text)
        self.assertIn("gh release upload", self.text)
        self.assertNotIn("--clobber", self.text)
        self.assertNotIn("--force", self.text)

    def test_retry_por_id_sem_alterar_metadados(self):
        self.assertNotIn("-m gateway convert", self.text)
        self.assertNotIn("-m gateway update", self.text)
        self.assertIn("$PLUGIN_ID.zip", self.text)
        self.assertIn("$PLUGIN_ID.zip.sha256", self.text)


class IssueTemplateStaticTests(unittest.TestCase):
    def test_template_de_conversao_com_rotulo_e_campos_exatos(self):
        text = read(TEMPLATES / "convert-plugin.yml")
        self.assertIn("conversion", text)
        for title in CONVERT_FIELD_TITLES:
            with self.subTest(campo=title):
                self.assertIn(f"label: {title}", text)

    def test_template_de_atualizacao_com_rotulo_e_campos_exatos(self):
        text = read(TEMPLATES / "update-plugin.yml")
        self.assertIn("update", text)
        for title in UPDATE_FIELD_TITLES:
            with self.subTest(campo=title):
                self.assertIn(f"label: {title}", text)


class WorkflowIssueFieldConsistencyTests(unittest.TestCase):
    def test_workflows_use_the_same_field_titles_as_templates(self):
        cases = (
            ("convert-plugin.yml", (CONVERT_FIELD_TITLES[0], CONVERT_FIELD_TITLES[2])),
            ("update-plugin.yml", (UPDATE_FIELD_TITLES[0],)),
        )
        for filename, titles in cases:
            text = read(WORKFLOWS / filename)
            for title in titles:
                with self.subTest(workflow=filename, field=title):
                    self.assertIn(f'"{title}"', text)


class CodeownersStaticTests(unittest.TestCase):
    def test_mantenedor_como_codeowner(self):
        path = GITHUB / "CODEOWNERS"
        self.assertTrue(path.is_file())
        self.assertIn("@endersonmenezes", read(path))


if __name__ == "__main__":
    unittest.main()
