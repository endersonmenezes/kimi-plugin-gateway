"""Interface única do Gateway chamada pelos workflows.

Os subcomandos serão implementados pelas tarefas seguintes do plano; por
enquanto cada um falha com um erro explícito de "não implementado".
"""

from __future__ import annotations

import argparse
import sys

__all__ = ["SUBCOMMANDS", "build_parser", "main"]

NOT_IMPLEMENTED_EXIT = 3

SUBCOMMANDS = ("convert", "update", "validate", "package", "changed-plugins")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway",
        description="Automações determinísticas do Kimi Plugin Gateway.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        subparsers.add_parser(name, help=f"operação '{name}' (ainda não implementada)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(
        f"gateway: subcomando '{args.command}' ainda não implementado",
        file=sys.stderr,
    )
    return NOT_IMPLEMENTED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
