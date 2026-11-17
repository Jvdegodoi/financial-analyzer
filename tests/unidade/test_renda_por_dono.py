# -*- coding: utf-8 -*-
"""
Camada de unidade — agregação de renda por dono da fonte (3b da sessão 5).

`IncomeSource.owner` existia, era editável e nenhuma análise o consultava —
o mesmo padrão de `FamilyAccount.owner` (achado 2.2). A pergunta que ele
responde é "quanto cada um dos dois faz por mês".

Ela ganhou peso porque para linha de RECEITA a CATEGORIA não responde nada:
receita não tem comerciante, nenhuma regra de conteúdo pontua e a linha cai
em "Transferências" pelo fallback de mecanismo (decisão nº 5). A fonte é o
único eixo que responde.

A atribuição transação→fonte continua manual (decisão nº 2) — aqui ela é
dada de entrada, nunca inferida.

A série mensal ATRAVESSA A VIRADA DE ANO de propósito.
"""

from datetime import datetime

import pytest

from src.business.calculator import FinancialCalculator
from src.data.models import (AppConfig, IncomeSource, Transaction,
                             TransactionType)

SEM_FONTE = FinancialCalculator.SEM_FONTE
SEM_DONO = FinancialCalculator.FONTE_SEM_DONO


def _receita(ano, mes, valor, fonte=None, dia=10) -> Transaction:
    t = Transaction(
        id="rec-%04d%02d%02d-%s" % (ano, mes, dia, fonte or "sem"),
        date=datetime(ano, mes, dia),
        value=valor,
        description="Pix recebido %02d/%04d" % (mes, ano),
        # De propósito: é onde toda receita real está, e o teste não pode
        # depender da categoria para achar o dono.
        category="Transferências",
        source_account="Nubank (conta) 99887766",
    )
    t.income_source = fonte
    return t


def _despesa(ano, mes, valor=-500.0, dia=12) -> Transaction:
    return Transaction(
        id="des-%04d%02d%02d" % (ano, mes, dia),
        date=datetime(ano, mes, dia),
        value=valor,
        description="Compra %02d/%04d" % (mes, ano),
        category="Alimentação",
        source_account="Nubank (conta) 99887766",
    )


@pytest.fixture
def config_fontes() -> AppConfig:
    """Duas pessoas, três fontes, mais uma fonte cadastrada SEM dono."""
    return AppConfig(income_sources=[
        IncomeSource(name="Salário Ana", type="fixa", owner="Ana Quintela"),
        IncomeSource(name="Freela Ana", type="variavel",
                     owner="Ana Quintela"),
        IncomeSource(name="Pró-labore Bruno", type="fixa",
                     owner="Bruno Quintela"),
        IncomeSource(name="Aluguel", type="fixa", owner=""),
    ])


def test_agrega_por_dono_e_nao_por_fonte(config_fontes):
    """Duas fontes do mesmo dono somam numa linha só."""
    trans = [
        _receita(2026, 3, 4000.0, "Salário Ana"),
        _receita(2026, 3, 1500.0, "Freela Ana"),
        _receita(2026, 3, 3000.0, "Pró-labore Bruno"),
    ]
    linhas = {l['owner']: l for l in
              FinancialCalculator.calculate_income_by_owner(
                  trans, config_fontes)}

    assert linhas["Ana Quintela"]['total'] == pytest.approx(5500.0)
    assert linhas["Ana Quintela"]['num_transacoes'] == 2
    assert linhas["Bruno Quintela"]['total'] == pytest.approx(3000.0)
    assert linhas["Ana Quintela"]['pct'] == pytest.approx(5500 / 8500 * 100)


def test_ordena_por_total_decrescente(config_fontes):
    trans = [
        _receita(2026, 3, 1000.0, "Salário Ana"),
        _receita(2026, 3, 9000.0, "Pró-labore Bruno"),
    ]
    linhas = FinancialCalculator.calculate_income_by_owner(
        trans, config_fontes)
    assert [l['owner'] for l in linhas] == ["Bruno Quintela", "Ana Quintela"]


