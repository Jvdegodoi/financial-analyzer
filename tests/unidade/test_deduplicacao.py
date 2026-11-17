# -*- coding: utf-8 -*-
"""
Camada de unidade — deduplicação determinística.

Dois caminhos independentes, e os dois precisam de teste próprio:

- **Chave primária** `(conta, external_id, valor)`, quando o banco dá
  identificador. O Nubank dá. O valor entra na chave porque o estorno do
  Nubank compartilha o identificador da transação original — sem o valor,
  o estorno seria descartado como duplicata da compra.
- **Contagem (multiset)** `(conta, data, valor, descrição normalizada)`,
  quando não há identificador. C6 e Inter caem aqui. A multiplicidade
  legítima de uma chave é quantas vezes ela aparece dentro de UM MESMO
  arquivo: banco não repete linha num extrato, então duas idênticas no
  mesmo arquivo são duas compras de verdade.

O caso que dá nome ao segundo caminho — duas transações legítimas e
idênticas no mesmo dia — é o que a versão anterior perdia em silêncio.
"""

from src.data.parser import TransactionDeduplicator

from tests.conftest import (C6_JAN, INTER_JAN, INTER_SOBREPOSTO, NUBANK_JAN,
                            NUBANK_SOBREPOSTO)


# ---------------------------------------------------------------------------
# Caminho da chave primária (Nubank)
# ---------------------------------------------------------------------------

def test_duas_transacoes_identicas_no_mesmo_dia_sao_preservadas(importar):
    """
    Duas compras de R$ 15,00 na mesma hortifruti, no mesmo dia, com
    identificadores distintos. São duas compras, não uma duplicata.
    """
    transacoes = importar(NUBANK_JAN).transactions
    hortifruti = [t for t in transacoes if "HORTIFRUTI" in t.description]
    assert len(hortifruti) == 2
    assert hortifruti[0].external_id != hortifruti[1].external_id

    unicas, dups = TransactionDeduplicator.remove_duplicates(transacoes, [])
    assert dups == 0
    assert len(unicas) == 6


def test_estorno_nao_e_deduplicado_apesar_do_id_compartilhado(importar):
    """
    O par de estorno divide o external_id com a transação original. Se o
    valor não entrasse na chave, o estorno sumiria como duplicata e a
    despesa ficaria de pé sozinha.
    """
    transacoes = importar(NUBANK_JAN).transactions
    par = [t for t in transacoes if "VALE VERDE" in t.description]
    assert len(par) == 2
    assert par[0].external_id == par[1].external_id
    assert par[0].value == -par[1].value

    unicas, _ = TransactionDeduplicator.remove_duplicates(transacoes, [])
    assert len([t for t in unicas if "VALE VERDE" in t.description]) == 2


def test_reimportar_o_mesmo_arquivo_deduplica_tudo(importar):
    """
    Reimportar do zero é operação legítima de recuperação: os extratos são
    a fonte da verdade e o JSON é estado derivado. Não pode duplicar nada.
    """
    base = importar(NUBANK_JAN).transactions
    denovo = importar(NUBANK_JAN).transactions

    unicas, dups = TransactionDeduplicator.remove_duplicates(denovo, base)
    assert unicas == []
    assert dups == len(base) == 6


def test_periodos_sobrepostos_com_identificador_deduplicam_a_interseccao(
        importar):
    """
    Os dois arquivos do Nubank se sobrepõem em 22/01. Importados juntos,
    a linha repetida sai; a de fevereiro, que só existe no segundo, fica.
    """
    juntos = (importar(NUBANK_JAN).transactions
              + importar(NUBANK_SOBREPOSTO).transactions)
    assert len(juntos) == 8

    unicas, dups = TransactionDeduplicator.remove_duplicates(juntos, [])
    assert dups == 1
    assert len(unicas) == 7
    assert sum(1 for t in unicas if "NETFLIX" in t.description) == 1


# ---------------------------------------------------------------------------
# Caminho da contagem (C6 e Inter, sem identificador)
# ---------------------------------------------------------------------------

def test_gemeas_legitimas_sem_identificador_no_mesmo_arquivo(importar):
    """
    Dois açaís de R$ 10,00 no mesmo dia, no Inter, que não fornece
    identificador. A multiplicidade legítima vem da contagem dentro do
    arquivo — as duas sobrevivem.
    """
    transacoes = importar(INTER_JAN).transactions
    acai = [t for t in transacoes if "Acai" in t.description]
    assert len(acai) == 2
    assert all(t.external_id is None for t in acai)

    unicas, dups = TransactionDeduplicator.remove_duplicates(transacoes, [])
    assert dups == 0
    assert len(unicas) == 4


def test_periodos_sobrepostos_sem_identificador_deduplicam_a_interseccao(
        importar):
    """
    Os dois extratos do Inter se sobrepõem em 19/01 e 21/01. O par de
    açaís continua sendo um par — não vira quatro nem colapsa em um.
    """
    juntos = (importar(INTER_JAN).transactions
              + importar(INTER_SOBREPOSTO).transactions)
    assert len(juntos) == 8

    unicas, dups = TransactionDeduplicator.remove_duplicates(juntos, [])
    assert dups == 3
    assert len(unicas) == 5
    assert sum(1 for t in unicas if "Acai" in t.description) == 2
    assert sum(1 for t in unicas if "Supermercado" in t.description) == 1
    assert sum(1 for t in unicas if "Drogaria" in t.description) == 1


def test_importacao_incremental_respeita_a_base_ja_existente(importar):
    """
    Mesma sobreposição, mas em duas importações. O resultado tem que ser
    igual ao de importar tudo de uma vez: só a linha nova de fevereiro.
    """
    base = importar(INTER_JAN).transactions
    novas = importar(INTER_SOBREPOSTO).transactions

    unicas, dups = TransactionDeduplicator.remove_duplicates(novas, base)
    assert dups == 3
    assert len(unicas) == 1
    assert "Drogaria" in unicas[0].description


def test_contas_diferentes_nao_se_deduplicam_entre_si(importar):
    """
    A conta faz parte das duas chaves. Duas contas do mesmo pool podem ter
    o mesmo lançamento no mesmo dia sem que uma apague a outra.
    """
    juntos = (importar(NUBANK_JAN).transactions
              + importar(C6_JAN).transactions
              + importar(INTER_JAN).transactions)

    unicas, dups = TransactionDeduplicator.remove_duplicates(juntos, [])
    assert dups == 0
    assert len(unicas) == 13
    assert len({t.source_account for t in unicas}) == 3
