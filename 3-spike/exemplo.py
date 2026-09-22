#!/usr/bin/env python3
"""
exemplo.py -- Spike: reconciliacao de saldo e deteccao de uso duplicado em
validacoes offline de bilhetagem (Caso Onibus / Envelope A -- startup, 6 devs,
sem equipe de operacao).

Prova a decisao mais arriscada do projeto, registrada em matriz.md, secao
"Direcao arquitetural adotada": usar arquitetura orientada a eventos, com
processamento idempotente e trilha imutavel inspirada em Event Sourcing,
para reconciliar saldo e descobrir uso duplicado de passagem -- ja que os
1.200 validadores embarcados aceitam a passagem offline (ate 4h sem rede,
resposta em ate 300 ms) e so sincronizam com a central depois.

Ver README.md nesta pasta para o que isto prova, como rodar, e o que
aconteceria se a decisao estivesse errada.
"""

import random
from dataclasses import dataclass
from collections import defaultdict

SEED = 42
TARIFA = 4.30
RECARGA_INICIAL = 50.00
JANELA_SUSPEITA_MIN = 5

@dataclass(frozen=True)
class Evento:
    event_id: str
    cartao: str
    onibus: str
    seq: int
    minuto: int
    tipo: str
    valor: float

def gerar_eventos_reais(rng):
    cartoes = [f"C{i:03d}" for i in range(1, 9)]
    onibus = [f"BUS{i:02d}" for i in range(1, 6)]
    eventos = []
    seq = defaultdict(int)
    eid = 0
    def novo(cartao, bus, minuto, tipo, valor):
        nonlocal eid
        eid += 1
        seq[cartao] += 1
        eventos.append(Evento(f"E{eid}", cartao, bus, seq[cartao], minuto, tipo, valor))
    for c in cartoes:
        novo(c, "APP", 0, "recarga", RECARGA_INICIAL)
    minuto = 1
    for _ in range(40):
        c = rng.choice(cartoes); b = rng.choice(onibus); minuto += rng.randint(1, 6)
        novo(c, b, minuto, "debito", TARIFA)
    for cartao, b1, b2 in [("C002", "BUS01", "BUS03"), ("C006", "BUS04", "BUS02")]:
        minuto += rng.randint(5, 10)
        novo(cartao, b1, minuto, "debito", TARIFA)
        novo(cartao, b2, minuto + rng.randint(1, 3), "debito", TARIFA)
    return eventos

