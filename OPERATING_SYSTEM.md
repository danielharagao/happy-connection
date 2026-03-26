# Mission Control — Operating System (v1)

## Objetivo
Garantir execução previsível, com qualidade e governança, no fluxo CRM do Cockpit.

## Princípios
1. Clareza de estado > velocidade bruta.
2. Evidência obrigatória para qualquer avanço de status.
3. Sem bypass de gate: Dan aprova Done.
4. Uma fonte da verdade: Kanban + logs de progresso.

## Fluxo oficial de trabalho e Responsáveis
1. **Ideias**
   - **Dono:** PO. 
   - **Regra:** O PO deve garantir que sempre haja pelo menos 5 ideias de CRM na coluna.
   - **Gate:** O Dan avalia as ideias e move as escolhidas para "Refinamento".

2. **Refinamento**
   - **Dono:** PO.
   - **Regra:** O PO pega os cards movidos pelo Dan, escreve a User Story e os Critérios de Aceite no corpo do card e, em seguida, move para "Desenvolvimento".

3. **Desenvolvimento**
   - **Dono:** Engenheiro Full Stack Senior.
   - **Regra:** Pega os cards refinados, implementa (código, UX, testes) e, ao terminar o incremento, move para "Teste".

4. **Teste**
   - **Dono:** PO.
   - **Regra:** O PO testa em ambiente local, valida os critérios de aceite e anexa evidências. Estando OK, move para "Review".

5. **Review**
   - **Dono:** Dan.
   - **Regra:** O Dan revisa a entrega com as evidências e aprova movendo para "Produção".

6. **Produção**
   - **Dono:** Dan (Aprovação Final).


## Isolamento de Squads
Os agentes são estritamente divididos por **Squad**. 
- O **Squad de CRM** (PO de CRM, Engenheiro de CRM) interage EXCLUSIVAMENTE com cards que possuem `"squad": "crm"`.
- O **Squad de Conteúdo** (PO de Conteúdo, Engenheiro de Conteúdo) interage EXCLUSIVAMENTE com cards que possuem `"squad": "conteudo"`.
Para criar novos cards ou atualizar, certifique-se de adicionar/atualizar o campo `"squad"` no JSON (via API HTTP em `http://127.0.0.1:8787/api/kanban/tasks` ou lendo/gravando `data/kanban_tasks.json` prestando atenção à propriedade `squad` de cada card).

## Papéis atuais
- **main (Alfred):** direção operacional, desbloqueio, governança.
- **po.mission-control:** PO de CRM (prioriza, especifica, testa, documenta).
- **eng.fullstack-senior:** implementação full-stack com qualidade e UX.

## Regras de qualidade
- Testes relevantes obrigatórios por ciclo.
- Nada de card “fantasma”: sem evidência = sem avanço.
- Sem criar tarefas duplicadas por tema.

## Checklist de execução por ciclo (obrigatório)
1. Ler este documento.
2. Validar status do card alvo no Kanban.
3. Executar incremento concreto.
4. Rodar testes.
5. Registrar evidência no card + progress log.
6. Publicar resumo curto para Dan.

## Auditoria de conformidade
- Qualquer agente que violar o fluxo deve registrar bloqueio e corrigir status.
- Em dúvida de escopo/decisão: escalar para Dan antes de avançar.
