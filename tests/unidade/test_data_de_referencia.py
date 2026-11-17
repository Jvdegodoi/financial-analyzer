# -*- coding: utf-8 -*-
"""
Camada de unidade — o parâmetro `hoje` das duas funções que contam a partir
do dia de hoje.

`TransactionFilter.filter_by_period(days=N)` e
`FinancialCalculator.predict_monthly_expenses` liam o relógio. Com extratos
de data fixa, a demonstração esvaziaria com o tempo: "Últimos 30 dias" e
"Despesa prevista" mostrariam zero poucas semanas depois de o conjunto ser
gerado. As duas ganharam `hoje`, e a demonstração passa a sua data de
referência.

O que se afirma:

- com `hoje`, o relógio NÃO é lido — o teste troca o relógio por um que
  levanta;
- sem `hoje`, o resultado é o de sempre: igual a passar o próprio instante do
  relógio. `tests/unidade/test_filtro_periodo.py` passa sem uma linha
  mudada, e é a outra metade desta prova.

Pela regra de datas do `CLAUDE.md`, toda janela aqui ATRAVESSA A VIRADA DE
ANO e tem lançamento exatamente no dia do corte e na véspera.

Um limite conhecido, que este arquivo não esconde: `predict_monthly_expenses`
calcula o corte com a hora que recebe, sem normalizar para o início do dia.
Às 14h35, o lançamento do dia do corte fica de fora. É o defeito que
`filter_by_period` tinha até 05/09/2026; está registrado na lista de
pendências e não foi corrigido aqui, porque mudaria um número da tela em
modo real. Os testes de corte abaixo usam `hoje` à meia-noite, que é o que a
demonstração passa; o teste do padrão afirma só que o padrão e o parâmetro
dão o mesmo número, sem dizer qual dos dois é o certo.
"""

from datetime import datetime

import pytest

from src.business import calculator as mod_calculator
from src.business.calculator import FinancialCalculator, TransactionFilter
from src.data.models import Transaction

# A demonstração passa a data à meia-noite.
HOJE = datetime(2026, 1, 20)
# O mesmo dia, no meio da tarde: a hora que o relógio de verdade carrega.
AGORA = datetime(2026, 1, 20, 14, 35, 12)

# Filtro de 60 dias: 60 dias antes de 20/01/2026 é 21/11/2025.
DIAS = 60
CORTE_DO_FILTRO = datetime(2025, 11, 21)
VESPERA_DO_FILTRO = datetime(2025, 11, 20)

# Previsão: a janela é de 90 dias. 90 dias antes de 20/01/2026 é 22/10/2025.
CORTE_DA_PREVISAO = datetime(2025, 10, 22)
VESPERA_DA_PREVISAO = datetime(2025, 10, 21)


def _transacao(quando: datetime, valor: float = -100.0,
               categoria: str = "Alimentação") -> Transaction:
    return Transaction(
        id="sint-%s-%s" % (quando.strftime("%Y%m%d"), valor),
        date=quando, value=valor,
        description="Compra sintética %s" % quando.strftime("%d/%m/%Y"),
        category=categoria, source_account="Nubank (conta) 99887766")


