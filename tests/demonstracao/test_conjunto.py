# -*- coding: utf-8 -*-
"""
O pipeline inteiro sobre o conjunto de demonstração.

Duas espécies de asserção, marcadas uma a uma:

- as **invariantes** valem para qualquer conjunto que o gerador venha a
  produzir: saldo que encadeia, perna pareada com contraparte de verdade,
  terceiro que não vira membro, série em ordem cronológica;
- as **amarradas a arquivo** são os números DESTE conjunto. O esperado vem de
  `demonstracao/conjunto.json`, calculado pelo gerador sem usar o produto;
  aqui o produto tem de chegar ao mesmo número pelo caminho dele.

A tabela do perfil ratificado pelo dono (plano da sessão 1b, com a emenda da
liberação de 13/11/2026 na linha das pernas sem contraparte) está espelhada
nos testes amarrados, linha a linha.
"""

from collections import Counter
from datetime import date, timedelta

import pytest

from demonstracao import gerar as gerador
from src.business.calculator import FinancialCalculator
from src.business.transfer_matcher import CoverageAnalyzer
from src.data.models import (AppConfig, CategoryManager, TransactionType,
                             ordem_do_mes)
from src.data.parser import CSVParser
from src.data.validator import DataValidator
from src.importacao import preparar_importacao

from tests.saldo import (cadeia_do_c6, cadeia_do_inter, dias_do_c6, relatar,
                         saldo_declarado_do_inter, saldos_do_inter)

EMPRESA = DataValidator.normalize_description(gerador.EMPRESA_DO_MEMBRO)


def _centavos(reais: float) -> int:
    return round(reais * 100)


def _ativas(base):
    return [t for t in base if not t.is_neutral]


def _extratos(conjunto, prefixo):
    return sorted(p for p in conjunto.pasta_dos_extratos.glob("*.csv")
                  if p.name.startswith(prefixo))


def _ler(caminho):
    with open(caminho, "rb") as f:
        return CSVParser().parse_file(f, caminho.name)


# ===========================================================================
# Invariantes
# ===========================================================================

@pytest.mark.invariante
def test_o_parser_le_toda_linha_de_todo_extrato(conjunto):
    declarado = {a["nome"]: a for a in conjunto.arquivos}
    for caminho in sorted(conjunto.pasta_dos_extratos.glob("*.csv")):
        resultado = _ler(caminho)
        assert not resultado.errors and not resultado.warnings, caminho.name
        assert len(resultado.transactions) == declarado[caminho.name]["linhas"]
        assert resultado.source_account == declarado[caminho.name]["conta"]


@pytest.mark.invariante
def test_cadeia_de_saldo_do_inter_fecha_linha_a_linha(conjunto):
    """O saldo que o gerador escreve é juiz do valor que o parser lê."""
    extratos = _extratos(conjunto, "INTER_")
    assert extratos
    for caminho in extratos:
        transacoes = _ler(caminho).transactions
        saldos = saldos_do_inter(caminho)
        quebras = cadeia_do_inter(transacoes, saldos)
        assert not quebras, caminho.name + "\n" + relatar(quebras)
        # O arquivo vem do mais novo para o mais velho: o saldo declarado no
        # preâmbulo é o da primeira linha.
        assert saldo_declarado_do_inter(caminho) == saldos[1], caminho.name
        datas = [t.date for t in sorted(transacoes,
                                        key=lambda t: t.raw_data["row_number"])]
        assert datas == sorted(datas, reverse=True), caminho.name


@pytest.mark.invariante
def test_cadeia_de_saldo_do_c6_fecha_por_dia_contabil(conjunto):
    extratos = _extratos(conjunto, "C6_")
    assert extratos
    lancadas_em_outro_dia = 0
    for caminho in extratos:
        transacoes = _ler(caminho).transactions
        dias = dias_do_c6(caminho)
        quebras = cadeia_do_c6(transacoes, dias)
        assert not quebras, caminho.name + "\n" + relatar(quebras)
        lancadas_em_outro_dia += sum(
            1 for t in transacoes
            if t.date.strftime("%d/%m/%Y")
            != dias[t.raw_data["row_number"]]["contabil"])
    assert lancadas_em_outro_dia >= 1, (
        "o conjunto perdeu o caso que separa Data Lançamento de Data Contábil")


