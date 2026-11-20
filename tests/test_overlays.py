"""Testes do staging seguro: cópia real do upstream com overlays e remoções.

Overlays são aplicados somente na cópia de destino; o upstream e o
diretório de overlays nunca são alterados. Caminhos absolutos,
traversal `..` e symlinks que apontam para fora são rejeitados.
"""

import hashlib
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from gateway.overlays import OverlayError, apply_overlays

FIXTURE = Path(__file__).parent / "fixtures" / "claude-basic"


def make_upstream(tmp: Path) -> Path:
    upstream = tmp / f"upstream-{uuid.uuid4().hex}"
    shutil.copytree(FIXTURE, upstream)
    return upstream


def make_overlays(tmp: Path) -> Path:
    overlays = tmp / f"overlays-{uuid.uuid4().hex}"
    overlays.mkdir()
    return overlays


def apply(upstream: Path, overlays: Path, dest: Path,
          remove: list[str] | None = None) -> list[str]:
    return apply_overlays(upstream, overlays, dest, list(remove or []))


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class StagingCopyTests(unittest.TestCase):
    def test_copia_real_sem_alterar_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            before = tree_digest(upstream)
            apply(upstream, overlays, tmp / "dest")
            after = tree_digest(upstream)
            dest = tmp / "dest"
            self.assertEqual(before, after)
            for rel in (
                ".claude-plugin/plugin.json",
                ".claude/skills/impeccable/SKILL.md",
                ".claude/skills/impeccable/probe.sh",
                ".claude/commands/polish.md",
                ".claude/agents/reviewer.md",
            ):
                self.assertTrue((dest / rel).is_file(), rel)
                self.assertEqual(
                    (dest / rel).read_bytes(), (upstream / rel).read_bytes(), rel
                )

    def test_git_nunca_e_copiado_para_o_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            git_dir = upstream / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            apply(upstream, make_overlays(tmp), tmp / "dest")
            self.assertFalse((tmp / "dest" / ".git").exists())

    def test_symlink_interno_do_upstream_e_materializado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            target = upstream / ".claude" / "commands" / "polish.md"
            link = upstream / ".claude" / "skills" / "link.md"
            link.symlink_to(target)
            apply(upstream, make_overlays(tmp), tmp / "dest")
            copied = tmp / "dest" / ".claude" / "skills" / "link.md"
            self.assertFalse(copied.is_symlink())
            self.assertEqual(copied.read_bytes(), target.read_bytes())


