"""Pacotes autocontidos: um ZIP por plugin, com SHA-256 determinístico.

Regras implementadas aqui:
- o pacote tem `kimi.plugin.json` e `gateway-source.json` na raiz e uma
  cópia real de `upstream/` com overlays aplicados, sem `.git` e sem
  `gateway.json`/`overlays/` (conteúdo do Gateway, não do plugin);
- o ZIP é determinístico: mesma entrada produz os mesmos bytes e o
  mesmo SHA-256;
- o staging é validado antes do ZIP e o pacote final é validado
  novamente depois do ZIP; conteúdo inseguro aborta o build;
- nenhum código upstream é executado em nenhuma etapa.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import GatewayConfig, load_config, release_tag
from .conversion import write_kimi_manifest
from .issues import IssueInputError
from .overlays import apply_overlays
from .validate import ValidationError, validate_plugin

__all__ = [
    "PackageResult",
    "build_package",
    "provenance_payload",
    "write_provenance",
]

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_FILE_ATTRS = 0o644 << 16


@dataclass(frozen=True)
class PackageResult:
    """Resumo do pacote: caminho do ZIP, SHA-256 e diagnósticos."""

    plugin_id: str
    zip_path: Path
    sha256: str
    warnings: list[str] = field(default_factory=list)


def build_package(plugin_dir: Path, output_dir: Path) -> PackageResult:
    """Empacota `plugins/<id>/` em `<output_dir>/<id>.zip` validado.

    O build falha com `ValidationError` quando o staging ou o pacote
    final não validam; nesse caso nenhum ZIP é publicado.
    """
    source = Path(plugin_dir)
    manifest_path = source / "kimi.plugin.json"
    if not manifest_path.is_file():
        raise ValidationError(
            f"manifesto Kimi não encontrado em {manifest_path}; execute a "
            "conversão antes de empacotar"
        )
    try:
        config = load_config(source / "gateway.json")
    except IssueInputError as exc:
        raise ValidationError(str(exc)) from exc

    out = Path(output_dir)
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gateway-package-") as tmp:
        staging = Path(tmp) / "package"
        warnings.extend(apply_overlays(
            source / "upstream", source / "overlays",
            staging / "upstream", config.remove_paths,
        ))
        shutil.copyfile(manifest_path, staging / "kimi.plugin.json")
        write_provenance(staging / "gateway-source.json", config)
        warnings.extend(validate_plugin(staging, packaged=True))

        out.mkdir(parents=True, exist_ok=True)
        zip_path = out / f"{config.plugin_id}.zip"
        _write_zip(staging, zip_path)
        try:
            warnings.extend(_validate_zip(zip_path))
        except IssueInputError:
            zip_path.unlink(missing_ok=True)
            raise

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return PackageResult(
        plugin_id=config.plugin_id,
        zip_path=zip_path,
        sha256=digest,
        warnings=warnings,
    )


def provenance_payload(config: GatewayConfig) -> dict:
    """Procedência do pacote: origem, commit e tag de release."""
    return {
        "id": config.plugin_id,
        "upstream": {
            "url": config.upstream_url,
            "requestedRef": config.requested_ref,
            "commit": config.commit,
            "sourceVersion": config.source_version,
        },
        "releaseRevision": config.release_revision,
        "tag": release_tag(config),
    }


def write_provenance(path: Path, config: GatewayConfig) -> None:
    """Grava `gateway-source.json` com bytes estáveis."""
    write_kimi_manifest(Path(path), provenance_payload(config))


def _write_zip(root: Path, zip_path: Path) -> None:
    files = sorted(p for p in root.rglob("*") if p.is_file())
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in files:
            info = zipfile.ZipInfo(
                path.relative_to(root).as_posix(), date_time=_ZIP_EPOCH
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _FILE_ATTRS
            zf.writestr(info, path.read_bytes())


def _validate_zip(zip_path: Path) -> list[str]:
    """Revalida o pacote final: nomes seguros, raiz completa e conteúdo."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for name in names:
            if name.startswith("/") or name.startswith("\\") \
                    or ".." in name.split("/"):
                raise ValidationError(
                    f"pacote com caminho inseguro no ZIP: {name!r}"
                )
            parts = name.split("/")
            if ".git" in parts:
                raise ValidationError(
                    f"pacote contém '.git' no ZIP: {name!r}"
                )
        for required in ("kimi.plugin.json", "gateway-source.json"):
            if required not in names:
                raise ValidationError(
                    f"pacote sem {required} na raiz do ZIP; build abortado"
                )
        with tempfile.TemporaryDirectory(prefix="gateway-zipcheck-") as tmp:
            zf.extractall(tmp)
            return validate_plugin(Path(tmp), packaged=True)