@pytest.mark.invariante
def test_todo_lancamento_cai_no_periodo_declarado(montada):
    datas = [t.date.date() for t in montada.base]
    assert min(datas) == montada.conjunto.inicio
    assert max(datas) == montada.conjunto.fim
    assert (montada.conjunto.data_de_referencia.date()
            == montada.conjunto.fim + timedelta(days=1))
    referencia = montada.conjunto.data_de_referencia
    assert (referencia.hour, referencia.minute, referencia.second) == (0, 0, 0)


@pytest.mark.invariante
def test_toda_perna_pareada_tem_a_contraparte_de_verdade(montada):
    por_id = {t.id: t for t in montada.base}
    pareadas = [t for t in montada.base if t.paired_transfer_id]
    assert pareadas
    for perna in pareadas:
        outra = por_id[perna.paired_transfer_id]
        assert outra.paired_transfer_id == perna.id
        assert outra.source_account != perna.source_account
        assert outra.date.date() == perna.date.date()
        assert round(outra.value + perna.value, 2) == 0.0
        assert perna.category == outra.category == "Transferência Interna"
        assert montada.matcher.member_mentioned(perna.description)
    internas = [t for t in montada.base if t.category == "Transferência Interna"]
    assert len(internas) == len(pareadas), (
        "há 'Transferência Interna' sem par: neutralizada pelo nome")


@pytest.mark.invariante
def test_perna_sem_contraparte_fica_pendente_e_conta_nas_metricas(montada):
    """Decisão fechada nº 1: não se neutraliza por coincidência de nome."""
    pendentes = montada.matcher.get_pending_transfers(montada.base)
    assert pendentes
    for t in pendentes:
        assert not t.is_neutral
        assert not t.paired_transfer_id
        assert t.category == "Transferências"
    ativas = {t.id for t in _ativas(montada.base)}
    assert all(t.id in ativas for t in pendentes)


@pytest.mark.invariante
def test_a_empresa_do_membro_e_pendencia_legitima_e_aceita_fonte(montada):
    """
    Decisão fechada nº 4: a empresa transaciona com as contas pessoais e
    aparece como pendência — não é auto-resolvida nem filtrada. A mesma
    linha é renda: aceita fonte e continua pendente depois de atribuída.
    """
    da_empresa = [t for t in montada.base
                  if EMPRESA in DataValidator.normalize_description(t.description)]
    pendentes = {t.id for t in montada.matcher.get_pending_transfers(montada.base)}
    assert da_empresa
    assert all(t.id in pendentes for t in da_empresa)
    recebidas = [t for t in da_empresa if t.type == TransactionType.RECEITA]
    assert recebidas and all(t.income_source == gerador.PRO_LABORE
                             for t in recebidas)
    enviadas = [t for t in da_empresa if t.type == TransactionType.DESPESA]
    assert len(enviadas) >= 2, "faltam os aportes da conta pessoal na empresa"


@pytest.mark.invariante
def test_terceiro_parecido_nao_e_reconhecido_como_membro(montada):
    presentes = set()
    for t in montada.base:
        for nome in gerador.TERCEIROS_PARECIDOS:
            if nome.lower() in t.description.lower():
                presentes.add(nome)
                assert montada.matcher.member_mentioned(t.description) is None, (
                    f"{nome} reconhecido como membro em {t.description!r}")
                assert not montada.categorizador._is_member_transfer(
                    t.description)
                assert not t.paired_transfer_id
                assert t.category != "Transferência Interna"
    # Perfil: ao menos 2 pessoas cujo nome ou sobrenome se sobrepõe ao de um
    # membro.
    sobrepostos = [n for n in presentes
                   if {"ana", "bruno", "quintela", "moreira"}
                   & set(n.lower().split())]
    assert len(sobrepostos) >= 2, "o conjunto perdeu os terceiros parecidos"


