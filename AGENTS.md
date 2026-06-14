# Instruções para agentes (Cursor / IA)

## Estilo de resposta

- Respostas **curtas e concisas** — direto ao ponto.
- Objetivas: o que fazer, por quê (uma linha se necessário), próximo passo.
- Sem enrolação, sem tom de tutorial genérico, sem “gptismos” (frases vazias, listas enormes sem pedido, fechamentos motivacionais, “fico à disposição”, etc.).
- Detalhar só quando o usuário pedir ou a tarefa exigir.

## Projeto

- CRM Neurix: FastAPI + Next.js + Supabase + Redis + Dokploy.
- Staging: ver `docs/staging-setup.md`.
- Não commitar secrets (`.env` está no `.gitignore`).
