"""Interface única do Gateway chamada pelos workflows.

Os subcomandos `convert` e `update` orquestram as operações das Tasks 1–3
e imprimem o resumo (id, commit, tag e relatório) para o corpo do PR.
Os workflows IssueOps (Task 6) invocam esses subcomandos com
`--issue-event <github-event.json>`: o CLI lê o evento da Issue, extrai os
campos dos formulários com `parse_issue_form` e valida os títulos exatos
dos Issue Forms — os valores nunca passam por shell dos workflows. Os
argumentos separados (`--repository-url`, `--ref`, `--plugin-id`,
`--manifest-path`) continuam disponíveis para desenvolvimento local.
Os subcomandos `validate` e `package` validam adaptações e empacotam
plugins autocontidos (Task 4). O subcomando `changed-plugins` (Task 5)
lê o evento de push e emite o JSON com os plugins alterados para a
Action de release.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config, validate_plugin_id
from .issues import IssueInputError, parse_issue_form
from .marketplace import upsert_marketplace_entry
from .operations import (
    ConversionInputs,
    OperationResult,
    UpdateInputs,
    run_conversion,
    run_update,
)
from .package import build_package
from .release import changed_plugins, load_push_event, push_range_from_event
from .validate import validate_plugin

__all__ = [
    "INPUT_ERROR_EXIT",
    "NOT_IMPLEMENTED_EXIT",
    "SUBCOMMANDS",
    "build_parser",
    "main",
]

NOT_IMPLEMENTED_EXIT = 3
INPUT_ERROR_EXIT = 2

SUBCOMMANDS = ("convert", "update", "validate", "package", "changed-plugins")

DEFAULT_MANIFEST_PATH = ".claude-plugin/plugin.json"

# Títulos exatos dos campos dos Issue Forms (.github/ISSUE_TEMPLATE/).
ISSUE_FIELD_REPOSITORY_URL = "URL pública do repositório GitHub"
ISSUE_FIELD_REQUESTED_REF = "Tag, branch ou commit de origem"
ISSUE_FIELD_DESIRED_ID = "Id desejado no Gateway (opcional)"
ISSUE_FIELD_MANIFEST_PATH = "Caminho do manifesto Claude"
ISSUE_FIELD_PLUGIN_ID = "Id do plugin no Gateway"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway",
        description="Automações determinísticas do Kimi Plugin Gateway.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert", help="converte um plugin Claude")
    convert.add_argument("--repository-url", default=None,
                         help="URL pública https do repositório GitHub "
                              "(obrigatório sem --issue-event)")
    convert.add_argument("--ref", dest="requested_ref", default=None,
                         help="tag, branch ou commit completo do upstream "
                              "(obrigatório sem --issue-event)")
    convert.add_argument("--issue-event", default=None,
                         help="caminho do JSON do evento da Issue do GitHub; "
                              "quando informado, os campos vêm do formulário")
    convert.add_argument("--plugin-id", default=None,
                         help="id do plugin (padrão: nome do manifesto)")
    convert.add_argument("--manifest-path", default=DEFAULT_MANIFEST_PATH,
                         help=f"caminho do manifesto Claude (padrão: {DEFAULT_MANIFEST_PATH})")
    convert.set_defaults(handler=_cmd_convert)

    update = subparsers.add_parser("update", help="atualiza um plugin convertido")
    update.add_argument("--plugin-id", default=None,
                        help="id do plugin existente em plugins/<id>/ "
                             "(obrigatório sem --issue-event)")
    update.add_argument("--ref", dest="requested_ref", default=None,
                        help="nova tag, branch ou commit completo do upstream "
                             "(obrigatório sem --issue-event)")
    update.add_argument("--issue-event", default=None,
                        help="caminho do JSON do evento da Issue do GitHub; "
                             "quando informado, os campos vêm do formulário")
    update.set_defaults(handler=_cmd_update)

    validate = subparsers.add_parser("validate", help="valida um plugin convertido")
    validate.add_argument("--plugin-id", required=True,
                          help="id do plugin existente em plugins/<id>/")
    validate.add_argument("--repo-root", default=".",
                          help="raiz do repositório do Gateway (padrão: .)")
    validate.set_defaults(handler=_cmd_validate)

    package = subparsers.add_parser("package", help="empacota um plugin validado")
    package.add_argument("--plugin-id", required=True,
                         help="id do plugin existente em plugins/<id>/")
    package.add_argument("--output-dir", required=True,
                         help="diretório de saída do ZIP do plugin")
    package.add_argument("--repo-root", default=".",
                         help="raiz do repositório do Gateway (padrão: .)")
    package.set_defaults(handler=_cmd_package)

    changed = subparsers.add_parser(
        "changed-plugins", help="lista os plugins alterados em um push"
    )
    changed.add_argument("--event-path", required=True,
                         help="caminho do JSON do evento de push do GitHub")
    changed.add_argument("--repo-root", default=".",
                         help="raiz do repositório do Gateway (padrão: .)")
    changed.set_defaults(handler=_cmd_changed_plugins)

    for sub in (convert, update):
        sub.add_argument("--repo-root", default=".",
                         help="raiz do repositório do Gateway (padrão: .)")
        sub.add_argument("--marketplace", default=None,
                         help="caminho do marketplace.json para upsert opcional")
        sub.add_argument("--owner-repo", default=None,
                         help="'<owner>/<repo>' do repositório do Gateway (obrigatório com --marketplace)")
        sub.add_argument("--display-name", default=None,
                         help="nome de exibição no marketplace (padrão: id do plugin)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        print(
            f"gateway: subcomando '{args.command}' ainda não implementado",
            file=sys.stderr,
        )
        return NOT_IMPLEMENTED_EXIT
    try:
        return handler(args)
    except IssueInputError as exc:
        print(f"gateway: {exc}", file=sys.stderr)
        return INPUT_ERROR_EXIT


def _cmd_convert(args: argparse.Namespace) -> int:
    if args.issue_event is not None:
        inputs = _conversion_inputs_from_issue(Path(args.issue_event))
    else:
        inputs = ConversionInputs(
            repository_url=_required_arg(
                args.repository_url, "--repository-url",
                "ou informe --issue-event <evento.json> para converter a "
                "partir de uma Issue"),
            requested_ref=_required_arg(
                args.requested_ref, "--ref",
                "ou informe --issue-event <evento.json> para converter a "
                "partir de uma Issue"),
            plugin_id=args.plugin_id,
            manifest_path=args.manifest_path,
        )
    result = run_conversion(Path(args.repo_root), inputs)
    _maybe_upsert_marketplace(args, result)
    _print_result("conversão", result)
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    if args.issue_event is not None:
        inputs = _update_inputs_from_issue(Path(args.issue_event))
    else:
        inputs = UpdateInputs(
            plugin_id=_required_arg(
                args.plugin_id, "--plugin-id",
                "ou informe --issue-event <evento.json> para atualizar a "
                "partir de uma Issue"),
            requested_ref=_required_arg(
                args.requested_ref, "--ref",
                "ou informe --issue-event <evento.json> para atualizar a "
                "partir de uma Issue"),
        )
    result = run_update(Path(args.repo_root), inputs)
    _maybe_upsert_marketplace(args, result)
    _print_result("atualização", result)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    plugin_dir = _existing_plugin_dir(args)
    diagnostics = validate_plugin(plugin_dir)
    print("gateway: validação concluída")
    print(f"plugin: {plugin_dir.name}")
    if diagnostics:
        print("diagnósticos:")
        for line in diagnostics:
            print(f"- {line}")
    else:
        print("diagnósticos: nenhum")
    return 0


def _cmd_package(args: argparse.Namespace) -> int:
    plugin_dir = _existing_plugin_dir(args)
    result = build_package(plugin_dir, Path(args.output_dir))
    print("gateway: pacote criado")
    print(f"plugin: {result.plugin_id}")
    print(f"zip: {result.zip_path}")
    print(f"sha256: {result.sha256}")
    if result.warnings:
        print("diagnósticos:")
        for line in result.warnings:
            print(f"- {line}")
    return 0


def _cmd_changed_plugins(args: argparse.Namespace) -> int:
    event = load_push_event(Path(args.event_path))
    before, after = push_range_from_event(event)
    plugins = changed_plugins(Path(args.repo_root), before, after)
    print(json.dumps({"plugins": plugins}, ensure_ascii=False))
    return 0


def _issue_event_fields(event_path: Path) -> dict[str, str]:
    """Lê o evento da Issue e devolve os campos do formulário parseados.

    O evento é lido de um arquivo JSON (`{"issue": {"number", "body"}}`),
    como gravado pelos workflows; os valores são tratados exclusivamente
    como dados e nunca são interpolados em shell.
    """
    path = Path(event_path)
    if not path.is_file():
        raise _InputError(
            f"arquivo do evento da Issue não encontrado: {path}; confira o "
            "caminho passado pelo workflow"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _InputError(f"evento da Issue inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise _InputError(
            f"evento da Issue em {path} deve conter um objeto JSON"
        )
    issue = data.get("issue")
    if not isinstance(issue, dict):
        raise _InputError(
            "evento da Issue sem objeto 'issue'; o workflow deve gravar o "
            "evento completo do GitHub (issue.number e issue.body)"
        )
    body = issue.get("body")
    if not isinstance(body, str) or not body.strip():
        raise _InputError(
            "corpo da Issue ausente ou vazio; a Issue deve usar o modelo "
            "com o formulário de campos"
        )
    return parse_issue_form(body)


def _required_issue_field(fields: dict[str, str], title: str) -> str:
    value = fields.get(title, "").strip()
    if not value:
        raise _InputError(
            f"campo '{title}' ausente ou vazio na Issue; preencha o "
            "formulário e repita a operação"
        )
    return value


def _optional_issue_field(fields: dict[str, str], title: str) -> str:
    return fields.get(title, "").strip()


def _conversion_inputs_from_issue(event_path: Path) -> ConversionInputs:
    fields = _issue_event_fields(event_path)
    desired_id = _optional_issue_field(fields, ISSUE_FIELD_DESIRED_ID)
    manifest_path = _optional_issue_field(fields, ISSUE_FIELD_MANIFEST_PATH)
    return ConversionInputs(
        repository_url=_required_issue_field(
            fields, ISSUE_FIELD_REPOSITORY_URL),
        requested_ref=_required_issue_field(fields, ISSUE_FIELD_REQUESTED_REF),
        plugin_id=desired_id or None,
        manifest_path=manifest_path or DEFAULT_MANIFEST_PATH,
    )


def _update_inputs_from_issue(event_path: Path) -> UpdateInputs:
    fields = _issue_event_fields(event_path)
    return UpdateInputs(
        plugin_id=_required_issue_field(fields, ISSUE_FIELD_PLUGIN_ID),
        requested_ref=_required_issue_field(fields, ISSUE_FIELD_REQUESTED_REF),
    )


def _required_arg(value: str | None, flag: str, hint: str) -> str:
    if not value:
        raise _InputError(f"{flag} é obrigatório ({hint})")
    return value


def _existing_plugin_dir(args: argparse.Namespace) -> Path:
    plugin_id = validate_plugin_id(args.plugin_id)
    plugin_dir = Path(args.repo_root) / "plugins" / plugin_id
    if not (plugin_dir / "gateway.json").is_file():
        raise _InputError(
            f"plugin '{plugin_id}' não encontrado em "
            f"plugins/{plugin_id}/gateway.json; confira o id informado"
        )
    return plugin_dir


def _maybe_upsert_marketplace(
    args: argparse.Namespace, result: OperationResult
) -> None:
    if args.marketplace is None:
        return
    if args.owner_repo is None:
        raise _InputError("--owner-repo é obrigatório quando --marketplace é informado")
    plugin_dir = result.plugin_dir
    if plugin_dir is None:  # pragma: no cover - defensivo
        raise _InputError("operação não retornou diretório do plugin")
    config = load_config(Path(plugin_dir) / "gateway.json")
    display_name = args.display_name or result.plugin_id
    upsert_marketplace_entry(
        Path(args.marketplace), config, args.owner_repo, display_name
    )


def _print_result(kind: str, result: OperationResult) -> None:
    print(f"gateway: {kind} concluída")
    print(f"plugin: {result.plugin_id}")
    if result.plugin_dir is not None:
        print(f"diretório: {result.plugin_dir}")
    print(f"commit de origem: {result.commit}")
    print(f"tag: {result.tag}")
    print("relatório:")
    for line in result.report:
        print(f"- {line}")


class _InputError(IssueInputError):
    """Erro de uso do CLI com ação corretiva."""