@pytest.mark.invariante
def test_todo_estorno_esta_pareado(montada):
    """Nenhum estorno avulso: a decisão sobre ele (DP2) está aberta, e o
    conjunto não pode escolher por ela."""
    em_estorno = [t for t in montada.base if t.category == "Estorno"]
    assert em_estorno
    por_identificador = Counter(t.external_id for t in em_estorno)
    assert all(n == 2 for n in por_identificador.values())
    for identificador in por_identificador:
        grupo = [t for t in em_estorno if t.external_id == identificador]
        assert round(sum(t.value for t in grupo), 2) == 0.0
        assert len({t.source_account for t in grupo}) == 1


@pytest.mark.invariante
def test_a_serie_mensal_sai_em_ordem_cronologica_e_atravessa_o_ano(montada):
    mensal = FinancialCalculator.calculate_monthly_trend(montada.base)
    meses = [m["month"] for m in mensal]

    assert meses == sorted(meses, key=ordem_do_mes)
    assert meses != sorted(meses), (
        "a série não atravessa a virada de ano: ordenar como texto daria o "
        "mesmo resultado e o teste não provaria nada")
    assert meses.index("12/2025") + 1 == meses.index("01/2026")
    por_dono = FinancialCalculator.calculate_income_by_owner_by_month(
        montada.base, montada.config)
    assert [m["month"] for m in por_dono] == meses
    cobertura = CoverageAnalyzer.all_months(
        CoverageAnalyzer.compute(montada.base, montada.config))
    assert cobertura == meses


@pytest.mark.invariante
def test_importar_o_conjunto_de_novo_nao_acrescenta_nada(montada):
    conjunto = montada.conjunto
    arquivos = [(p.name, p.read_bytes())
                for p in sorted(conjunto.pasta_dos_extratos.glob("*.csv"))]
    de_novo = preparar_importacao(arquivos, montada.base, montada.categorizador)

    assert de_novo.novas == []
    assert de_novo.duplicatas == sum(a["linhas"] for a in conjunto.arquivos)


@pytest.mark.invariante
def test_so_tem_fonte_a_receita_que_a_lista_aponta(montada):
    """A atribuição é exata: nenhuma receita ganha fonte por parecer com
    outra. Decisão fechada nº 2."""
    apontadas = {(a["arquivo"], a["linha"]): a["fonte"]
                 for a in montada.conjunto.atribuicoes}
    com_fonte = {(t.raw_data["filename"], t.raw_data["row_number"]):
                 t.income_source for t in montada.base if t.income_source}

    assert com_fonte == apontadas
    assert all(t.type == TransactionType.RECEITA and not t.is_neutral
               for t in montada.base if t.income_source)


@pytest.mark.invariante
def test_o_pool_da_demonstracao_e_o_ficticio_do_codigo(montada):
    padrao = AppConfig()
    assert [m.to_dict() for m in montada.config.members] == [
        m.to_dict() for m in padrao.members]
    assert [a.to_dict() for a in montada.config.accounts] == [
        a.to_dict() for a in padrao.accounts]
    assert CoverageAnalyzer.discover_accounts(montada.base, montada.config) == []


@pytest.mark.invariante
def test_pix_de_terceiro_nao_vira_servicos_pelo_nome_da_instituicao(montada):
    """
    A palavra "banco" no nome da instituição levaria todo Pix de terceiro a
    "Serviços", pela regra de tarifa bancária. As instituições do conjunto
    são inventadas sem ela, e os Pix caem no fallback "Transferências".
    """
    com_instituicao = [t for t in montada.base
                       if any(i in t.description for i in gerador.INSTITUICOES)]
    assert com_instituicao
    assert not [t.description for t in com_instituicao
                if t.category == "Serviços"]


# ===========================================================================
# Amarrados a arquivo — os números deste conjunto
# ===========================================================================

