"""Parsing seguro dos formulários de Issue e validação dos inputs.

Os valores de Issue são sempre tratados como dados: nada aqui executa
comandos, faz rede ou interpola valores em shell.
"""

from __future__ import annotations

import posixpath
import re
from urllib.parse import urlsplit

__all__ = [
    "IssueInputError",
    "parse_issue_form",
    "validate_plugin_id",
    "validate_relative_path",
    "validate_repository_url",
]


class IssueInputError(ValueError):
    """Um campo de Issue é inválido; a mensagem aponta o campo e a ação."""


_NO_RESPONSE = "_No response_"
_H3_HEADER = re.compile(r"^###\s+(?P<label>.+?)\s*$")
_KIMI_ID = re.compile(
    r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*(?:@[A-Za-z0-9_-]+)?\Z"
)
_GITHUB_REPO = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\Z")


def parse_issue_form(body: str) -> dict[str, str]:
    """Extrai os campos dos cabeçalhos `###` gerados pelos Issue Forms.

    Campos vazios ou com `_No response_` viram string vazia. Blocos
    multilinha são preservados. Somente cabeçalhos de nível 3 são campos.
    """
    fields: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is None:
            return
        value = "\n".join(buffer).strip("\n").strip()
        fields[current] = "" if value == _NO_RESPONSE else value

    for line in body.splitlines():
        match = _H3_HEADER.match(line)
        if match:
            flush()
            current = match.group("label")
            buffer = []
        elif current is not None:
            buffer.append(line)
    flush()
    return fields


def validate_repository_url(value: str) -> str:
    """Valida uma URL pública de repositório GitHub e retorna a forma
    normalizada `https://github.com/<owner>/<repo>`, sem `.git` nem barra
    final. Somente HTTPS, sem credenciais, sem path extra."""
    raw = value.strip()
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise IssueInputError(
            f"URL do repositório inválida ({exc}); informe https://github.com/<owner>/<repo>"
        ) from exc
    if parts.scheme.lower() != "https":
        raise IssueInputError(
            "URL do repositório deve usar https; informe https://github.com/<owner>/<repo>"
        )
    host = parts.hostname or ""
    if host.lower() != "github.com":
        raise IssueInputError(
            "URL do repositório deve ser do GitHub; informe https://github.com/<owner>/<repo>"
        )
    if parts.username or parts.password:
        raise IssueInputError(
            "URL do repositório não pode conter credenciais; informe a URL pública"
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise IssueInputError(
            f"URL do repositório tem porta inválida ({exc}); "
            "informe https://github.com/<owner>/<repo>"
        ) from exc
    if port is not None:
        raise IssueInputError(
            "URL do repositório não pode especificar porta; informe https://github.com/<owner>/<repo>"
        )
    if parts.query or parts.fragment:
        raise IssueInputError(
            "URL do repositório não pode conter query nem fragmento"
        )
    segments = [seg for seg in parts.path.split("/") if seg]
    if len(segments) != 2:
        raise IssueInputError(
            "URL do repositório deve apontar para a raiz de um repositório "
            "(https://github.com/<owner>/<repo>)"
        )
    owner, repo = segments
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    for name, segment in (("owner", owner), ("repo", repo)):
        if not _GITHUB_REPO.match(segment):
            raise IssueInputError(
                f"segmento '{name}' inválido na URL do repositório: {segment!r}"
            )
    return f"https://github.com/{owner}/{repo}"


def validate_plugin_id(value: str) -> str:
    """Valida o id pelo padrão de nomes do manifesto Kimi."""
    raw = value.strip()
    if not raw:
        raise IssueInputError("id do plugin não pode ser vazio")
    if raw.startswith("-"):
        raise IssueInputError(
            f"id do plugin não pode iniciar com '-': {raw!r}; informe um id como 'meu-plugin'"
        )
    if not _KIMI_ID.fullmatch(raw):
        raise IssueInputError(
            f"id do plugin inválido: {raw!r}; use letras, dígitos, '-', '_' "
            "e opcionalmente segmentos separados por '.' ou um sufixo '@'"
        )
    return raw


def validate_relative_path(value: str) -> str:
    """Valida um caminho relativo de manifesto/overlay e retorna a forma
    normalizada POSIX. Rejeita absolutos, traversal e valores vazios."""
    raw = value.strip()
    if not raw:
        raise IssueInputError("caminho não pode ser vazio")
    if raw.startswith("-"):
        raise IssueInputError(
            f"caminho não pode iniciar com '-': {raw!r}; informe um caminho relativo"
        )
    if raw.startswith("/") or re.match(r"\A[A-Za-z]:[\\/]", raw):
        raise IssueInputError(
            f"caminho absoluto não é permitido: {raw!r}; informe um caminho relativo ao upstream"
        )
    if "\\" in raw:
        raise IssueInputError(
            f"caminho deve usar separadores '/': {raw!r}"
        )
    if "\x00" in raw:
        raise IssueInputError("caminho contém caractere nulo")
    segments = raw.split("/")
    if any(seg == ".." for seg in segments):
        raise IssueInputError(
            f"traversal '..' não é permitido no caminho: {raw!r}"
        )
    normalized = posixpath.normpath(raw)
    if normalized in (".", ""):
        raise IssueInputError(f"caminho inválido: {raw!r}")
    if normalized.startswith("/") or normalized.startswith(".."):
        raise IssueInputError(
            f"caminho fora da raiz não é permitido: {raw!r}"
        )
    return normalized
