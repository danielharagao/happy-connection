# MEMORY.md — QA Guardian

## Contexto inicial
- Projeto: Cockpit OpenClaw
- Time: Engenharia & Produto
- Última atualização: (preencher em cada execução)

## Decisões e preferências
- Backlog executivo: somente Dan, Alfred e PO criam itens.
- Executor deve ficar explícito nos cron jobs.
- Kanban orientado a fluxo, sem ruído.

## Registro de trabalho
- (acrescente bullets por execução)

- [2026-03-07] Daily Vault Audit (BA Pro) executada via Cron:
  - Validado ambiente `launch-repo/docs/ementa-lp`: Identificadas atualizações na LP (8 módulos da Ementa, novos campos no formulário `app.js`, tabelas de preço atualizadas e novo PDF oficial).
  - Tarefa sugerida incluída no Kanban (`task-`): "QA Audit: Deploy Ementa LP e Validação de Fluxo de Cadastro" delegada ao PO para revisão e posterior deploy.
  - Suíte de regressão do openclaw-cockpit não apresentou falhas críticas durante a auditoria em paralelo.
