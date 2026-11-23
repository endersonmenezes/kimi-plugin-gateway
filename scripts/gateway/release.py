"""Seleção de plugins alterados em um push para releases individuais.

Regras implementadas aqui:
- somente arquivos sob `plugins/<id>/` geram release; alterações em docs,
  scripts e workflows são ignoradas e nenhum pacote agregado é produzido;
- `before` e `after` vêm do evento de push do GitHub e são validados como
  SHA de 40 hex minúsculos antes de qualquer chamada Git — os valores
  chegam por argv (`shell=False`) e refs arbitrários são rejeitados;
- push inicial (`before` zerado) difere contra a árvore vazia: todo
  plugin presente em `after` é selecionado, pois todos os seus arquivos
  são novos; a imutabilidade das tags protege reexecuções;
- branch excluída (`after` zerado) seleciona lista vazia: não há nada a
  publicar;
- a saída é ordenada e sem duplicatas; plugins nunca são agregados.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .issues import IssueInputError

__all__ = [
    "ReleaseError",
    "changed_plugins",
    "load_push_event",
    "push_range_from_event",
]

_FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
_ZERO_SHA = "0" * 40
_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_PLUGINS_PREFIX = "plugins/"


class ReleaseError(IssueInputError):
    """Seleção de releases impossível; a mensagem aponta o campo e a ação."""


def changed_plugins(repo_root: Path, before: str, after: str) -> list[str]:
    """Ids dos plugins com arquivos alterados entre `before` e `after`.

    `before`/`after` são os SHAs do evento de push. SHA zerado em `after`
    (branch excluída) retorna lista vazia; SHA zerado em `before` (push
    inicial) difere contra a árvore vazia do Git. O resultado é ordenado
    e sem duplicatas.
    """
    root = Path(repo_root)
    first = _validate_sha("before", before)
    second = _validate_sha("after", after)
    if second == _ZERO_SHA:
        return []
    base = _EMPTY_TREE_SHA if first == _ZERO_SHA else first
    proc = _run_git([
        "-C", str(root), "diff", "--name-only", "--no-renames", base, second,
    ])
    return _plugins_from_paths(proc.stdout.splitlines())


def load_push_event(event_path: Path) -> dict:
    """Lê o JSON do evento de push a partir de `event_path`."""
    path = Path(event_path)
    if not path.is_file():
        raise ReleaseError(
            f"arquivo do evento de push não encontrado: {path}; confira o "
            "caminho passado pelo workflow"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"evento de push inválido em {path}: {exc}") from exc
    return data


def push_range_from_event(event: dict) -> tuple[str, str]:
    """Extrai e valida a presença de `before` e `after` do evento de push."""
    if not isinstance(event, dict):
        raise ReleaseError("evento de push deve conter um objeto JSON")
    return _event_sha(event, "before"), _event_sha(event, "after")


def _event_sha(event: dict, key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseError(
            f"campo '{key}' ausente ou vazio no evento de push; o workflow "
            "deve passar o evento completo do GitHub"
        )
    return value


def _validate_sha(name: str, value: str) -> str:
    if not isinstance(value, str) or not _FULL_SHA.fullmatch(value):
        raise ReleaseError(
            f"campo '{name}': SHA de push inválido {value!r}; esperado "
            "hex minúsculo de 40 caracteres, como no evento de push do GitHub"
        )
    return value


def _plugins_from_paths(paths: list[str]) -> list[str]:
    ids: set[str] = set()
    for line in paths:
        path = line.strip()
        if not path.startswith(_PLUGINS_PREFIX):
            continue
        rest = path[len(_PLUGINS_PREFIX):]
        if not rest:
            continue
        plugin_id = rest.split("/", 1)[0]
        if plugin_id:
            ids.add(plugin_id)
    return sorted(ids)


def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ReleaseError("git não encontrado no PATH") from exc
    except subprocess.CalledProcessError as exc:
        command = " ".join(["git", *args[:2]])
        raise ReleaseError(
            f"operação Git falhou ({command} ...): {exc.stderr.strip()}"
        ) from exc
