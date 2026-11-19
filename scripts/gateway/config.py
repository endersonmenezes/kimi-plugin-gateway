"""Schema de `gateway.json`, ids, versões, tags e URLs de release.

Regras implementadas aqui:
- tags seguem `<id>-v<sourceVersion>-gateway.<revision>`;
- `sourceVersion` vem do manifesto upstream e só aceita `[0-9A-Za-z._-]`,
  sem sanitização silenciosa;
- toda origem é uma URL pública HTTPS de repositório GitHub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .issues import (
    IssueInputError,
    validate_plugin_id as _validate_plugin_id,
    validate_relative_path as _validate_relative_path,
    validate_repository_url as _validate_repository_url,
)

__all__ = [
    "ConfigError",
    "GatewayConfig",
    "load_config",
    "release_tag",
    "release_url",
    "validate_plugin_id",
    "validate_source_version",
]


class ConfigError(IssueInputError):
    """Configuração inválida; a mensagem aponta o campo e a ação."""


_VERSION = re.compile(r"[0-9A-Za-z._-]+\Z")
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_OWNER_REPO = re.compile(r"\A[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SOURCE_VERSION_CHARSET = "0-9A-Za-z._-"


@dataclass(frozen=True)
class GatewayConfig:
    """Dados controlados pelo Gateway para uma adaptação de plugin."""

    plugin_id: str
    upstream_url: str
    requested_ref: str
    commit: str
    manifest_path: str
    source_version: str
    release_revision: int
    remove_paths: list[str] = field(default_factory=list)


def validate_plugin_id(value: str) -> str:
    """Id validado pela regra Kimi, com erro de configuração."""
    return _guard("id", value, _validate_plugin_id)


def validate_source_version(value: str) -> str:
    """Versão de origem: obrigatória e restrita a `[0-9A-Za-z._-]`."""
    raw = value.strip()
    if not raw:
        raise ConfigError(
            "campo 'sourceVersion': versão ausente no manifesto upstream; "
            "preencha o manifesto ou resolva a conversão em PR manual"
        )
    if raw.startswith("-"):
        raise ConfigError(
            f"campo 'sourceVersion': versão não pode iniciar com '-': {raw!r}"
        )
    if not _VERSION.fullmatch(raw):
        raise ConfigError(
            f"campo 'sourceVersion': versão {raw!r} contém caracteres fora de "
            f"[{_SOURCE_VERSION_CHARSET}]; corrija o manifesto upstream"
        )
    return raw


def release_tag(config: GatewayConfig) -> str:
    """Tag determinística `<id>-v<sourceVersion>-gateway.<revision>`."""
    plugin_id = validate_plugin_id(config.plugin_id)
    version = validate_source_version(config.source_version)
    revision = config.release_revision
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ConfigError(
            f"campo 'releaseRevision': revisão deve ser um inteiro >= 1, "
            f"obtido {revision!r}"
        )
    return f"{plugin_id}-v{version}-gateway.{revision}"


def release_url(config: GatewayConfig, owner_repo: str) -> str:
    """URL determinística do asset ZIP na release do repositório do Gateway."""
    target = owner_repo.strip()
    if not _OWNER_REPO.fullmatch(target):
        raise ConfigError(
            f"owner_repo inválido: {owner_repo!r}; informe '<owner>/<repo>'"
        )
    return (
        f"https://github.com/{target}/releases/download/"
        f"{release_tag(config)}/{validate_plugin_id(config.plugin_id)}.zip"
    )


def load_config(path: Path) -> GatewayConfig:
    """Lê e valida um `gateway.json`, retornando `GatewayConfig`."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(
            f"arquivo de configuração não encontrado: {config_path}; "
            "confira o id do plugin e o caminho plugins/<id>/gateway.json"
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"gateway.json inválido em {config_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"gateway.json deve conter um objeto JSON: {config_path}")

    plugin_id = _require_str(data, "id")
    upstream = data.get("upstream")
    if not isinstance(upstream, dict):
        raise ConfigError("campo 'upstream' ausente ou não é um objeto")

    upstream_url = _guard("upstream.url", _require_str(upstream, "url"), _validate_repository_url)
    requested_ref = _require_str(upstream, "requestedRef")
    commit = _require_str(upstream, "commit")
    if not _FULL_COMMIT.fullmatch(commit):
        raise ConfigError(
            f"campo 'upstream.commit': deve ser um SHA completo de 40 hex, "
            f"obtido {commit!r}"
        )
    manifest_path = _guard(
        "upstream.manifest", _require_str(upstream, "manifest"), _validate_relative_path
    )
    source_version = validate_source_version(_require_str(upstream, "sourceVersion"))

    revision = data.get("releaseRevision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ConfigError(
            f"campo 'releaseRevision': deve ser um inteiro >= 1, obtido {revision!r}"
        )

    remove_paths = _load_remove_paths(data)

    return GatewayConfig(
        plugin_id=validate_plugin_id(plugin_id),
        upstream_url=upstream_url,
        requested_ref=requested_ref,
        commit=commit,
        manifest_path=manifest_path,
        source_version=source_version,
        release_revision=revision,
        remove_paths=remove_paths,
    )


def _load_remove_paths(data: dict) -> list[str]:
    overlays = data.get("overlays", {})
    if not isinstance(overlays, dict):
        raise ConfigError("campo 'overlays' deve ser um objeto")
    remove = overlays.get("remove", [])
    if not isinstance(remove, list) or not all(isinstance(p, str) for p in remove):
        raise ConfigError("campo 'overlays.remove' deve ser uma lista de caminhos")
    return [
        _guard(f"overlays.remove[{i}]", p, _validate_relative_path)
        for i, p in enumerate(remove)
    ]


def _require_str(container: dict, key: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"campo '{key}' ausente ou vazio em gateway.json")
    return value


def _guard(name: str, value: str, validator) -> str:
    try:
        return validator(value)
    except IssueInputError as exc:
        raise ConfigError(f"campo '{name}': {exc}") from exc
