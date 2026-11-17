# -*- coding: utf-8 -*-
"""
Camada de unidade — a importação em duas etapas (`src/importacao.py`).

A função existe para que a sequência de importação tenha um lugar fora da
tela, e desde a sessão 1c é por ela que o `main()` importa. O risco agora é a
orquestração mudar sem ninguém ver. Por isso há duas provas, de naturezas
diferentes, as duas contra a sequência escrita aqui, passo a passo
(`_sequencia_de_referencia`):

- a função, em um lote e arquivo por arquivo;
- o PRÓPRIO BOTÃO: os testes que confirmam pelo botão abrem o app pelo
  `AppTest`, sobem as fixtures pelo `st.file_uploader`, clicam em confirmar e
  comparam a base que o app gravou com a da referência — sobre base vazia e
  sobre base cheia.

Um terceiro teste pelo botão, sem confirmar, fixa o que o bloco de importação
mostra de cada arquivo: aceito, sem movimento, recusado.

Dado: as oito fixtures sintéticas e o pool fictício do código. Nenhum dado
real.
"""

import ast
import io
import json

import pytest

from src.business.categorizer import ReversalMatcher, SmartCategorizer
from src.business.transfer_matcher import TransferMatcher
from src.data.models import AppConfig
from src.data.parser import CSVParser, TransactionDeduplicator
from src.data.storage import StorageManager
from src.importacao import (Confirmacao, confirmar_importacao,
                            preparar_importacao)

from tests.conftest import (C6_JAN, INTER_JAN, NUBANK_VALOR_EM_BRANCO, RAIZ,
                            SINTETICOS)

FIXTURES = sorted(p.name for p in SINTETICOS.glob("*.csv"))


def _arquivos(nomes=None):
    return [(n, (SINTETICOS / n).read_bytes()) for n in (nomes or FIXTURES)]


def _categorizador(config):
    return SmartCategorizer(members=config.members,
                            category_manager=config.get_category_manager())


def _impressao(base):
    """O que identifica cada linha da base, sem o `id` (um uuid novo a cada
    leitura) nem os carimbos de data de criação."""
    return sorted((t.raw_data["filename"], t.raw_data["row_number"],
                   t.date.isoformat(), round(t.value, 2), t.description,
                   t.external_id or "", t.source_account, t.category,
                   t.subcategory or "", round(t.confidence, 6),
                   bool(t.paired_transfer_id))
                  for t in base)


def _sequencia_de_referencia(lotes, config):
    """
    A sequência de importação escrita à mão, passo a passo, sem
    `src/importacao.py`: por lote, ler, categorizar só o que entrou,
    deduplicar contra a base, juntar, parear estornos e conciliar.

    É o caminho independente. Desde a sessão 1c o `main()` importa pela
    função, e comparar o botão com a função provaria só que um chama a outra.
    Contra esta sequência, a comparação acusa se a orquestração mudar: no
    botão, a ordem dos passos e a base que se passa; na função, também o que
    se categoriza, que o teste arquivo por arquivo e
    `test_so_o_que_entrou_e_categorizado` vigiam. Usa os mesmos componentes
    que a função (parser, categorizador, deduplicador, pareamento,
    conciliação): confere a orquestração, não os componentes.
    """
    categorizador = _categorizador(config)
    parser = CSVParser()
    base = []
    for lote in lotes:
        lidas = []
        for nome, dados in lote:
            resultado = parser.parse_file(io.BytesIO(dados), nome)
            if resultado.profile_name and not resultado.errors:
                lidas.extend(resultado.transactions)
        categorizador.categorize_batch(lidas)
        unicas, _ = TransactionDeduplicator.remove_duplicates(lidas, base)
        base.extend(unicas)
        ReversalMatcher.pair_reversals(base)
        TransferMatcher(config).reconcile(base)
    return base


def _importar(lotes, config):
    """Pela função de `src/importacao.py`, lote a lote."""
    categorizador = _categorizador(config)
    base, confirmacoes = [], []
    for lote in lotes:
        preparacao = preparar_importacao(lote, base, categorizador)
        confirmacoes.append(confirmar_importacao(preparacao, base, config))
    return base, confirmacoes


def test_as_oito_fixtures_estao_la():
    assert len(FIXTURES) == 8


# ---------------------------------------------------------------------------
# A função dá a base da sequência de referência
# ---------------------------------------------------------------------------

def test_um_lote_da_a_base_da_sequencia_de_referencia():
    config = AppConfig()
    base, _ = _importar([_arquivos()], config)

    assert len(base) == 30
    assert _impressao(base) == _impressao(
        _sequencia_de_referencia([_arquivos()], AppConfig()))


