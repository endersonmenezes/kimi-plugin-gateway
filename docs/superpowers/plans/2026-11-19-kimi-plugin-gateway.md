# Kimi Plugin Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir um Gateway IssueOps que converta e atualize plugins Claude com submódulos, revisão obrigatória e releases ZIP independentes instaláveis pelo Kimi Code, entregando o Impeccable como primeiro plugin.

**Architecture:** Um pacote Python local, sem dependências externas, concentrará parsing, conversão, overlays, validação e empacotamento. GitHub Actions apenas orquestrará esse pacote e operações Git: Issues abrirão PRs, merges publicarão releases e o marketplace apontará para assets imutáveis. O Impeccable ficará em `plugins/impeccable/upstream`, com adaptações separadas em `overlays`.

**Tech Stack:** Python 3.12+ com biblioteca padrão e `unittest`, Git/GitHub CLI, GitHub Actions, GitHub Issue Forms, JSON e ZIP.

**Spec:** `docs/superpowers/specs/2026-11-19-kimi-plugin-gateway-design.md`

## Global Constraints

- Não criar forks nem repositórios de distribuição separados.
- Toda origem deve ser um repositório público HTTPS do GitHub fixado em SHA completo.
- Nenhum campo de Issue pode ser interpolado diretamente em shell.
- Não executar código, hooks, instaladores ou gerenciadores de pacotes do upstream.
- Todo caminho de manifesto ou overlay deve permanecer dentro da raiz permitida após resolver symlinks.
- Não ativar hooks ou MCP automaticamente durante a conversão.
- Não apagar adaptações humanas nem usar force-push.
- Releases e assets são imutáveis; nomes seguem `<id>-v<sourceVersion>-gateway.<revision>`.
- O ZIP deve conter `kimi.plugin.json` na raiz e uma cópia real de `upstream`, sem metadados `.git`.
- A aprovação do CODEOWNER e os checks são obrigatórios antes do merge.
- Usar somente Python com biblioteca padrão; não adicionar dependências de runtime ou teste.

## Review Focus

- Inputs de Issue multilinha, ausentes ou com valores que parecem opções de comando devem ser tratados como dados, nunca como shell; teste em `tests/test_issues.py` na Task 1.
- Um manifesto sem `version`, com versão insegura ou com paths que escapem da raiz deve falhar sem criar pacote; testes em `tests/test_conversion.py` e `tests/test_validate.py` nas Tasks 2 e 5.
- Atualização que remova o alvo de um overlay deve falhar; overlay idêntico ao upstream deve apenas avisar; testes em `tests/test_overlays.py` na Task 4.
- Um ref de branch com mesmo conteúdo de uma tag deve produzir o mesmo `sourceVersion`, pois a versão vem do manifesto; teste em `tests/test_conversion.py` na Task 2.
- Um merge que altere vários plugins deve gerar uma lista independente de plugins e nunca um ZIP agregado; teste em `tests/test_release.py` na Task 6.

---

## Mapa de arquivos

- `scripts/gateway/issues.py`: parsing seguro dos formulários e validação dos inputs.
- `scripts/gateway/config.py`: schema de `gateway.json`, ids, versões, tags e URLs.
- `scripts/gateway/conversion.py`: leitura do manifesto Claude, descoberta de capacidades e geração Kimi.
- `scripts/gateway/operations.py`: criação e atualização de adaptações e geração do relatório de PR.
- `scripts/gateway/overlays.py`: aplicação de substituições, adições e remoções declarativas.
- `scripts/gateway/validate.py`: validação estrutural e de segurança de uma adaptação/pacote.
- `scripts/gateway/package.py`: staging, ZIP, checksum e manifesto de procedência.
- `scripts/gateway/marketplace.py`: entradas estáveis e URLs de assets.
- `scripts/gateway/release.py`: detecção dos plugins modificados em um push.
- `scripts/gateway/cli.py` e `__main__.py`: interface única chamada pelos workflows.
- `tests/`: testes unitários por responsabilidade e fixtures mínimas.
- `.github/ISSUE_TEMPLATE/`: formulários de conversão e atualização.
- `.github/workflows/`: IssueOps, validação e release.
- `plugins/impeccable/`: primeira adaptação e submódulo.
- `marketplace.json`, `README.md`, `.github/CODEOWNERS`: catálogo, uso e governança.

