"""Validação de adaptações e de pacotes autocontidos.

Regras implementadas aqui:
- erros levantam `ValidationError`; diagnósticos não bloqueantes voltam
  na lista de avisos;
- caminhos do manifesto precisam começar com `./upstream/`, existir e
  resolver dentro do plugin, sem escape por `..` ou symlink;
- hooks e MCP nunca entram no manifesto Kimi nem são ativados
  automaticamente; se aparecerem, a validação falha;
- `.git` nunca pode estar presente, exceto o gitlink `upstream/.git`
  do submódulo da adaptação (arquivo `gitdir:`); todo symlink precisa
  resolver dentro da raiz validada;
- no modo `packaged=True`, exige também `gateway-source.json` na raiz
  com a proveniência coerente com o manifesto.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .config import load_config, validate_plugin_id, validate_source_version
from .issues import IssueInputError

__all__ = ["ValidationError", "validate_plugin"]

_UPSTREAM_PREFIX = "./upstream/"
_CAPABILITIES = ("skills", "commands", "agents")
_FORBIDDEN_MANIFEST_FIELDS = ("hooks", "mcpServers")
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class ValidationError(IssueInputError):
    """Plugin ou pacote inválido; a mensagem aponta o campo e a ação."""


def validate_plugin(plugin_dir: Path, packaged: bool = False) -> list[str]:
    """Valida `plugin_dir` e retorna diagnósticos não bloqueantes.

    Com `packaged=False` (padrão), valida a adaptação em
    `plugins/<id>/` (gateway.json, manifesto Kimi, overlays e upstream).
    Com `packaged=True`, valida o conteúdo do pacote autocontido
    (manifesto e proveniência na raiz, upstream sem `.git`). Erros
    levantam `ValidationError`.
    """
    root = Path(plugin_dir)
    if not root.is_dir():
        raise ValidationError(
            f"diretório do plugin não encontrado: {root}; confira o id informado"
        )
    warnings: list[str] = []
    manifest = _load_manifest(root / "kimi.plugin.json")
    _validate_identity(manifest)
    _validate_no_hooks_mcp(manifest)
    _validate_capability_paths(root, manifest)
    _validate_no_git(root)
    _validate_symlinks(root, root)
    if packaged:
        _validate_provenance(root, manifest)
    else:
        warnings.extend(_validate_gateway_files(root, manifest))
    return warnings


def _load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise ValidationError(
            f"manifesto Kimi não encontrado em {path}; execute a conversão "
            "antes de validar ou empacotar"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"manifesto Kimi inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"manifesto Kimi deve conter um objeto JSON: {path}")
    return data


def _validate_identity(manifest: dict) -> None:
    name = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValidationError(
            "manifesto Kimi precisa dos campos 'name' e 'version'"
        )
    try:
        validate_plugin_id(name)
        validate_source_version(version)
    except IssueInputError as exc:
        raise ValidationError(f"manifesto Kimi: {exc}") from exc


def _validate_no_hooks_mcp(manifest: dict) -> None:
    for field in _FORBIDDEN_MANIFEST_FIELDS:
        if field in manifest:
            raise ValidationError(
                f"manifesto Kimi contém '{field}'; o Gateway nunca ativa "
                "hooks/MCP automaticamente — remova o campo e adapte a "
                "funcionalidade em PR manual"
            )


def _validate_capability_paths(root: Path, manifest: dict) -> None:
    upstream_root = (root / "upstream").resolve()
    for field in _CAPABILITIES:
        value = manifest.get(field)
        if value is None:
            continue
        raw_paths = [value] if isinstance(value, str) else value
        if not isinstance(raw_paths, list):
            raise ValidationError(
                f"campo '{field}': deve ser um caminho ou lista de caminhos"
            )
        for raw in raw_paths:
            if not isinstance(raw, str):
                raise ValidationError(
                    f"campo '{field}': caminho deve ser string, obtido {raw!r}"
                )
            if not raw.startswith(_UPSTREAM_PREFIX):
                raise ValidationError(
                    f"campo '{field}': caminho '{raw}' não começa com "
                    "'./upstream/'; caminhos só podem apontar para dentro "
                    "do upstream"
                )
            resolved = (root / raw).resolve()
            if resolved != upstream_root and upstream_root not in resolved.parents:
                raise ValidationError(
                    f"campo '{field}': caminho '{raw}' resolve para fora de "
                    "upstream/"
                )
            if not resolved.exists():
                raise ValidationError(
                    f"campo '{field}': caminho '{raw}' não existe no "
                    "pacote; confira o upstream"
                )


def _validate_no_git(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        if ".git" in dirnames:
            rel = Path(dirpath).relative_to(root)
            raise ValidationError(
                f"'.git' presente em {rel / '.git'}; o pacote nunca pode "
                "conter metadados Git do upstream"
            )
        if ".git" in filenames and not _is_submodule_gitlink(root, Path(dirpath)):
            rel = Path(dirpath).relative_to(root)
            raise ValidationError(
                f"'.git' presente em {rel / '.git'}; o pacote nunca pode "
                "conter metadados Git do upstream"
            )


def _is_submodule_gitlink(root: Path, dirpath: Path) -> bool:
    """Gitlink do submódulo da adaptação: somente o arquivo `upstream/.git`
    cujo conteúdo aponta para o gitdir do submódulo."""
    if dirpath != Path(root) / "upstream":
        return False
    try:
        content = (dirpath / ".git").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return content.startswith("gitdir:")


def _validate_symlinks(root: Path, current: Path, seen: frozenset = frozenset()) -> None:
    resolved_dir = current.resolve()
    if resolved_dir in seen:
        raise ValidationError(f"symlink cíclico detectado em '{current}'")
    seen = seen | {resolved_dir}
    for entry in sorted(current.iterdir(), key=lambda e: e.name):
        if entry.is_symlink():
            resolved_root = root.resolve()
            resolved = entry.resolve()
            if resolved != resolved_root and resolved_root not in resolved.parents:
                raise ValidationError(
                    f"symlink '{entry.relative_to(root).as_posix()}' resolve "
                    "para fora do plugin"
                )
        elif entry.is_dir():
            _validate_symlinks(root, entry, seen)


def _validate_provenance(root: Path, manifest: dict) -> None:
    path = root / "gateway-source.json"
    if not path.is_file():
        raise ValidationError(
            f"proveniência não encontrada em {path}; o pacote precisa de "
            "gateway-source.json na raiz"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"gateway-source.json inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("gateway-source.json deve conter um objeto JSON")
    upstream = data.get("upstream")
    if data.get("id") != manifest.get("name"):
        raise ValidationError(
            f"gateway-source.json com id {data.get('id')!r} divergente do "
            f"manifesto ({manifest.get('name')!r}); regenere o pacote"
        )
    if not isinstance(upstream, dict) \
            or not _FULL_COMMIT.fullmatch(str(upstream.get("commit", ""))):
        raise ValidationError(
            "gateway-source.json sem 'upstream.commit' de 40 hex; a "
            "procedência do pacote está incompleta"
        )


def _validate_gateway_files(root: Path, manifest: dict) -> list[str]:
    """Diagnósticos da adaptação: gateway.json, overlays e remove_paths."""
    warnings: list[str] = []
    upstream = root / "upstream"
    if not upstream.is_dir():
        raise ValidationError(
            f"upstream/ não encontrado em {upstream}; a adaptação está "
            "incompleta"
        )
    config_path = root / "gateway.json"
    try:
        config = load_config(config_path)
    except IssueInputError as exc:
        raise ValidationError(str(exc)) from exc

    if manifest.get("version") != config.source_version:
        warnings.append(
            f"versão divergente: manifesto Kimi com "
            f"{manifest.get('version')!r}, gateway.json com sourceVersion "
            f"{config.source_version!r}"
        )

    for rel in config.remove_paths:
        if not (upstream / rel).exists():
            warnings.append(
                f"overlays.remove: '{rel}' não existe em upstream/; nada "
                "a remover"
            )

    overlays_dir = root / "overlays"
    if not overlays_dir.is_dir():
        warnings.append(
            "diretório overlays/ ausente; nenhum overlay será aplicado no "
            "pacote"
        )
        return warnings
    for dirpath, _dirnames, filenames in os.walk(overlays_dir, followlinks=False):
        for name in sorted(filenames):
            overlay = Path(dirpath) / name
            if overlay.is_symlink():
                resolved_root = overlays_dir.resolve()
                resolved = overlay.resolve()
                if resolved != resolved_root and resolved_root not in resolved.parents:
                    raise ValidationError(
                        f"overlay '{overlay.relative_to(overlays_dir).as_posix()}' "
                        "resolve para fora de overlays/"
                    )
            rel = overlay.relative_to(overlays_dir).as_posix()
            target = upstream / rel
            if not target.exists():
                warnings.append(
                    f"overlay '{rel}' sem alvo em upstream/ (arquivo novo "
                    "ou alvo removido no update)"
                )
            elif target.is_file() and overlay.read_bytes() == target.read_bytes():
                warnings.append(f"overlay '{rel}' idêntico a upstream/ (redundante)")
    return warnings