def test_arquivo_por_arquivo_da_a_mesma_base_que_um_lote():
    um_lote, _ = _importar([_arquivos()], AppConfig())
    um_por_vez, _ = _importar([[a] for a in _arquivos()], AppConfig())

    assert _impressao(um_por_vez) == _impressao(um_lote)
    assert _impressao(um_por_vez) == _impressao(
        _sequencia_de_referencia([[a] for a in _arquivos()], AppConfig()))


# ---------------------------------------------------------------------------
# preparar
# ---------------------------------------------------------------------------

def test_preparar_devolve_o_que_o_preview_mostra_e_nao_toca_na_base():
    config = AppConfig()
    base, _ = _importar([_arquivos([C6_JAN])], config)
    antes = _impressao(base)
    ids_antes = [t.id for t in base]

    preparacao = preparar_importacao(_arquivos(), base, _categorizador(config))

    assert [t.id for t in base] == ids_antes, "preparar juntou algo à base"
    assert _impressao(base) == antes, "preparar mexeu no que já estava na base"

    assert [a.nome for a in preparacao.arquivos] == FIXTURES
    assert all(a.aceito for a in preparacao.arquivos)
    assert {a.conta for a in preparacao.arquivos} == {
        "Nubank (conta) 99887766", "C6 Bank (conta) 12345678",
        "Inter (conta) 87654321"}
    assert sum(a.transacoes for a in preparacao.arquivos) == 34
    # As 3 do C6 de janeiro já estavam na base; 4 se repetem entre arquivos.
    assert preparacao.duplicatas == 7
    assert len(preparacao.novas) == 27
    assert all(t.category for t in preparacao.novas)
    assert any(t.confidence > 0 for t in preparacao.novas), (
        "o que entrou não foi categorizado")

    avisos = "\n".join(preparacao.avisos)
    assert f"[{C6_JAN}] Linha 3: Valor zero" in avisos
    assert f"[{NUBANK_VALOR_EM_BRANCO}] Linha 2: Valor ausente" in avisos
    assert preparacao.erros == []


def test_arquivo_com_erro_nao_entra_e_fica_registrado():
    config = AppConfig()
    limpa = preparar_importacao(_arquivos(), [], _categorizador(config))
    com_lixo = preparar_importacao(
        _arquivos() + [("vazio.csv", b""),
                       ("sem_tabela.csv", b"isto nao e um extrato\n")],
        [], _categorizador(config))

    assert _impressao(com_lixo.novas) == _impressao(limpa.novas)
    recusados = [a for a in com_lixo.arquivos if not a.aceito]
    assert [a.nome for a in recusados] == ["vazio.csv", "sem_tabela.csv"]
    assert all(a.erros and a.transacoes == 0 for a in recusados)
    assert len(com_lixo.erros) == 2
    assert com_lixo.erros[0].startswith("[vazio.csv] ")


def test_extrato_sem_movimento_e_aceito_e_nao_traz_transacao():
    """Extrato válido de um mês parado: o `main()` o lista como
    "sem movimentações", e não como erro."""
    nome = "NU_99887766_01MAR2026_31MAR2026.csv"
    cabecalho = "Data,Valor,Identificador,Descrição\n".encode("utf-8")

    preparacao = preparar_importacao([(nome, cabecalho)], [],
                                     _categorizador(AppConfig()))

    registro, = preparacao.arquivos
    assert registro.aceito
    assert registro.conta == "Nubank (conta) 99887766"
    assert registro.transacoes == 0
    assert preparacao.novas == [] and preparacao.duplicatas == 0


def test_importar_de_novo_nao_acrescenta_nada():
    config = AppConfig()
    base, _ = _importar([_arquivos()], config)

    de_novo = preparar_importacao(_arquivos(), base, _categorizador(config))

    assert de_novo.novas == []
    assert de_novo.duplicatas == 34
    confirmacao = confirmar_importacao(de_novo, base, config)
    assert confirmacao == Confirmacao(importadas=0, neutralizadas_por_estorno=0,
                                      pares_novos=0, demovidas=0)
    assert len(base) == 30


# ---------------------------------------------------------------------------
# confirmar
# ---------------------------------------------------------------------------

