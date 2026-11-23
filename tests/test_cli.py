"""Testes da integração do CLI com eventos de Issue (`--issue-event`).

Os workflows IssueOps gravam o evento da Issue em JSON e passam apenas o
caminho ao CLI (`convert`/`update --issue-event <arquivo.json>`). Estes
testes cobrem o mapeamento dos títulos exatos dos campos dos Issue Forms
para os inputs das operações, os erros de parsing/validação e a
compatibilidade com os argumentos separados usados em desenvolvimento.
As operações em si são isoladas com `mock`, como em test_operations.py.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gateway import cli
from gateway.cli import INPUT_ERROR_EXIT, main
from gateway.operations import ConversionInputs, OperationResult, UpdateInputs

REPO_ROOT = Path(__file__).resolve().parent.parent

CONVERT_BODY = """### Public GitHub repository URL

https://github.com/pbakaus/impeccable

### Source tag, branch, or commit

v4.10.0

### Desired Gateway plugin ID (optional)

meu-plugin

### Claude manifest path

.claude-plugin/plugin.json

### Adaptation notes (optional)

Revisar hooks antes de ativar.
"""

UPDATE_BODY = """### Gateway plugin ID

meu-plugin

### Source tag, branch, or commit

v4.11.0

### Update reason (optional)