def test_separa_sem_fonte_de_fonte_sem_dono(config_fontes):
    """
    As duas ausências são distintas, e a distinção diz qual ação resolve:
    "sem fonte atribuída" é classificação que falta fazer na tabela;
    "fonte sem dono" é cadastro incompleto na sidebar.
    """
    trans = [
        _receita(2026, 3, 4000.0, "Salário Ana"),
        _receita(2026, 3, 700.0, None),        # nunca classificada
        _receita(2026, 3, 250.0, "Aluguel"),   # fonte existe, dono vazio
    ]
    linhas = {l['owner']: l['total'] for l in
              FinancialCalculator.calculate_income_by_owner(
                  trans, config_fontes)}

    assert linhas[SEM_FONTE] == pytest.approx(700.0)
    assert linhas[SEM_DONO] == pytest.approx(250.0)
    assert SEM_FONTE != SEM_DONO


def test_fonte_que_sumiu_do_cadastro_vira_sem_dono(config_fontes):
    """Atribuição preservada + fonte apagada: é ausência de DONO."""
    trans = [_receita(2026, 3, 900.0, "Fonte Extinta")]
    linhas = {l['owner']: l['total'] for l in
              FinancialCalculator.calculate_income_by_owner(
                  trans, config_fontes)}
    assert linhas == {SEM_DONO: pytest.approx(900.0)}


def test_despesas_e_neutras_ficam_de_fora(config_fontes):
    trans = [
        _receita(2026, 3, 4000.0, "Salário Ana"),
        _despesa(2026, 3, -900.0),
    ]
    neutra = _receita(2026, 3, 5000.0, "Salário Ana")
    neutra.category = "Transferência Interna"
    trans.append(neutra)

    linhas = FinancialCalculator.calculate_income_by_owner(
        trans, config_fontes)
    assert len(linhas) == 1
    assert linhas[0]['total'] == pytest.approx(4000.0)
    assert linhas[0]['pct'] == pytest.approx(100.0)


def test_serie_mensal_atravessa_a_virada_de_ano(config_fontes):
    """
    Novembro/2025 a fevereiro/2026. Ordenar "MM/AAAA" como texto poria
    01/2026 e 02/2026 ANTES de 11/2025 — e passaria despercebido numa
    fatia de um ano só.
    """
    trans = [
        _receita(2025, 11, 4000.0, "Salário Ana"),
        _receita(2025, 11, 3000.0, "Pró-labore Bruno"),
        _receita(2025, 12, 4000.0, "Salário Ana"),
        _receita(2026, 1, 4200.0, "Salário Ana"),
        _receita(2026, 1, 3100.0, "Pró-labore Bruno"),
        _receita(2026, 2, 3100.0, "Pró-labore Bruno"),
    ]
    serie = FinancialCalculator.calculate_income_by_owner_by_month(
        trans, config_fontes)

    assert [l['month'] for l in serie] == [
        "11/2025", "12/2025", "01/2026", "02/2026"]

    por_mes = {l['month']: l for l in serie}
    assert por_mes["11/2025"]["Ana Quintela"] == pytest.approx(4000.0)
    assert por_mes["11/2025"]["Bruno Quintela"] == pytest.approx(3000.0)
    # Mês em que só um dos dois recebeu: o outro vem 0.0, não ausente —
    # senão a série do gráfico ganha buraco.
    assert por_mes["12/2025"]["Bruno Quintela"] == pytest.approx(0.0)
    assert por_mes["02/2026"]["Ana Quintela"] == pytest.approx(0.0)


def test_serie_mensal_tem_a_mesma_coluna_em_todos_os_meses(config_fontes):
    trans = [
        _receita(2025, 12, 4000.0, "Salário Ana"),
        _receita(2026, 1, 3000.0, "Pró-labore Bruno"),
        _receita(2026, 2, 500.0, None),
    ]
    serie = FinancialCalculator.calculate_income_by_owner_by_month(
        trans, config_fontes)
    colunas = [sorted(l.keys()) for l in serie]
    assert all(c == colunas[0] for c in colunas)
    assert set(colunas[0]) == {
        'month', "Ana Quintela", "Bruno Quintela", SEM_FONTE}


def test_periodo_vazio_nao_quebra(config_fontes):
    assert FinancialCalculator.calculate_income_by_owner(
        [], config_fontes) == []
    assert FinancialCalculator.calculate_income_by_owner_by_month(
        [], config_fontes) == []