def test_confirmar_junta_pareia_estornos_e_concilia():
    config = AppConfig()
    base = []
    preparacao = preparar_importacao(_arquivos(), base, _categorizador(config))

    confirmacao = confirmar_importacao(preparacao, base, config)

    # Uma neutralizada: a compra. A linha do estorno já chega em "Estorno"
    # pela categorização; quem leva a compra junto é o pareamento.
    assert confirmacao == Confirmacao(importadas=30, neutralizadas_por_estorno=1,
                                      pares_novos=1, demovidas=0)
    assert len(base) == 30
    estornos = [t for t in base if t.category == "Estorno"]
    assert len(estornos) == 2
    assert estornos[0].external_id == estornos[1].external_id
    assert round(sum(t.value for t in estornos), 2) == 0.0

    internas = [t for t in base if t.category == "Transferência Interna"]
    assert len(internas) == 2
    assert internas[0].paired_transfer_id == internas[1].id
    assert internas[1].paired_transfer_id == internas[0].id
    assert internas[0].source_account != internas[1].source_account


def test_confirmar_olha_a_base_inteira_e_nao_so_o_que_entrou():
    """
    A contraparte pode chegar numa importação posterior. A perna do C6 entra
    sozinha e fica pendente; quando o extrato do Inter chega, é a perna que
    JÁ ESTAVA na base que vira "Transferência Interna".
    """
    config = AppConfig()
    base, _ = _importar([_arquivos([C6_JAN])], config)
    perna, = [t for t in base if "Bruno Quintela" in t.description]
    assert perna.category == "Transferências" and not perna.paired_transfer_id

    preparacao = preparar_importacao(_arquivos([INTER_JAN]), base,
                                     _categorizador(config))
    confirmacao = confirmar_importacao(preparacao, base, config)

    assert confirmacao.pares_novos == 1
    assert perna.category == "Transferência Interna"
    assert perna.paired_transfer_id


def test_o_estorno_que_chega_depois_neutraliza_a_compra_que_ja_estava():
    config = AppConfig()
    cabecalho = "Data,Valor,Identificador,Descrição\n"
    compra = (cabecalho + "07/01/2026,-88.00,abcd0000-0000-0000-0000-000000000001,"
              "Compra no débito - RESTAURANTE VALE VERDE\n").encode("utf-8")
    estorno = (cabecalho + "09/01/2026,88.00,abcd0000-0000-0000-0000-000000000001,"
               "Estorno - Compra no débito - RESTAURANTE VALE VERDE\n").encode("utf-8")

    base, primeira = _importar(
        [[("NU_99887766_01JAN2026_08JAN2026.csv", compra)]], config)
    assert base[0].category == "Alimentação"
    assert primeira[0].neutralizadas_por_estorno == 0

    preparacao = preparar_importacao(
        [("NU_99887766_09JAN2026_15JAN2026.csv", estorno)], base,
        _categorizador(config))
    confirmacao = confirmar_importacao(preparacao, base, config)

    assert confirmacao.neutralizadas_por_estorno == 1
    assert [t.category for t in base] == ["Estorno", "Estorno"]


def test_so_o_que_entrou_e_categorizado():
    """
    A armadilha do `categorize_batch` sobre a base inteira: ele devolveria a
    "Transferências" as duas pernas já conciliadas, e a conciliação seguinte
    não as promove de novo, porque respeita o par existente.
    """
    config = AppConfig()
    base, _ = _importar([_arquivos([C6_JAN, INTER_JAN])], config)
    par = [t for t in base if t.paired_transfer_id]
    assert len(par) == 2

    preparacao = preparar_importacao(_arquivos([NUBANK_VALOR_EM_BRANCO]), base,
                                     _categorizador(config))
    confirmar_importacao(preparacao, base, config)

    assert all(t.category == "Transferência Interna" for t in par)
    assert all(t.paired_transfer_id for t in par)


# ---------------------------------------------------------------------------
# O módulo fica fora da tela
# ---------------------------------------------------------------------------

def test_o_modulo_nao_importa_a_interface():
    fonte = (RAIZ / "src" / "importacao.py").read_text(encoding="utf-8")
    importados = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            importados |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
    assert not [m for m in importados if m.split(".")[0] == "streamlit"]
    assert not [m for m in importados if m.split(".")[0] == "app"]


# ---------------------------------------------------------------------------
# Contra o próprio botão
# ---------------------------------------------------------------------------

# Arquivos inventados para o que as fixtures não têm. O extrato sem movimento
# é só o cabeçalho do Nubank, como no teste da função acima.
SEM_MOVIMENTO = ("NU_99887766_01MAR2026_31MAR2026.csv",
                 "Data,Valor,Identificador,Descrição\n".encode("utf-8"))