Correções na skill principal.
"""


def make_event(path: Path, body: str, number: int = 7) -> Path:
    event = {"issue": {"number": number, "body": body}}
    target = Path(path) / "issue-event.json"
    target.write_text(json.dumps(event), encoding="utf-8")
    return target


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def fake_result(plugin_id: str = "meu-plugin") -> OperationResult:
    return OperationResult(
        plugin_id=plugin_id,
        commit="a" * 40,
        tag=f"{plugin_id}-v1.0.0-gateway.1",
        report=["plugin: " + plugin_id],
        plugin_dir=REPO_ROOT / "plugins" / plugin_id,
    )


class ConvertIssueEventTests(unittest.TestCase):
    def test_mapeia_campos_do_evento_para_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), CONVERT_BODY)
            with mock.patch.object(cli, "run_conversion") as run:
                run.return_value = fake_result()
                code, out, err = run_cli([
                    "convert", "--issue-event", str(event),
                    "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            run.assert_called_once()
            inputs = run.call_args.args[1]
            self.assertIsInstance(inputs, ConversionInputs)
            self.assertEqual(inputs.repository_url,
                             "https://github.com/pbakaus/impeccable")
            self.assertEqual(inputs.requested_ref, "v4.10.0")
            self.assertEqual(inputs.plugin_id, "meu-plugin")
            self.assertEqual(inputs.manifest_path, ".claude-plugin/plugin.json")
            self.assertIn("meu-plugin", out)

    def test_sem_id_opcional_usa_nome_do_manifesto(self):
        body = CONVERT_BODY.replace(
            "### Desired Gateway plugin ID (optional)\n\nmeu-plugin",
            "### Desired Gateway plugin ID (optional)\n\n_No response_",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            with mock.patch.object(cli, "run_conversion") as run:
                run.return_value = fake_result("impeccable")
                code, _, err = run_cli([
                    "convert", "--issue-event", str(event),
                    "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            self.assertIsNone(run.call_args.args[1].plugin_id)

    def test_sem_caminho_do_manifesto_usa_padrao(self):
        body = CONVERT_BODY.replace(
            "### Claude manifest path\n\n.claude-plugin/plugin.json",
            "### Claude manifest path\n\n_No response_",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            with mock.patch.object(cli, "run_conversion") as run:
                run.return_value = fake_result()
                code, _, err = run_cli([
                    "convert", "--issue-event", str(event),
                    "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            self.assertEqual(run.call_args.args[1].manifest_path,
                             ".claude-plugin/plugin.json")

    def test_url_obrigatoria_ausente_retorna_erro_de_input(self):
        body = CONVERT_BODY.replace(
            "### Public GitHub repository URL\n\n"
            "https://github.com/pbakaus/impeccable",
            "### Public GitHub repository URL\n\n_No response_",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("Public GitHub repository URL", err)

    def test_ref_obrigatorio_ausente_retorna_erro_de_input(self):
        body = CONVERT_BODY.replace(
            "### Source tag, branch, or commit\n\nv4.10.0",
            "### Source tag, branch, or commit\n\n_No response_",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("Source tag, branch, or commit", err)

    def test_evento_inexistente_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli([
                "convert", "--issue-event", str(Path(tmp) / "faltando.json"),
                "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("evento", err)

    def test_evento_json_invalido_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "evento.json"
            bad.write_text("{não é json", encoding="utf-8")
            code, _, err = run_cli([
                "convert", "--issue-event", str(bad), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("evento", err)

    def test_evento_sem_objeto_issue_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "evento.json"
            event.write_text(json.dumps({"action": "opened"}),
                             encoding="utf-8")
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("issue", err)

    def test_issue_sem_corpo_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "evento.json"
            event.write_text(json.dumps({"issue": {"number": 7, "body": ""}}),
                             encoding="utf-8")
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("corpo", err)

    def test_id_existente_e_rejeitado_antes_de_qualquer_rede(self):
        body = CONVERT_BODY.replace("meu-plugin", "duplo")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "duplo"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "gateway.json").write_text("{}", encoding="utf-8")
            event = make_event(root, body)
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", str(root),
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("duplo", err)

    def test_url_invalida_e_rejeitada_antes_de_qualquer_rede(self):
        body = CONVERT_BODY.replace(
            "https://github.com/pbakaus/impeccable",
            "https://gitlab.com/pbakaus/impeccable",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            code, _, err = run_cli([
                "convert", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("URL", err)


class UpdateIssueEventTests(unittest.TestCase):
    def test_mapeia_campos_do_evento_para_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), UPDATE_BODY, number=9)
            with mock.patch.object(cli, "run_update") as run:
                run.return_value = fake_result()
                code, _, err = run_cli([
                    "update", "--issue-event", str(event), "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            inputs = run.call_args.args[1]
            self.assertIsInstance(inputs, UpdateInputs)
            self.assertEqual(inputs.plugin_id, "meu-plugin")
            self.assertEqual(inputs.requested_ref, "v4.11.0")

    def test_id_ausente_retorna_erro_de_input(self):
        body = UPDATE_BODY.replace(
            "### Gateway plugin ID\n\nmeu-plugin",
            "### Gateway plugin ID\n\n_No response_",
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), body)
            code, _, err = run_cli([
                "update", "--issue-event", str(event), "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("Gateway plugin ID", err)

    def test_plugin_inexistente_e_rejeitado_antes_de_qualquer_rede(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = make_event(Path(tmp), UPDATE_BODY)
            code, _, err = run_cli([
                "update", "--issue-event", str(event),
                "--repo-root", str(Path(tmp)),
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("meu-plugin", err)


class ExplicitArgsCompatibilityTests(unittest.TestCase):
    def test_convert_com_argumentos_separados_continua_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "run_conversion") as run:
                run.return_value = fake_result()
                code, _, err = run_cli([
                    "convert",
                    "--repository-url", "https://github.com/pbakaus/impeccable",
                    "--ref", "v4.10.0",
                    "--plugin-id", "meu-plugin",
                    "--manifest-path", ".claude-plugin/plugin.json",
                    "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            inputs = run.call_args.args[1]
            self.assertEqual(inputs.repository_url,
                             "https://github.com/pbakaus/impeccable")
            self.assertEqual(inputs.plugin_id, "meu-plugin")

    def test_convert_sem_evento_nem_url_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(["convert", "--repo-root", tmp])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("--issue-event", err)

    def test_convert_sem_ref_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli([
                "convert", "--repository-url",
                "https://github.com/pbakaus/impeccable", "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("--ref", err)

    def test_update_com_argumentos_separados_continua_funcionando(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "run_update") as run:
                run.return_value = fake_result()
                code, _, err = run_cli([
                    "update", "--plugin-id", "meu-plugin", "--ref", "v4.11.0",
                    "--repo-root", tmp,
                ])
            self.assertEqual(code, 0, err)
            inputs = run.call_args.args[1]
            self.assertEqual(inputs.plugin_id, "meu-plugin")
            self.assertEqual(inputs.requested_ref, "v4.11.0")

    def test_update_sem_ref_nem_evento_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli([
                "update", "--plugin-id", "meu-plugin", "--repo-root", tmp,
            ])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("--ref", err)

    def test_update_sem_id_retorna_erro_de_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(["update", "--ref", "v4.11.0",
                                    "--repo-root", tmp])
            self.assertEqual(code, INPUT_ERROR_EXIT)
            self.assertIn("--plugin-id", err)


if __name__ == "__main__":
    unittest.main()
