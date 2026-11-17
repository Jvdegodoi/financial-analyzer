# -*- coding: utf-8 -*-
"""
Camada de unidade — taxa de poupança (3c da sessão 5, achado 1.6).

Duas partes, e as duas eram do mesmo card:

1. O clamp `max(0.0, savings_rate)` escondia o negativo. Em mês que gastou
   mais do que entrou o saldo é negativo, e o negativo É a informação.

2. `calculate_savings_rate` rodava `calculate_summary` com
   `exclude_internal=True` por dentro, enquanto os três cards ao lado usavam
   o que o usuário escolheu no checkbox. Em parte dos meses os quatro
   números da mesma linha saíam de populações diferentes.

A coerência é testada nos DOIS estados do checkbox, contra o saldo sobre
receitas dos cards vizinhos.
"""

from datetime import datetime

import pytest

from src.business.calculator import FinancialCalculator
from src.data.models import Transaction


def _t(dia, valor, categoria="Alimentação") -> Transaction:
    return Transaction(
        id="sint-%02d-%s" % (dia, categoria[:4]),
        date=datetime(2026, 3, dia),
        value=valor,
        description="Movimento %02d" % dia,
        category=categoria,
        source_account="Nubank (conta) 99887766",
    )


@pytest.fixture
def mes_no_vermelho():
    """Receita 3.000, despesa 4.500 — saldo −1.500, taxa −50%."""
    return [_t(1, 3000.0, "Transferências"), _t(5, -4500.0)]


@pytest.fixture
def mes_com_neutras():
    """
    As mesmas linhas, mais um par de transferência interna de 2.000 que
    infla receita E despesa quando as neutras entram. É esse par que fazia
    os quatro números divergirem.
    """
    neutras = [
        _t(8, 2000.0, "Transferência Interna"),
        _t(8, -2000.0, "Transferência Interna"),
    ]
    return [_t(1, 3000.0, "Transferências"), _t(5, -4500.0)] + neutras


def test_mes_no_vermelho_devolve_taxa_negativa(mes_no_vermelho):
    """O clamp zerava exatamente isto."""
    taxa = FinancialCalculator.calculate_savings_rate(mes_no_vermelho)
    assert taxa < 0
    assert taxa == pytest.approx(-50.0)


def test_mes_no_azul_continua_positivo():
    trans = [_t(1, 5000.0, "Transferências"), _t(5, -1000.0)]
    assert FinancialCalculator.calculate_savings_rate(trans) == \
        pytest.approx(80.0)


def test_sem_receita_devolve_zero_e_nao_divide_por_zero():
    assert FinancialCalculator.calculate_savings_rate(
        [_t(5, -1000.0)]) == 0.0
    assert FinancialCalculator.calculate_savings_rate([]) == 0.0


@pytest.mark.parametrize("excluir_neutras", [True, False])
def test_taxa_casa_com_os_cards_vizinhos(mes_com_neutras, excluir_neutras):
    """
    A propriedade que faltava: taxa == saldo/receitas dos MESMOS cards.

    Os três cards saem de um `calculate_summary` com a escolha do usuário;
    a taxa precisa sair do mesmo. Com `exclude_internal=False` as neutras
    entram nos dois lados; com True, saem dos dois.
    """
    summary = FinancialCalculator.calculate_summary(
        mes_com_neutras, exclude_internal=excluir_neutras)
    taxa = FinancialCalculator.calculate_savings_rate(
        mes_com_neutras, exclude_internal=excluir_neutras)

    esperado = summary.saldo / summary.total_receitas * 100
    assert taxa == pytest.approx(esperado)
    assert FinancialCalculator.savings_rate_from_summary(summary) == \
        pytest.approx(taxa)


def test_o_checkbox_muda_a_taxa_de_verdade(mes_com_neutras):
    """
    Se os dois estados dessem o mesmo número, o teste acima passaria por
    coincidência. Aqui está a diferença que existia e não aparecia na tela:
    o par neutro de 2.000 muda o denominador.
    """
    com = FinancialCalculator.calculate_savings_rate(
        mes_com_neutras, exclude_internal=False)
    sem = FinancialCalculator.calculate_savings_rate(
        mes_com_neutras, exclude_internal=True)

    assert com != pytest.approx(sem)
    assert sem == pytest.approx(-50.0)             # 3.000 / −4.500
    assert com == pytest.approx(-1500 / 5000 * 100)  # 5.000 / −6.500


def test_padrao_do_parametro_preserva_o_comportamento_antigo(mes_com_neutras):
    """
    `exclude_internal` nasce True — a chamada sem argumento continua
    significando o que significava. O que mudou foi o clamp e o fato de o
    chamador PODER casar a população.
    """
    assert FinancialCalculator.calculate_savings_rate(mes_com_neutras) == \
        pytest.approx(FinancialCalculator.calculate_savings_rate(
            mes_com_neutras, exclude_internal=True))
