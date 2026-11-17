# -*- coding: utf-8 -*-
"""
Cadeia de saldo, camada de unidade — fixtures sintéticas.

O extrato do Inter e o do C6 trazem, em cada linha, o saldo da conta. Até
a sessão 6 essa coluna era lida e jogada fora. Ela é um juiz EXTERNO: o
número foi escrito pelo banco, e comparar o valor que o parser produziu
contra ele valida, de uma vez, leitura de valor, sinal, ordem e
completude — e localiza a quebra quando há.

Estes testes rodam em qualquer máquina. Os equivalentes sobre os extratos
reais estão em `tests/integracao/test_cadeia_de_saldo.py`.

As fixtures são novas, e não reaproveitam `INTER_JAN`/`C6_JAN`: aquelas
foram escritas quando a coluna de saldo não significava nada, e os
números dela não encadeiam. Mexer nelas mudaria insumo já calibrado por
outros testes; escrever fixture nova não mexe em nada.
"""

import pytest

from tests.conftest import C6_CADEIA, INTER_CADEIA, SINTETICOS
from tests.saldo import (cadeia_do_c6, cadeia_do_inter, dias_do_c6, relatar,
                         saldo_declarado_do_inter, saldos_do_inter)


# ---------------------------------------------------------------------------
# Inter — cadeia linha a linha
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_inter_cadeia_de_saldo_fecha_linha_a_linha(importar):
    """
    Centenas de linhas no extrato real, 6 aqui. Se o parser trocar um sinal,
    perder uma linha ou reordenar, algum elo deixa de fechar.
    """
    resultado = importar(INTER_CADEIA)
    saldos = saldos_do_inter(SINTETICOS / INTER_CADEIA)

    assert len(resultado.transactions) == len(saldos) == 6

    quebras = cadeia_do_inter(resultado.transactions, saldos)
    assert not quebras, relatar(quebras)


@pytest.mark.invariante
def test_inter_soma_do_periodo_bate_com_o_saldo_declarado(importar):
    """
    A fixture abre em zero, então a soma de todos os valores tem que dar
    exatamente o `Saldo` do preâmbulo. É a mesma propriedade que o extrato
    real tem — ele também abre em zero — e que fecha a janela inteira sem
    depender de nenhum número informado à mão.
    """
    resultado = importar(INTER_CADEIA)
    caminho = SINTETICOS / INTER_CADEIA
    saldos = saldos_do_inter(caminho)

    primeira = max(saldos)                       # última linha do arquivo
    abertura = round(saldos[primeira]
                     - next(t.value for t in resultado.transactions
                            if t.raw_data["row_number"] == primeira), 2)
    assert abertura == 0.00

    soma = round(sum(t.value for t in resultado.transactions), 2)
    assert soma == saldo_declarado_do_inter(caminho) == 229.25


@pytest.mark.invariante
def test_inter_saldo_e_por_linha_e_nao_por_dia(importar):
    """
    O que a coluna É foi determinado por medição, e a medição fica gravada
    aqui: existem dois lançamentos no mesmo dia com saldos diferentes.
    Fosse "saldo do dia", os dois repetiriam o número, e a cadeia teria
    que fechar por dia — outra granularidade, outro teste.
    """
    resultado = importar(INTER_CADEIA)
    saldos = saldos_do_inter(SINTETICOS / INTER_CADEIA)

    por_dia = {}
    for transacao in resultado.transactions:
        chave = transacao.date.date()
        por_dia.setdefault(chave, set()).add(
            round(saldos[transacao.raw_data["row_number"]], 2))

    multiplos = {d: s for d, s in por_dia.items()
                 if sum(1 for t in resultado.transactions
                        if t.date.date() == d) > 1}
    assert multiplos, "a fixture precisa ter um dia com mais de um lançamento"
    for dia, distintos in multiplos.items():
        assert len(distintos) > 1, (
            "em %s o saldo se repetiu — isso seria saldo DO DIA, e a cadeia "
            "do Inter deixaria de valer linha a linha" % dia)


# ---------------------------------------------------------------------------
# C6 — cadeia por dia contábil
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_c6_cadeia_de_saldo_fecha_por_dia_contabil(importar):
    resultado = importar(C6_CADEIA)
    dias = dias_do_c6(SINTETICOS / C6_CADEIA)

    assert len(resultado.transactions) == len(dias) == 7

    quebras = cadeia_do_c6(resultado.transactions, dias)
    assert not quebras, relatar(quebras)


@pytest.mark.invariante
def test_c6_o_dia_da_cadeia_e_o_contabil_nao_o_lancamento(importar):
    """
    A fixture tem uma linha lançada em 03/01/2026 com Data Contábil
    02/01/2026 — a mesma forma de uma linha do extrato real.
    Agrupar por Data Lançamento quebra a cadeia; por Data Contábil, não.
    É o teste que impede alguém de "simplificar" a chave de agrupamento.
    """
    resultado = importar(C6_CADEIA)
    dias = dias_do_c6(SINTETICOS / C6_CADEIA)

    divergentes = [n for n, d in dias.items()
                   if d["contabil"] != next(
                       t.date.strftime("%d/%m/%Y")
                       for t in resultado.transactions
                       if t.raw_data["row_number"] == n)]
    assert divergentes, (
        "a fixture perdeu a linha em que contábil e lançamento diferem — "
        "sem ela este teste não distingue as duas leituras")

    # Pela Data Lançamento (que é a data canônica da Transaction), a mesma
    # cadeia NÃO fecha. Se um dia fechar, a distinção deixou de existir e
    # este teste precisa ser repensado, não apagado.
    por_lancamento = {
        n: {"contabil": next(t.date.strftime("%d/%m/%Y")
                             for t in resultado.transactions
                             if t.raw_data["row_number"] == n),
            "saldo": d["saldo"]}
        for n, d in dias.items()}
    assert cadeia_do_c6(resultado.transactions, por_lancamento), (
        "agrupar por Data Lançamento passou a fechar — a fixture não "
        "distingue mais as duas leituras")


@pytest.mark.invariante
def test_c6_cadeia_atravessa_a_virada_de_ano(importar):
    """
    A fixture vai de 29/12/2025 a 15/01/2026 de propósito. Ordenar
    "DD/MM/AAAA" como texto põe janeiro antes de dezembro e a cadeia
    quebra — é a primeira metade da regra de data do CLAUDE.md, e o
    conjunto real (só 2026) não a exercita.
    """
    resultado = importar(C6_CADEIA)
    dias = dias_do_c6(SINTETICOS / C6_CADEIA)

    anos = {d["contabil"][-4:] for d in dias.values()}
    assert anos == {"2025", "2026"}, (
        "a fixture deixou de atravessar a virada de ano: %s" % sorted(anos))

    assert not cadeia_do_c6(resultado.transactions, dias)
