# -*- coding: utf-8 -*-
"""
Camada de unidade — o app em cada modo de `src/ambiente.py`.

Roda `app.py` pelo `AppTest`, com o ambiente montado por `monkeypatch` e o
dado sintético em `tmp_path`. Nenhum teste aqui lê dado real: os que
exercitam o modo real apontam `FA_DADOS` para uma raiz inventada.

O que se afirma:

- Sem configuração, o app abre em demonstração, numa pasta temporária fora
  do projeto, com o pool fictício, o conjunto fictício montado e a tela
  dizendo isso.
- Em modo real a montagem da demonstração NÃO roda, com a base vazia ou
  cheia, e a data de referência da demonstração não vaza: "Últimos N dias"
  contam do relógio.
- Pasta configurada que não existe para o app, com a mensagem, e não cria
  nada.
- Em modo real, `config.json` ilegível cai na semente local; sem semente
  local, o app para. Em nenhum dos dois casos o arquivo é regravado.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.data.models import AppConfig, FamilyAccount, FamilyMember
from src.data.storage import StorageManager


@pytest.fixture
def abrir_app(monkeypatch):
    """Abre o app com o ambiente dado. Limpa o cache de `init_storage`, que é
    global ao processo, antes e depois."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from tests.conftest import RAIZ

    def _abrir(**ambiente):
        for chave in ("FA_DEMO", "FA_DADOS", "DATA_DIR"):
            monkeypatch.delenv(chave, raising=False)
        for chave, valor in ambiente.items():
            monkeypatch.setenv(chave, str(valor))
        st.cache_resource.clear()
        at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=300)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        return at

    yield _abrir
    st.cache_resource.clear()


def _textos(at):
    partes = []
    for colecao in (at.markdown, at.warning, at.error, at.info, at.caption):
        partes += [str(e.value) for e in colecao]
    return "\n".join(partes)


def _raiz_real(tmp_path, config_json=None):
    """Uma raiz do dado inventada, com `data/` e, se pedido, um config.json."""
    raiz = tmp_path / "dado"
    dados = raiz / "data"
    dados.mkdir(parents=True)
    if config_json is not None:
        (dados / "config.json").write_text(config_json, encoding="utf-8")
    return raiz


def _semente_local(raiz):
    """Uma semente 'real' inventada, diferente do pool fictício do código."""
    conteudo = {
        "members": [{"name": "Helena Varanda",
                     "aliases": ["helena varanda"]}],
        "accounts": [{"label": "Inter (conta) 10203040",
                      "owner": "Helena Varanda"}],
    }
    (raiz / "semente.local.json").write_text(json.dumps(conteudo),
                                             encoding="utf-8")


# ---------------------------------------------------------------------------
# Demonstração
# ---------------------------------------------------------------------------

def test_sem_configuracao_abre_em_demonstracao_fora_do_projeto(abrir_app,
                                                               tmp_path):
    from tests.conftest import RAIZ

    # O ini do projeto, se houver nesta máquina, nunca entra: a demonstração
    # é testada por FA_DEMO, que vence tudo e é o que o Code usa para subir o
    # app. O caminho "sem nada configurado" é o mesmo ramo de
    # `src/ambiente.py`, testado em test_ambiente.py.
    antes = sorted(p.name for p in RAIZ.iterdir())
    at = abrir_app(FA_DEMO="1")

    textos = _textos(at)
    assert "MODO DEMONSTRAÇÃO" in textos, "faixa fixa do topo ausente"
    assert "Demonstração." in textos, "aviso da barra lateral ausente"
    assert "Pasta dos dados: temporária" in textos

    nomes = [m.name for m in at.session_state["config"].members]
    assert nomes == [m.name for m in AppConfig().members]
    # A base não nasce vazia: é o conjunto fictício de `demonstracao/`,
    # montado na pasta temporária. O que ela mostra, tela a tela, está em
    # `tests/demonstracao/test_app_em_demonstracao.py`.
    from src import demonstracao as demo
    esperadas = demo.carregar_conjunto().esperado["transacoes"]
    assert len(at.session_state["transactions"]) == esperadas > 0

    pasta = Path(at.session_state["pasta_dos_dados"]).resolve()
    assert Path(tempfile.gettempdir()).resolve() in pasta.parents
    assert RAIZ.resolve() not in pasta.parents
    assert sorted(p.name for p in RAIZ.iterdir()) == antes, (
        "abrir em demonstração criou algo na pasta do projeto")


def test_demonstracao_nao_mostra_o_aviso_de_config_do_modo_real(abrir_app):
    at = abrir_app(FA_DEMO="1")
    assert "Membros e contas" not in _textos(at)


# ---------------------------------------------------------------------------
# A trava da suíte: sem FA_DEMO e sem FA_DADOS, o app não abre o dado real
# ---------------------------------------------------------------------------

def test_a_suite_nao_enxerga_o_ini_do_projeto():
    """A trava de `tests/conftest.py` está ligada neste teste, como em todos."""
    from src import ambiente
    from tests.conftest import RAIZ

    assert ambiente.RAIZ_PROJETO != RAIZ
    assert not (ambiente.RAIZ_PROJETO / ambiente.ARQUIVO_INI).exists()


