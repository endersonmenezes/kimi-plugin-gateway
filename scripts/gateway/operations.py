"""Criação e atualização de adaptações de plugins e relatório de PR.

Regras implementadas aqui:
- toda operação Git usa `subprocess.run` com lista de argumentos e
  `shell=False`; o ref é validado antes de qualquer chamada Git e nenhum
  valor de Issue vira shell;
- a atualização mantém a URL de origem cadastrada, não regenera o
  manifesto inteiro e nunca remove ou reescreve overlays;
- `sourceVersion` vem sempre do campo `version` do manifesto upstream,
  nunca do ref solicitado;
- `releaseRevision` reinicia em 1 quando a versão muda e incrementa quando
  permanece;
- relatórios determinísticos para o corpo do PR.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    load_config,
    release_tag,
    validate_plugin_id,
    validate_source_version,
)
from .conversion import convert_manifest, write_kimi_manifest
from .issues import (
    IssueInputError,
    validate_relative_path as _validate_relative_path,
    validate_repository_url as _validate_repository_url,
)

__all__ = [
    "ConversionInputs",
    "OperationError",
    "OperationResult",
    "UpdateInputs",
    "convert_plugin",
    "fetch_upstream_tree",
    "resolve_remote_ref",
    "run_conversion",
    "run_update",
    "update_plugin",
    "validate_requested_ref",
]

_REF_ALLOWED = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
_CAPABILITIES = ("skills", "commands", "agents")


class OperationError(IssueInputError):
    """Operação impossível; a mensagem aponta o campo e a ação."""


@dataclass(frozen=True)
class ConversionInputs:
    """Dados de uma Issue de conversão, já tratados como dados."""

    repository_url: str
    requested_ref: str
    plugin_id: str | None
    manifest_path: str


@dataclass(frozen=True)
class UpdateInputs:
    """Dados de uma Issue de atualização; a URL continua sendo a
    cadastrada em `plugins/<id>/gateway.json`."""

    plugin_id: str
    requested_ref: str


@dataclass(frozen=True)
class OperationResult:
    """Resumo de uma operação para o corpo do PR."""

    plugin_id: str
    commit: str
    tag: str
    report: list[str] = field(default_factory=list)
    plugin_dir: Path | None = None


def validate_requested_ref(value: str) -> str:
    """Valida um ref antes de qualquer operação Git.

    Rejeita valor vazio, iniciado por '-' e formas perigosas para o Git
    (`..`, `@{`, `^{}`, wildcards, dois-pontos, espaços, terminação
    `.lock`). O alfabeto é o conservador de nomes de ref Git.
    """
    raw = value.strip()
    if not raw:
        raise OperationError("campo 'requestedRef': ref não pode ser vazio")
    if raw.startswith("-"):
        raise OperationError(
            f"campo 'requestedRef': ref não pode iniciar com '-': {raw!r}"
        )
    if not _REF_ALLOWED.fullmatch(raw):
        raise OperationError(
            f"campo 'requestedRef': ref contém caracteres fora de "
            f"[A-Za-z0-9._/-]: {raw!r}"
        )
    if ".." in raw or "//" in raw or "@{" in raw:
        raise OperationError(
            f"campo 'requestedRef': forma de ref não permitida: {raw!r}"
        )
    if raw.endswith(".lock") or raw.endswith("/"):
        raise OperationError(f"campo 'requestedRef': ref malformado: {raw!r}")
    return raw


def resolve_remote_ref(repository_url: str, requested_ref: str) -> str:
    """Resolve um ref remoto em SHA completo, como o GitHub faria.

    SHA completo é aceito diretamente; demais refs são resolvidos com
    `git ls-remote`. Em testes, esta função é substituída por um fake que
    opera sobre repositórios Git temporários.
    """
    ref = validate_requested_ref(requested_ref)
    if _FULL_SHA.fullmatch(ref):
        return ref
    proc = _run_git(["ls-remote", repository_url, ref])
    resolved: str | None = None
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, name = parts
        if name == f"refs/tags/{ref}^{{}}":
            return sha
        if name in (f"refs/heads/{ref}", f"refs/tags/{ref}", ref):
            resolved = sha
    if resolved is None:
        raise OperationError(
            f"ref {ref!r} não encontrado em {repository_url}; confira a "
            "tag, branch ou commit informado na Issue"
        )
    return resolved


def fetch_upstream_tree(repository_url: str, commit: str, destination: Path) -> None:
    """Materializa o snapshot de `commit` em `destination`, sem `.git`.

    `git clone` não executa código do repositório clonado; o checkout é
    fixado no SHA completo e os metadados Git são removidos.
    """
    if not _FULL_SHA.fullmatch(commit):
        raise OperationError(f"commit inválido para fetch: {commit!r}")
    dest = Path(destination)
    if dest.exists():
        shutil.rmtree(dest)
    _run_git(["clone", "--quiet", repository_url, str(dest)])
    _run_git(["-C", str(dest), "checkout", "--quiet", "--detach", commit])
    git_meta = dest / ".git"
    if git_meta.is_dir():
        shutil.rmtree(git_meta)
    elif git_meta.exists():
        git_meta.unlink()


def run_conversion(repo_root: Path, inputs: ConversionInputs) -> OperationResult:
    """Cria `plugins/<id>/` a partir do upstream e devolve o resumo do PR.

    A duplicidade de id é rejeitada antes de qualquer operação Git quando
    o id é informado; com `plugin_id=None`, o id vem do nome do manifesto
    upstream e a checagem ocorre após o fetch.
    """
    root = Path(repo_root)
    url = _guard("repository_url", inputs.repository_url, _validate_repository_url)
    ref = validate_requested_ref(inputs.requested_ref)
    manifest_path = _guard("manifest_path", inputs.manifest_path,
                           _validate_relative_path)
    plugin_id = validate_plugin_id(inputs.plugin_id) \
        if inputs.plugin_id is not None else None

    plugins_root = root / "plugins"
    if plugin_id is not None:
        _reject_existing_plugin(plugins_root / plugin_id)

    sha = resolve_remote_ref(url, ref)
    with tempfile.TemporaryDirectory(prefix="gateway-convert-", dir=root) as tmp:
        staging = Path(tmp) / "upstream"
        fetch_upstream_tree(url, sha, staging)
        converted = convert_manifest(staging, manifest_path, plugin_id=plugin_id)
        resolved_id = plugin_id if plugin_id is not None \
            else validate_plugin_id(converted.manifest["name"])
        plugin_dir = plugins_root / resolved_id
        _reject_existing_plugin(plugin_dir)
        plugin_dir.mkdir(parents=True)
        shutil.move(str(staging), str(plugin_dir / "upstream"))
        write_kimi_manifest(plugin_dir / "kimi.plugin.json", converted.manifest)
        _write_json(plugin_dir / "gateway.json", _config_payload(
            plugin_id=resolved_id,
            upstream_url=url,
            requested_ref=ref,
            commit=sha,
            manifest_path=manifest_path,
            source_version=converted.source_version,
            release_revision=1,
            remove_paths=(),
        ))
        (plugin_dir / "overlays").mkdir()

    config = load_config(plugin_dir / "gateway.json")
    tag = release_tag(config)
    report = [
        f"plugin: {resolved_id}",
        f"origem: {url}",
        f"ref resolvido: {ref} -> {sha}",
        f"versão de origem: {converted.source_version}",
        f"tag de release: {tag}",
        *converted.report,
    ]
    return OperationResult(
        plugin_id=resolved_id, commit=sha, tag=tag, report=report,
        plugin_dir=plugin_dir,
    )


def convert_plugin(repo_root: Path, inputs: ConversionInputs) -> Path:
    """Cria a adaptação e devolve o diretório `plugins/<id>/`.

    Assinatura conforme o brief; o resumo completo para o PR (id, commit,
    tag e relatório) vem de `run_conversion`.
    """
    return _required_dir(run_conversion(repo_root, inputs).plugin_dir)


def run_update(repo_root: Path, inputs: UpdateInputs) -> OperationResult:
    """Atualiza `plugins/<id>/` para o novo ref e devolve o resumo do PR.

    A URL de origem cadastrada é mantida; o manifesto Kimi existente só
    tem o campo gerado `version` atualizado; overlays nunca são removidos,
    renomeados ou reescritos.
    """
    root = Path(repo_root)
    plugin_id = validate_plugin_id(inputs.plugin_id)
    ref = validate_requested_ref(inputs.requested_ref)
    plugin_dir = root / "plugins" / plugin_id
    config_path = plugin_dir / "gateway.json"
    if not config_path.is_file():
        raise OperationError(
            f"plugin '{plugin_id}' não encontrado em "
            f"plugins/{plugin_id}/gateway.json; confira o id na Issue"
        )
    config = load_config(config_path)
    kimi_path = plugin_dir / "kimi.plugin.json"
    old_manifest = _load_kimi_manifest(kimi_path)

    sha = resolve_remote_ref(config.upstream_url, ref)
    report = [
        f"plugin: {plugin_id}",
        f"origem: {config.upstream_url} (URL mantida)",
    ]
    if sha == config.commit:
        report.append(f"sem mudanças: {ref} já está em {sha}")
        return OperationResult(
            plugin_id=plugin_id, commit=sha, tag=release_tag(config),
            report=report, plugin_dir=plugin_dir,
        )

    upstream_dir = plugin_dir / "upstream"
    with tempfile.TemporaryDirectory(prefix="gateway-update-", dir=root) as tmp:
        staging = Path(tmp) / "upstream"
        fetch_upstream_tree(config.upstream_url, sha, staging)
        new_version = _read_manifest_version(staging, config.manifest_path)
        old_caps = _capability_set(convert_manifest(
            upstream_dir, config.manifest_path, plugin_id=plugin_id).manifest)
        new_caps = _capability_set(convert_manifest(
            staging, config.manifest_path, plugin_id=plugin_id).manifest)
        shutil.rmtree(upstream_dir)
        shutil.move(str(staging), str(upstream_dir))

    revision = 1 if new_version != config.source_version \
        else config.release_revision + 1
    if new_version != old_manifest.get("version"):
        updated = dict(old_manifest)
        updated["version"] = new_version
        write_kimi_manifest(kimi_path, updated)
    _write_json(config_path, _config_payload(
        plugin_id=plugin_id,
        upstream_url=config.upstream_url,
        requested_ref=ref,
        commit=sha,
        manifest_path=config.manifest_path,
        source_version=new_version,
        release_revision=revision,
        remove_paths=config.remove_paths,
    ))
    tag = release_tag(load_config(config_path))
    report.extend([
        f"ref resolvido: {ref} -> {sha}",
        f"versão de origem: {config.source_version} -> {new_version}",
        f"releaseRevision: {config.release_revision} -> {revision}",
        f"tag de release: {tag}",
        *_capability_report(old_caps, new_caps),
        *_overlay_report(plugin_dir),
    ])
    return OperationResult(
        plugin_id=plugin_id, commit=sha, tag=tag, report=report,
        plugin_dir=plugin_dir,
    )


def update_plugin(repo_root: Path, inputs: UpdateInputs) -> Path:
    """Atualiza a adaptação e devolve o diretório `plugins/<id>/`.

    Assinatura conforme o brief; o resumo completo para o PR vem de
    `run_update`.
    """
    return _required_dir(run_update(repo_root, inputs).plugin_dir)


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
        raise OperationError("git não encontrado no PATH") from exc
    except subprocess.CalledProcessError as exc:
        command = " ".join(["git", *args[:2]])
        raise OperationError(
            f"operação Git falhou ({command} ...): {exc.stderr.strip()}"
        ) from exc


def _guard(name: str, value: str, validator) -> str:
    try:
        return validator(value)
    except IssueInputError as exc:
        raise OperationError(f"campo '{name}': {exc}") from exc


def _reject_existing_plugin(plugin_dir: Path) -> None:
    if plugin_dir.exists():
        raise OperationError(
            f"id duplicado: {plugin_dir} já existe; a conversão só cria "
            "plugins novos — para alterar um plugin existente use a Issue "
            "de atualização"
        )


def _required_dir(path: Path | None) -> Path:
    if path is None:  # pragma: no cover - defensivo
        raise OperationError("operação não retornou diretório")
    return path


def _write_json(path: Path, payload: dict) -> None:
    write_kimi_manifest(path, payload)


def _config_payload(
    *,
    plugin_id: str,
    upstream_url: str,
    requested_ref: str,
    commit: str,
    manifest_path: str,
    source_version: str,
    release_revision: int,
    remove_paths,
) -> dict:
    payload = {
        "id": plugin_id,
        "upstream": {
            "url": upstream_url,
            "requestedRef": requested_ref,
            "commit": commit,
            "manifest": manifest_path,
            "sourceVersion": source_version,
        },
        "releaseRevision": release_revision,
    }
    if remove_paths:
        payload["overlays"] = {"remove": list(remove_paths)}
    return payload


def _load_kimi_manifest(path: Path) -> dict:
    if not path.is_file():
        raise OperationError(
            f"manifesto Kimi não encontrado em {path}; a adaptação está "
            "incompleta e precisa de revisão manual"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationError(f"manifesto Kimi inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise OperationError(f"manifesto Kimi deve conter um objeto JSON: {path}")
    return data


def _read_manifest_version(upstream: Path, manifest_path: str) -> str:
    path = Path(upstream) / manifest_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationError(
            f"manifesto inválido no novo upstream ({manifest_path}): {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise OperationError(
            f"campo 'version': versão ausente no manifesto do novo "
            f"upstream ({manifest_path}); resolva a atualização em PR manual"
        )
    return validate_source_version(data["version"])


def _capability_set(manifest: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in _CAPABILITIES:
        value = manifest.get(name)
        if isinstance(value, str):
            out[name] = [value]
        elif isinstance(value, list):
            out[name] = sorted(str(item) for item in value)
    return out


def _capability_report(old: dict[str, list[str]],
                       new: dict[str, list[str]]) -> list[str]:
    report: list[str] = []
    for name in _CAPABILITIES:
        added = sorted(set(new.get(name, [])) - set(old.get(name, [])))
        removed = sorted(set(old.get(name, [])) - set(new.get(name, [])))
        for path in added:
            report.append(f"capacidade adicionada: {name} {path}")
        for path in removed:
            report.append(f"capacidade removida: {name} {path}")
    return report


def _overlay_report(plugin_dir: Path) -> list[str]:
    overlays_dir = plugin_dir / "overlays"
    if not overlays_dir.is_dir():
        return []
    report: list[str] = []
    for overlay in sorted(p for p in overlays_dir.rglob("*") if p.is_file()):
        rel = overlay.relative_to(overlays_dir).as_posix()
        target = plugin_dir / "upstream" / rel
        if not target.exists():
            report.append(
                f"overlay afetado: {rel} perdeu o alvo no novo upstream; "
                "mantido para revisão humana"
            )
        elif _same_content(overlay, target):
            report.append(
                f"overlay redundante: {rel} idêntico ao novo upstream; "
                "mantido para revisão humana"
            )
        else:
            report.append(f"overlay preservado: {rel}")
    return report


def _same_content(overlay: Path, target: Path) -> bool:
    try:
        return overlay.read_bytes() == target.read_bytes()
    except OSError:
        return False
