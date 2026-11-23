"""Entradas estáveis do `marketplace.json` e URLs determinísticas de assets.

Regras implementadas aqui:
- a URL do asset é sempre a determinística de release
  (`release_url` da Task 1), nunca um valor digitado;
- `upsert` atualiza a entrada do id ou a cria; ids duplicados no arquivo
  são rejeitados como estado inválido;
- a saída é estável em bytes: mesma entrada, mesmos bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import GatewayConfig, release_url, validate_plugin_id
from .issues import IssueInputError

__all__ = ["MarketplaceError", "upsert_marketplace_entry"]


class MarketplaceError(IssueInputError):
    """Marketplace inválido; a mensagem aponta o campo e a ação."""


def upsert_marketplace_entry(
    path: Path,
    config: GatewayConfig,
    owner_repo: str,
    display_name: str,
) -> None:
    """Cria ou atualiza a entrada de `config.plugin_id` no marketplace.

    O campo `source` recebe a URL determinística da release do
    `owner_repo` informado; campos desconhecidos de entradas existentes
    são preservados.
    """
    target = Path(path)
    if not target.is_file():
        raise MarketplaceError(
            f"marketplace.json não encontrado em {target}; confira o "
            "caminho do arquivo de catálogo"
        )
    data = _load(target)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        raise MarketplaceError(
            "campo 'plugins' ausente ou não é uma lista em marketplace.json"
        )
    plugin_id = validate_plugin_id(config.plugin_id)
    source = release_url(config, owner_repo)
    name = _validate_display_name(display_name)

    matches = [e for e in plugins
               if isinstance(e, dict) and e.get("id") == plugin_id]
    if len(matches) > 1:
        raise MarketplaceError(
            f"marketplace.json contém {len(matches)} entradas com id "
            f"{plugin_id!r}; corrija o arquivo manualmente"
        )
    if matches:
        entry = matches[0]
    else:
        entry = {"id": plugin_id}
        plugins.append(entry)
    entry["displayName"] = name
    entry["source"] = source
    data["plugins"] = sorted(plugins, key=lambda e: str(e.get("id")))
    _write(target, data)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketplaceError(f"marketplace.json inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MarketplaceError("marketplace.json deve conter um objeto JSON")
    for entry in data.get("plugins", []):
        if not isinstance(entry, dict):
            raise MarketplaceError(
                "toda entrada de 'plugins' deve ser um objeto em marketplace.json"
            )
    return data


def _write(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _validate_display_name(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise MarketplaceError("displayName não pode ser vazio")
    if any(ord(ch) < 0x20 for ch in raw):
        raise MarketplaceError("displayName contém caracteres de controle")
    return raw