### Task 1: Inputs, configuração e interface do CLI

**Files:**
- Create: `scripts/gateway/__init__.py`
- Create: `scripts/gateway/__main__.py`
- Create: `scripts/gateway/issues.py`
- Create: `scripts/gateway/config.py`
- Create: `scripts/gateway/cli.py`
- Test: `tests/test_issues.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `parse_issue_form(body: str) -> dict[str, str]`.
- Produces: `validate_repository_url(value: str) -> str`, retornando URL normalizada sem `.git` nem barra final.
- Produces: `validate_plugin_id(value: str) -> str`.
- Produces: `GatewayConfig` com `plugin_id`, `upstream_url`, `requested_ref`, `commit`, `manifest_path`, `source_version`, `release_revision` e `remove_paths`.
- Produces: `load_config(path: Path) -> GatewayConfig`, `release_tag(config) -> str` e `release_url(config, owner_repo: str) -> str`.
- Produces: CLI `python3 -m gateway <convert|update|validate|package|changed-plugins>`; os subcomandos posteriores podem inicialmente retornar erro explícito de não implementado.

- [ ] **Step 1: Escrever testes falhos de parsing e validação**

Cobrir campos na ordem do formulário, valores vazios, blocos multilinha, `_No response_`, ids válidos/inválidos, URLs fora do GitHub, `javascript:`, URL com credenciais, `../` e valores iniciados por `-`. Testar `release_tag` com `4.10.0` e revisão `1`, além de rejeição de versão ausente ou fora de `[0-9A-Za-z._-]`.

- [ ] **Step 2: Rodar os testes e confirmar falha**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_issues tests.test_config -v`
Expected: FAIL por módulos/funções ainda inexistentes.

- [ ] **Step 3: Implementar parsing, modelos e CLI mínima**

Parsear somente os cabeçalhos `###` gerados pelos Issue Forms. Normalizar URLs sem fazer rede. Validar ids pela regra Kimi e proibir qualquer path absoluto ou traversal. Usar `dataclasses` e exceções com mensagem acionável. Criar entrypoint que encaminha os cinco subcomandos.

- [ ] **Step 4: Rodar os testes e confirmar sucesso**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_issues tests.test_config -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gateway tests/test_issues.py tests/test_config.py
git commit -m "feat: add gateway input and config parsing"
```

### Task 2: Conversão determinística de manifests

**Files:**
- Create: `scripts/gateway/conversion.py`
- Test: `tests/test_conversion.py`
- Create: `tests/fixtures/claude-basic/` com manifesto e Skills mínimas

**Interfaces:**
- Consumes: `validate_plugin_id` e validação de versão da Task 1.
- Produces: `ConversionResult(manifest: dict, source_version: str, report: list[str])`.
- Produces: `convert_manifest(upstream: Path, manifest_path: str, plugin_id: str | None = None) -> ConversionResult`.
- Produces: `write_kimi_manifest(path: Path, manifest: dict) -> None`, com JSON ordenado e estável.

- [ ] **Step 1: Escrever testes falhos da conversão**

Usar os metadados reais essenciais do Impeccable: nome `impeccable`, versão `4.10.0` e Skills em `./.claude/skills/`. Verificar saída `skills: ["./upstream/.claude/skills/"]`. Testar descoberta de `commands` e `agents`, campos desconhecidos no relatório, hooks/MCP apenas como pendências, ausência de versão e path que escape de `upstream`. Criar dois refs Git com o mesmo conteúdo e nomes diferentes e confirmar o mesmo `sourceVersion`, comprovando que ele vem do manifesto e não do ref.

- [ ] **Step 2: Rodar os testes e confirmar falha**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_conversion -v`
Expected: FAIL por `conversion.py` inexistente.

- [ ] **Step 3: Implementar conversão e descoberta**

Ler `.claude-plugin/plugin.json`, mapear metadados comuns e detectar capacidades sem executar arquivos. Prefixar paths locais com `./upstream/`; não reescrever textos de Skills. A versão deve vir exclusivamente do manifesto. Manter hooks/MCP fora do manifesto gerado e registrá-los no relatório.

