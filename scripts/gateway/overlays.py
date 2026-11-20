"""Staging seguro: cópia real do upstream com overlays e remoções.

Regras implementadas aqui:
- overlays são aplicados somente na cópia de destino; o upstream e o
  diretório de overlays nunca são alterados;
- caminhos de remoção são validados (relativos, sem '..', sem absolutos)
  e todo symlink precisa resolver dentro da sua raiz; escapes por
  symlink são rejeitados antes de qualquer cópia;
- `.git` nunca é copiado para o destino;
- avisos (não erros) descrevem overlays redundantes, overlays sem alvo e
  remoções sem alvo.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .issues import IssueInputError, validate_relative_path

__all__ = ["OverlayError", "apply_overlays"]


class OverlayError(IssueInputError):
    """Overlay ou remoção insegura; a mensagem aponta o caminho e a ação."""


def apply_overlays(
    upstream: Path,
    overlays: Path,
    destination: Path,
    remove_paths: list[str],
) -> list[str]:
    """Copia `upstream` para `destination` aplicando overlays e remoções.

    Overlays espelham a árvore do upstream: um arquivo em
    `overlays/<rel>` substitui (ou adiciona) `destination/<rel>`.
    `remove_paths` declara caminhos do upstream que não vão para o
    destino. Retorna avisos não bloqueantes; caminhos inseguros
    (`..`, absolutos, symlinks para fora) levantam `OverlayError`.
    """
    source = Path(upstream)
    overlays_dir = Path(overlays)
    dest = Path(destination)
    if not source.is_dir():
        raise OverlayError(
            f"upstream não encontrado: {source}; confira o diretório do plugin"
        )
    removals = [_guard_remove_path(p) for p in remove_paths]

    if dest.is_dir() and not dest.is_symlink():
        shutil.rmtree(dest)
    elif dest.exists():
        raise OverlayError(
            f"destino existe e não é um diretório: {dest}; informe outro path"
        )
    dest.mkdir(parents=True)

    _copy_tree(source, dest, source)

    warnings: list[str] = []
    for rel in removals:
        target = dest / rel
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
            warnings.append(f"removido: '{rel}'")
        elif target.exists() or target.is_symlink():
            target.unlink()
            warnings.append(f"removido: '{rel}'")
        else:
            warnings.append(f"remoção sem alvo: '{rel}' não existe no upstream")

    if overlays_dir.is_dir():
        for rel, path in _overlay_files(overlays_dir, overlays_dir):
            upstream_target = source / rel
            if not upstream_target.exists():
                warnings.append(
                    f"overlay sem alvo no upstream: '{rel}' (arquivo novo ou "
                    "alvo removido no update); aplicado no staging"
                )
            elif upstream_target.is_file() and path.read_bytes() == upstream_target.read_bytes():
                warnings.append(
                    f"overlay redundante: '{rel}' idêntico ao upstream; "
                    "aplicado no staging"
                )
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return warnings


def _guard_remove_path(value) -> str:
    if not isinstance(value, str):
        raise OverlayError(f"overlays.remove: caminho deve ser string, obtido {value!r}")
    try:
        return validate_relative_path(value)
    except IssueInputError as exc:
        raise OverlayError(f"overlays.remove: {exc}") from exc


def _overlay_files(root: Path, current: Path, prefix: str = "", seen: frozenset = frozenset()):
    """Yield `(rel, path)` dos arquivos de overlay, com contenção verificada."""
    resolved_dir = current.resolve()
    if resolved_dir in seen:
        raise OverlayError(f"symlink cíclico detectado em '{prefix.rstrip('/')}'")
    seen = seen | {resolved_dir}
    for entry in sorted(current.iterdir(), key=lambda e: e.name):
        rel = f"{prefix}{entry.name}"
        if entry.name == ".git":
            raise OverlayError(
                f"overlay '{rel}': '.git' não pode vir de overlay; remova o "
                "caminho de overlays/"
            )
        if entry.is_symlink():
            resolved = _resolved_within(root, entry, rel)
            if resolved.is_dir():
                yield from _overlay_files(root, resolved, rel + "/", seen)
            else:
                yield rel, resolved
        elif entry.is_dir():
            yield from _overlay_files(root, entry, rel + "/", seen)
        elif entry.is_file():
            yield rel, entry


def _copy_tree(source_dir: Path, dest_dir: Path, root: Path,
               prefix: str = "", seen: frozenset = frozenset()) -> None:
    """Copia a árvore materializando symlinks seguros e pulando `.git`."""
    resolved_dir = source_dir.resolve()
    if resolved_dir in seen:
        raise OverlayError(f"symlink cíclico detectado em '{prefix.rstrip('/')}'")
    seen = seen | {resolved_dir}
    dest_dir.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source_dir.iterdir(), key=lambda e: e.name):
        rel = f"{prefix}{entry.name}"
        if entry.name == ".git":
            continue
        target = dest_dir / entry.name
        if entry.is_symlink():
            resolved = _resolved_within(root, entry, rel)
            if resolved.is_dir():
                _copy_tree(resolved, target, root, rel + "/", seen)
            elif resolved.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(resolved, target)
        elif entry.is_dir():
            _copy_tree(entry, target, root, rel + "/", seen)
        elif entry.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, target)


def _resolved_within(root: Path, entry: Path, label: str) -> Path:
    """Resolve `entry` e exige que o destino fique dentro de `root`."""
    resolved_root = Path(root).resolve()
    try:
        resolved = entry.resolve()
    except OSError as exc:
        raise OverlayError(f"'{label}': symlink ilegível: {exc}") from exc
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise OverlayError(
            f"'{label}': symlink resolve para fora de {resolved_root}: {entry}"
        )
    return resolved
