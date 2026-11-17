# -*- coding: utf-8 -*-
"""
Camada de unidade — o estado "revisado".

`is_manual_category` só fica True quando o usuário TROCA a categoria: o
editor grava a alteração apenas se `new_path != path_of(trans)`. Linha que
ele abriu, leu e concordou ficava indistinguível de linha que ele nunca viu.
Não havia nenhum registro de "eu revisei isto e estava certo", que é
justamente o dado de que a medição de acurácia precisa — sem ele, o gabarito
perde as linhas em que o motor de regras ACERTOU, e a métrica piora à medida
que o dono rotula mais.

`revisada` é esse registro, e é um campo à parte de propósito. Os testes de
app.py aqui rodam contra um `data/` sintético montado em `tmp_path`: nenhum
dado real, nenhum pré-requisito de máquina.
"""

import json
from datetime import datetime

import pytest

from src.data.models import AppConfig, Transaction
from src.data.storage import StorageManager


def _transacao(identificador: str, valor: float = -50.0,
               categoria: str = "Alimentação", subcategoria=None,
               descricao=None) -> Transaction:
    return Transaction(
        id=identificador,
        date=datetime(2026, 1, 15),
        value=valor,
        description=descricao or ("Compra sintética %s" % identificador),
        category=categoria,
        subcategory=subcategoria,
        source_account="Nubank (conta) 99887766",
    )


# ---------------------------------------------------------------------------
# O campo no modelo
# ---------------------------------------------------------------------------

def test_transacao_nova_nasce_nao_revisada():
    assert _transacao("t-1").revisada is False


def test_registro_antigo_sem_o_campo_vira_nao_revisada():
    """
    Compatibilidade com tudo que foi gravado antes de o campo existir: o
    `from_dict` não pode explodir nem inventar True.
    """
    antigo = _transacao("t-1").to_dict()
    del antigo['revisada']

    assert Transaction.from_dict(antigo).revisada is False


def test_revisada_faz_roundtrip():
    original = _transacao("t-1")
    original.marcar_revisada()

    assert original.to_dict()['revisada'] is True
    assert Transaction.from_dict(original.to_dict()).revisada is True


def test_marcar_revisada_e_idempotente():
    t = _transacao("t-1")

    assert t.marcar_revisada() is True
    carimbo = t.updated_at

    assert t.marcar_revisada() is False, "remarcar deveria devolver False"
    assert t.revisada is True
    assert t.updated_at == carimbo, (
        "remarcar não pode reescrever updated_at: quem já estava revisada "
        "não mudou de estado")


def test_revisada_e_independente_de_is_manual_category():
    """
    O ponto do campo existir. As quatro combinações são estados legítimos:
    o dono pode concordar sem corrigir, corrigir sem ter sido pela tabela,
    ou nenhum dos dois.
    """
    concordou = _transacao("t-1")
    concordou.marcar_revisada()
    assert concordou.revisada is True
    assert concordou.is_manual_category is False

    corrigiu = _transacao("t-2")
    corrigiu.update_category("Lazer", None, is_manual=True)
    assert corrigiu.is_manual_category is True
    assert corrigiu.revisada is False, (
        "trocar a categoria não marca revisada por si — quem marca é o save "
        "da página, e é essa separação que o campo existe para manter")


def test_trocar_a_categoria_depois_nao_desmarca_a_revisao():
    t = _transacao("t-1")
    t.marcar_revisada()
    t.update_category("Lazer", None, is_manual=True)

    assert t.revisada is True


def test_revisada_sobrevive_ao_disco(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    marcada, nao_marcada = _transacao("t-1"), _transacao("t-2")
    marcada.marcar_revisada()

    storage.save_transactions([marcada, nao_marcada])
    recarregadas = {t.id: t for t in storage.load_transactions()}

    assert recarregadas["t-1"].revisada is True
    assert recarregadas["t-2"].revisada is False


# ---------------------------------------------------------------------------
# O comportamento do app: a PÁGINA INTEIRA vira revisada
# ---------------------------------------------------------------------------

@pytest.fixture
def app_com_dados(tmp_path, monkeypatch):
    """
    Monta um `data/` sintético e devolve um `AppTest` já rodado sobre ele.

    `init_storage` é `@st.cache_resource`, e o cache é global ao processo:
    sem limpá-lo, o segundo teste reusaria o `StorageManager` do primeiro,
    apontado para outro diretório temporário.

    O app chega ao `data/` sintético por `FA_DADOS`, que é como
    `src/ambiente.py` aponta o dado. `FA_DEMO` sai do ambiente porque
    venceria `FA_DADOS`.
    """
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from tests.conftest import RAIZ

    dados = tmp_path / "data"
    dados.mkdir()
    storage = StorageManager(data_dir=str(dados))
    storage.save_config(AppConfig())
    storage.save_transactions(
        [_transacao("t-%02d" % i, valor=-(10.0 + i)) for i in range(6)],
        create_backup=False)

    st.cache_resource.clear()
    monkeypatch.delenv("FA_DEMO", raising=False)
    monkeypatch.setenv("FA_DADOS", str(tmp_path))

    def _abrir():
        at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=300)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        return at

    yield _abrir, dados
    st.cache_resource.clear()


def _salvar_a_tabela(at):
    botao = [b for b in at.button if str(b.key or "").startswith("save_page_")]
    assert botao, "botão de salvar da tabela não encontrado"
    botao[0].click().run()
    return at


def test_salvar_marca_a_pagina_inteira_e_nao_so_o_que_mudou(app_com_dados):
    abrir, dados = app_com_dados
    at = abrir()

    assert all(not t.revisada for t in at.session_state["transactions"])

    _salvar_a_tabela(at)

    transacoes = at.session_state["transactions"]
    assert all(t.revisada for t in transacoes), (
        "a página inteira deveria virar revisada, não só as linhas alteradas")
    assert all(not t.is_manual_category for t in transacoes), (
        "marcar como revisada não pode marcar como corrigida à mão")


def test_a_marcacao_da_pagina_chega_ao_disco(app_com_dados):
    abrir, dados = app_com_dados
    at = abrir()
    _salvar_a_tabela(at)

    bruto = json.loads((dados / "transactions.json").read_text(
        encoding="utf-8"))
    assert all(r['revisada'] for r in bruto['transactions'])


def test_salvar_de_novo_sem_mexer_em_nada_nao_muda_nada(app_com_dados):
    """
    Idempotência pelo lado do app: a segunda gravação não tem o que marcar,
    e a interface diz isso em vez de fingir que salvou.
    """
    abrir, dados = app_com_dados
    at = abrir()
    _salvar_a_tabela(at)
    gravado = (dados / "transactions.json").read_text(encoding="utf-8")

    _salvar_a_tabela(at)

    assert any("já estava revisada" in str(i.value) for i in at.info)
    assert (dados / "transactions.json").read_text(
        encoding="utf-8") == gravado