def test_sem_fa_demo_e_sem_fa_dados_o_app_abre_em_demonstracao(abrir_app):
    """
    O caso do `FA_DADOS` esquecido. Na máquina do dono há um `fa.local.ini`
    na pasta do projeto apontando o dado real; mesmo assim, dentro da suíte,
    o app aberto sem `FA_DEMO` e sem `FA_DADOS` cai na demonstração.

    A ordem das duas metades é de propósito. A primeira pergunta ao
    resolvedor, que só lê a configuração e não abre dado nenhum. Se a trava
    estiver desligada e houver `fa.local.ini`, o teste falha ALI, e o app não
    chega a ser aberto sobre o dado real.
    """
    import os

    from src import ambiente

    sem_nada = {k: v for k, v in os.environ.items()
                if k not in ("FA_DEMO", "FA_DADOS", *ambiente.VARIAVEIS_ANTIGAS)}
    resolvido = ambiente.resolver(env=sem_nada)
    assert resolvido.demonstracao, (
        "sem FA_DEMO e sem FA_DADOS a suíte resolveu %s: a trava de "
        "tests/conftest.py não está valendo, e o app abriria esse dado"
        % resolvido.descrever())

    at = abrir_app()

    assert "MODO DEMONSTRAÇÃO" in _textos(at)
    pasta = Path(at.session_state["pasta_dos_dados"]).resolve()
    assert Path(tempfile.gettempdir()).resolve() in pasta.parents


# ---------------------------------------------------------------------------
# Pasta configurada que não está lá
# ---------------------------------------------------------------------------

def test_raiz_inexistente_para_o_app_e_nao_cria_nada(abrir_app, tmp_path):
    antes = sorted(p.name for p in tmp_path.iterdir())
    at = abrir_app(FA_DADOS=tmp_path / "hd_desligado")

    assert any("não existe" in str(e.value) for e in at.error)
    assert "transactions" not in at.session_state
    assert sorted(p.name for p in tmp_path.iterdir()) == antes


def test_raiz_sem_data_para_o_app_e_nao_cria_nada(abrir_app, tmp_path):
    raiz = tmp_path / "pasta_errada"
    raiz.mkdir()
    at = abrir_app(FA_DADOS=raiz)

    assert any("não tem a subpasta data" in str(e.value) for e in at.error)
    assert list(raiz.iterdir()) == []


# ---------------------------------------------------------------------------
# Modo real: config.json íntegro, ilegível, e a semente local
# ---------------------------------------------------------------------------

def test_modo_real_com_config_integro_nao_precisa_de_semente(abrir_app,
                                                             tmp_path):
    raiz = _raiz_real(tmp_path)
    config = AppConfig(
        members=[FamilyMember(name="Otávio Lagoa", aliases=["otavio lagoa"])],
        accounts=[FamilyAccount(label="C6 Bank (conta) 50607080",
                                owner="Otávio Lagoa")])
    StorageManager(data_dir=str(raiz / "data")).save_config(config)

    at = abrir_app(FA_DADOS=raiz)

    assert [m.name for m in at.session_state["config"].members] == [
        "Otávio Lagoa"]
    assert "MODO DEMONSTRAÇÃO" not in _textos(at)


def test_modo_real_config_ilegivel_cai_na_semente_local(abrir_app, tmp_path):
    raiz = _raiz_real(tmp_path, config_json="{isto não é json")
    _semente_local(raiz)
    bytes_antes = (raiz / "data" / "config.json").read_bytes()

    at = abrir_app(FA_DADOS=raiz)

    assert [m.name for m in at.session_state["config"].members] == [
        "Helena Varanda"], "caiu em membro fictício em vez da semente local"
    assert any("semente local" in str(w.value) for w in at.warning)
    assert (raiz / "data" / "config.json").read_bytes() == bytes_antes, (
        "abrir o app não pode regravar o config.json")


def test_modo_real_config_ilegivel_sem_semente_para_o_app(abrir_app,
                                                          tmp_path):
    raiz = _raiz_real(tmp_path, config_json="{isto não é json")
    bytes_antes = (raiz / "data" / "config.json").read_bytes()

    at = abrir_app(FA_DADOS=raiz)

    assert any("semente local não foi encontrada" in str(e.value)
               for e in at.error)
    assert "config" not in at.session_state
    assert "transactions" not in at.session_state
    assert (raiz / "data" / "config.json").read_bytes() == bytes_antes


def test_modo_real_base_nova_nasce_da_semente_local(abrir_app, tmp_path):
    """`data/` vazia, sem config.json: é base nova, e nasce do pool real."""
    raiz = _raiz_real(tmp_path)
    _semente_local(raiz)

    at = abrir_app(FA_DADOS=raiz)

    assert [m.name for m in at.session_state["config"].members] == [
        "Helena Varanda"]
    assert not (raiz / "data" / "config.json").exists(), (
        "abrir não grava: o config.json só nasce no primeiro ajuste")