- [ ] **Step 4: Rodar os testes e confirmar sucesso**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_conversion -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gateway/conversion.py tests/test_conversion.py tests/fixtures/claude-basic
git commit -m "feat: convert Claude plugin manifests"
```

### Task 3: Operações de conversão e atualização

**Files:**
- Create: `scripts/gateway/operations.py`
- Modify: `scripts/gateway/cli.py`
- Create: `scripts/gateway/marketplace.py`
- Test: `tests/test_operations.py`
- Test: `tests/test_marketplace.py`

**Interfaces:**
- Consumes: `GatewayConfig`, `convert_manifest`, parsing de Issues e URLs das Tasks 1–2.
- Produces: `ConversionInputs(repository_url: str, requested_ref: str, plugin_id: str | None, manifest_path: str)` e `UpdateInputs(plugin_id: str, requested_ref: str)`.
- Produces: `convert_plugin(repo_root: Path, inputs: ConversionInputs) -> Path`.
- Produces: `update_plugin(repo_root: Path, inputs: UpdateInputs) -> Path`.
- Produces: `upsert_marketplace_entry(path: Path, config: GatewayConfig, owner_repo: str, display_name: str) -> None`.
- Produces: `OperationResult` com id, commit de origem, tag e relatório para o PR.

- [ ] **Step 1: Escrever testes falhos com repositórios Git temporários**

Criar upstream local somente como fixture de teste e simular a resolução externa do GitHub para SHA. Verificar criação de `gateway.json`, manifesto e entrada de marketplace; atualização de SHA/ref/versão; preservação de campos humanos e overlays; reset/incremento de `releaseRevision`; rejeição de id duplicado, troca de URL e remoção automática de overlays.

- [ ] **Step 2: Rodar os testes e confirmar falha**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_operations tests.test_marketplace -v`
Expected: FAIL por operações inexistentes.

- [ ] **Step 3: Implementar criação, atualização e marketplace**

Fazer operações Git por listas de argumentos com `subprocess.run(..., shell=False)`. Na atualização, carregar o manifesto existente e alterar somente metadados gerados necessários. Atualizar `sourceVersion`, SHA e ref, nunca a URL cadastrada. Gerar relatório com capacidades adicionadas/removidas e overlays afetados.

- [ ] **Step 4: Rodar os testes e confirmar sucesso**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_operations tests.test_marketplace -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gateway/operations.py scripts/gateway/marketplace.py scripts/gateway/cli.py tests/test_operations.py tests/test_marketplace.py
git commit -m "feat: add plugin conversion and update operations"
```

### Task 4: Overlays, validação e pacotes autocontidos

**Files:**
- Create: `scripts/gateway/overlays.py`
- Create: `scripts/gateway/validate.py`
- Create: `scripts/gateway/package.py`
- Modify: `scripts/gateway/cli.py`
- Test: `tests/test_overlays.py`
- Test: `tests/test_validate.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: configuração e manifests produzidos nas Tasks 1–3.
- Produces: `apply_overlays(upstream: Path, overlays: Path, destination: Path, remove_paths: list[str]) -> list[str]`, retornando avisos.
- Produces: `validate_plugin(plugin_dir: Path, packaged: bool = False) -> list[str]`, retornando diagnósticos não bloqueantes e levantando `ValidationError` para erros.
- Produces: `build_package(plugin_dir: Path, output_dir: Path) -> PackageResult`, com caminhos do ZIP e SHA-256.

- [ ] **Step 1: Escrever testes falhos de overlays e confinamento**

Cobrir adição, substituição, remoção declarada, arquivo-alvo removido no update, overlay redundante, `..`, path absoluto e symlink que aponta para fora. Confirmar que overlay original nunca é alterado.

- [ ] **Step 2: Escrever testes falhos de validação e empacotamento**

Verificar manifesto na raiz do ZIP, Skills reais dentro de `upstream`, ausência de `.git`, paths inexistentes, paths inseguros em hooks/MCP, checksum estável e dois plugins produzindo arquivos separados. Incluir na fixture um script upstream que criaria um arquivo-marca se executado e confirmar que a marca não existe após conversão, validação e empacotamento.