@pytest.mark.amarrado_a_arquivo
def test_volume_duplicatas_e_o_que_a_montagem_conta(montada):
    esperado = montada.conjunto.esperado

    assert len(montada.base) == esperado["transacoes"] == 776
    assert montada.montagem.duplicatas == esperado["duplicatas"] == 36
    assert montada.montagem.arquivos == len(montada.conjunto.arquivos) == 36
    assert sum(a["linhas"] for a in montada.conjunto.arquivos) == (
        esperado["linhas_nos_arquivos"]) == 812
    assert 600 <= len(montada.base) <= 900, "perfil: volume de 600 a 900 linhas"


@pytest.mark.amarrado_a_arquivo
def test_periodo_e_data_de_referencia(conjunto):
    assert (conjunto.inicio, conjunto.fim) == (date(2025, 9, 1),
                                                date(2026, 10, 31))
    assert conjunto.data_de_referencia.date() == date(2026, 11, 1)
    assert conjunto.periodo_str == "01/09/2025 a 31/10/2026"
    assert conjunto.referencia_str == "01/11/2026"


@pytest.mark.amarrado_a_arquivo
def test_pares_pendencias_e_estornos(montada):
    esperado = montada.conjunto.esperado
    pares = sum(1 for t in montada.base if t.paired_transfer_id) // 2
    pendentes = montada.matcher.get_pending_transfers(montada.base)
    da_empresa = [t for t in pendentes
                  if EMPRESA in DataValidator.normalize_description(t.description)]

    assert pares == montada.montagem.pares == esperado["pares_conciliados"] == 43
    assert pares >= 20, "perfil: ao menos 20 pares conciliados"
    assert len(pendentes) == esperado["pendencias"] == 23
    # Perfil, com a emenda de 13/11: as da empresa (14 pró-labores e os
    # aportes) mais 4 a 8 de outras origens.
    assert len(da_empresa) == esperado["pendencias_da_empresa"] == 17
    assert sum(1 for t in da_empresa if t.value > 0) == 14
    assert sum(1 for t in da_empresa if t.value < 0) == 3
    outras = len(pendentes) - len(da_empresa)
    assert outras == esperado["pendencias_de_outras_origens"] == 6
    assert 4 <= outras <= 8

    em_estorno = [t for t in montada.base if t.category == "Estorno"]
    assert len(em_estorno) == esperado["transacoes_em_estorno"] == 4


@pytest.mark.amarrado_a_arquivo
def test_totais_e_taxa_de_poupanca(montada):
    esperado = montada.conjunto.esperado
    resumo = FinancialCalculator.calculate_summary(montada.base)

    assert _centavos(resumo.total_receitas) == (
        esperado["total_receitas_centavos"]) == 13_988_391
    assert _centavos(resumo.total_despesas) == (
        esperado["total_despesas_centavos"]) == 12_422_560
    taxa = FinancialCalculator.savings_rate_from_summary(resumo)
    assert round(taxa, 2) == 11.19
    assert 5 <= taxa <= 15, "perfil: poupança positiva, entre 5% e 15%"


@pytest.mark.amarrado_a_arquivo
def test_saldo_de_cada_mes_e_os_tres_negativos(montada):
    esperado = montada.conjunto.esperado
    mensal = FinancialCalculator.calculate_monthly_trend(montada.base)
    saldos = {m["month"]: _centavos(m["saldo"]) for m in mensal}

    assert len(saldos) == 14, "perfil: 14 meses inteiros"
    assert saldos == esperado["saldo_por_mes_centavos"]
    negativos = [m for m, v in saldos.items() if v < 0]
    assert negativos == esperado["meses_negativos"] == [
        "01/2026", "06/2026", "10/2026"]
    posicoes = [list(saldos).index(m) for m in negativos]
    assert all(b - a > 1 for a, b in zip(posicoes, posicoes[1:])), (
        "perfil: os meses negativos não são consecutivos")
    # Taxa de poupança NEGATIVA no mês em que o saldo é negativo — o sinal é
    # a informação (decisão fechada nº 9).
    outubro = [t for t in montada.base if t.month_year == "10/2026"]
    assert FinancialCalculator.calculate_savings_rate(outubro) < 0


