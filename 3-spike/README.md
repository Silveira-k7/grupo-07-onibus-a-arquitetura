# Spike — reconciliação de saldo com validação offline

**Caso:** Ônibus (bilhetagem e mobilidade urbana) · **Envelope:** A, startup
**ADR que este código prova:** a decisão mais arriscada do projeto, registrada em
`1-matriz/matriz.md`, seção "Direção arquitetural adotada" (deve corresponder ao
ADR-0005 — "decisão mais arriscada" — na Entrega 2; os ADRs formais ainda não
foram anexados a esta conversa, então o spike referencia a matriz diretamente).
A decisão: usar **arquitetura orientada a eventos** com **processamento
idempotente** e **trilha imutável inspirada em Event Sourcing** para reconciliar
saldo e descobrir uso duplicado de passagem.

## O que prova

Os 1.200 validadores embarcados respondem em até 300 ms **sem rede** (até 4h
offline) e só sincronizam depois. Isso força duas perguntas do caso: como o
saldo fica consistente com sincronização atrasada, e como o sistema descobre
que a mesma passagem foi usada em dois ônibus, já que o validador local não
pode impedir isso na hora.

O `exemplo.py` simula: (1) a linha do tempo real dos eventos (recargas e
débitos, incluindo dois casos deliberados de uso duplicado); (2) a rede 4G
instável entregando esses eventos à central — com retransmissões
(duplicatas) e fora de ordem; e (3) dois consumidores desses eventos: um
**idempotente** (deduplica por `event_id`, reconcilia por cartão respeitando a
ordem causal, guarda tudo numa trilha imutável) e um **ingênuo** (aplica cada
evento na ordem em que chega, sem dedup).

O resultado mostra que o reconciliador idempotente sempre bate com o saldo
real e é 100% reconstruível a partir só da trilha (prova de auditabilidade),
enquanto o ingênuo diverge em metade dos cartões por causa das
retransmissões — dinheiro contado errado. A trilha imutável também permite
detectar, depois do fato, os casos de uso duplicado que o validador offline
não via na hora.

## Como rodar

```bash
python3 exemplo.py
```

Sem dependências além da biblioteca padrão do Python 3.12. A saída é
determinística (seed fixa) e está registrada em `saida-esperada.txt` — rodar
de novo deve produzir exatamente o mesmo texto.

## Se a decisão estivesse errada

Se a central processasse eventos sem idempotência e sem reconciliação causal
(o reconciliador "ingênuo" do script), toda retransmissão de rede — normal
num 4G intermitente com 1.200 ônibus — viraria um débito ou recarga duplicado
de verdade: saldo errado, conciliação com o banco não fecha, e a contestação
de até 30 dias fica sem uma trilha confiável para arbitrar quem tem razão. E
sem a trilha imutável, o uso duplicado da mesma passagem em dois ônibus nunca
seria descoberto — só apareceria como prejuízo agregado no repasse mensal,
sem forma de apontar o cartão ou o evento responsável.