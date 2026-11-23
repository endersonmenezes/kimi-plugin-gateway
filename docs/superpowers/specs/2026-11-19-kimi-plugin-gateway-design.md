# Kimi Plugin Gateway — desenho

## Intenção

O `kimi-plugin-gateway` será um catálogo de plugins Kimi adaptados de plugins Claude existentes, sem criar forks dos projetos de origem. Cada adaptação referenciará o repositório original como um submódulo Git fixado em um commit exato e poderá conter manifestos e arquivos de adaptação mantidos no Gateway.

O primeiro caso de uso será o `pbakaus/impeccable`. O fluxo também deverá atender a projetos como `AgriciDaniel/claude-seo`, embora uma conversão possa exigir adaptações manuais quando houver recursos específicos do Claude.

As operações começam por Issues e terminam em Pull Requests. Somente o mantenedor do Gateway aprova as mudanças; o autor do projeto original não precisa participar do fluxo.

## Objetivos

- Converter um plugin Claude em uma estrutura instalável pelo Kimi Code por meio de uma Issue.
- Atualizar um plugin já cadastrado para uma tag, branch ou commit solicitado por meio de outra Issue.
- Fixar toda origem em um commit completo, mesmo quando a solicitação usa uma tag ou branch.
- Permitir alterações mantidas pelo Gateway sem editar o conteúdo do submódulo.
- Exigir revisão do mantenedor antes do merge.
- Publicar um ZIP independente por plugin, contendo tudo o que a instalação precisa.
- Oferecer um marketplace personalizado no qual o usuário escolha somente um plugin.
- Registrar origem, commit, licença e adaptações de cada pacote.
- Validar os pacotes sem executar código não confiável do projeto de origem.

## Não objetivos

- Criar forks ou repositórios separados para cada plugin.
- Fazer merge ou release automático sem revisão humana.
- Garantir conversão integral e automática de todo plugin Claude.
- Executar instaladores, hooks, servidores MCP ou scripts da origem durante a conversão.
- Monitorar automaticamente todos os upstreams na primeira versão.
- Manter um serviço próprio de marketplace ou um backend além do GitHub.
- Publicar novamente o `kimi-seo` neste primeiro incremento; ele serve como referência de conversão.

## Resultados que caracterizariam falha

- Instalar um plugin exigir baixar ou habilitar todos os demais.
- Um ZIP depender de inicializar submódulos depois da instalação.
- Uma adaptação exigir commits dentro do repositório de origem.
- Uma Issue conseguir alterar o `main` sem aprovação do CODEOWNER.
- O conversor descartar silenciosamente comandos, agentes, hooks ou outras capacidades da origem.
- Uma atualização sobrescrever adaptações manuais sem mostrar a diferença no PR.
- Uma release existente ser substituída por outro conteúdo usando a mesma tag.

## Restrições conhecidas do Kimi Code

A documentação oficial informa que:

- O manifesto fica em `kimi.plugin.json` ou `.kimi-plugin/plugin.json`; este projeto usará o primeiro.
- Caminhos de Skills, agentes, comandos, prompts, hooks e executáveis precisam permanecer dentro da raiz do plugin após resolver links simbólicos.
- A instalação por URL de repositório GitHub baixa uma release ou um ZIP da branch/commit; submódulos não fazem parte desse ZIP.
- Um marketplace personalizado contém uma lista de entradas com `id` e `source`, e `source` pode apontar para um ZIP.
- A instalação local copia os arquivos para a área gerenciada pelo Kimi.

Por isso, o submódulo ficará dentro da raiz de cada adaptação e o artefato de release conterá uma cópia real dos arquivos dele.

Fonte: https://www.kimi.com/code/docs/en/kimi-code-cli/customization/plugins.html

## Abordagens consideradas

### 1. Submódulos e releases independentes — escolhida

Cada pasta de plugin contém o submódulo e suas adaptações. Após o merge, uma Action gera um ZIP somente daquele plugin e atualiza uma entrada de marketplace cuja URL aponta para a release correspondente.

Vantagens: instalação isolada, origem rastreável, nenhum fork e nenhuma necessidade de clone recursivo para o usuário final.

Custo: é necessário implementar empacotamento, versionamento de release e publicação de artefatos.

### 2. Somente instalação local

O usuário clonaria o Gateway com submódulos e instalaria `./plugins/<id>`.

Vantagem: dispensa releases.

Desvantagens: pior experiência, exige Git e clone recursivo e baixa o catálogo inteiro. Será mantida como caminho de desenvolvimento e verificação, não como distribuição principal.

### 3. Um repositório de distribuição por plugin

