# -*- coding: utf-8 -*-
"""
Camada de unidade — "Manutenção" como subcategoria de Transporte (3a).

Critério de granularidade: a divisão só existe se muda decisão. Combustível
é função de quanto se roda, manutenção é da idade do carro, e as duas se
corrigem de formas diferentes — logo, divide. Manutenção subdividida por
tipo de reparo não muda nada — logo, não divide (e este arquivo guarda
isso: a árvore continua com teto de dois níveis, decisão nº 7).

As regras que já existiam para `manutencao veiculo|mecanica` caíam no pai.
Agora apontam para a subcategoria — o `CategoryManager` documenta que toda
subcategoria semeada tem regra correspondente no `SmartCategorizer`.

Medido: nenhuma transação da base real casa com essas regras hoje. A
mudança não move o benchmark; ela dá ao dono a opção no dropdown e ao motor
o destino certo quando a linha aparecer.
"""

from datetime import datetime

import pytest

from src.business.categorizer import SmartCategorizer
from src.data.models import CategoryManager, Transaction


@pytest.fixture
def gerenciador() -> CategoryManager:
    return CategoryManager()


@pytest.fixture
def categorizador(config_sintetica) -> SmartCategorizer:
    return SmartCategorizer(members=config_sintetica.members)


def _despesa(descricao: str, valor: float = -280.0) -> Transaction:
    return Transaction(
        id="sint-" + descricao[:12].replace(" ", "-"),
        date=datetime(2026, 3, 11),
        value=valor,
        description=descricao,
        category="Outros",   # será substituída pelo motor
        source_account="Nubank (conta) 99887766",
    )


def test_manutencao_esta_na_arvore_semeada(gerenciador):
    subs = gerenciador.get_tree()["Transporte"]
    assert "Manutenção" in subs
    # As três que já existiam continuam onde estavam.
    for antiga in ("Combustível", "Estacionamento", "App de Transporte"):
        assert antiga in subs


def test_caminho_de_dois_niveis_e_reversivel(gerenciador):
    """Decisão nº 7: campo separado, teto de dois níveis."""
    caminho = "Transporte" + CategoryManager.SEPARATOR + "Manutenção"
    assert caminho in gerenciador.get_all_paths()
    cat, sub = CategoryManager.parse_path(caminho)
    assert (cat, sub) == ("Transporte", "Manutenção")
    assert CategoryManager.SEPARATOR not in sub


@pytest.mark.parametrize("descricao", [
    "MANUTENCAO VEICULO SILVA LTDA",
    "MECANICA DO ZE",
    "OFICINA CENTRAL AUTOS",
    "AUTO CENTER PARANOA",
    "PNEUS BRASILIA COMERCIO",
])
def test_descricoes_de_manutencao_caem_na_subcategoria(categorizador,
                                                       descricao):
    categoria, subcategoria, _ = categorizador.categorize(_despesa(descricao))
    assert categoria == "Transporte"
    assert subcategoria == "Manutenção"


@pytest.mark.parametrize("descricao,esperada", [
    ("POSTO IPIRANGA CENTRO", "Combustível"),
    ("AUTO POSTO GASOLINA", "Combustível"),
    ("ESTAPAR ESTACIONAMENTO", "Estacionamento"),
    ("UBER TRIP SP", "App de Transporte"),
])
def test_as_outras_subcategorias_nao_foram_desviadas(categorizador,
                                                     descricao, esperada):
    """A regra nova não pode roubar o que já classificava certo."""
    categoria, subcategoria, _ = categorizador.categorize(_despesa(descricao))
    assert categoria == "Transporte"
    assert subcategoria == esperada


@pytest.mark.parametrize("descricao", [
    "SEGURO AUTO PORTO SEGURO",
    "IPVA 2026 DETRAN DF",
    "PEDAGIO CCR",
])
def test_o_que_nao_e_manutencao_fica_no_pai(categorizador, descricao):
    """
    Seguro e IPVA não são manutenção nem combustível: são custo fixo de ter
    o carro, não de rodar nem de consertar. Ficam em Transporte (geral) —
    dividir aí não mudaria decisão nenhuma.
    """
    categoria, subcategoria, _ = categorizador.categorize(_despesa(descricao))
    assert categoria == "Transporte"
    assert subcategoria is None