@pytest.mark.amarrado_a_arquivo
def test_renda_por_tipo_por_fonte_e_por_dono(montada):
    esperado = montada.conjunto.esperado
    base, config = montada.base, montada.config

    assert [(s.name, s.type, s.owner) for s in config.income_sources] == [
        ("Salário", "fixa", "Ana Quintela"),
        ("Pró-labore", "fixa", "Bruno Quintela"),
        ("Serviços avulsos", "variavel", "Bruno Quintela"),
        ("Aulas particulares", "variavel", "Ana Quintela"),
        ("Rendimentos", "variavel", ""),
    ]

    analise = FinancialCalculator.calculate_income_analysis(base, config)
    assert _centavos(analise["fixa"]) == esperado["renda_fixa_centavos"] == 11_200_000
    assert _centavos(analise["variavel"]) == (
        esperado["renda_variavel_centavos"]) == 2_499_552
    assert _centavos(analise["nao_classificada"]) == 288_839
    assert _centavos(analise["renda_necessaria"]) == (
        esperado["total_despesas_centavos"]), (
        "renda necessária é o total de despesas do período (decisão nº 3)")
    fixa_pct = analise["fixa"] / (analise["fixa"] + analise["variavel"]) * 100
    assert round(fixa_pct, 2) == 81.75
    assert 75 <= fixa_pct <= 85, "perfil: renda fixa entre 75% e 85% da atribuída"

    por_fonte = Counter()
    quantas = Counter()
    for t in _ativas(base):
        if t.income_source:
            por_fonte[t.income_source] += _centavos(t.value)
            quantas[t.income_source] += 1
    assert dict(por_fonte) == esperado["renda_por_fonte_centavos"]
    assert quantas == {"Salário": 14, "Pró-labore": 14, "Serviços avulsos": 18,
                       "Aulas particulares": 29, "Rendimentos": 13}
    salarios = {t.value for t in base if t.income_source == "Salário"}
    pro_labores = {t.value for t in base if t.income_source == "Pró-labore"}
    assert salarios == {5200.0} and pro_labores == {2800.0}

    por_dono = {d["owner"]: (_centavos(d["total"]), d["num_transacoes"])
                for d in FinancialCalculator.calculate_income_by_owner(base, config)}
    # "Sem fonte atribuída" e "Fonte sem dono" separadas (decisão nº 10).
    assert por_dono == {
        "Ana Quintela": (7_716_000, 43),
        "Bruno Quintela": (5_932_000, 32),
        FinancialCalculator.SEM_FONTE: (288_839, 8),
        FinancialCalculator.FONTE_SEM_DONO: (51_552, 13),
    }


@pytest.mark.amarrado_a_arquivo
def test_receitas_sem_fonte(montada):
    sem_fonte = [t for t in _ativas(montada.base)
                 if t.type == TransactionType.RECEITA and not t.income_source]

    assert len(sem_fonte) == montada.conjunto.receitas_sem_fonte == 8
    assert montada.montagem.receitas_sem_fonte == 8
    assert 6 <= len(sem_fonte) <= 10, "perfil: entre 6 e 10 receitas sem fonte"
    assert len(montada.conjunto.atribuicoes) == montada.montagem.atribuidas == 88


@pytest.mark.amarrado_a_arquivo
def test_cobertura_tem_o_buraco_e_as_duas_contas_sem_extrato(montada):
    esperado = montada.conjunto.esperado["transacoes_por_conta_e_mes"]
    cobertura = CoverageAnalyzer.compute(montada.base, montada.config)

    com_extrato = {conta: meses for conta, meses in cobertura.items() if meses}
    assert com_extrato == esperado
    assert sorted(com_extrato) == [
        "C6 Bank (conta) 12345678", "Inter (conta) 87654321",
        "Nubank (conta) 55667788", "Nubank (conta) 99887766"]
    # Perfil: as outras duas contas ficam cadastradas, sem extrato.
    assert sorted(c for c, meses in cobertura.items() if not meses) == [
        "C6 Bank (conta) 44332211", "Inter (conta) 11223344"]
    # Perfil: um mês sem extrato numa das quatro contas.
    buracos = [(conta, mes) for conta, meses in com_extrato.items()
               for mes in CoverageAnalyzer.all_months(cobertura)
               if mes not in meses]
    assert buracos == [("Nubank (conta) 55667788", "03/2026")]