class OverlayApplicationTests(unittest.TestCase):
    def test_overlay_adiciona_arquivo_novo_no_destino(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            (overlays / "docs").mkdir()
            (overlays / "docs" / "extra.md").write_text("# extra\n", encoding="utf-8")
            warnings = apply(upstream, overlays, tmp / "dest")
            self.assertTrue((tmp / "dest" / "docs" / "extra.md").is_file())
            self.assertFalse((upstream / "docs" / "extra.md").exists())
            self.assertTrue(any("docs/extra.md" in w for w in warnings))

    def test_overlay_substitui_arquivo_existente(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            skill = overlays / ".claude" / "skills" / "impeccable"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# versão humana\n", encoding="utf-8")
            original = (upstream / ".claude" / "skills" / "impeccable" / "SKILL.md") \
                .read_bytes()
            warnings = apply(upstream, overlays, tmp / "dest")
            self.assertEqual(
                (tmp / "dest" / ".claude" / "skills" / "impeccable" / "SKILL.md")
                .read_text(encoding="utf-8"),
                "# versão humana\n",
            )
            self.assertEqual(
                (upstream / ".claude" / "skills" / "impeccable" / "SKILL.md")
                .read_bytes(),
                original,
            )
            self.assertFalse(any("redundante" in w for w in warnings))

    def test_overlay_original_nunca_e_alterado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            skill = overlays / ".claude" / "skills" / "impeccable"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# versão humana\n", encoding="utf-8")
            before = tree_digest(overlays)
            apply(upstream, overlays, tmp / "dest")
            self.assertEqual(before, tree_digest(overlays))

    def test_overlay_sem_alvo_no_upstream_avisa_e_aplica(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            lost = overlays / ".claude" / "commands" / "removido.md"
            lost.parent.mkdir(parents=True)
            lost.write_text("# sobreviveu ao update\n", encoding="utf-8")
            warnings = apply(upstream, overlays, tmp / "dest")
            self.assertTrue((tmp / "dest" / ".claude" / "commands" / "removido.md").is_file())
            self.assertTrue(
                any("removido.md" in w and "alvo" in w for w in warnings)
            )

    def test_overlay_redundante_idêntico_ao_upstream_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            skill = overlays / ".claude" / "skills" / "impeccable"
            skill.mkdir(parents=True)
            original = upstream / ".claude" / "skills" / "impeccable" / "SKILL.md"
            (skill / "SKILL.md").write_bytes(original.read_bytes())
            warnings = apply(upstream, overlays, tmp / "dest")
            self.assertTrue(any("redundante" in w and "SKILL.md" in w for w in warnings))
            self.assertEqual(
                (tmp / "dest" / ".claude" / "skills" / "impeccable" / "SKILL.md")
                .read_bytes(),
                original.read_bytes(),
            )


class DeclaredRemovalTests(unittest.TestCase):
    def test_remocao_declarada_elimina_alvo_do_destino(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            legacy = upstream / "bin"
            legacy.mkdir()
            (legacy / "legacy.sh").write_text("# legado\n", encoding="utf-8")
            warnings = apply(upstream, make_overlays(tmp), tmp / "dest",
                             remove=["bin/legacy.sh"])
            self.assertFalse((tmp / "dest" / "bin" / "legacy.sh").exists())
            self.assertTrue((upstream / "bin" / "legacy.sh").is_file())
            self.assertTrue(any("removido" in w and "bin/legacy.sh" in w for w in warnings))

    def test_remocao_declarada_de_diretorio_inteiro(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            (upstream / "docs").mkdir()
            (upstream / "docs" / "a.md").write_text("a\n", encoding="utf-8")
            apply(upstream, make_overlays(tmp), tmp / "dest", remove=["docs"])
            self.assertFalse((tmp / "dest" / "docs").exists())

    def test_remocao_sem_alvo_no_upstream_avisa(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            warnings = apply(upstream, make_overlays(tmp), tmp / "dest",
                             remove=["nope.txt"])
            self.assertTrue(any("nope.txt" in w for w in warnings))


class OverlayConfinementTests(unittest.TestCase):
    def test_traversal_na_remocao_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            with self.assertRaises(OverlayError):
                apply(upstream, make_overlays(tmp), tmp / "dest",
                      remove=["../escape.txt"])

    def test_path_absoluto_na_remocao_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            with self.assertRaises(OverlayError):
                apply(upstream, make_overlays(tmp), tmp / "dest",
                      remove=["/tmp/escape.txt"])

    def test_symlink_de_overlay_apontando_para_fora_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            outside = tmp / "outside.md"
            outside.write_text("fora\n", encoding="utf-8")
            (overlays / "link.md").symlink_to(outside)
            with self.assertRaises(OverlayError):
                apply(upstream, overlays, tmp / "dest")

    def test_diretorio_symlink_de_overlay_apontando_para_fora_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            outside = tmp / "outside"
            outside.mkdir()
            (overlays / "linkdir").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OverlayError):
                apply(upstream, overlays, tmp / "dest")

    def test_symlink_de_overlay_interno_e_permitido(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            real = overlays / "real.md"
            real.write_text("conteúdo interno\n", encoding="utf-8")
            (overlays / "link.md").symlink_to(real)
            apply(upstream, overlays, tmp / "dest")
            self.assertEqual(
                (tmp / "dest" / "link.md").read_text(encoding="utf-8"),
                "conteúdo interno\n",
            )

    def test_overlay_contendo_git_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            overlays = make_overlays(tmp)
            git_overlay = overlays / ".git"
            git_overlay.mkdir()
            (git_overlay / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            with self.assertRaises(OverlayError):
                apply(upstream, overlays, tmp / "dest")

    def test_symlink_ciclico_no_upstream_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            upstream = make_upstream(tmp)
            loop = upstream / "loop"
            loop.symlink_to(upstream, target_is_directory=True)
            with self.assertRaises(OverlayError):
                apply(upstream, make_overlays(tmp), tmp / "dest")

    def test_upstream_nao_encontrado_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaises(OverlayError):
                apply(tmp / "ausente", make_overlays(tmp), tmp / "dest")


if __name__ == "__main__":
    unittest.main()