SEM_TABELA = ("sem_tabela.csv", b"isto nao e um extrato\n")
# Perfil e erro ao mesmo tempo: o CSV genérico acha a tabela, mas, sem coluna
# de descrição, não monta linha nenhuma.
SO_DATA_E_VALOR = ("so_data_e_valor.csv", b"Data,Valor\n05/01/2026,10.00\n")


@pytest.fixture
def app_sobre_raiz_inventada(tmp_path, monkeypatch):
    """
    O app em modo real sobre uma raiz inventada, com o pool fictício gravado
    no `config.json`. Modo real de propósito: a base de partida não pode
    depender do conteúdo da demonstração.

    Devolve `abrir(lotes=())`. A base de partida é a da sequência de
    referência sobre `lotes` — vazia por padrão —, gravada pelo
    `StorageManager` antes de o app abrir, como fica a base do dono entre uma
    sessão e outra. `abrir` confere que o app abriu essa raiz com essa base, e
    devolve o `AppTest` e a pasta `data/`.
    """
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    def abrir(lotes=()):
        raiz = tmp_path / "dado"
        dados = raiz / "data"
        dados.mkdir(parents=True)
        storage = StorageManager(data_dir=str(dados))
        storage.save_config(AppConfig())
        partida = _sequencia_de_referencia(lotes, AppConfig())
        if partida:
            storage.save_transactions(partida)

        st.cache_resource.clear()
        monkeypatch.delenv("FA_DEMO", raising=False)
        monkeypatch.setenv("FA_DADOS", str(raiz))

        at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=300)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["pasta_dos_dados"] == str(dados), (
            "o app não abriu a raiz inventada deste teste")
        assert (_impressao(at.session_state["transactions"])
                == _impressao(partida)), (
            "o app não abriu com a base de partida deste teste")
        return at, dados

    yield abrir
    st.cache_resource.clear()


def _subir(at, arquivos):
    at.file_uploader[0].set_value(
        [(nome, conteudo, "text/csv") for nome, conteudo in arquivos]).run()
    assert not at.exception, [e.value for e in at.exception]


def _confirmar(at):
    confirmar, = [b for b in at.button if "Confirmar Importação" in str(b.label)]
    confirmar.click().run()
    assert not at.exception, [e.value for e in at.exception]


def _bloco_de_importacao(at):
    """
    O que o bloco de importação desenhou, na ordem da tela: os elementos da
    área principal entre o uploader e o que vem depois do bloco — o divisor
    das análises ou, com a base vazia, o "Bem-vindo". Cada elemento vira uma
    tupla curta: a tabela leva o número de linhas; o expander, o rótulo e os
    textos; as colunas, os rótulos dos botões. Os alertas saem sem o ícone,
    que o Streamlit separa do texto.
    """
    from streamlit.testing.v1.element_tree import Block

    filhos = [at.main.children[i] for i in sorted(at.main.children)]
    uploader = next(i for i, no in enumerate(filhos)
                    if no.type == "file_uploader")
    tela = []
    for no in filhos[uploader + 1:]:
        if no.type in ("divider", "info"):
            break
        if no.type == "expander":
            tela.append(("expander", no.label, [t.value for t in no.text]))
        elif isinstance(no, Block):
            tela.append(("botoes", [b.label for b in no.button]))
        elif no.type == "dataframe":
            tela.append(("tabela", len(no.value)))
        else:
            tela.append((no.type, no.value))
    return tela


def _preview(at):
    """O cabeçalho do preview e o aviso das duplicatas, se houver."""
    return tuple(valor for tipo, valor, *_ in _bloco_de_importacao(at)
                 if tipo in ("subheader", "warning"))


def _relida(dados):
    """A base como o app a gravou: relida do `transactions.json`."""
    return StorageManager(data_dir=str(dados),
                          somente_leitura=True).load_transactions()


def _gravado(dados):
    return json.loads((dados / "transactions.json").read_text(encoding="utf-8"))


def test_o_botao_sobre_base_vazia_da_a_base_da_sequencia_de_referencia(
        app_sobre_raiz_inventada):
    at, dados = app_sobre_raiz_inventada()

    _subir(at, _arquivos())
    assert _preview(at) == ("📊 Preview: 30 novas transações",
                            "4 duplicatas detectadas e removidas")
    assert at.session_state["transactions"] == [], (
        "o preview não pode mexer na base")

    _confirmar(at)

    referencia = _impressao(
        _sequencia_de_referencia([_arquivos()], AppConfig()))
    assert len(referencia) == 30
    assert _impressao(at.session_state["transactions"]) == referencia
    assert _impressao(_relida(dados)) == referencia, (
        "o JSON gravado não é a base da referência")
    assert _gravado(dados)["total_transactions"] == 30


