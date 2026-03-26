# Plano Técnico — Demo Namastex (Omni + Genie via WhatsApp)

## Objetivo
Montar um ambiente de demonstração onde eu consigo conversar pelo WhatsApp e acionar agentes orquestrados pelo Genie, com uma camada de controle entre o canal do usuário e o canal dos agentes.

---

## 1) Escopo do teste

### Macro-objetivo
Demonstrar um fluxo ponta a ponta de operação assistida por agentes:

**WhatsApp (Omni) → Camada de Controle/Políticas → Genie (orquestração) → resposta no WhatsApp**

### Micro-objetivos
1. Usar **Omni** como runtime de canal e eventos.
2. Usar **Genie** como runtime de execução técnica com agentes.
3. Provar uma **barreira de segurança/governança** entre usuário e agente.

---

## 2) Arquitetura proposta (alto nível)

1. **Omni** recebe mensagem no WhatsApp.
2. Evento `message.received` entra no barramento.
3. **Policy Layer** valida regras (allowlist, intents permitidas, limites, risco).
4. Mensagem aprovada vira comando de trabalho para o **Genie**.
5. Genie executa pipeline (`wish/work/review`) com agentes.
6. Resultado passa de novo pela Policy Layer (sanitização/controle).
7. Omni envia resposta ao usuário (`message.sent`).

---

## 3) Componentes do demo

- **Omni server + CLI**
  - Instância WhatsApp conectada por QR.
  - Eventos e automações habilitados.
- **Genie CLI**
  - Time com agentes especialistas.
  - Execução em worktree para isolamento.
- **Policy Layer (bridge)**
  - Pode ser script Node/Python simples no início.
  - Funções mínimas:
    - filtrar quem pode acionar (allowlist);
    - mapear intents permitidas;
    - bloquear comandos perigosos;
    - impor limites (rate/tempo/tamanho);
    - registrar trilha de auditoria.

---

## 4) Setup rápido (30–45 min)

### Etapa A — Omni
1. Instalar/atualizar Omni.
2. Subir API local.
3. Criar instância WhatsApp.
4. Parear por QR.
5. Validar envio/recebimento no próprio número de teste.

### Etapa B — Genie
1. Instalar/atualizar Genie.
2. Rodar `genie setup`.
3. Criar time de demo (`team create`).
4. Cadastrar agentes necessários (ex.: planner, engineer, reviewer).
5. Validar execução local de um wish simples.

### Etapa C — Bridge (Policy Layer)
1. Assinar eventos do Omni (inbound).
2. Aplicar políticas e rotear para Genie.
3. Coletar saída do Genie e sanitizar resposta.
4. Publicar retorno via Omni.

---

## 5) Fluxos obrigatórios para apresentar

## Omni (mensageria/eventos)
- `message.received`
- `message.sent`
- `message.failed`
- `instance.connected` / `instance.disconnected`
- `automation.triggered` / `automation.failed`

## Genie (orquestração)
- `brainstorm`
- `wish`
- `work` (dispatch paralelo)
- `review`
- `done` / `blocked`

## Fluxo integrado (principal)
`message.received` → policy check → `wish/work` → review gate → resposta final (`message.sent`)

---

## 6) Guardrails mínimos (diferencial da entrevista)

1. **Allowlist de usuários** para acionar agente.
2. **Intent whitelist** (só comandos permitidos).
3. **Bloqueio de ações sensíveis** (sem execução destrutiva por padrão).
4. **Rate limit por usuário**.
5. **Timeout e fallback** de resposta.
6. **Auditoria** (log de entrada, decisão de política e saída).

---

## 7) Critérios de aceite do teste

- [ ] Envio e recebimento WhatsApp funcionando no Omni.
- [ ] Comando do usuário aciona execução no Genie.
- [ ] Resposta volta ao mesmo chat com rastreabilidade.
- [ ] Política bloqueia pelo menos 1 comando indevido (prova de barreira).
- [ ] Demonstração clara dos fluxos Omni + Genie + integração.

---

## 8) Roteiro de demo (5 minutos)

1. Mostrar diagrama da arquitetura.
2. Enviar mensagem no WhatsApp com tarefa permitida.
3. Exibir passagem na Policy Layer.
4. Mostrar Genie executando pipeline.
5. Receber resposta final no WhatsApp.
6. Fazer um teste com comando bloqueado para provar governança.

---

## 9) Riscos e mitigação

- **Instabilidade de canal:** usar ambiente de teste + retry.
- **Latência de agente:** resposta assíncrona com status intermediário.
- **Execução insegura:** políticas restritivas por padrão.
- **Contexto confuso:** templates de prompt por intent.

---

## 10) Resultado esperado

Entregar um demo funcional, simples e convincente que prova:
- domínio de arquitetura orientada a eventos,
- domínio de orquestração por agentes,
- e maturidade de segurança/governança na integração canal ↔ agentes.
