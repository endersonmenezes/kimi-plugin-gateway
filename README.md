# kimi-plugin-gateway

Gateway de distribuição de plugins Kimi convertidos de plugins Claude. Cada
plugin fica em `plugins/<id>/` com o upstream como submódulo Git em
`upstream/`, um manifesto Kimi gerado (`kimi.plugin.json`), os metadados de
procedência (`gateway.json`), overlays declarativos em `overlays/` e uma
entrada no catálogo `marketplace.json` na raiz.

## Solicitando um plugin (usuários)

1. Abra uma **Issue** com um dos modelos:
   - **Converter plugin Claude** (rótulo `conversion`): informe a URL pública
     do repositório GitHub, a tag/branch/commit de origem, o id desejado
     (opcional) e o caminho do manifesto Claude.
   - **Atualizar plugin convertido** (rótulo `update`): informe o id de um
     plugin existente e o novo ref upstream.
2. O workflow IssueOps correspondente valida os campos, executa a operação
   via CLI (`--issue-event`) e abre um PR a partir da branch determinística
   `issueops/issue-<número>-<id>`.
3. Se algo falhar, um comentário automático na Issue explica o motivo e
   aponta o run.

Nenhum campo de Issue é interpolado em shell: os workflows gravam o evento
em JSON e passam apenas o caminho ao CLI.

## Revisando (mantenedores)

- `.github/CODEOWNERS` designa `@endersonmenezes` como revisor obrigatório
  de catálogo, workflows e scripts.
- Todo PR dispara o workflow de validação: suíte completa de testes mais
  validação e empacotamento local de todos os plugins, sem publicar nada.
- O PR do IssueOps contém o resumo da operação (id, commit de origem,
  tag e relatório de capacidades) para revisão da cadeia de origem.
- Para repetir uma operação: **Actions → IssueOps → Run workflow** informando
  o número da Issue. A repetição relê os campos atuais da Issue, reutiliza a
  branch e o mesmo PR (push comum, sem force-push) e adiciona um novo commit.

## Releases

- Somente o workflow `release.yml` publica, após push na `main` — releases
  nunca são criadas a partir de Issue ou PR.
- O workflow seleciona os plugins com arquivos alterados no push
  (`changed-plugins` sobre o evento de push) e publica **um release por
  plugin**, em jobs independentes (`fail-fast: false`): ZIP autocontido
  `<id>.zip` e checksum separado `<id>.zip.sha256`.
- Tags (`<id>-v<versão>-gateway.<revisão>`) e assets são **imutáveis**: o
  workflow confere tag e release existentes antes de criar e falha visível
  em vez de substituir. O retry manual (`workflow_dispatch` com o id do
  plugin) republica sem alterar metadados nem o marketplace.

## Desenvolvimento local

Requisitos: Python 3 (somente biblioteca padrão) e Git.

```bash
# converter um plugin Claude (rede: clona o upstream)
PYTHONPATH=scripts python3 -m gateway convert \
  --repository-url https://github.com/<owner>/<repo> --ref v1.2.0 \
  --plugin-id meu-plugin --repo-root .

# atualizar um plugin convertido para um novo ref
PYTHONPATH=scripts python3 -m gateway update \
  --plugin-id meu-plugin --ref v1.3.0 --repo-root .

# validar e empacotar localmente
PYTHONPATH=scripts python3 -m gateway validate --plugin-id meu-plugin --repo-root .
PYTHONPATH=scripts python3 -m gateway package --plugin-id meu-plugin \
  --output-dir dist --repo-root .

# listar plugins alterados por um evento de push (usado pelo release)
PYTHONPATH=scripts python3 -m gateway changed-plugins \
  --event-path event.json --repo-root .

# testes
PYTHONPATH=scripts python3 -m unittest discover -s tests -v
```

Os mesmos comandos `convert` e `update` aceitam `--issue-event <arquivo.json>`
com o evento da Issue, como usado pelos workflows.

## Governança

- `.github/CODEOWNERS`: revisão obrigatória de `@endersonmenezes`.
- Permissões mínimas por workflow nos arquivos de `.github/workflows/`
  (workflows de IssueOps não publicam releases; validação é somente leitura).

### Proteção da branch `main` (configuração obrigatória)

A proteção de branch **não pode ser garantida pelos arquivos deste
repositório** — ela é uma configuração administrativa do GitHub e **pode não
estar ativa**. O mantenedor deve conferir e manter em
**Settings → Branches** as seguintes regras para `main`:

- exigir pull request antes do merge;
- exigir pelo menos 1 aprovação e revisão de CODEOWNER;
- exigir resolução das conversas;
- exigir os status checks do workflow de validação;
- invalidar aprovações quando novos commits forem adicionados;
- restringir pushes diretos (inclusive para administradores).

Sem essa configuração, CODEOWNERS e os checks de CI não impedem que um merge
ou push direto contorne a revisão.
