# -*- coding: utf-8 -*-
"""
O app aberto em demonstração, tela por tela.

Roda o `app.py` pelo `AppTest`, com `FA_DEMO=1`, e afirma que cada parte da
tela mostra o conjunto: os cards do resumo, as sete abas, a barra lateral,
a tabela paginada e a faixa. Os números esperados não estão escritos aqui:
saem do `conjunto.json` e das funções de cálculo sobre a mesma base, e o
teste confere que a TELA os mostra.

É também onde se prova a data de referência: na demonstração, "Últimos 30
dias" e "Despesa prevista" contam de 01/11/2026 e mostram valor; contados do
relógio, esvaziariam com o tempo.
"""

import json
from datetime import timedelta

import pytest

from src.business.calculator import FinancialCalculator, TransactionFilter
from src.data.models import TransactionType

from tests.conftest import RAIZ

ABAS = ["🌞 Categorias (2 níveis)", "📈 Evolução Mensal",
        "📉 Evolução por Categoria", "💰 Maiores Despesas", "📊 Estatísticas",
        "👨‍👩‍👦 Pool Familiar", "💵 Renda"]


def _reais(valor: float) -> str:
    return f"R$ {valor:,.2f}"


def _abrir(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    for chave in ("FA_DADOS", "DATA_DIR"):
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.setenv("FA_DEMO", "1")
    st.cache_resource.clear()
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    return at


@pytest.fixture
def app(monkeypatch):
    """O app em demonstração, aberto de novo a cada teste: a montagem roda
    numa pasta temporária nova, e um teste não herda o filtro do outro."""
    import streamlit as st
    yield _abrir(monkeypatch)
    st.cache_resource.clear()


def _cards(at):
    return {m.label: m for m in at.metric}


def _numeros(eixo):
    """Os números de um eixo do gráfico. O Plotly grava vetor numérico como
    binário em base64 (`{"dtype": ..., "bdata": ...}`), e lista de texto como
    lista."""
    if isinstance(eixo, dict) and "bdata" in eixo:
        import base64

        import numpy as np
        return [float(v) for v in np.frombuffer(
            base64.b64decode(eixo["bdata"]), dtype=np.dtype(eixo["dtype"]))]
    return list(eixo)


def _aba(at, rotulo):
    aba, = [a for a in at.tabs if a.label == rotulo]
    return aba


def _escolher_periodo(at, periodo):
    seletor, = [s for s in at.selectbox if s.label == "Período"]
    seletor.set_value(periodo).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------------------
# A faixa e a base
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_a_faixa_diz_o_periodo_e_a_data_de_referencia_do_conjunto(app, conjunto):
    faixa, = [m.value for m in app.markdown if "fa-faixa-demo" in m.value]
    texto = faixa.split('<div class="fa-faixa-demo">')[1]

    assert "MODO DEMONSTRAÇÃO" in texto
    assert conjunto.periodo_str in texto
    assert conjunto.referencia_str in texto
    aviso, = [w.value for w in app.sidebar.warning]
    assert "Demonstração." in aviso and "inventados" in aviso


@pytest.mark.invariante
def test_a_base_aberta_e_a_montagem_do_conjunto(app, montada):
    def impressao(base):
        return sorted((t.raw_data["filename"], t.raw_data["row_number"],
                       t.value, t.category, t.subcategory or "",
                       t.income_source or "", bool(t.paired_transfer_id))
                      for t in base)

    assert impressao(app.session_state["transactions"]) == impressao(montada.base)
    assert [s.name for s in app.session_state["config"].income_sources] == [
        s.name for s in montada.config.income_sources]


# ---------------------------------------------------------------------------
# Os cards do resumo
# ---------------------------------------------------------------------------

@pytest.mark.amarrado_a_arquivo
def test_os_cards_do_resumo_mostram_os_totais_do_conjunto(app, conjunto):
    esperado = conjunto.esperado
    receitas = esperado["total_receitas_centavos"] / 100
    despesas = esperado["total_despesas_centavos"] / 100
    cards = _cards(app)

    assert cards["💰 Receitas"].value == _reais(receitas) == "R$ 139,883.91"
    assert cards["💸 Despesas"].value == _reais(despesas) == "R$ 124,225.60"
    assert cards["💵 Saldo"].value == _reais(receitas - despesas)
    assert cards["💵 Saldo"].delta == "Positivo"
    assert cards["📊 Taxa de Poupança"].value == "11.2%"
    legendas = [c.value for c in app.main.caption]
    assert f"Período: {conjunto.periodo_str}" in legendas


# ---------------------------------------------------------------------------
# As sete abas
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_as_sete_abas_estao_na_tela(app):
    assert [a.label for a in app.tabs] == ABAS


@pytest.mark.amarrado_a_arquivo
def test_aba_categorias_tem_o_grafico_e_os_percentuais(app):
    aba = _aba(app, ABAS[0])
    barras = [p.proto.text for p in aba.get("progress")]

    assert len(aba.get("plotly_chart")) == 1
    assert len(barras) == 14, "a lista mostra os 14 maiores caminhos"
    assert barras[0].startswith("Moradia > Aluguel e Condomínio: R$ 35,280.00")
    assert any(b.startswith("Alimentação > Supermercado") for b in barras)


@pytest.mark.invariante
def test_aba_evolucao_mensal_atravessa_a_virada_de_ano(app, conjunto):
    grafico, = _aba(app, ABAS[1]).get("plotly_chart")
    figura = json.loads(grafico.proto.spec)
    series = {s["name"]: s for s in figura["data"]}

    meses = series["Saldo"]["x"]
    assert meses == list(conjunto.esperado["saldo_por_mes_centavos"])
    assert meses.index("12/2025") + 1 == meses.index("01/2026")
    assert meses[0] == "09/2025" and meses[-1] == "10/2026"
    saldos = {m: round(v * 100)
              for m, v in zip(meses, _numeros(series["Saldo"]["y"]))}
    assert saldos == conjunto.esperado["saldo_por_mes_centavos"]
    assert set(series) == {"Receitas", "Despesas", "Saldo"}


@pytest.mark.amarrado_a_arquivo
def test_aba_evolucao_por_categoria_abre_com_quatro_series(app):
    aba = _aba(app, ABAS[2])
    escolha, = aba.multiselect

    assert escolha.value == ["Moradia > Aluguel e Condomínio",
                             "Alimentação > Supermercado", "Transferências",
                             "Saúde"]
    grafico, = aba.get("plotly_chart")
    figura = json.loads(grafico.proto.spec)
    assert [s["name"] for s in figura["data"]] == escolha.value
    assert all(len(s["x"]) == 14 for s in figura["data"])
    assert len(aba.metric) == 4


@pytest.mark.amarrado_a_arquivo
def test_aba_maiores_despesas_lista_dez(app):
    aba = _aba(app, ABAS[3])
    descricoes = [t.value for t in aba.text]
    valores = [m.value for m in aba.markdown if m.value.startswith("**R$")]

    assert len(descricoes) == 10
    assert descricoes[0] == "Compra no débito - OFICINA TRES IRMAOS"
    assert valores[0] == "**R$ 2,900.00**"
    assert len(valores) == 10


@pytest.mark.amarrado_a_arquivo
def test_aba_estatisticas_tem_medias_e_a_despesa_prevista(app, montada):
    aba = _aba(app, ABAS[4])
    cards = {m.label: m.value for m in aba.metric}
    ativas = [t for t in montada.base if not t.is_neutral]
    prevista = FinancialCalculator.predict_monthly_expenses(
        ativas, hoje=montada.conjunto.data_de_referencia)

    assert cards["Maior Receita"] == "R$ 5,200.00"
    assert cards["Maior Despesa"] == "R$ 2,900.00"
    assert cards["Despesa Prevista (próx. mês)"] == _reais(prevista) == (
        "R$ 9,414.29")
    assert prevista > 0
    dias = [t.value for t in aba.text]
    assert len(dias) == 7 and all("R$ 0.00" not in d for d in dias)


@pytest.mark.amarrado_a_arquivo
def test_aba_pool_familiar_mostra_pares_pendencias_e_o_buraco(app, conjunto):
    aba = _aba(app, ABAS[5])
    esperado = conjunto.esperado
    pernas, = aba.metric
    pendencias, cobertura = [d.value for d in aba.dataframe]

    assert pernas.value == str(esperado["pares_conciliados"] * 2) == "86"
    assert pernas.delta == "43 pares"
    assert "⏳ Pendências (23)" in [s.value for s in aba.subheader]
    assert len(pendencias) == esperado["pendencias"] == 23
    # A pendência legítima da empresa de um membro (decisão fechada nº 4).
    da_empresa = pendencias[pendencias["Descrição"].str.contains(
        "Bruno Quintela Tecnologia Ltda")]
    assert len(da_empresa) == esperado["pendencias_da_empresa"] == 17

    assert list(cobertura.columns) == ["Conta"] + list(
        esperado["saldo_por_mes_centavos"])
    linhas = cobertura.set_index("Conta")
    assert linhas.loc["Nubank (conta) 55667788", "03/2026"] == "—", (
        "o buraco de cobertura sumiu")
    assert linhas.loc["Nubank (conta) 55667788", "02/2026"].startswith("✓")
    for sem_extrato in ("C6 Bank (conta) 44332211", "Inter (conta) 11223344"):
        assert set(linhas.loc[sem_extrato]) == {"—"}
    for conta, meses in esperado["transacoes_por_conta_e_mes"].items():
        for mes, quantas in meses.items():
            assert linhas.loc[conta, mes] == f"✓ {quantas}"


@pytest.mark.amarrado_a_arquivo
def test_aba_renda_mostra_fontes_pessoas_e_o_que_falta_classificar(app, conjunto):
    aba = _aba(app, ABAS[6])
    esperado = conjunto.esperado
    cards = {m.label: m for m in aba.metric}

    assert cards["Renda Fixa"].value == _reais(
        esperado["renda_fixa_centavos"] / 100) == "R$ 112,000.00"
    assert cards["Renda Variável"].value == _reais(
        esperado["renda_variavel_centavos"] / 100)
    assert cards["Não Classificada"].value == "R$ 2,888.39"
    assert cards["Renda Necessária (gastos)"].value == _reais(
        esperado["total_despesas_centavos"] / 100)

    # Renda por pessoa, com as duas ausências separadas (decisão nº 10).
    assert cards["Ana Quintela"].value == "R$ 77,160.00"
    assert cards["Bruno Quintela"].value == "R$ 59,320.00"
    assert cards["Sem fonte atribuída"].delta.endswith("8 transações")
    assert cards["Fonte sem dono"].delta.endswith("13 transações")

    classificar, = [d.value for d in aba.dataframe]
    assert len(classificar) == conjunto.receitas_sem_fonte == 8
    assert set(classificar["Fonte"]) == {"— não classificada"}
    assert len(aba.get("plotly_chart")) == 2


# ---------------------------------------------------------------------------
# A tabela e a barra lateral
# ---------------------------------------------------------------------------

@pytest.mark.amarrado_a_arquivo
def test_a_tabela_tem_mais_de_uma_pagina(app):
    pagina, = [n for n in app.number_input if n.label == "Página"]
    legendas = [c.value for c in app.main.caption]

    assert (pagina.min, pagina.max) == (1, 14)
    assert "Mostrando 1-50 de 686 transações" in legendas
    tabela = [d.value for d in app.main.dataframe
              if list(d.value.columns)[:2] == ["Data", "Descrição"]
              and "Categoria" in d.value.columns][-1]
    assert len(tabela) == 50

    pagina.set_value(14).run()
    assert not app.exception, [e.value for e in app.exception]
    assert "Mostrando 651-686 de 686 transações" in [
        c.value for c in app.main.caption]


@pytest.mark.amarrado_a_arquivo
def test_a_barra_lateral_mostra_a_base_o_pool_e_as_fontes(app, conjunto):
    lateral = app.sidebar
    cards = {m.label: m.value for m in lateral.metric}
    textos = [t.value for t in lateral.text]
    legendas = [c.value for c in lateral.caption]

    assert cards["Total de Transações"] == str(conjunto.esperado["transacoes"])
    assert cards["Backups Disponíveis"] == "0"
    assert "Mais antiga: 01/09/2025" in textos
    assert "Mais recente: 31/10/2026" in textos
    assert "Pasta dos dados: temporária, apagada quando o app fecha." in legendas
    assert "Contas do Pool (6)" in [s.value for s in lateral.subheader]
    for conta in conjunto.esperado["transacoes_por_conta_e_mes"]:
        assert conta in textos
    for fonte in ("Salário", "Pró-labore", "Serviços avulsos",
                  "Aulas particulares", "Rendimentos"):
        assert fonte in textos
    # As seis contas estão cadastradas: nenhuma "detectada, não registrada".
    assert not [m.value for m in lateral.markdown if "Contas detectadas" in m.value]


# ---------------------------------------------------------------------------
# A data de referência
# ---------------------------------------------------------------------------

@pytest.mark.amarrado_a_arquivo
def test_ultimos_30_dias_contam_da_data_de_referencia(app, montada):
    referencia = montada.conjunto.data_de_referencia
    ativas = [t for t in montada.base if not t.is_neutral]
    janela = TransactionFilter.filter_by_period(ativas, days=30, hoje=referencia)
    despesas = sum(t.absolute_value for t in janela
                   if t.type == TransactionType.DESPESA)
    receitas = sum(t.value for t in janela if t.type == TransactionType.RECEITA)
    corte = referencia - timedelta(days=30)

    _escolher_periodo(app, "Últimos 30 dias")
    cards = _cards(app)

    assert min(t.date for t in janela) >= corte
    assert len(janela) == 49
    assert cards["💸 Despesas"].value == _reais(despesas) == "R$ 11,933.38"
    assert cards["💰 Receitas"].value == _reais(receitas) == "R$ 8,538.39"
    # Outubro de 2026 é um dos meses de saldo negativo: a taxa de poupança
    # aparece NEGATIVA, e o sinal é a informação (decisão fechada nº 9).
    assert cards["💵 Saldo"].delta == "Negativo"
    assert cards["📊 Taxa de Poupança"].value == "-39.8%"
    legendas = [c.value for c in app.main.caption]
    assert "Período: 02/10/2026 a 31/10/2026" in legendas
    assert "Mostrando 1-49 de 49 transações" in legendas


@pytest.mark.amarrado_a_arquivo
def test_o_dia_do_corte_entra_e_a_vespera_fica_fora(montada):
    """
    A fronteira dos "Últimos 30 dias" da demonstração, sobre o conjunto:
    30 dias antes de 01/11/2026 é 02/10/2026. O conjunto tem lançamento
    nesse dia e na véspera; o primeiro entra, o segundo não.
    """
    referencia = montada.conjunto.data_de_referencia
    corte = referencia - timedelta(days=30)
    vespera = corte - timedelta(days=1)
    datas_da_base = {t.date for t in montada.base}
    assert corte in datas_da_base and vespera in datas_da_base, (
        "o conjunto não tem lançamento no dia do corte e na véspera")

    janela = TransactionFilter.filter_by_period(montada.base, days=30,
                                                hoje=referencia)
    datas = {t.date for t in janela}

    assert corte in datas
    assert vespera not in datas
    assert min(datas) == corte


@pytest.mark.invariante
def test_contados_do_relogio_os_filtros_relativos_esvaziariam(montada):
    """Por que a data de referência existe: com um hoje dois meses depois do
    fim do conjunto, "Últimos 30 dias" e a previsão de 90 dias... """
    depois = montada.conjunto.data_de_referencia + timedelta(days=120)

    assert TransactionFilter.filter_by_period(montada.base, days=30,
                                              hoje=depois) == []
    assert FinancialCalculator.predict_monthly_expenses(montada.base,
                                                        hoje=depois) == 0.0


@pytest.mark.amarrado_a_arquivo
def test_ultimos_7_dias_tambem_tem_conteudo(app):
    _escolher_periodo(app, "Últimos 7 dias")

    legendas = [c.value for c in app.main.caption]
    assert "Período: 25/10/2026 a 31/10/2026" in legendas
    assert "Mostrando 1-11 de 11 transações" in legendas
