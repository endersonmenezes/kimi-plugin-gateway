"""Conversão determinística de manifests Claude em manifests Kimi.

Regras implementadas aqui:
- somente leitura de manifests e descoberta de arquivos; nenhum código
  upstream é executado;
- `source_version` vem exclusivamente do campo `version` do manifesto,
  nunca do ref solicitado;
- caminhos ganham o prefixo `./upstream/` e precisam existir dentro do
  diretório upstream, sem escape por `..` ou por link simbólico;
- hooks e MCP aparecem apenas como pendências no relatório, nunca no
  manifesto gerado;
- textos de Skills, comandos e agentes nunca são reescritos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, validate_source_version
from .issues import IssueInputError
from .issues import validate_plugin_id as _check_plugin_id
from .issues import validate_relative_path as _check_relative_path

__all__ = [
    "ConversionError",
    "ConversionResult",
    "convert_manifest",
    "write_kimi_manifest",
]

_UPSTREAM_PREFIX = "./upstream/"

_METADATA_FIELDS = ("description", "author", "homepage", "license", "keywords")
_CAPABILITIES = ("skills", "commands", "agents")
_DISCOVERY_DIRS = {
    "skills": ".claude/skills",
    "commands": ".claude/commands",
    "agents": ".claude/agents",
}
_REVIEW_FIELDS = ("commands", "agents")
_PENDING_FIELDS = ("hooks", "mcpServers")
_UNMAPPED_KNOWN_FIELDS = ("repository",)

_ALL_KNOWN_FIELDS = frozenset(
    {"name", "version"}
    | set(_METADATA_FIELDS)
    | set(_CAPABILITIES)
    | set(_PENDING_FIELDS)
    | set(_UNMAPPED_KNOWN_FIELDS)
)


class ConversionError(IssueInputError):
    """Conversão impossível; a mensagem aponta o campo e a ação."""


@dataclass(frozen=True)
class ConversionResult:
    """Manifest Kimi gerado, versão de origem e relatório da conversão."""

    manifest: dict
    source_version: str
    report: list[str]


def convert_manifest(
    upstream: Path,
    manifest_path: str,
    plugin_id: str | None = None,
) -> ConversionResult:
    """Converte o manifesto Claude de `upstream` em um manifesto Kimi.

    `plugin_id` opcional substitui o nome declarado no manifesto de
    origem. Levanta `ConversionError` com diagnóstico quando a conversão
    automática não é segura (versão ausente/inválida, caminho fora de
    upstream, manifesto ilegível).
    """
    root = Path(upstream)
    rel_manifest = _guard_relative_path("manifest", manifest_path)
    data = _load_manifest(root / rel_manifest, rel_manifest)

    name = _resolve_name(data, plugin_id)
    source_version = _resolve_version(data)

    manifest: dict = {"name": name, "version": source_version}
    for field in _METADATA_FIELDS:
        if field in data:
            manifest[field] = data[field]

    report: list[str] = []
    for field in _CAPABILITIES:
        _convert_capability(root, data, field, manifest, report)

    for field in _PENDING_FIELDS:
        if field in data:
            report.append(
                f"pendência: '{field}' presente no manifesto de origem; "
                "exige adaptação explícita e revisão antes de entrar no "
                "manifesto Kimi"
            )

    for field in _UNMAPPED_KNOWN_FIELDS:
        if field in data:
            report.append(
                f"ignorado: '{field}' sem equivalente Kimi; a origem fica "
                "registrada em gateway.json"
            )

    for field in sorted(k for k in data if k not in _ALL_KNOWN_FIELDS):
        report.append(
            f"ignorado: campo desconhecido '{field}' no manifesto de origem"
        )

    return ConversionResult(
        manifest=manifest,
        source_version=source_version,
        report=report,
    )


def write_kimi_manifest(path: Path, manifest: dict) -> None:
    """Grava o manifest Kimi como JSON ordenado, estável e legível.

    A mesma entrada produz sempre os mesmos bytes: chaves ordenadas,
    indentação fixa, UTF-8 sem escapes e quebra final de linha.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    target.write_text(text + "\n", encoding="utf-8")