- [ ] **Step 3: Rodar os testes e confirmar falha**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_overlays tests.test_validate tests.test_package -v`
Expected: FAIL por módulos inexistentes.

- [ ] **Step 4: Implementar staging seguro e validação**

Copiar para diretório temporário, aplicar overlays somente no staging e gerar `gateway-source.json`. Resolver paths com `Path.resolve()` e exigir contenção. Validar o pacote final novamente depois do ZIP. Não seguir symlinks inseguros nem incluir `.git`.

- [ ] **Step 5: Rodar os testes e confirmar sucesso**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_overlays tests.test_validate tests.test_package -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/gateway/overlays.py scripts/gateway/validate.py scripts/gateway/package.py scripts/gateway/cli.py tests/test_overlays.py tests/test_validate.py tests/test_package.py
git commit -m "feat: build validated standalone plugin packages"
```

### Task 5: Seleção de releases por plugin

**Files:**
- Create: `scripts/gateway/release.py`
- Modify: `scripts/gateway/cli.py`
- Test: `tests/test_release.py`

**Interfaces:**
- Consumes: configuração e empacotamento das Tasks anteriores.
- Produces: `changed_plugins(repo_root: Path, before: str, after: str) -> list[str]`, ordenado e sem duplicatas.
- CLI: `python3 -m gateway changed-plugins --event-path <path> --repo-root <path>`, emitindo JSON para o workflow.

- [ ] **Step 1: Escrever testes falhos da seleção**

Criar histórico Git temporário com alterações em documentação, um plugin e dois plugins. Verificar lista vazia para docs/scripts, um id para mudança isolada e dois ids para mudança múltipla. Testar push inicial e SHA anterior zerado com comportamento explícito e seguro.

- [ ] **Step 2: Rodar os testes e confirmar falha**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_release -v`
Expected: FAIL por `release.py` inexistente.

- [ ] **Step 3: Implementar seleção baseada no diff**

Ler `before` e `after` do evento JSON, usar `git diff --name-only` e considerar somente arquivos sob `plugins/<id>/`. Não inferir releases pelo marketplace e não agregar plugins.

- [ ] **Step 4: Rodar os testes e confirmar sucesso**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_release -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/gateway/release.py scripts/gateway/cli.py tests/test_release.py
git commit -m "feat: select changed plugins for release"
```

### Task 6: Workflows IssueOps, validação e governança

**Files:**
- Create: `.github/ISSUE_TEMPLATE/convert-plugin.yml`
- Create: `.github/ISSUE_TEMPLATE/update-plugin.yml`
- Create: `.github/workflows/convert-plugin.yml`
- Create: `.github/workflows/update-plugin.yml`
- Create: `.github/workflows/validate.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/CODEOWNERS`
- Modify: `README.md`

**Interfaces:**
- Consumes: todos os subcomandos do CLI das Tasks 1–5.
- Produces: branches `issueops/issue-<número>-<id>`, um PR por Issue e releases por plugin alterado.

- [ ] **Step 1: Adicionar validações estáticas falhas para workflows**

Criar testes de configuração com biblioteca padrão que leiam os arquivos YAML como texto e confirmem eventos, permissões mínimas, ausência de interpolação direta de campos de Issue em `run`, checkout recursivo e proibição de force-push. No release, exigir criação sem flags de substituição e uma verificação prévia de tag/asset existente. Não adicionar parser YAML externo.

- [ ] **Step 2: Rodar testes e confirmar ausência dos workflows**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_workflows -v`
Expected: FAIL por arquivos ausentes.

- [ ] **Step 3: Criar Issue Forms e workflows de PR**

Disparar por `issues: opened` com labels `conversion`/`update` e permitir `workflow_dispatch` com número da Issue. Passar somente o caminho de `github.event` ao CLI. Implementar concorrência por id, branch determinística, comentário de erro e criação/reutilização de PR sem force-push.

- [ ] **Step 4: Criar validação e release**

Em PRs, fazer checkout recursivo, rodar toda a suíte e validar/construir todos os pacotes sem publicar. Após push no `main`, usar `changed-plugins` e matrix para validar, empacotar e criar releases/assets imutáveis. Permitir retry manual por id sem alterar metadados.

- [ ] **Step 5: Configurar governança e documentação**

Definir `@endersonmenezes` como CODEOWNER. Documentar a configuração obrigatória de branch protection e os comandos para usuários, mantenedores e desenvolvedores. Não afirmar que a proteção está ativa antes de conferir as configurações do GitHub.

- [ ] **Step 6: Rodar testes estáticos e suíte completa**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .github scripts tests README.md
git commit -m "feat: add IssueOps and release workflows"
```