def test_semente_local_malformada_para_o_app(abrir_app, tmp_path):
    raiz = _raiz_real(tmp_path)
    (raiz / "semente.local.json").write_text('{"members": []}',
                                             encoding="utf-8")

    at = abrir_app(FA_DADOS=raiz)

    assert any("semente local não se deixa ler" in str(e.value)
               for e in at.error)


# ---------------------------------------------------------------------------
# Em modo real a montagem da demonstração não roda
# ---------------------------------------------------------------------------

def _fotografia(raiz):
    """Todo arquivo da raiz, com os bytes: nada pode entrar, sair ou mudar."""
    return {p.relative_to(raiz).as_posix(): p.read_bytes()
            for p in raiz.rglob("*") if p.is_file()}


def _config_inventado():
    return AppConfig(
        members=[FamilyMember(name="Otávio Lagoa", aliases=["otavio lagoa"])],
        accounts=[FamilyAccount(label="C6 Bank (conta) 50607080",
                                owner="Otávio Lagoa")])


@pytest.mark.parametrize("como_nasce", ["config íntegro", "semente local"])
def test_modo_real_com_a_base_vazia_nao_monta_a_demonstracao(abrir_app,
                                                             tmp_path, como_nasce):
    """
    A base vazia é o caso que tenta: é exatamente a pasta em que a montagem
    escreveria. Em modo real ela continua vazia — nenhuma transação entra,
    nenhum arquivo nasce ou muda.
    """
    raiz = _raiz_real(tmp_path)
    if como_nasce == "config íntegro":
        StorageManager(data_dir=str(raiz / "data")).save_config(
            _config_inventado())
    else:
        _semente_local(raiz)
    antes = _fotografia(raiz)

    at = abrir_app(FA_DADOS=raiz)

    assert at.session_state["transactions"] == []
    assert at.session_state["config"].income_sources == []
    assert "MODO DEMONSTRAÇÃO" not in _textos(at)
    assert any("Bem-vindo" in str(i.value) for i in at.info)
    assert not (raiz / "data" / "transactions.json").exists()
    assert _fotografia(raiz) == antes, "abrir em modo real mudou a raiz"


def test_modo_real_com_a_base_cheia_nao_monta_a_demonstracao(abrir_app,
                                                             tmp_path):
    from datetime import datetime

    from src.data.models import Transaction

    raiz = _raiz_real(tmp_path)
    storage = StorageManager(data_dir=str(raiz / "data"))
    storage.save_config(_config_inventado())
    storage.save_transactions([
        Transaction(id="real-%d" % i, date=datetime(2026, 3, 1 + i),
                    value=-(20.0 + i), description="Compra inventada %d" % i,
                    category="Outros", source_account="C6 Bank (conta) 50607080")
        for i in range(4)], create_backup=False)
    antes = _fotografia(raiz)

    at = abrir_app(FA_DADOS=raiz)

    assert sorted(t.id for t in at.session_state["transactions"]) == [
        "real-0", "real-1", "real-2", "real-3"]
    assert at.session_state["config"].income_sources == []
    assert "MODO DEMONSTRAÇÃO" not in _textos(at)
    assert _fotografia(raiz) == antes, "abrir em modo real mudou a raiz"


def test_em_modo_real_os_ultimos_n_dias_contam_do_relogio(abrir_app, tmp_path):
    """
    A data de referência da demonstração (01/11/2026) não vaza para o modo
    real. Duas compras: uma de três dias atrás, pelo relógio; outra de
    28/10/2026, que só cairia em "Últimos 7 dias" se o hoje fosse o da
    demonstração. Em modo real, o filtro mostra só a primeira.
    """
    from datetime import datetime, timedelta

    from src.data.models import Transaction

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    assert hoje - timedelta(days=7) > datetime(2026, 10, 28), (
        "o relógio desta máquina está antes de 05/11/2026: o teste não "
        "separa os dois hojes")
    raiz = _raiz_real(tmp_path)
    storage = StorageManager(data_dir=str(raiz / "data"))
    storage.save_config(_config_inventado())
    storage.save_transactions([
        Transaction(id="recente", date=hoje - timedelta(days=3), value=-30.0,
                    description="Compra inventada recente", category="Outros",
                    source_account="C6 Bank (conta) 50607080"),
        Transaction(id="de-outubro", date=datetime(2026, 10, 28), value=-40.0,
                    description="Compra inventada de outubro",
                    category="Outros",
                    source_account="C6 Bank (conta) 50607080"),
    ], create_backup=False)

    at = abrir_app(FA_DADOS=raiz)
    periodo, = [s for s in at.selectbox if s.label == "Período"]
    periodo.set_value("Últimos 7 dias").run()
    assert not at.exception, [e.value for e in at.exception]

    legendas = [str(c.value) for c in at.caption]
    assert "Mostrando 1-1 de 1 transações" in legendas, legendas
    despesas, = [m for m in at.metric if m.label == "💸 Despesas"]
    assert despesas.value == "R$ 30.00"
