# -*- coding: utf-8 -*-
"""
Camada de unidade — fronteira de `TransactionFilter.filter_by_period`.

`filter_by_period(days=N)` calcula o corte a partir de `datetime.now()`, que
carrega a HORA do instante da chamada. Toda transação é gravada à meia-noite
(o extrato traz data, não horário). Sem normalizar, um corte às 14h cai no
dia da fronteira às 14h e descarta esse dia inteiro: medido em 05/09/2026,
"últimos 30 dias" começava no dia seguinte ao da fronteira e deixava de fora
todas as transações do dia da fronteira.

Não é comparação de data como texto — é `datetime` contra `datetime` com um
lado carregando hora e o outro não. Classe diferente da ordenação de
"MM/AAAA", mesma família: data que não foi normalizada antes de comparar.

Os cinco métodos de `TransactionFilter` nunca eram executados pela suíte
(revisão de 01/09). Este arquivo cobre o que a Fase 2 tocou.

TODA janela aqui ATRAVESSA A VIRADA DE ANO de propósito. A armadilha do
`CLAUDE.md` existe porque tudo foi calibrado numa fatia de um único ano
civil, e dentro de um ano civil quase todo defeito de data se esconde.
"""

from datetime import datetime

import pytest

from src.business import calculator as mod_calculator
from src.business.calculator import TransactionFilter
from src.data.models import Transaction


# "Agora" fica no meio da tarde de propósito: é a hora que o corte carregava
# e que fazia o dia da fronteira sumir. Meia-noite esconderia o defeito.
AGORA = datetime(2026, 1, 20, 14, 35, 12)

# 60 dias antes de 20/01/2026 é 21/11/2025 — a janela cruza a virada de ano.
DIAS = 60
FRONTEIRA = datetime(2025, 11, 21)
VESPERA = datetime(2025, 11, 20)


def _transacao(quando: datetime, valor: float = -100.0,
               descricao: str = "Compra sintética") -> Transaction:
    return Transaction(
        id="sint-" + quando.strftime("%Y%m%d%H%M%S"),
        date=quando,
        value=valor,
        description="%s %s" % (descricao, quando.strftime("%d/%m/%Y")),
        category="Alimentação",
        source_account="Nubank (conta) 99887766",
    )


@pytest.fixture
def agora_fixo(monkeypatch):
    """
    Congela o `datetime.now()` que o `calculator` enxerga.

    O módulo faz `from datetime import datetime`, então o nome a trocar é
    `src.business.calculator.datetime` — trocar `datetime.datetime` global
    não alcançaria a referência já importada.
    """
    class _DatetimeFixo(datetime):
        @classmethod
        def now(cls, tz=None):
            return AGORA

    monkeypatch.setattr(mod_calculator, "datetime", _DatetimeFixo)
    return AGORA


@pytest.fixture
def base_atravessando_o_ano():
    """
    Uma transação por dia relevante em torno da fronteira, mais âncoras
    dentro e fora da janela. A virada de ano fica no meio.
    """
    return [
        _transacao(datetime(2025, 9, 15)),      # bem fora
        _transacao(VESPERA),                    # véspera da fronteira: FORA
        _transacao(FRONTEIRA),                  # exatamente na fronteira: DENTRO
        _transacao(datetime(2025, 11, 22)),     # dia seguinte: dentro
        _transacao(datetime(2025, 12, 31)),     # último dia do ano velho
        _transacao(datetime(2026, 1, 1)),       # primeiro do ano novo
        _transacao(datetime(2026, 1, 20)),      # o próprio "hoje"
    ]


def test_dia_da_fronteira_entra(agora_fixo, base_atravessando_o_ano):
    """
    O caso medido em 05/09/2026, transposto para uma janela que cruza o ano.

    Transação gravada às 00:00 do dia da fronteira contra um corte às 14:35
    do mesmo dia: sem normalizar, `t.date >= cutoff` é falso e o dia inteiro
    desaparece.
    """
    dentro = TransactionFilter.filter_by_period(
        base_atravessando_o_ano, days=DIAS)
    datas = {t.date for t in dentro}

    assert FRONTEIRA in datas, (
        "a transação do dia da fronteira (%s) ficou de fora — o corte não "
        "foi normalizado para o início do dia" % FRONTEIRA.date()
    )
    assert min(datas) == FRONTEIRA


def test_vespera_da_fronteira_fica_fora(agora_fixo, base_atravessando_o_ano):
    """
    A correção normaliza para baixo; não pode alargar a janela em um dia
    inteiro. O dia anterior à fronteira continua fora.
    """
    dentro = TransactionFilter.filter_by_period(
        base_atravessando_o_ano, days=DIAS)
    datas = {t.date for t in dentro}

    assert VESPERA not in datas
    assert datetime(2025, 9, 15) not in datas


def test_janela_atravessa_a_virada_de_ano(agora_fixo, base_atravessando_o_ano):
    """
    A janela de 60 dias contém dezembro de 2025 E janeiro de 2026. Um filtro
    que comparasse a data pela forma renderizada ("DD/MM/AAAA" ou "MM/AAAA")
    quebraria exatamente aqui, e passaria numa fatia de um ano só.
    """
    dentro = TransactionFilter.filter_by_period(
        base_atravessando_o_ano, days=DIAS)
    datas = sorted(t.date for t in dentro)

    assert datetime(2025, 12, 31) in datas
    assert datetime(2026, 1, 1) in datas
    assert datas == sorted(datas)
    assert datas[0] == FRONTEIRA
    assert datas[-1] == datetime(2026, 1, 20)
    assert len(datas) == 5


def test_corte_independe_da_hora_da_chamada(monkeypatch,
                                            base_atravessando_o_ano):
    """
    Duas chamadas no MESMO dia de calendário, em horas diferentes, precisam
    devolver o mesmo conjunto. Era isso que falhava: o resultado dependia de
    a que horas o usuário abriu o app.
    """
    resultados = []
    for hora in (0, 9, 14, 23):
        class _DatetimeFixo(datetime):
            _h = hora

            @classmethod
            def now(cls, tz=None):
                return AGORA.replace(hour=cls._h, minute=59, second=59)

        monkeypatch.setattr(mod_calculator, "datetime", _DatetimeFixo)
        dentro = TransactionFilter.filter_by_period(
            base_atravessando_o_ano, days=DIAS)
        resultados.append(sorted(t.id for t in dentro))

    assert all(r == resultados[0] for r in resultados), (
        "o conjunto filtrado mudou conforme a hora da chamada"
    )
    assert len(resultados[0]) == 5


def test_janela_por_datas_explicitas_atravessa_o_ano(base_atravessando_o_ano):
    """
    O ramo `start_date`/`end_date` não passa por `datetime.now()` e por isso
    não tinha o defeito — mas nunca havia sido executado pela suíte. Cobre a
    fronteira nos dois extremos, com a virada de ano dentro.
    """
    dentro = TransactionFilter.filter_by_period(
        base_atravessando_o_ano,
        start_date=FRONTEIRA,
        end_date=datetime(2026, 1, 1),
    )
    datas = sorted(t.date for t in dentro)

    assert datas[0] == FRONTEIRA          # início inclusivo
    assert datas[-1] == datetime(2026, 1, 1)   # fim inclusivo
    assert VESPERA not in datas
    assert datetime(2026, 1, 20) not in datas
    assert len(datas) == 4