def _load_manifest(path: Path, rel_manifest: str) -> dict:
    if not path.is_file():
        raise ConversionError(
            f"manifesto não encontrado em upstream/{rel_manifest}; confira "
            "o caminho informado"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConversionError(
            f"manifesto inválido em upstream/{rel_manifest}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ConversionError(
            f"manifesto em upstream/{rel_manifest} deve conter um objeto JSON"
        )
    return data


def _resolve_name(data: dict, plugin_id: str | None) -> str:
    if plugin_id is not None:
        return _validate_name("plugin_id", plugin_id)
    raw = data.get("name")
    if not isinstance(raw, str) or not raw.strip():
        raise ConversionError(
            "campo 'name': manifesto de origem sem nome; informe plugin_id "
            "na conversão"
        )
    return _validate_name("name", raw)


def _validate_name(field: str, value: str) -> str:
    try:
        return _check_plugin_id(value)
    except IssueInputError as exc:
        raise ConversionError(f"campo '{field}': {exc}") from exc


def _resolve_version(data: dict) -> str:
    raw = data.get("version")
    if not isinstance(raw, str):
        raise ConversionError(
            "campo 'version': versão ausente no manifesto upstream; "
            "preencha o manifesto ou resolva a conversão em PR manual"
        )
    try:
        return validate_source_version(raw)
    except ConfigError as exc:
        raise ConversionError(str(exc)) from exc


def _convert_capability(
    root: Path,
    data: dict,
    field: str,
    manifest: dict,
    report: list[str],
) -> None:
    declared = data.get(field)
    discovered = False
    if declared is None:
        discovery_dir = root / _DISCOVERY_DIRS[field]
        if not discovery_dir.is_dir():
            return
        declared = "./" + _DISCOVERY_DIRS[field]
        discovered = True

    if isinstance(declared, str):
        raw_paths = [declared]
    elif isinstance(declared, list):
        raw_paths = declared
    else:
        raise ConversionError(
            f"campo '{field}': deve ser um caminho ou lista de caminhos, "
            f"obtido {declared!r}"
        )

    if not raw_paths:
        report.append(f"ignorado: '{field}' declarado com lista vazia")
        return

    out_paths = [_convert_path(root, field, raw) for raw in raw_paths]
    manifest[field] = out_paths

    origin = f"descoberto em {_DISCOVERY_DIRS[field]}" if discovered else "declarado"
    report.append(
        f"convertido: {field} {origin} ({len(out_paths)} caminho(s)): "
        + ", ".join(out_paths)
    )
    if field in _REVIEW_FIELDS:
        report.append(
            f"revisão: {field} pode conter instruções específicas do "
            "Claude; texto preservado sem reescrita"
        )


def _convert_path(root: Path, field: str, raw) -> str:
    if not isinstance(raw, str):
        raise ConversionError(
            f"campo '{field}': caminho deve ser string, obtido {raw!r}"
        )
    rel = _guard_relative_path(field, raw)
    target = root / rel
    if not target.exists():
        raise ConversionError(
            f"campo '{field}': caminho declarado {raw!r} não existe no "
            "upstream"
        )
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if (
        resolved_target != resolved_root
        and resolved_root not in resolved_target.parents
    ):
        raise ConversionError(
            f"campo '{field}': caminho {raw!r} resolve para fora de "
            "upstream/"
        )
    suffix = "/" if resolved_target.is_dir() else ""
    return f"{_UPSTREAM_PREFIX}{rel}{suffix}"


def _guard_relative_path(field: str, value: str) -> str:
    try:
        return _check_relative_path(value)
    except IssueInputError as exc:
        raise ConversionError(f"campo '{field}': {exc}") from exc