def test_o_botao_sobre_base_cheia_deduplica_contra_a_base_aberta(
        app_sobre_raiz_inventada):
    """
    O caminho do dono: o app abre com base, e sobe extrato que se sobrepõe a
    ela. A base de partida é o C6 de janeiro, gravada antes de o app abrir. A
    perna de transferência dele está pendente e forma par com a do Inter de
    janeiro, que chega com as oito.
    """
    ja_na_base = _arquivos([C6_JAN])
    at, dados = app_sobre_raiz_inventada([ja_na_base])

    # Só o que já está na base: zero novas, e o preview aparece assim mesmo.
    _subir(at, ja_na_base)
    assert _preview(at) == ("📊 Preview: 0 novas transações",
                            "3 duplicatas detectadas e removidas")

    # As oito, o C6 de janeiro entre elas: 3 duplicatas vêm da base, 4 se
    # repetem entre os arquivos.
    _subir(at, _arquivos())
    assert _preview(at) == ("📊 Preview: 27 novas transações",
                            "7 duplicatas detectadas e removidas")
    assert len(at.session_state["transactions"]) == 3, (
        "o preview não pode mexer na base")

    _confirmar(at)

    referencia = _impressao(
        _sequencia_de_referencia([ja_na_base, _arquivos()], AppConfig()))
    assert len(referencia) == 30
    assert _impressao(at.session_state["transactions"]) == referencia
    assert _impressao(_relida(dados)) == referencia, (
        "o JSON gravado não é a base da referência")
    assert _gravado(dados)["total_transactions"] == 30


def test_o_botao_mostra_de_cada_arquivo_so_o_que_a_preparacao_aceitou(
        app_sobre_raiz_inventada):
    """
    O que o `main()` lê da preparação — `aceito`, `transacoes`, `avisos` e
    `erros` —, em quatro uploads seguidos, sem confirmar. Cada um pega uma
    condição que parece equivalente à de hoje e não é.
    """
    at, dados = app_sobre_raiz_inventada()
    parado = SEM_MOVIMENTO[0]
    linha_do_parado = (f"🏦 **{parado}** → Nubank (conta) 99887766"
                       f" *(sem movimentações)*")
    erros_do_sem_tabela = [
        ("error", "Erros encontrados:"),
        ("text", "[sem_tabela.csv] Não foi possível localizar a tabela de "
                 "transações (formato tentado: CSV genérico). Verifique se o "
                 "arquivo contém colunas de data, valor e descrição.")]

    # 1. Com movimento, sem movimento e recusado, juntos: o aviso do parado
    #    entra no expander, e o erro sai abaixo dos botões.
    _subir(at, _arquivos([C6_JAN]) + [SEM_MOVIMENTO, SEM_TABELA])
    assert _bloco_de_importacao(at) == [
        ("markdown", f"🏦 **{C6_JAN}** → C6 Bank (conta) 12345678"),
        ("markdown", linha_do_parado),
        ("subheader", "📊 Preview: 3 novas transações"),
        ("tabela", 3),
        ("expander", "⚠️ 2 avisos (com motivo)", [
            f"[{C6_JAN}] Linha 3: Valor zero (ignorada)",
            f"[{parado}] Extrato sem movimentações no período"]),
        ("botoes", ["✅ Confirmar Importação", "❌ Cancelar"]),
    ] + erros_do_sem_tabela

    # 2. O sem movimento sozinho: a linha dele e nada mais — sem preview e,
    #    portanto, sem o aviso. Abrir o preview por "algum arquivo aceito"
    #    o mostraria.
    _subir(at, [SEM_MOVIMENTO])
    assert _bloco_de_importacao(at) == [("markdown", linha_do_parado)]

    # 3. O recusado sozinho: só o erro. Abrir o preview por "algum arquivo"
    #    o mostraria.
    _subir(at, [SEM_TABELA])
    assert _bloco_de_importacao(at) == erros_do_sem_tabela

    # 4. Perfil e erro ao mesmo tempo: sem linha 🏦. Escolher a linha pelo
    #    perfil ou pela conta, e não por `aceito`, a mostraria.
    _subir(at, [SO_DATA_E_VALOR])
    assert _bloco_de_importacao(at) == [
        ("error", "Erros encontrados:"),
        ("text", "[so_data_e_valor.csv] Formato 'CSV genérico' detectado, "
                 "mas as colunas obrigatórias não foram mapeadas.")]

    assert at.session_state["transactions"] == []
    assert not (dados / "transactions.json").exists()