O Gateway publicaria cada pacote em um repositório próprio.

Vantagem: instalação direta pela URL do repositório.

Desvantagens: multiplica repositórios, credenciais, releases e manutenção. Não será adotada.

## Estrutura do repositório

```text
.github/
  CODEOWNERS
  ISSUE_TEMPLATE/
    convert-plugin.yml
    update-plugin.yml
  workflows/
    convert-plugin.yml
    update-plugin.yml
    validate.yml
    release.yml
plugins/
  impeccable/
    gateway.json
    kimi.plugin.json
    overlays/
      # caminhos relativos à raiz do upstream, quando necessários
    upstream/             # submódulo pbakaus/impeccable
scripts/
  # automações determinísticas do Gateway
marketplace.json
README.md
```

`gateway.json` registrará os dados controlados pelo Gateway:

```json
{
  "id": "impeccable",
  "upstream": {
    "url": "https://github.com/pbakaus/impeccable",
    "requestedRef": "v4.10.0",
    "commit": "<sha-completo>",
    "manifest": ".claude-plugin/plugin.json",
    "sourceVersion": "4.10.0"
  },
  "releaseRevision": 1
}
```

O SHA completo será preenchido pela automação. O manifesto de origem poderá estar em outro caminho quando informado na Issue. `sourceVersion` será sempre o campo `version` do manifesto Claude no commit escolhido, independentemente de o ref solicitado ser tag, branch ou commit. O ref não será interpretado como versão. Se esse campo estiver ausente, vazio ou contiver caracteres fora de `[0-9A-Za-z._-]`, o fluxo automático falhará com um diagnóstico e deixará o caso para PR manual; não haverá sanitização silenciosa nem troca por `0.0.0`. A comparação de `sourceVersion` determinará a reinicialização de `releaseRevision`.

Os overlays reproduzem caminhos do upstream. Por exemplo:

```text
plugins/impeccable/overlays/.claude/skills/impeccable/SKILL.md
```

substitui, apenas no pacote:

```text
plugins/impeccable/upstream/.claude/skills/impeccable/SKILL.md
```

Adições usam a mesma regra. Remoções não ficarão implícitas: se forem necessárias, serão declaradas em uma lista `overlays.remove` no `gateway.json`, para aparecerem claramente no PR.

## Formato dos pacotes

O ZIP terá o manifesto na raiz e preservará o diretório `upstream`:

```text
kimi.plugin.json
gateway-source.json
upstream/
  .claude/
  LICENSE
  ...
```

Para o Impeccable, o manifesto inicial apontará para `./upstream/.claude/skills/`. Metadados como nome, descrição, versão, autor, homepage e licença serão derivados do manifesto Claude quando existirem.

`gateway-source.json` será gerado no empacotamento com URL, ref solicitado, commit completo, revisão do Gateway e hash SHA-256 do ZIP não poderá estar dentro do próprio ZIP; o checksum será publicado como arquivo separado na release.

O nome do ativo será estável por plugin e tag:

```text
impeccable.zip
impeccable.zip.sha256
```

A tag combinará id, versão de origem e revisão do Gateway:

```text
impeccable-v4.10.0-gateway.1
```

A revisão começa em `1`, volta para `1` quando a versão upstream mudar e aumenta quando somente a adaptação mudar. Releases e assets existentes serão tratados como imutáveis; o workflow falhará em vez de sobrescrevê-los.

## IssueOps

### Execução e repetição

Os workflows automáticos serão disparados somente por `issues: opened` com o rótulo correspondente. Editar uma Issue ou adicionar comentários não iniciará outra operação. O mantenedor poderá repetir a operação por `workflow_dispatch`, informando o número da Issue; essa repetição lerá os campos atuais.

Cada Issue usará uma branch determinística `issueops/issue-<número>-<id>` e no máximo um PR. Uma repetição fará checkout da branch existente, adicionará um novo commit e atualizará o mesmo PR por push comum, sem force-push. Se ainda não houver PR, criará um após validar a branch. Uma execução que falhar comentará na Issue com o motivo e o link do run; branches parciais não serão apagadas automaticamente.

Haverá concorrência por id de plugin para impedir que duas operações modifiquem a mesma pasta simultaneamente. Uma segunda Issue para o mesmo id deverá aguardar; se já existir PR aberto para outra Issue do mesmo id, a automação falhará com um link para ele em vez de criar branches concorrentes.

### Conversão

A Issue terá campos para:

- URL pública do repositório GitHub;
- tag, branch ou commit de origem;
- id desejado no Gateway, opcional;
- caminho do manifesto Claude, com padrão `.claude-plugin/plugin.json`;
- observações sobre adaptações necessárias, opcional.

