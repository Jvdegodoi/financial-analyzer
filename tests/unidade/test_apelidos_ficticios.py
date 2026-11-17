# -*- coding: utf-8 -*-
"""
Camada de unidade — o mecanismo do matching de apelido, com nomes fictícios.

O pool aqui é o padrão do código (`AppConfig()`), fictício. Os terceiros são
inventados para reproduzir as formas de sobreposição que existem num
extrato de verdade: mesmo primeiro nome, mesmo sobrenome, sobrenome em outra
ordem, grafia parecida, empresa com o sobrenome. Nenhum pode ser reconhecido
como membro.

A versão com os nomes reais — terceiros que de fato aparecem nos extratos
do dono — fica em `tests/test_apelidos.py`, lendo os arquivos locais, e só
roda na máquina dele.

O teste cobre os **dois caminhos independentes** que varrem apelidos:

- `TransferMatcher.member_mentioned` — decide se a transação é candidata a
  perna de transferência interna, e portanto se pode sair das métricas.
- `SmartCategorizer._is_member_transfer` — decide se a transação vira
  "Transferências" na categorização.

Os dois usam `alias in descricao_normalizada`, sem fronteira de palavra,
sobre a mesma lista. Uma mudança que passe em um e falhe no outro é
exatamente o buraco que este arquivo existe para fechar. O lado positivo
também é obrigatório: teste que só proíbe passa com um matcher que nunca
reconhece ninguém.
"""

import pytest

from src.business.categorizer import SmartCategorizer
from src.business.transfer_matcher import TransferMatcher
from src.data.models import AppConfig, FamilyMember

TERCEIROS_FICTICIOS = [
    "Ana Paula Ribeiro Lopes",            # mesmo primeiro nome
    "Ana Moreira Quintela",               # mesmo nome, sobrenomes em outra ordem
    "Ana Quintanilha Reis",               # começo de sobrenome igual
    "Anabela Quintas",                    # prefixo do primeiro nome
    "Bruno Henrique Saldanha",            # mesmo primeiro nome
    "Bruno Quintino Moreira",             # nome igual, sobrenome parecido
    "Bruna Quintela Dias",                # uma letra de diferença no nome
    "Brunno Quintella Rocha",             # grafia dobrada
    "Carla Quintela Ramos",               # mesmo sobrenome
    "Diego Moreira Lopes",                # mesmo sobrenome secundário
    "Felipe Quintela Prado",              # mesmo sobrenome
    "Quintela Materiais de Construcao",   # empresa com o sobrenome
]

# Nome dado de cada membro do pool fictício: um apelido feito só disto
# casaria com qualquer homônimo.
NOMES_DADOS = {"Ana Quintela": {"ana"}, "Bruno Quintela": {"bruno"}}
PARTICULAS = {"de", "da", "do", "das", "dos", "e"}


def _descricoes(nome):
    """As duas formas em que um terceiro aparece num extrato brasileiro."""
    return [
        f"Transferência enviada pelo Pix - {nome} - •••.000.000-•• - "
        f"NU PAGAMENTOS - IP (0260) Agência: 1 Conta: 00000000-0",
        f"Transferência recebida pelo Pix - {nome}",
    ]


@pytest.fixture(scope="module")
def config():
    return AppConfig()


@pytest.fixture(scope="module")
def matcher(config):
    return TransferMatcher(config)


@pytest.fixture(scope="module")
def categorizador(config):
    return SmartCategorizer(members=config.members,
                            category_manager=config.get_category_manager())


def test_o_pool_padrao_e_o_ficticio_que_este_arquivo_supoe(config):
    assert set(NOMES_DADOS) == {m.name for m in config.members}


def test_nenhum_terceiro_e_na_verdade_um_membro(config):
    nomes_membros = {m.name.lower() for m in config.members}
    assert not any(n.lower() in nomes_membros for n in TERCEIROS_FICTICIOS)


# ---------------------------------------------------------------------------
# Lado negativo — os dois caminhos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nome", TERCEIROS_FICTICIOS)
def test_terceiro_nao_e_reconhecido_pelos_dois_caminhos(nome, matcher,
                                                        categorizador):
    for descricao in _descricoes(nome):
        mencionado = matcher.member_mentioned(descricao)
        transferencia = categorizador._is_member_transfer(descricao)
        assert mencionado is None, f"{nome!r} reconhecido como {mencionado!r}"
        assert transferencia is False, (
            f"{nome!r} tratado como transferência de membro")


# ---------------------------------------------------------------------------
# Lado positivo — os apelidos do pool têm que casar
# ---------------------------------------------------------------------------

def _parametros_positivos():
    for membro in AppConfig().members:
        for alias in membro.aliases:
            yield pytest.param(alias, membro.name,
                               id=f"{membro.name}::{alias}")


@pytest.mark.parametrize("alias,esperado", list(_parametros_positivos()))
def test_apelido_e_reconhecido_pelos_dois_caminhos(alias, esperado, matcher,
                                                   categorizador):
    for descricao in _descricoes(alias):
        assert matcher.member_mentioned(descricao) == esperado
        assert categorizador._is_member_transfer(descricao) is True


# ---------------------------------------------------------------------------
# A guarda contra apelido curto, e o que ela evita
# ---------------------------------------------------------------------------

def test_todo_apelido_traz_ao_menos_um_sobrenome(config):
    """
    O matching é por substring, sem fronteira de palavra. Enquanto todo
    apelido trouxer sobrenome, a colisão exige que o terceiro repita nome E
    sobrenome.
    """
    for membro in config.members:
        dados = NOMES_DADOS[membro.name]
        for alias in membro.aliases:
            palavras = set(alias.lower().split()) - PARTICULAS
            assert palavras - dados, (
                f"o apelido {alias!r} de {membro.name} é só nome dado: casa "
                f"por substring dentro do nome de qualquer homônimo")


def test_apelido_so_com_nome_dado_casaria_com_terceiro():
    """O defeito que a guarda acima evita, mostrado com um pool de teste."""
    pool = AppConfig(members=[FamilyMember(name="Ana Quintela",
                                           aliases=["ana"])])
    descricao = _descricoes("Ana Paula Ribeiro Lopes")[0]

    assert TransferMatcher(pool).member_mentioned(descricao) == "Ana Quintela"


def test_apelido_mais_longo_vence_o_mais_curto(matcher):
    descricao = "Pix recebido - Ana Quintela Moreira"
    assert matcher.member_mentioned(descricao) == "Ana Quintela"


def test_membro_sem_palavra_de_transferencia_nao_vira_transferencia(
        matcher, categorizador):
    """
    Os dois caminhos divergem DE PROPÓSITO aqui: `member_mentioned` só olha o
    apelido, enquanto `_is_member_transfer` exige também uma palavra de
    mecanismo. Compra num comerciante homônimo não é transferência.
    """
    descricao = "Compra no débito - Bruno Quintela Moreira"
    assert matcher.member_mentioned(descricao) == "Bruno Quintela"
    assert categorizador._is_member_transfer(descricao) is False


def test_descricao_sem_nenhum_membro_nao_casa(matcher, categorizador):
    descricao = ("Transferência enviada pelo Pix - "
                 "PADARIA FLOR DE TRIGO - 11.111.111/0001-11")
    assert matcher.member_mentioned(descricao) is None
    assert categorizador._is_member_transfer(descricao) is False