@pytest.mark.amarrado_a_arquivo
def test_ha_extratos_da_mesma_conta_com_periodo_sobreposto(montada):
    """Perfil: ao menos dois arquivos da mesma conta com período sobreposto.
    São eles que produzem as duplicatas que a importação descarta."""
    por_arquivo = Counter(t.raw_data["filename"] for t in montada.base)
    lidas = {a["nome"]: a["linhas"] for a in montada.conjunto.arquivos}
    perderam_linha = sorted(n for n in lidas if por_arquivo[n] < lidas[n])

    assert perderam_linha == [
        "C6_12345678_2025-12-01_a_2026-03-31.csv",
        "INTER_87654321_2025-12-01_a_2026-03-31.csv",
        "NU_99887766_15JUN2026_15JUL2026.csv"]
    assert por_arquivo["NU_99887766_15JUN2026_15JUL2026.csv"] == 0, (
        "o extrato pedido no meio do mês só repete os dois mensais")


@pytest.mark.amarrado_a_arquivo
def test_toda_categoria_de_despesa_tem_linha(montada):
    despesas = Counter()
    for t in _ativas(montada.base):
        if t.type == TransactionType.DESPESA:
            despesas[CategoryManager.path_of(t.category, t.subcategory)] += 1
    categorias = {caminho.split(" > ")[0].replace(" (geral)", "")
                  for caminho in despesas}

    # Perfil: toda categoria de despesa das regras com ao menos uma linha.
    assert {"Alimentação", "Transporte", "Moradia", "Saúde", "Lazer",
            "Educação", "Vestuário", "Serviços", "Transferências",
            "Investimentos", "Outros"} == categorias
    # Perfil: em Alimentação e em Transporte, cada subcategoria alcançável
    # sem marca. Delivery só se alcança por marca e fica vazia, por decisão
    # do dono na liberação de 13/11/2026.
    assert {c for c in despesas if c.startswith("Alimentação")} == {
        "Alimentação > Supermercado", "Alimentação > Padaria e Lanches",
        "Alimentação > Restaurantes e Bares"}
    assert {c for c in despesas if c.startswith("Transporte")} == {
        "Transporte (geral)", "Transporte > Combustível",
        "Transporte > Estacionamento", "Transporte > App de Transporte",
        "Transporte > Manutenção"}
    assert despesas == {
        "Alimentação > Padaria e Lanches": 115,
        "Alimentação > Restaurantes e Bares": 36,
        "Alimentação > Supermercado": 85,
        "Educação > Cursos e Livros": 8,
        "Educação > Mensalidades": 14,
        "Investimentos": 14,
        "Lazer (geral)": 14,
        "Lazer > Eventos e Passeios": 9,
        "Lazer > Streaming": 14,
        "Moradia (geral)": 1,
        "Moradia > Aluguel e Condomínio": 28,
        "Moradia > Energia": 14,
        "Moradia > Telefone e Internet": 28,
        "Moradia > Água": 14,
        "Outros": 23,
        "Saúde (geral)": 14,
        "Saúde > Consultas e Exames": 8,
        "Saúde > Farmácia": 26,
        "Serviços": 15,
        "Transferências": 22,
        "Transporte (geral)": 8,
        "Transporte > App de Transporte": 11,
        "Transporte > Combustível": 32,
        "Transporte > Estacionamento": 22,
        "Transporte > Manutenção": 2,
        "Vestuário": 13,
    }


@pytest.mark.amarrado_a_arquivo
def test_os_terceiros_parecidos_que_o_conjunto_traz(montada):
    presentes = sorted(nome for nome in gerador.TERCEIROS_PARECIDOS
                       if any(nome.lower() in t.description.lower()
                              for t in montada.base))
    assert presentes == ["Ana Paula Ribeiro Lopes", "Bruno Henrique Saldanha",
                         "Carla Quintela Ramos", "Diego Moreira Lopes",
                         "Felipe Quintela Prado"]
