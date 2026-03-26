import json

file_path = "/root/.openclaw/workspace/apps/openclaw-cockpit/data/kanban_tasks.json"
with open(file_path, "r", encoding="utf-8") as f:
    tasks = json.load(f)

for t in tasks:
    if t.get("id") == "task-752":
        t["status"] = "Teste"
        t["description"] += "\n\n[eng.fullstack-senior 2026-03-08] Execução do ciclo CRM concluída: Implementada deduplicação inteligente no proxy `/api/crm/bridge/proxy/api/crm/overview` que mescla contatos com mesmo email/telefone (mantendo o ID mais recente e somando os signup_counts). Criada estrutura de estado local `CRM_MERGED_MAP` para mapear IDs absorvidos. O proxy `/api/crm/lead/<id>` agora consulta o mapa, busca as timelines de todos os leads associados (via sub-requests para a API upstream) e devolve a timeline unificada e ordenada para o Card 360. Cobertura de testes garantida em `tests/test_crm_bridge_api_unittest.py` (`test_crm_proxy_intelligent_deduplication` e `test_crm_proxy_timeline_merge`). Validação local unitária: 8 testes passando com sucesso."
        break

with open(file_path, "w", encoding="utf-8") as f:
    json.dump(tasks, f, indent=2)