O workflow:

1. Confere se a Issue usa o modelo e o rótulo `conversion`.
2. Normaliza e valida os campos sem interpolá-los diretamente em comandos shell.
3. Aceita somente URLs HTTPS públicas de repositórios GitHub e ids compatíveis com o manifesto Kimi.
4. Resolve o ref para um commit completo e verifica que o id ainda não existe.
5. Cria o submódulo no commit resolvido.
6. Lê o manifesto e gera os arquivos iniciais do plugin e a entrada de marketplace.
7. Produz um relatório de capacidades convertidas, capacidades que exigem revisão e campos ignorados.
8. Executa as validações estruturais e empacota localmente para confirmar que o ZIP é autocontido.
9. Abre um PR vinculado à Issue, sem aprovar nem fazer merge.

Se a automação não souber converter uma capacidade, ela ainda poderá abrir o PR com um aviso visível, desde que o pacote mínimo seja válido. A revisão humana decidirá se criará overlays ou ajustará o manifesto antes do merge.

### Atualização

A Issue terá campos para:

- id de um plugin existente;
- nova tag, branch ou commit;
- motivo da atualização, opcional.

O workflow:

1. Localiza `plugins/<id>/gateway.json` e mantém a URL de origem já cadastrada.
2. Resolve o novo ref para um commit completo.
3. Move o submódulo para esse commit e atualiza `requestedRef` e `commit`.
4. Atualiza somente os metadados gerados necessários, como a versão, sem regenerar todo o manifesto e apagar edições humanas.
5. Recalcula `releaseRevision`: `1` se a versão upstream mudou; revisão seguinte se ela permaneceu igual.
6. Atualiza a URL da entrada de marketplace.
7. Detecta mudanças de estrutura e capacidades entre os dois commits e as apresenta no PR.
8. Executa as mesmas validações da conversão e abre o PR.

Se um arquivo de overlay ou alvo de remoção deixar de existir no novo upstream, a validação falhará e bloqueará o PR até revisão humana. Se um overlay ficar idêntico ao novo arquivo de origem, a automação emitirá um aviso de redundância, mas não o removerá sozinha. Se o alvo continuar existindo e tiver mudado, o overlay será preservado e o PR destacará a diferença para revisão. Nenhum overlay será removido, renomeado ou reescrito automaticamente.

Mudanças de URL de origem, renomeação de id e remoção de plugin ficam fora desses dois fluxos iniciais e exigem PR manual.

## Conversão de capacidades

A primeira versão usará conversão determinística em Python, com biblioteca padrão, e scripts de workflow para operações Git. Python foi escolhido por facilitar validação de JSON, caminhos e testes sem adicionar dependências ao projeto vazio.

O conversor deverá:

- mapear metadados comuns do `.claude-plugin/plugin.json` para `kimi.plugin.json`;
- reconhecer Skills explícitas no manifesto e Skills em `.claude/skills/`;
- reconhecer comandos e agentes nos diretórios usados pela origem quando existirem;
- ajustar os caminhos para incluir o prefixo `./upstream/`;
- manter o manifesto Kimi legível e ordenado de forma estável;
- listar campos desconhecidos e recursos não convertidos no relatório do PR.

Agentes, comandos e instruções podem conter nomes de ferramentas, modelos ou comportamentos específicos do Claude. A conversão não fará substituições globais de texto nem presumirá equivalência. Esses pontos serão destacados para revisão e corrigidos por overlays quando necessário.

Hooks e MCP não serão ativados automaticamente. O conversor poderá registrá-los como pendências; declarações Kimi correspondentes somente entram após adaptação explícita e revisão. Isso evita executar comandos da origem por efeito colateral da instalação.

## Marketplace e instalação

O `marketplace.json` versionado na branch principal terá uma entrada por plugin:

```json
{
  "version": "2",
  "plugins": [
    {
      "id": "impeccable",
      "displayName": "Impeccable",
      "source": "https://github.com/endersonmenezes/kimi-plugin-gateway/releases/download/impeccable-v4.10.0-gateway.1/impeccable.zip"
    }
  ]
}
```

O PR de conversão ou atualização já prepara a URL determinística. Logo após o merge, a release publica o asset naquele endereço. Até a publicação terminar, a entrada nova pode existir sem o asset; o workflow de release deverá falhar visivelmente e poderá ser repetido sem criar outra versão.

O usuário poderá abrir o marketplace pela URL do arquivo ou instalar diretamente o ZIP de um plugin. A instalação nunca usará o ZIP da branch principal.

### Escopo das releases

