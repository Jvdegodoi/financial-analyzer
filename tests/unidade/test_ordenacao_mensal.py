# -*- coding: utf-8 -*-
"""
Camada de unidade — ordenação cronológica das séries mensais.

`Transaction.month_year` devolve "MM/AAAA". Ordenar essa string como texto
compara o MÊS antes do ANO: numa base de 08/2025 a 08/2026 a série sai
01/2026...07/2026, 08/2025, 08/2026, 09/2025, 10/2025, 11/2025, 12/2025. Os
valores ficam certos e a ordem errada, e as abas de evolução mensal mostram
tendência falsa.

O defeito passou por 211 testes e uma revisão completa porque tudo foi
calibrado numa fatia de um único ano civil — dentro de um ano, ordem
alfabética e ordem cronológica coincidem. Por isso todo teste aqui
ATRAVESSA A VIRADA DE ANO de propósito: é a única forma de o caso aparecer.

As transações são construídas à mão, sem passar por CSV: o que está sob
teste é a ordenação da série, não a importação.
"""

from datetime import datetime

import pytest

from src.business.calculator import FinancialCalculator
from src.business.transfer_matcher import CoverageAnalyzer
from src.data.models import Transaction, ordem_do_mes

# A base de verdade vai de agosto/2025 a agosto/2026 — treze meses, duas
# viradas de ano dentro da janela. É esse recorte que o teste reproduz.
MESES_ESPERADOS = [
    "08/2025", "09/2025", "10/2025", "11/2025", "12/2025",
    "01/2026", "02/2026", "03/2026", "04/2026", "05/2026",
    "06/2026", "07/2026", "08/2026",
]


def _transacao(ano: int, mes: int, valor: float, categoria: str = "Alimentação",
               subcategoria=None) -> Transaction:
    """`type` é derivado do sinal do valor, não é campo — daí só o valor."""
    return Transaction(
        id="sint-%04d%02d-%s" % (ano, mes, "r" if valor > 0 else "d"),
        date=datetime(ano, mes, 15),
        value=valor,
        description="Compra sintética %02d/%d" % (mes, ano),
        category=categoria,
        subcategory=subcategoria,
        source_account="Nubank (conta) 99887766",
    )


@pytest.fixture
def treze_meses():
    """
    Uma despesa e uma receita por mês, de 08/2025 a 08/2026. O valor cresce
    com o tempo para que uma série fora de ordem seja detectável pelos
    números, não só pelos rótulos.
    """
    transacoes = []
    for i, rotulo in enumerate(MESES_ESPERADOS):
        mes, ano = int(rotulo[:2]), int(rotulo[3:])
        transacoes.append(_transacao(ano, mes, -(100.0 + i)))
        transacoes.append(_transacao(ano, mes, 1000.0 + i, categoria="Salário"))
    return transacoes


# ---------------------------------------------------------------------------
# A chave em si
# ---------------------------------------------------------------------------

def test_ordem_do_mes_ordena_por_ano_e_depois_por_mes():
    fora_de_ordem = ["01/2026", "08/2025", "12/2025", "08/2026", "09/2025"]
    assert sorted(fora_de_ordem, key=ordem_do_mes) == [
        "08/2025", "09/2025", "12/2025", "01/2026", "08/2026"]


def test_ordenar_como_texto_e_diferente_de_ordenar_cronologicamente():
    """
    Guarda o motivo do helper existir. Se um dia as duas ordens coincidirem
    para esta entrada, o teste perdeu o sentido e precisa de outra entrada.
    """
    assert sorted(MESES_ESPERADOS) != MESES_ESPERADOS
    assert sorted(MESES_ESPERADOS, key=ordem_do_mes) == MESES_ESPERADOS


# ---------------------------------------------------------------------------
# As séries que a interface desenha
# ---------------------------------------------------------------------------

def test_evolucao_mensal_atravessa_a_virada_de_ano_em_ordem(treze_meses):
    """Aba 2 — `calculate_monthly_trend`."""
    serie = FinancialCalculator.calculate_monthly_trend(treze_meses)

    assert [linha["month"] for linha in serie] == MESES_ESPERADOS
    # Despesas foram construídas crescentes: a série ordenada é monótona.
    despesas = [linha["despesas"] for linha in serie]
    assert despesas == sorted(despesas)


def test_evolucao_por_caminho_atravessa_a_virada_de_ano_em_ordem(treze_meses):
    """Aba 3 — `calculate_monthly_trend_by_path`, a que o app de fato usa."""
    serie = FinancialCalculator.calculate_monthly_trend_by_path(
        treze_meses, paths=["Alimentação"])

    assert [linha["month"] for linha in serie] == MESES_ESPERADOS
    valores = [linha["Alimentação"] for linha in serie]
    assert valores == sorted(valores)


def test_renda_por_mes_atravessa_a_virada_de_ano_em_ordem(treze_meses,
                                                          config_sintetica):
    """Aba 7 — `calculate_income_by_month`."""
    serie = FinancialCalculator.calculate_income_by_month(
        treze_meses, config_sintetica)

    assert [linha["month"] for linha in serie] == MESES_ESPERADOS
    nao_classificada = [linha["nao_classificada"] for linha in serie]
    assert nao_classificada == sorted(nao_classificada)


def test_cobertura_lista_os_meses_em_ordem(treze_meses, config_sintetica):
    """
    `CoverageAnalyzer.all_months` já ordenava certo — é de lá que a chave
    saiu. O teste existe para que a extração para o helper não a quebre.
    """
    cobertura = CoverageAnalyzer.compute(treze_meses, config_sintetica)
    assert CoverageAnalyzer.all_months(cobertura) == MESES_ESPERADOS


# ---------------------------------------------------------------------------
# O caso mínimo, para quando o de treze meses ficar difícil de ler
# ---------------------------------------------------------------------------

def test_dezembro_vem_antes_de_janeiro_do_ano_seguinte():
    transacoes = [_transacao(2026, 1, -10.0), _transacao(2025, 12, -20.0)]
    serie = FinancialCalculator.calculate_monthly_trend(transacoes)

    assert [linha["month"] for linha in serie] == ["12/2025", "01/2026"]
    assert serie[0]["despesas"] == 20.0
    assert serie[1]["despesas"] == 10.0
