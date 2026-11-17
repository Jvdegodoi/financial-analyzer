# -*- coding: utf-8 -*-
"""
A montagem da demonstração (`src/demonstracao.py`).

O que se afirma:

- monta numa pasta vazia e grava transações, configuração e aprendizado;
- recusa pasta que já tenha base, sem tocar nela;
- a lista de atribuições casa por inteiro, e qualquer desencontro DERRUBA a
  montagem antes de a primeira linha ir ao disco. Cada sabotagem abaixo é
  feita numa cópia do conjunto em `tmp_path`; o conjunto versionado nunca é
  editado por teste.
"""

import ast
import copy
import json
from datetime import timedelta

import pytest

from src import demonstracao as demo
from src.data.models import AppConfig, TransactionType
from src.data.storage import StorageManager

from tests.conftest import RAIZ


def _arquivos_de(pasta):
    return {p.relative_to(pasta).as_posix(): p.read_bytes()
            for p in pasta.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# O caminho feliz
# ---------------------------------------------------------------------------

@pytest.mark.amarrado_a_arquivo
def test_montar_grava_a_base_a_configuracao_e_o_aprendizado(montada):
    gravadas = json.loads((montada.pasta / "transactions.json").read_text(
        encoding="utf-8"))
    config = json.loads((montada.pasta / "config.json").read_text(
        encoding="utf-8"))

    assert gravadas["total_transactions"] == 776
    assert [m["name"] for m in config["members"]] == ["Ana Quintela",
                                                       "Bruno Quintela"]
    assert len(config["accounts"]) == 6
    assert [f["name"] for f in config["income_sources"]] == [
        "Salário", "Pró-labore", "Serviços avulsos", "Aulas particulares",
        "Rendimentos"]
    assert json.loads((montada.pasta / "learning_data.json").read_text(
        encoding="utf-8")) == {}
    assert not list((montada.pasta / "backups").iterdir()), (
        "a montagem não tem base anterior de que fazer backup")


@pytest.mark.invariante
def test_montar_duas_vezes_da_a_mesma_base(montada, montada_para_mexer):
    def impressao(base):
        return sorted((t.raw_data["filename"], t.raw_data["row_number"],
                       t.date.isoformat(), t.value, t.description, t.category,
                       t.subcategory or "", t.income_source or "",
                       bool(t.paired_transfer_id)) for t in base)

    assert impressao(montada.base) == impressao(montada_para_mexer.base)


@pytest.mark.invariante
def test_o_modulo_nao_importa_a_interface_nem_o_ambiente():
    """Quem decide que é demonstração é o `app.py`. A montagem só sabe
    montar na pasta que recebe."""
    fonte = (RAIZ / "src" / "demonstracao.py").read_text(encoding="utf-8")
    importados = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            importados |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
    assert not [m for m in importados if m.split(".")[0] in ("streamlit", "app")]
    assert "src.ambiente" not in importados


@pytest.mark.invariante
def test_a_pasta_do_conjunto_nao_depende_da_raiz_que_a_suite_esconde():
    """`tests/conftest.py` troca `ambiente.RAIZ_PROJETO` por uma pasta vazia
    em todo teste; o conjunto tem de ser achado mesmo assim."""
    from src import ambiente
    assert ambiente.RAIZ_PROJETO != RAIZ
    assert demo.PASTA == RAIZ / "demonstracao"
    assert (demo.PASTA / demo.ARQUIVO_CONJUNTO).is_file()


# ---------------------------------------------------------------------------
# Só monta em pasta sem base
# ---------------------------------------------------------------------------

@pytest.mark.invariante
@pytest.mark.parametrize("o_que_ja_existe", ["config", "transacoes"])
def test_pasta_que_ja_tem_base_e_recusada_e_fica_como_estava(tmp_path,
                                                             o_que_ja_existe):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    if o_que_ja_existe == "config":
        storage.save_config(AppConfig())
    else:
        storage.save_transactions([], create_backup=False)
    antes = _arquivos_de(tmp_path)

    with pytest.raises(demo.MontagemRecusada, match="já tem uma base"):
        demo.montar(storage)

    assert _arquivos_de(tmp_path) == antes


# ---------------------------------------------------------------------------
# A lista de atribuições casa por inteiro — ou a montagem para
# ---------------------------------------------------------------------------

def _uma_despesa(montada):
    return next(t for t in montada.base
                if t.type == TransactionType.DESPESA and not t.is_neutral)


def _apontar_para(item, transacao):
    item["arquivo"] = transacao.raw_data["filename"]
    item["linha"] = transacao.raw_data["row_number"]
    item["data"] = transacao.date.date().isoformat()
    item["valor"] = f"{transacao.value:.2f}"


SABOTAGENS = {
    "linha que não existe": (
        lambda d, m: d["atribuicoes"][0].update(linha=9999),
        "não achou a sua linha"),
    "arquivo que não existe": (
        lambda d, m: d["atribuicoes"][0].update(arquivo="NU_0_nada.csv"),
        "não achou a sua linha"),
    "duas atribuições para a mesma linha": (
        lambda d, m: d["atribuicoes"].append(dict(d["atribuicoes"][0])),
        "mais de uma atribuição para a mesma linha"),
    "fonte que não existe": (
        lambda d, m: d["atribuicoes"][0].update(fonte="Herança"),
        "não está entre as fontes de renda"),
    "valor que não confere": (
        lambda d, m: d["atribuicoes"][0].update(valor="1.00"),
        "declara o valor 1.00"),
    "data que não confere": (
        lambda d, m: d["atribuicoes"][0].update(data="2020-01-01"),
        "declara a data 2020-01-01"),
    "atribuição numa despesa": (
        lambda d, m: _apontar_para(d["atribuicoes"][0], _uma_despesa(m)),
        "não é uma receita"),
    "uma atribuição a menos": (
        lambda d, m: d["atribuicoes"].pop(),
        "declara 8 receitas sem fonte e a base montada tem 9"),
    "contagem de receitas sem fonte errada": (
        lambda d, m: d.update(receitas_sem_fonte=7),
        "declara 7 receitas sem fonte e a base montada tem 8"),
}


@pytest.mark.invariante
@pytest.mark.parametrize("nome", list(SABOTAGENS))
def test_atribuicao_que_nao_casa_derruba_a_montagem(nome, montada,
                                                    copia_do_conjunto, tmp_path):
    pasta, reescrever = copia_do_conjunto
    mexer, mensagem = SABOTAGENS[nome]
    reescrever(lambda dados: mexer(dados, montada))
    storage = StorageManager(data_dir=str(tmp_path / "data"))

    with pytest.raises(demo.ConjuntoInvalido, match=mensagem):
        demo.montar(storage, pasta=pasta)

    assert not storage.data_file.exists(), "gravou transações antes de parar"
    assert not storage.config_file.exists(), "gravou configuração antes de parar"


@pytest.mark.invariante
def test_a_copia_sem_sabotagem_monta(copia_do_conjunto, tmp_path):
    """O controle das sabotagens acima: a mesma cópia, intacta, monta."""
    pasta, _ = copia_do_conjunto
    storage = StorageManager(data_dir=str(tmp_path / "data"))

    montagem = demo.montar(storage, pasta=pasta)

    assert montagem.atribuidas == len(demo.carregar_conjunto(pasta).atribuicoes)
    assert storage.data_file.exists()


@pytest.mark.invariante
def test_linha_que_aparece_duas_vezes_na_base_e_recusada(montada_para_mexer):
    """A atribuição tem de achar EXATAMENTE uma linha."""
    base = montada_para_mexer.base
    for t in base:
        t.income_source = None
    apontada = montada_para_mexer.conjunto.atribuicoes[0]
    original = next(t for t in base
                    if (t.raw_data["filename"], t.raw_data["row_number"])
                    == (apontada["arquivo"], apontada["linha"]))
    base.append(copy.deepcopy(original))

    with pytest.raises(demo.ConjuntoInvalido, match="achou 2 linhas"):
        demo.aplicar_atribuicoes(base, montada_para_mexer.conjunto)

    assert not any(t.income_source for t in base), (
        "atribuiu parte da lista antes de parar")


# ---------------------------------------------------------------------------
# Os extratos da pasta são os do conjunto, inteiros
# ---------------------------------------------------------------------------

def _um_extrato_a_mais(pasta):
    origem = sorted((pasta / demo.PASTA_EXTRATOS).glob("NU_*.csv"))[0]
    (pasta / demo.PASTA_EXTRATOS / "NU_99887766_01NOV2026_30NOV2026.csv"
     ).write_bytes(origem.read_bytes())


def _um_extrato_a_menos(pasta):
    sorted((pasta / demo.PASTA_EXTRATOS).glob("C6_*.csv"))[0].unlink()


def _um_extrato_sem_a_ultima_linha(pasta):
    alvo = sorted((pasta / demo.PASTA_EXTRATOS).glob("NU_55667788_*.csv"))[0]
    linhas = alvo.read_bytes().split(b"\n")
    alvo.write_bytes(b"\n".join(linhas[:-2]) + b"\n")


def _um_extrato_que_nao_e_extrato(pasta):
    sorted((pasta / demo.PASTA_EXTRATOS).glob("INTER_*.csv"))[0].write_bytes(
        b"isto nao e um extrato\n")


@pytest.mark.invariante
@pytest.mark.parametrize("estragar, mensagem", [
    (_um_extrato_a_mais, "sobram"),
    (_um_extrato_a_menos, "faltam"),
    (_um_extrato_sem_a_ultima_linha, "não leu todas as linhas"),
    (_um_extrato_que_nao_e_extrato, "recusado pelo parser"),
], ids=["a mais", "a menos", "truncado", "ilegível"])
def test_extrato_fora_do_conjunto_derruba_a_montagem(estragar, mensagem,
                                                     copia_do_conjunto, tmp_path):
    pasta, _ = copia_do_conjunto
    estragar(pasta)
    storage = StorageManager(data_dir=str(tmp_path / "data"))

    with pytest.raises(demo.ConjuntoInvalido, match=mensagem):
        demo.montar(storage, pasta=pasta)

    assert not storage.data_file.exists()


# ---------------------------------------------------------------------------
# O conjunto.json
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_conjunto_ilegivel_ou_incompleto_e_recusado_com_mensagem(
        copia_do_conjunto):
    pasta, reescrever = copia_do_conjunto

    reescrever(lambda d: d.pop("data_de_referencia"))
    with pytest.raises(demo.ConjuntoInvalido, match="incompleto ou malformado"):
        demo.carregar_conjunto(pasta)

    (pasta / demo.ARQUIVO_CONJUNTO).write_text("{isto não é json",
                                               encoding="utf-8")
    with pytest.raises(demo.ConjuntoInvalido, match="não é JSON válido"):
        demo.carregar_conjunto(pasta)

    (pasta / demo.ARQUIVO_CONJUNTO).unlink()
    with pytest.raises(demo.ConjuntoInvalido, match="não consegui ler"):
        demo.carregar_conjunto(pasta)


@pytest.mark.invariante
def test_data_de_referencia_antes_do_fim_do_periodo_e_recusada(
        copia_do_conjunto):
    pasta, reescrever = copia_do_conjunto
    reescrever(lambda d: d.update(data_de_referencia=d["periodo"][1]))

    with pytest.raises(demo.ConjuntoInvalido, match="depois do período"):
        demo.carregar_conjunto(pasta)


@pytest.mark.invariante
def test_a_data_de_referencia_e_fixa_e_nao_sai_da_base(montada_para_mexer):
    """
    Decisão do dono: a data é declarada junto do conjunto, e não recalculada
    da base aberta. Um lançamento mais novo na base não a move.
    """
    antes = demo.data_de_referencia()
    mais_nova = copy.deepcopy(montada_para_mexer.base[0])
    mais_nova.date = antes + timedelta(days=40)
    montada_para_mexer.base.append(mais_nova)

    assert demo.data_de_referencia() == antes
    assert antes == montada_para_mexer.conjunto.data_de_referencia
