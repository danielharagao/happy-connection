# CRM Follow-up Playbook v1 (PO)

Data de emissão: 2026-03-07 (UTC)
Card: `task-po-crm-20260307-01`

## Objetivo
Garantir que todo lead ativo tenha próxima ação explícita, prazo e tipo de ação, reduzindo leads sem dono operacional no meio de funil.

## Regras operacionais
1. Campo obrigatório por lead ativo:
   - `nextActionAt` (UTC ISO-8601)
   - `nextActionType` (`whatsapp_followup` | `email_followup` | `call` | `proposal` | `nurture`)
2. SLA de atraso:
   - `overdue` quando `now > nextActionAt + 24h`
3. Filtros mínimos no Lead Board:
   - `Sem próxima ação` (`nextActionAt` ausente)
   - `Atrasados` (`overdue=true`)
4. Histórico no Lead 360:
   - registrar transições de `nextAction*` com `changedBy`, `changedAt`, `reason`
5. Antiduplicidade de alertas:
   - no máximo 1 alerta por lead por janela de 6h para o mesmo motivo de SLA.

## Contrato funcional (proposto)
### API
- `PATCH /api/crm/leads/:id/next-action`
  - body: `{ nextActionAt, nextActionType, reason? }`
- `GET /api/crm/leads?missingNextAction=true`
- `GET /api/crm/leads?overdueNextAction=true`
- `POST /api/crm/alerts/followup-sla/run` (job idempotente)

### Evento interno
- `crm.followup.sla.overdue`
  - payload: `{ leadId, nextActionAt, nextActionType, owner, overdueHours }`

## Critérios de aceite testáveis (QA)
1. Lead ativo não salva sem `nextActionAt` e `nextActionType`.
2. Badge visual aparece quando atraso >24h.
3. Filtro “Sem próxima ação” retorna somente leads sem `nextActionAt`.
4. Job de alerta não duplica alerta na janela de 6h.
5. Histórico exibe última alteração de próxima ação no Lead 360.

## Evidência operacional usada no ciclo
Fonte: `data/crm_interactions.json` (snapshot 2026-03-07 UTC)
- Interações registradas: 2
- Leads tocados no snapshot: 2 (`leadId` 40 e 42)

Conclusão PO: aprovado o playbook funcional v1 para implementação técnica no próximo ciclo de engenharia CRM.
