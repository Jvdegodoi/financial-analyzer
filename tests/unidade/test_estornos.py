# -*- coding: utf-8 -*-
"""
Camada de unidade — neutralização de pares de estorno.

O estorno do Nubank compartilha o `external_id` da transação original.
Quando os dois lados estão presentes e os valores se cancelam, AMBOS
viram "Estorno" e saem das métricas: não houve receita nem despesa.

Um lado sozinho não neutraliza nada — o dinheiro pode ter saído mesmo.
"""

from src.business.categorizer import ReversalMatcher, SmartCategorizer

from tests.conftest import NUBANK_JAN


def _categorizador(config_sintetica):
    return SmartCategorizer(
        members=config_sintetica.members,
        category_manager=config_sintetica.get_category_manager())


def test_par_de_estorno_neutraliza_os_dois_lados(importar, config_sintetica):
    transacoes = importar(NUBANK_JAN).transactions
    _categorizador(config_sintetica).categorize_batch(transacoes)

    neutralizadas = ReversalMatcher.pair_reversals(transacoes)

    par = [t for t in transacoes if "VALE VERDE" in t.description]
    assert len(par) == 2
    assert all(t.category == "Estorno" for t in par)
    assert all(t.is_neutral for t in par)
    # A linha marcada 'Estorno -' já sai categorizada assim da
    # categorização; só a contraparte precisa ser virada aqui.
    assert neutralizadas == 1


def test_a_marca_de_estorno_na_descricao_vence_qualquer_comerciante(
        importar, config_sintetica):
    """
    'Estorno - Transferência enviada pelo Pix - RESTAURANTE VALE VERDE'
    carrega 'restaurante', que pontuaria alto em Alimentação. O estorno é
    avaliado antes de qualquer regra de conteúdo.
    """
    transacoes = importar(NUBANK_JAN).transactions
    _categorizador(config_sintetica).categorize_batch(transacoes)

    marcada = [t for t in transacoes
               if t.description.startswith("Estorno -")][0]
    assert marcada.category == "Estorno"


def test_compra_sem_estorno_permanece_despesa(importar, config_sintetica):
    transacoes = importar(NUBANK_JAN).transactions
    _categorizador(config_sintetica).categorize_batch(transacoes)
    ReversalMatcher.pair_reversals(transacoes)

    hortifruti = [t for t in transacoes if "HORTIFRUTI" in t.description]
    assert len(hortifruti) == 2
    assert all(t.category != "Estorno" for t in hortifruti)
    assert all(not t.is_neutral for t in hortifruti)


def test_estorno_sem_contraparte_nao_neutraliza(parser, config_sintetica):
    """
    Só a linha de estorno, sem a compra original no conjunto. Os valores
    não se cancelam dentro do grupo, então nada é neutralizado além da
    própria linha marcada.
    """
    so_estorno = (
        "Data,Valor,Identificador,Descrição\n"
        "07/01/2026,88.00,bbbb2222-0000-0000-0000-000000000002,"
        "Estorno - Transferência enviada pelo Pix - RESTAURANTE VALE VERDE\n"
    )
    r = parser.parse_file(so_estorno.encode("utf-8"),
                          "NU_99887766_01JAN2026_31JAN2026.csv")
    _categorizador(config_sintetica).categorize_batch(r.transactions)

    assert ReversalMatcher.pair_reversals(r.transactions) == 0
    assert len(r.transactions) == 1


def test_pair_reversals_e_idempotente(importar, config_sintetica):
    transacoes = importar(NUBANK_JAN).transactions
    _categorizador(config_sintetica).categorize_batch(transacoes)

    assert ReversalMatcher.pair_reversals(transacoes) == 1
    assert ReversalMatcher.pair_reversals(transacoes) == 0
