"""Interface única do Gateway chamada pelos workflows.

Os subcomandos `convert` e `update` orquestram as operações das Tasks 1–3
e imprimem o resumo (id, commit, tag e relatório) para o corpo do PR.
Os subcomandos `validate` e `package` validam adaptações e empacotam
plugins autocontidos (Task 4). O restante será implementado pelas
tarefas seguintes do plano e falha com um erro explícito de "não
implementado".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config, validate_plugin_id
from .issues import IssueInputError
from .marketplace import upsert_marketplace_entry
from .operations import (
    ConversionInputs,
    OperationResult,
    UpdateInputs,
    run_conversion,
    run_update,
)
from .package import build_package
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway",
        description="Automações determinísticas do Kimi Plugin Gateway.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert", help="converte um plugin Claude")
    convert.add_argument("--repository-url", required=True,
                         help="URL pública https do repositório GitHub")
    convert.add_argument("--ref", dest="requested_ref", required=True,
                         help="tag, branch ou commit completo do upstream")
    convert.add_argument("--plugin-id", default=None,
                         help="id do plugin (padrão: nome do manifesto)")
    convert.add_argument("--manifest-path", default=DEFAULT_MANIFEST_PATH,
                         help=f"caminho do manifesto Claude (padrão: {DEFAULT_MANIFEST_PATH})")
    convert.set_defaults(handler=_cmd_convert)

    update = subparsers.add_parser("update", help="atualiza um plugin convertido")
    update.add_argument("--plugin-id", required=True,
                        help="id do plugin existente em plugins/<id>/")
    update.add_argument("--ref", dest="requested_ref", required=True,
                        help="nova tag, branch ou commit completo do upstream")
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

    subparsers.add_parser(
        "changed-plugins", help="operação 'changed-plugins' (ainda não implementada)"
    )

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
    inputs = ConversionInputs(
        repository_url=args.repository_url,
        requested_ref=args.requested_ref,
        plugin_id=args.plugin_id,
        manifest_path=args.manifest_path,
    )
    result = run_conversion(Path(args.repo_root), inputs)
    _maybe_upsert_marketplace(args, result)
    _print_result("conversão", result)
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    inputs = UpdateInputs(
        plugin_id=args.plugin_id,
        requested_ref=args.requested_ref,
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
