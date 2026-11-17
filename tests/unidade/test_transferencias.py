# -*- coding: utf-8 -*-
"""
Camada de unidade — conciliação de transferências do pool.

Duas regras, e a segunda é decisão fechada (CLAUDE.md, item 1):

1. Par conciliado: duas pernas, contas diferentes, mesma data, valores
   opostos, ambas mencionando um membro. As duas viram "Transferência
   Interna", ficam vinculadas por `paired_transfer_id` e saem das
   métricas — dinheiro que mudou de bolso dentro do grupo.
2. **Perna solta permanece pendente e conta nas métricas.** Não se
   neutraliza por coincidência de nome: ou o extrato do outro lado ainda
   não foi importado, ou o dinheiro saiu do pool de verdade. Esconder o
   valor seria mentir para o usuário.
"""

from src.business.categorizer import SmartCategorizer
from src.business.transfer_matcher import CoverageAnalyzer, TransferMatcher

from tests.conftest import C6_JAN, INTER_JAN, NUBANK_JAN


def _base(importar, config_sintetica):
    transacoes = (importar(NUBANK_JAN).transactions
                  + importar(C6_JAN).transactions
                  + importar(INTER_JAN).transactions)
    SmartCategorizer(
        members=config_sintetica.members,
        category_manager=config_sintetica.get_category_manager()
    ).categorize_batch(transacoes)
    return transacoes


# ---------------------------------------------------------------------------
# Par conciliado
# ---------------------------------------------------------------------------

def test_par_de_pernas_em_contas_diferentes_e_conciliado(
        importar, config_sintetica):
    base = _base(importar, config_sintetica)
    novos, demovidas = TransferMatcher(config_sintetica).reconcile(base)

    assert novos == 1
    assert demovidas == 0

    saida = [t for t in base if t.value == -410.00][0]
    entrada = [t for t in base if t.value == 410.00][0]

    assert saida.source_account != entrada.source_account
    assert saida.date.date() == entrada.date.date()
    assert saida.paired_transfer_id == entrada.id
    assert entrada.paired_transfer_id == saida.id
    assert saida.category == entrada.category == "Transferência Interna"
    assert saida.is_neutral and entrada.is_neutral


def test_duas_pernas_na_mesma_conta_nao_formam_par(parser, config_sintetica):
    """
    Valores opostos e mesma data dentro de UMA conta não são transferência
    entre contas do pool — é o caso dos micro-Pix de ida e volta.
    """
    mesma_conta = (
        "Data,Valor,Identificador,Descrição\n"
        "10/01/2026,-1.00,1111aaaa-0000-0000-0000-000000000011,"
        "Transferência enviada pelo Pix - Bruno Quintela Moreira\n"
        "10/01/2026,1.00,2222bbbb-0000-0000-0000-000000000022,"
        "Transferência recebida pelo Pix - Bruno Quintela Moreira\n"
    )
    r = parser.parse_file(mesma_conta.encode("utf-8"),
                          "NU_99887766_01JAN2026_31JAN2026.csv")
    SmartCategorizer(
        members=config_sintetica.members,
        category_manager=config_sintetica.get_category_manager()
    ).categorize_batch(r.transactions)

    novos, _ = TransferMatcher(config_sintetica).reconcile(r.transactions)
    assert novos == 0
    assert all(t.paired_transfer_id is None for t in r.transactions)


def test_reconcile_e_idempotente(importar, config_sintetica):
    base = _base(importar, config_sintetica)
    matcher = TransferMatcher(config_sintetica)

    assert matcher.reconcile(base) == (1, 0)
    assert matcher.reconcile(base) == (0, 0)


# ---------------------------------------------------------------------------
# Perna solta — decisão fechada nº 1
# ---------------------------------------------------------------------------

def test_perna_sem_contraparte_permanece_pendente(importar, config_sintetica):
    base = _base(importar, config_sintetica)
    matcher = TransferMatcher(config_sintetica)
    matcher.reconcile(base)

    pendentes = matcher.get_pending_transfers(base)
    assert len(pendentes) == 1

    solta = pendentes[0]
    assert solta.value == -120.00
    assert solta.paired_transfer_id is None
    assert solta.category == "Transferências"


def test_perna_solta_continua_contando_nas_metricas(
        importar, config_sintetica):
    """
    O ponto da decisão: pendente NÃO é neutra. O valor segue nas despesas
    porque o dinheiro pode ter saído do pool de verdade.
    """
    base = _base(importar, config_sintetica)
    TransferMatcher(config_sintetica).reconcile(base)

    solta = [t for t in base if t.value == -120.00][0]
    assert not solta.is_neutral
    assert not solta.is_internal_transfer


def test_pernas_conciliadas_ficam_fora_das_pendencias(
        importar, config_sintetica):
    base = _base(importar, config_sintetica)
    matcher = TransferMatcher(config_sintetica)
    matcher.reconcile(base)

    pendentes = matcher.get_pending_transfers(base)
    assert not any(t.paired_transfer_id for t in pendentes)
    assert not any(t.category == "Transferência Interna" for t in pendentes)


# ---------------------------------------------------------------------------
# Categorização: "Transferências" é fallback de mecanismo
# ---------------------------------------------------------------------------

def test_transferencias_perde_para_categoria_de_conteudo(
        importar, config_sintetica):
    """
    Decisão fechada nº 5. 'Transferência enviada pelo Pix - HORTIFRUTI
    BOA COLHEITA' carrega o mecanismo E o comerciante. O comerciante vence:
    se 'pix'/'enviada' pontuassem junto, tudo viraria Transferências.
    """
    base = _base(importar, config_sintetica)
    hortifruti = [t for t in base if "HORTIFRUTI" in t.description]
    assert len(hortifruti) == 2
    assert all(t.category_path == "Alimentação > Supermercado"
               for t in hortifruti)


def test_transferencias_vence_quando_nao_ha_comerciante(
        importar, config_sintetica):
    base = _base(importar, config_sintetica)
    solta = [t for t in base if t.value == -120.00][0]
    assert solta.category == "Transferências"


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------

def test_cobertura_lista_as_contas_registradas_e_seus_meses(
        importar, config_sintetica):
    base = _base(importar, config_sintetica)
    cobertura = CoverageAnalyzer.compute(base, config_sintetica)

    assert all(a.label in cobertura for a in config_sintetica.accounts)
    assert cobertura["Nubank (conta) 99887766"]["01/2026"] == 6
    assert cobertura["C6 Bank (conta) 12345678"]["01/2026"] == 3
    assert cobertura["Inter (conta) 87654321"]["01/2026"] == 4


def test_conta_registrada_sem_transacao_aparece_vazia(config_sintetica):
    """Linha vazia no painel = extrato nunca importado, e isso tem que
    ser visível em vez de virar buraco silencioso nas métricas."""
    cobertura = CoverageAnalyzer.compute([], config_sintetica)
    assert cobertura["Inter (conta) 87654321"] == {}
