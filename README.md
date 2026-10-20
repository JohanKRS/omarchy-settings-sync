# Agent Settings for Omarchy

Um botão na barra do Omarchy que abre um painel suspenso para conversar com
seu agente, ajustar o sistema e sincronizar preferências entre computadores.
O painel segue o tema do Omarchy, fica preso à barra e não participa do
layout de janelas. Escape ou um clique fora o ocultam, preservando a tarefa.

O **plugin** e suas **configurações pessoais** ficam em repositórios separados.
No primeiro uso, informe o repositório de configurações ou peça ao agente para
criar um novo. Nenhum repositório pessoal vem embutido no código.

## Instalação

Requer Omarchy com suporte a plugins de barra, Python 3.11+ e ao menos um agente
instalado e autenticado. Para um repositório privado, autentique o Git antes:
`gh auth login` e `gh auth setup-git`.

```bash
omarchy plugin add https://github.com/JohanKRS/omarchy-agent-settings.git --enable
```

O primeiro clique instala, se necessário, `python-gobject`, `gtk4`, `vte4`
e `gtk4-layer-shell`
pelo gerenciador de pacotes do Omarchy, em um terminal visível. Ele pode pedir
a senha de administrador.

Para atualizar: `omarchy plugin update community.agent-settings`.
Para remover: `omarchy plugin remove community.agent-settings`.
O estado e o repositório de configurações são preservados.

## Uso

- **Clique no ícone de ajustes:** abre ou fecha o painel de conversa.
- **Sincronizar agora**, ou **botão direito no ícone:** envia ao agente um pedido
  preparado para buscar, conciliar, aplicar e testar o repositório configurado.
- **Enviar pedido:** peça uma alteração, como “ative Caps Lock e salve essa
  preferência para os outros computadores”.
- **Salvar no repositório:** autoriza publicar os ajustes reutilizáveis após
  validá-los. Desmarcado, o agente faz apenas a aplicação local.
- **Engrenagem:** muda o repositório, a branch e as permissões do Codex integrado.
- **Nova conversa:** arquiva o histórico local e começa outro contexto.

Escolha agente, modelo e esforço antes de enviar. A sincronização é executada
pelo agente: o plugin não sobrescreve arquivos nem executa `git pull` sozinho.
O [procedimento enviado ao agente](plugin/WORKFLOW.md) pede comparação com a
última versão aplicada, backups, adaptações de hardware, testes e um registro
de resultado. Conflitos reais aparecem na conversa.

Em uso recorrente, a primeira etapa consulta apenas o commit remoto. Se ele
for igual ao da última sincronização concluída nesta máquina, a resposta é
somente **“No changes.”**, sem varrer arquivos, reinstalar ou recarregar nada.
Primeiro uso não significa instalação vazia: configurações já presentes são
adotadas. Tentativas incompletas retomam pendências; novos pedidos fazem
alterações pontuais. Histórico local e registros são separados por repositório.

Na outra máquina, instale o mesmo plugin, selecione o mesmo repositório de
configurações e clique em **Sincronizar agora**.

## Agentes e acesso

**Codex:** conversa integrada por `codex app-server --stdio`, com lista de
modelos e níveis de raciocínio retornados pela sua instalação. Usa o perfil,
login, skills e servidores MCP locais. Exibe respostas, andamento, perguntas
e solicitações de autorização. Permite retomar a conversa e interromper tarefas.
Testado com Codex CLI 0.163.0.

O padrão é `workspace-write` com revisão automática. Você também pode escolher
autorizações manuais ou somente leitura, sem escalada. **Abrir no terminal**
retoma a conversa na CLI quando uma extensão exige a interface oficial.
Conexões exclusivas de outro aplicativo não são copiadas: precisam estar
disponíveis no perfil da CLI escolhida.

**Claude Code:** CLI interativa dentro da janela, com modelo e esforço
(`low`, `medium`, `high`, `xhigh`, `max`). A disponibilidade de cada combinação
depende da versão, conta e modelo do Claude.

**Outros agentes reconhecidos pelo Omarchy:** OpenCode, Gemini CLI, GitHub
Copilot, Crush, Cursor CLI, Grok, Hermes, Muse Code, Oh My Pi, OpenClaw e Pi.
O plugin inicia a CLI em um terminal integrado usando a forma de prompt do
lançador do Omarchy. Login, ferramentas, perguntas e aprovações continuam sob
controle dessa CLI. Modelo só é oferecido nos adaptadores que aceitam a opção;
os demais controles ficam na própria conversa. Sessões externas são encerradas
pelo comando de saída do agente; **Interromper** envia Ctrl+C.

Agentes diferentes têm capacidades e permissões diferentes. O plugin não
instala agentes nem fornece credenciais. Use o menu de agentes do Omarchy.

## Repositório de configurações

Inclua um `README.md` e, de preferência, `SYNC.md` com:

- arquivos compartilhados e seus destinos;
- trechos que devem ser mesclados, em vez de substituir arquivos completos;
- dependências, comandos de validação e condições de hardware;
- preferências que devem continuar locais.

Pode usar HTTPS, SSH ou `usuario/repositorio`; branch vazia usa a padrão.
O setup de repositório novo pede ao agente um repositório **privado**. Tokens,
cookies, sessões, perfis completos, históricos e modelos baixados não devem
ser incluídos.

## Arquivos locais

Respeita `XDG_CONFIG_HOME`, `XDG_STATE_HOME` e `XDG_DATA_HOME`.

| Local padrão | Conteúdo |
| --- | --- |
| `~/.config/omarchy-agent-settings/settings.json` | Repositório, seleções, permissões e ID de conversa |
| `~/.local/state/omarchy-agent-settings/` | Conversa, histórico, log, backups e último resultado |
| `~/.local/share/omarchy-agent-settings/workspace/` | Área de trabalho e cópia do repositório |

Esses dados ficam locais. O plugin não tem servidor web, telemetria nem API key
própria. Fechar a janela durante uma tarefa apenas a oculta; clique novamente
no ícone para acompanhar.

## Desenvolvimento

```bash
python3 -m unittest discover -s tests -v
omarchy plugin validate .
bash plugin/launch.sh
```

O painel usa GTK4 Layer Shell, sem servidor web nem janela XDG comum.
O widget informa o monitor e a posição da barra ao abrir.
O código da interface fica em `plugin/app.py`, protocolo e adaptadores em
`plugin/core.py`, widget em `plugin/BarWidget.qml`. Os testes de interface usam
GTK com estado temporário; não sincronizam configurações reais. A integração
foi validada localmente com Codex e Claude; os demais adaptadores seguem o
lançador do Omarchy e precisam ser exercitados com suas respectivas contas.

O visual acompanha `colors.toml` e `shell.toml` do tema ativo do Omarchy:
paleta, fonte monoespaçada, estados dos controles e arredondamento das janelas.
A paleta e a tipografia são recarregadas quando o tema muda.

A interface segue o idioma do aplicativo/sistema (`LANGUAGE`, `LC_ALL`,
`LC_MESSAGES`, `LANG`), com inglês como fallback. Inclui inglês, português
e espanhol. Traduções adicionais podem ser incluídas em `plugin/locales/`.
Para testar: `AGENT_SETTINGS_LANGUAGE=pt bash plugin/launch.sh`.

Teste visual isolado: `python3 tests/ui_smoke.py`.
O teste real do Codex verificou execução de comando e acesso aos MCPs do perfil;
o Claude foi verificado com uma resposta sem ferramentas. Os testes GTK
exercitam também o ciclo do terminal integrado, perguntas e persistência.

Licença MIT.