@pytest.fixture
def relogio_proibido(monkeypatch):
    """Um relógio que levanta se alguém o consultar."""
    class _SemRelogio(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("a função leu o relógio apesar de receber `hoje`")

    monkeypatch.setattr(mod_calculator, "datetime", _SemRelogio)


@pytest.fixture
def relogio_fixo(monkeypatch):
    class _Fixo(datetime):
        @classmethod
        def now(cls, tz=None):
            return AGORA

    monkeypatch.setattr(mod_calculator, "datetime", _Fixo)
    return AGORA


# ---------------------------------------------------------------------------
# filter_by_period
# ---------------------------------------------------------------------------

@pytest.fixture
def base_do_filtro():
    return [
        _transacao(datetime(2025, 9, 15)),      # bem fora
        _transacao(VESPERA_DO_FILTRO),          # véspera do corte: FORA
        _transacao(CORTE_DO_FILTRO),            # no dia do corte: DENTRO
        _transacao(datetime(2025, 12, 31)),     # último dia do ano velho
        _transacao(datetime(2026, 1, 1)),       # primeiro do ano novo
        _transacao(HOJE),                       # o próprio "hoje"
    ]


def test_filtro_com_hoje_nao_le_o_relogio_e_corta_no_dia_certo(
        relogio_proibido, base_do_filtro):
    dentro = TransactionFilter.filter_by_period(base_do_filtro, days=DIAS,
                                                hoje=HOJE)
    datas = sorted(t.date for t in dentro)

    assert datas == [CORTE_DO_FILTRO, datetime(2025, 12, 31),
                     datetime(2026, 1, 1), HOJE]
    assert VESPERA_DO_FILTRO not in datas


def test_filtro_com_hoje_no_meio_da_tarde_da_o_mesmo_conjunto(
        relogio_proibido, base_do_filtro):
    """O corte do filtro é normalizado para o início do dia: a hora de
    `hoje` não muda o resultado."""
    meia_noite = TransactionFilter.filter_by_period(base_do_filtro, days=DIAS,
                                                    hoje=HOJE)
    tarde = TransactionFilter.filter_by_period(base_do_filtro, days=DIAS,
                                               hoje=AGORA)

    assert [t.id for t in tarde] == [t.id for t in meia_noite]
    assert CORTE_DO_FILTRO in {t.date for t in tarde}


def test_filtro_sem_hoje_e_o_de_sempre(relogio_fixo, base_do_filtro):
    padrao = TransactionFilter.filter_by_period(base_do_filtro, days=DIAS)
    com_o_relogio = TransactionFilter.filter_by_period(
        base_do_filtro, days=DIAS, hoje=relogio_fixo)

    assert [t.id for t in padrao] == [t.id for t in com_o_relogio]
    assert len(padrao) == 4


def test_hoje_nao_muda_o_filtro_por_datas_explicitas(relogio_proibido,
                                                     base_do_filtro):
    """`hoje` só vale com `days`. O ramo de início e fim não olha para ele
    nem para o relógio."""
    sem = TransactionFilter.filter_by_period(
        base_do_filtro, start_date=CORTE_DO_FILTRO, end_date=datetime(2026, 1, 1))
    com = TransactionFilter.filter_by_period(
        base_do_filtro, start_date=CORTE_DO_FILTRO, end_date=datetime(2026, 1, 1),
        hoje=datetime(2030, 1, 1))

    assert [t.id for t in sem] == [t.id for t in com]
    assert len(sem) == 3


# ---------------------------------------------------------------------------
# predict_monthly_expenses
# ---------------------------------------------------------------------------

@pytest.fixture
def base_da_previsao():
    return [
        _transacao(datetime(2025, 9, 1), -5000.0),          # bem fora
        _transacao(VESPERA_DA_PREVISAO, -9000.0),           # véspera do corte: FORA
        _transacao(CORTE_DA_PREVISAO, -90.0),               # no dia do corte: DENTRO
        _transacao(datetime(2025, 12, 31), -180.0),         # último dia do ano velho
        _transacao(datetime(2026, 1, 1), -270.0),           # primeiro do ano novo
        _transacao(HOJE, -360.0),                           # o próprio "hoje"
        _transacao(datetime(2025, 12, 10), 4000.0),         # receita: não é despesa
        _transacao(datetime(2025, 12, 11), -700.0, "Estorno"),              # neutra
        _transacao(datetime(2025, 12, 12), -800.0, "Transferência Interna"),  # neutra
    ]


def test_previsao_com_hoje_nao_le_o_relogio_e_corta_no_dia_certo(
        relogio_proibido, base_da_previsao):
    """
    Dentro da janela: 90 + 180 + 270 + 360 = R$ 900 em 90 dias, R$ 10 por
    dia, R$ 300 por mês. A véspera, com R$ 9.000, mudaria o número para
    R$ 3.300 se entrasse; a receita e as duas neutras não entram.
    """
    previsto = FinancialCalculator.predict_monthly_expenses(base_da_previsao,
                                                            hoje=HOJE)
    assert previsto == pytest.approx(300.0)

    dois_meses = FinancialCalculator.predict_monthly_expenses(
        base_da_previsao, months_to_predict=2, hoje=HOJE)
    assert dois_meses == pytest.approx(600.0)


def test_previsao_sem_o_dia_do_corte_perde_exatamente_esse_lancamento(
        relogio_proibido, base_da_previsao):
    """O lançamento do dia do corte é o que separa as duas janelas: tirá-lo
    da base baixa a previsão em R$ 30 (90 / 90 dias × 30)."""
    sem_o_corte = [t for t in base_da_previsao if t.date != CORTE_DA_PREVISAO]

    previsto = FinancialCalculator.predict_monthly_expenses(sem_o_corte,
                                                            hoje=HOJE)
    assert previsto == pytest.approx(270.0)


def test_previsao_sem_despesa_na_janela_e_zero(relogio_proibido,
                                               base_da_previsao):
    """Com o hoje um ano e meio adiante, a janela não alcança nada — é o que
    aconteceria à demonstração sem a data de referência."""
    assert FinancialCalculator.predict_monthly_expenses(
        base_da_previsao, hoje=datetime(2027, 7, 1)) == 0.0
    assert FinancialCalculator.predict_monthly_expenses([], hoje=HOJE) == 0.0


def test_previsao_sem_hoje_e_a_de_sempre(relogio_fixo, base_da_previsao):
    """
    O padrão é o relógio: o mesmo número de passar o instante do relógio.
    Não afirma qual janela é a certa às 14h35 — ver a nota no topo.
    """
    padrao = FinancialCalculator.predict_monthly_expenses(base_da_previsao)
    com_o_relogio = FinancialCalculator.predict_monthly_expenses(
        base_da_previsao, hoje=relogio_fixo)

    assert padrao == com_o_relogio
    assert padrao > 0