def simular_rede_instavel(eventos, rng):
    entregues = list(eventos)
    duplicatas = rng.sample(eventos, k=max(1, len(eventos) // 6))
    entregues.extend(duplicatas)
    rng.shuffle(entregues)
    return entregues

class ReconciliadorEventos:
    def __init__(self):
        self.saldo = defaultdict(float); self.processados = set()
        self.esperado = defaultdict(lambda: 1); self.buffer = defaultdict(dict)
        self.log = []; self.duplicatas_filtradas = 0; self.eventos_reordenados = 0
    def receber(self, ev):
        if ev.event_id in self.processados:
            self.duplicatas_filtradas += 1; return
        self.processados.add(ev.event_id)
        if ev.seq != self.esperado[ev.cartao]:
            self.buffer[ev.cartao][ev.seq] = ev; self.eventos_reordenados += 1; return
        self._aplicar(ev)
        prox = self.esperado[ev.cartao]
        while prox in self.buffer[ev.cartao]:
            self._aplicar(self.buffer[ev.cartao].pop(prox)); prox = self.esperado[ev.cartao]
    def _aplicar(self, ev):
        self.saldo[ev.cartao] += ev.valor if ev.tipo == "recarga" else -ev.valor
        self.log.append(ev); self.esperado[ev.cartao] += 1
    def reconstruir_do_log(self):
        saldo = defaultdict(float)
        for ev in self.log: saldo[ev.cartao] += ev.valor if ev.tipo == "recarga" else -ev.valor
        return dict(saldo)
    def detectar_uso_duplicado(self, janela_min=JANELA_SUSPEITA_MIN):
        por_cartao = defaultdict(list)
        for ev in self.log:
            if ev.tipo == "debito": por_cartao[ev.cartao].append(ev)
        achados = []
        for cartao, evs in por_cartao.items():
            evs = sorted(evs, key=lambda e: e.minuto)
            for a, b in zip(evs, evs[1:]):
                if b.minuto - a.minuto <= janela_min and a.onibus != b.onibus:
                    achados.append((cartao, a, b))
        return achados

class ReconciliadorIngenuo:
    def __init__(self): self.saldo = defaultdict(float)
    def receber(self, ev): self.saldo[ev.cartao] += ev.valor if ev.tipo == "recarga" else -ev.valor

def saldo_verdadeiro(eventos):
    saldo = defaultdict(float)
    for ev in eventos: saldo[ev.cartao] += ev.valor if ev.tipo == "recarga" else -ev.valor
    return dict(saldo)

def main():
    rng = random.Random(SEED); eventos = gerar_eventos_reais(rng)
    entregues = simular_rede_instavel(eventos, rng); verdade = saldo_verdadeiro(eventos)
    idem = ReconciliadorEventos()
    for ev in entregues: idem.receber(ev)
    ingenuo = ReconciliadorIngenuo()
    for ev in entregues: ingenuo.receber(ev)
    reconstruido = idem.reconstruir_do_log()
    print("=" * 72)
    print("SPIKE -- reconciliacao de saldo com validacao offline (Caso Onibus / A)")
    print("=" * 72)
    print(f"Eventos gerados (linha do tempo real): {len(eventos)}")
    print(f"Eventos entregues a central (com retransmissoes, fora de ordem): {len(entregues)}")
    print(f"Duplicatas de rede filtradas pelo reconciliador: {idem.duplicatas_filtradas}")
    print(f"Eventos que chegaram fora de ordem (bufferizados ate a sequencia fechar): {idem.eventos_reordenados}")
    print()
    print("-" * 72)
    print(f"{'Cartao':<8}{'Saldo real':>14}{'Reconciliador (idempotente)':>30}{'Ingenuo':>16}")
    print("-" * 72)
    todos_ok = True
    for cartao in sorted(verdade):
        v = verdade[cartao]; i = idem.saldo[cartao]; n = ingenuo.saldo[cartao]
        ok = abs(v - i) < 1e-9; todos_ok = todos_ok and ok
        print(f"{cartao:<8}{v:>14.2f}{i:>30.2f}{n:>16.2f}   [{'OK' if ok else 'FALHOU'}]")
    print("-" * 72)
    bate = reconstruido == dict(idem.saldo)
    print(); print(f"Reconstrucao a partir da trilha imutavel bate com o saldo em memoria: {'SIM' if bate else 'NAO'}")
    divergentes = sum(1 for c in verdade if abs(verdade[c] - ingenuo.saldo[c]) > 1e-9)
    print(); print(f"Cartoes onde o reconciliador ingenuo diverge do saldo real: {divergentes} de {len(verdade)}")
    print("(cada divergencia e dinheiro contado errado por causa de retransmissao")
    print(" de rede nao tratada -- exatamente o risco que a decisao mitiga.)")
    print(); print("Uso duplicado da mesma passagem em onibus diferentes, detectado na")
    print("trilha imutavel (o validador embarcado nao podia ver isso offline):")
    achados = idem.detectar_uso_duplicado()
    if achados:
        for cartao, a, b in achados:
            print(f"  - {cartao}: debito em {a.onibus} (min {a.minuto}) e {b.onibus} (min {b.minuto}) -- diferenca de {b.minuto - a.minuto} min")
    else: print("  (nenhum caso na simulacao)")
    print(); print("=" * 72)
    if todos_ok and bate and divergentes > 0 and achados:
        print("RESULTADO: PASS -- a reconciliacao idempotente bate com a realidade,")
        print("a trilha e reconstruivel do zero, e tanto o desvio do reconciliador")
        print("ingenuo quanto a deteccao de uso duplicado provam por que a decisao")
        print("da matriz (eventos + idempotencia + trilha imutavel) e necessaria.")
    else: print("RESULTADO: FAIL -- ver detalhes acima.")
    print("=" * 72)

if __name__ == "__main__":
    main()
