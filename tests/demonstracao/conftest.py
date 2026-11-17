# -*- coding: utf-8 -*-
"""
Testes sobre o conjunto de demonstração (`demonstracao/`).

É a camada de integração que roda em qualquer máquina: o pipeline inteiro —
parser, categorização, deduplicação, estornos, conciliação, renda — sobre
extratos fictícios e versionados. Nenhum teste daqui lê dado real.

Toda asserção leva uma das duas marcas de `pytest.ini`, e o gancho abaixo
recusa a coleta de um teste desta pasta que não tenha nenhuma:

- `invariante` — vale para qualquer versão do conjunto. Se falhar, é achado
  no produto ou no gerador: parar e reportar, nunca ajustar o número.
- `amarrado_a_arquivo` — número que só faz sentido para ESTES extratos. Quem
  mudar o gerador e regerar o conjunto recalibra de propósito, registrando o
  valor velho e o novo. Quase todos leem o esperado de `conjunto.json`, que
  o próprio gerador escreve: o que o teste afirma é que o PRODUTO chega ao
  mesmo número que o gerador calculou por outro caminho.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest

from src import demonstracao as demo
from src.business.categorizer import SmartCategorizer
from src.business.transfer_matcher import TransferMatcher
from src.data.models import AppConfig, Transaction
from src.data.storage import StorageManager

MARCAS = {"invariante", "amarrado_a_arquivo"}
AQUI = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    sem_marca = [item.nodeid for item in items
                 if AQUI in Path(str(item.fspath)).resolve().parents
                 and not MARCAS & {m.name for m in item.iter_markers()}]
    if sem_marca:
        raise pytest.UsageError(
            "teste de tests/demonstracao/ sem a marca invariante ou "
            "amarrado_a_arquivo: " + ", ".join(sem_marca))


@dataclass
class Montada:
    """A base de demonstração montada e lida de volta do disco, como o app
    a lê."""
    conjunto: demo.Conjunto
    montagem: demo.Montagem
    config: AppConfig
    base: List[Transaction]
    matcher: TransferMatcher
    categorizador: SmartCategorizer
    pasta: Path


def montar_em(pasta_data: Path) -> Montada:
    storage = StorageManager(data_dir=str(pasta_data))
    montagem = demo.montar(storage)
    config = storage.load_config()
    return Montada(
        conjunto=demo.carregar_conjunto(), montagem=montagem, config=config,
        base=storage.load_transactions(), matcher=TransferMatcher(config),
        categorizador=SmartCategorizer(
            members=config.members,
            category_manager=config.get_category_manager()),
        pasta=pasta_data)


@pytest.fixture(scope="session")
def conjunto() -> demo.Conjunto:
    return demo.carregar_conjunto()


@pytest.fixture(scope="module")
def montada(tmp_path_factory) -> Montada:
    """Uma montagem por módulo de teste. SÓ PARA LER: o teste que precisa
    mexer na base pede `montada_para_mexer`."""
    return montar_em(tmp_path_factory.mktemp("demonstracao") / "data")


@pytest.fixture
def montada_para_mexer(tmp_path) -> Montada:
    return montar_em(tmp_path / "data")


@pytest.fixture
def copia_do_conjunto(tmp_path):
    """
    Uma cópia do conjunto em `tmp_path`, para sabotar. O conjunto versionado
    nunca é editado por teste. Devolve a pasta e uma função que reescreve o
    `conjunto.json` da cópia.
    """
    pasta = tmp_path / "conjunto_sabotado"
    shutil.copytree(demo.PASTA, pasta,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def reescrever(mexer):
        caminho = pasta / demo.ARQUIVO_CONJUNTO
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        mexer(dados)
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    return pasta, reescrever