Após cada push no `main`, o workflow identificará os plugins cujos arquivos mudaram no intervalo do push e publicará cada um em um job independente. PRs manuais seguem a mesma regra dos PRs IssueOps: o mantenedor precisa atualizar `releaseRevision` e a URL do marketplace no próprio PR. Um merge que altere vários plugins poderá gerar várias releases, mas nunca um pacote agregado; uma falha será reportada por plugin e não apagará releases já publicadas.

Alterações somente em scripts, documentação ou workflows não geram releases. Uma alteração de plugin sem nova tag falhará pela política de imutabilidade. A execução manual de release exigirá um id de plugin e usará somente a versão e revisão já commitadas; não incrementará metadados nem alterará o marketplace automaticamente.

## Revisão e permissões

- `.github/CODEOWNERS` atribuirá o catálogo, workflows e scripts ao mantenedor do Gateway.
- A proteção da branch `main` deverá exigir PR, pelo menos uma aprovação, revisão de CODEOWNER, resolução de conversas e validações obrigatórias.
- A aprovação será invalidada por novos commits.
- O token das Actions terá somente as permissões necessárias em cada workflow.
- Workflows disparados por Issues poderão ler o repositório, criar branches/PRs e comentar na Issue; não poderão publicar releases.
- Somente o workflow após merge no `main`, ou uma execução manual autorizada, poderá publicar releases.
- A configuração de branch protection é uma etapa administrativa do repositório e será documentada, pois não pode ser garantida apenas por arquivos Git.

## Segurança da automação

- Nenhum campo de Issue será inserido diretamente em shell; valores chegarão por arquivos JSON ou variáveis devidamente delimitadas.
- A automação não executará código, instaladores, hooks ou gerenciadores de pacotes do upstream.
- A origem será limitada a repositórios públicos do GitHub.
- Refs serão resolvidos para commits completos antes do PR.
- Caminhos de overlays e manifestos serão normalizados para impedir `..`, caminhos absolutos e escapes por links simbólicos.
- A cópia para o pacote não incluirá metadados `.git`.
- A validação verificará que todos os caminhos declarados existem e permanecem dentro da raiz.
- Releases não substituirão tags ou assets existentes.
- O relatório do PR mostrará o commit e as adaptações, facilitando revisão da cadeia de origem.

## Validação e verificação

Testes automatizados cobrirão:

- leitura e geração de manifests;
- resolução e confinamento de caminhos;
- aplicação e remoção declarativa de overlays;
- preservação de adaptações durante atualização;
- formação de tags, URLs e entradas de marketplace;
- empacotamento com manifesto na raiz e conteúdo real do submódulo;
- rejeição de ids, URLs, paths e releases inválidos ou duplicados;
- ausência de execução de scripts da origem.

O PR executará testes unitários com `unittest`, validará todos os manifests e construirá os ZIPs sem publicá-los.

Antes de concluir o primeiro incremento, o cenário completo será exercido com o Impeccable:

1. Criar a adaptação no commit/tag escolhido.
2. Construir o ZIP e conferir seu conteúdo e checksum.
3. Instalar somente esse ZIP em um `KIMI_CODE_HOME` temporário usando o Kimi Code CLI.
4. Confirmar no `/plugins info` que o manifesto e a Skill foram reconhecidos sem diagnósticos.
5. Confirmar que nenhum outro plugin do Gateway foi instalado.
6. Exercitar a atualização para outro ref e verificar que overlays permanecem aplicados.

A verificação com o CLI será feita localmente se o ambiente de CI não possuir o executável; nesse caso, a limitação será relatada, não substituída por uma alegação de sucesso baseada apenas em imports ou compilação.

## Primeira entrega

A primeira entrega incluirá:

- os dois modelos de Issue e seus workflows;
- scripts de conversão, atualização, validação e empacotamento com testes;
- proteção por CODEOWNERS e instruções para configurar a branch protegida;
- geração de releases e marketplace;
- a adaptação funcional do Impeccable;
- documentação curta de uso para solicitar, revisar, instalar e atualizar um plugin.

## Decisões deixadas ao implementador

- Nomes internos de funções e divisão exata dos módulos Python.
- Pequenos ajustes de mensagens, desde que os erros apontem o campo e a ação necessária.
- Uso de jobs reutilizáveis para evitar duplicação entre os workflows.
- Escolha do ref inicial do Impeccable: preferir a tag correspondente à versão do manifesto de origem; se não existir, usar o commit completo resolvido da branch padrão e registrar essa decisão no PR.
- Adaptações específicas mínimas do Impeccable, após inspecionar sua Skill e confirmar o comportamento no Kimi.