### Task 7: Primeira adaptação do Impeccable

**Files:**
- Create: `plugins/impeccable/gateway.json`
- Create: `plugins/impeccable/kimi.plugin.json`
- Create: `plugins/impeccable/upstream` como submódulo de `https://github.com/pbakaus/impeccable`
- Create: `plugins/impeccable/overlays/` somente se a verificação exigir adaptação
- Modify: `.gitmodules`
- Modify: `marketplace.json`

**Interfaces:**
- Consumes: conversor, validador e empacotador das Tasks 2–5.
- Produces: `impeccable.zip`, `impeccable.zip.sha256` e entrada de marketplace instalável.

- [ ] **Step 1: Selecionar e registrar a origem**

Preferir a tag correspondente à versão do manifesto; se não existir, resolver a branch padrão para SHA completo. Adicionar o submódulo nesse SHA e conferir `git submodule status`. Não executar `npx impeccable install` nem hooks do projeto.

- [ ] **Step 2: Gerar a adaptação e inspecionar o relatório**

Run: `PYTHONPATH=scripts python3 -m gateway convert ...`
Expected: manifesto apontando para `./upstream/.claude/skills/`, `sourceVersion` igual ao manifesto de origem e relatório sem recursos omitidos silenciosamente.

- [ ] **Step 3: Criar overlays mínimos se necessários**

Adaptar somente incompatibilidades comprovadas do Kimi. Manter autoria e licença. Explicar no PR cada arquivo alterado e não editar diretamente o submódulo.

- [ ] **Step 4: Validar e empacotar**

Run: `PYTHONPATH=scripts python3 -m gateway validate --plugin impeccable`
Run: `PYTHONPATH=scripts python3 -m gateway package --plugin impeccable --output dist`
Expected: `dist/impeccable.zip` e checksum; ZIP contém manifesto, procedência e arquivos reais da Skill, sem `.git`.

- [ ] **Step 5: Rodar a suíte completa**

Run: `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .gitmodules marketplace.json plugins/impeccable
git commit -m "feat: add Impeccable Kimi plugin"
```

### Task 8: Verificação ponta a ponta da entrega

**Files:**
- Modify: `README.md` apenas se a verificação revelar instrução incorreta
- Modify: arquivos da adaptação somente se a instalação real revelar incompatibilidade

**Interfaces:**
- Consumes: `dist/impeccable.zip` e os workflows completos.
- Produces: evidência de instalação isolada, diagnóstico do plugin e comportamento da atualização.

- [ ] **Step 1: Instalar o ZIP em um diretório Kimi temporário**

Criar diretório temporário e usá-lo como `KIMI_CODE_HOME`. Conferir `kimi --help` e executar o prompt não interativo suportado com `/plugins install <caminho-absoluto-do-ZIP>`; se o CLI não oferecer esse caminho, usar a TUI e registrar exatamente a etapa manual.

- [ ] **Step 2: Confirmar reconhecimento e isolamento**

Run: `kimi -p "/plugins info impeccable"` com o mesmo `KIMI_CODE_HOME`.
Expected: plugin `impeccable` habilitado, Skill reconhecida e nenhum diagnóstico de path/manifesto. Listar plugins e confirmar que nenhum outro plugin do Gateway foi instalado.

- [ ] **Step 3: Exercitar a Skill real**

Invocar uma operação não destrutiva da Skill Impeccable em um alvo mínimo e confirmar que suas instruções são carregadas pelo Kimi. Se exigir runtime adicional, instalar somente com autorização e registrar a dependência; não confundir manifesto reconhecido com funcionamento completo.

- [ ] **Step 4: Exercitar atualização com overlay**

Usar fixture ou outro ref real, aplicar a operação `update`, verificar preservação do overlay e construir novo ZIP com revisão correta. Testar o bloqueio quando o alvo do overlay desaparece.

- [ ] **Step 5: Conferir o estado final do repositório**

Run: `git status --short`
Expected: nenhum log, diretório temporário, ZIP local ou cache de teste deixado no repositório. Manter somente arquivos que fazem parte da entrega.

- [ ] **Step 6: Commit final de correções, se houver**

```bash
git add <somente-arquivos-corrigidos-pela-verificação>
git commit -m "fix: verify standalone Impeccable installation"
```
