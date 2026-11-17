# -*- coding: utf-8 -*-
"""
O gerador do conjunto de demonstração (`demonstracao/gerar.py`).

O conjunto versionado tem de ser, byte a byte, o que o gerador produz — é
isso que permite conferir cada extrato lendo o gerador, em vez de ler 800
linhas de CSV. E o gerador tem de se recusar a escrever um conjunto que não
cumpra o perfil que declara.
"""

import ast
import re
import sys

import pytest

from demonstracao import gerar as gerador
from src import demonstracao as demo

FORMA_DE_ARQUIVO_DO_INTER = re.compile(
    r"^Extrato-\d{2}-\d{2}-\d{4}-a-\d{2}-\d{2}-\d{4}-CSV\.csv$", re.IGNORECASE)
FORMA_DE_ARQUIVO_DO_C6 = re.compile(r"^[0-9A-Z]{26}\.csv$", re.IGNORECASE)
FORMA_DE_ARQUIVO_DO_NUBANK = re.compile(
    r"^NU_(\d+)_\d{2}[A-Z]{3}\d{4}_\d{2}[A-Z]{3}\d{4}\.csv$")


@pytest.fixture(scope="module")
def saida():
    return gerador.gerar()


def _extratos(saida):
    return {rel.split("/", 1)[1]: conteudo for rel, conteudo in saida.items()
            if rel.startswith(gerador.PASTA_EXTRATOS + "/")}


# ---------------------------------------------------------------------------
# O conjunto se refaz
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_gerar_de_novo_da_os_mesmos_bytes(saida):
    assert gerador.gerar() == saida


@pytest.mark.invariante
def test_o_que_esta_versionado_e_o_que_o_gerador_produz(saida):
    assert gerador.diferencas(demo.PASTA, saida) == [], (
        "o conjunto versionado difere do que o gerador produz: rode "
        "demonstracao/gerar.py e recalibre os testes amarrados a arquivo")
    na_pasta = {p.relative_to(demo.PASTA).as_posix()
                for p in demo.PASTA.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts}
    assert na_pasta == set(saida) | {"gerar.py"}


@pytest.mark.invariante
def test_o_gerador_so_usa_a_biblioteca_padrao():
    """Nada de `src/` nem de terceiros: quem confere o conjunto contra o
    produto são os testes, e os bytes não podem depender de versão de
    pandas."""
    fonte = (demo.PASTA / "gerar.py").read_text(encoding="utf-8")
    importados = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            importados |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            importados.add((no.module or "").split(".")[0])
    de_fora = sorted(m for m in importados
                     if m not in sys.stdlib_module_names)
    assert de_fora == []


@pytest.mark.invariante
def test_o_sorteio_so_usa_random_random():
    """`random()` é o único método cuja sequência o Python garante entre
    versões para a mesma semente. `randint`, `choice`, `shuffle` e os outros
    podem mudar — e mudariam os bytes do conjunto sem ninguém mexer nele."""
    fonte = (demo.PASTA / "gerar.py").read_text(encoding="utf-8")
    usados = set(re.findall(r"_gerador\.(\w+)\(", fonte))
    assert usados == {"random"}


# ---------------------------------------------------------------------------
# A forma dos arquivos
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_cada_extrato_tem_os_bytes_do_seu_banco(saida):
    for nome, conteudo in _extratos(saida).items():
        if nome.startswith("C6_"):
            assert conteudo.startswith(b"\xef\xbb\xbf"), nome
            assert conteudo.count(b"\r\n") == conteudo.count(b"\n") > 0, nome
        else:
            assert not conteudo.startswith(b"\xef\xbb\xbf"), nome
            assert b"\r" not in conteudo, nome
        conteudo.decode("utf-8-sig")


@pytest.mark.invariante
def test_nenhum_nome_de_arquivo_tem_a_forma_de_um_extrato_de_verdade(saida):
    """
    Decisão do dono: nome de arquivo da demonstração não pode coincidir com
    extrato real, nem com um que ele venha a baixar. Inter e C6 levam nome
    próprio, com a conta fictícia, e não a forma que o banco dá. O Nubank
    não tem escolha — a conta só existe no nome —, e o que o separa de um
    extrato real é o número da conta, que é do pool fictício.
    """
    contas = {c.numero for c in gerador.CONTAS}
    for nome in _extratos(saida):
        assert not FORMA_DE_ARQUIVO_DO_INTER.match(nome), nome
        assert not FORMA_DE_ARQUIVO_DO_C6.match(nome), nome
        banco, conta = nome.split("_")[:2]
        assert banco in ("NU", "C6", "INTER") and conta in contas, nome
        if banco == "NU":
            assert FORMA_DE_ARQUIVO_DO_NUBANK.match(nome), nome


@pytest.mark.invariante
def test_as_contas_do_conjunto_sao_do_pool_ficticio(saida):
    from src.data.models import AppConfig
    cadastradas = {a.label for a in AppConfig().accounts}
    com_extrato = {c.rotulo for c in gerador.CONTAS}
    assert com_extrato < cadastradas
    assert {gerador.ANA, gerador.BRUNO} == {m.name for m in AppConfig().members}
    assert sorted(gerador.APELIDOS) == sorted(
        a for m in AppConfig().members for a in m.aliases)


# ---------------------------------------------------------------------------
# O gerador se recusa a escrever um conjunto que não cumpre o perfil
# ---------------------------------------------------------------------------

@pytest.mark.invariante
def test_perfil_que_nao_fecha_nao_gera(monkeypatch):
    """Sem os fatos de cada mês — as despesas grandes, os aportes, as pernas
    soltas, os estornos — o perfil declarado não se cumpre."""
    monkeypatch.setattr(gerador, "_fatos_do_mes", lambda *_: None)
    with pytest.raises(gerador.PerfilNaoFecha,
                       match="meses de saldo negativo") as erro:
        gerador.gerar()
    assert "pernas soltas de outras origens" in str(erro.value)
    assert "estornos pareados" in str(erro.value)


@pytest.mark.invariante
def test_terceiro_que_seria_lido_como_membro_nao_gera(monkeypatch):
    """
    O casamento de apelido é por trecho, sem fronteira de palavra: "Mariana
    Quintela" contém "ana quintela". O gerador tem de pegar isso antes de o
    nome chegar a um extrato.
    """
    monkeypatch.setattr(gerador, "DIARISTA", "Mariana Quintela Ramos")
    with pytest.raises(gerador.PerfilNaoFecha, match="menção a membro"):
        gerador.gerar()


@pytest.mark.invariante
def test_perna_solta_que_parearia_por_acidente_nao_gera(monkeypatch):
    """Um aporte na empresa com o valor e o dia de outra perna do pool viraria
    par no produto, e sumiria das pendências."""
    original = gerador._fatos_do_mes

    def com_coincidencia(livro, ano, mes, d):
        original(livro, ano, mes, d)
        if (ano, mes) == (2026, 4):
            # Mesmo dia e mesmo valor da transferência mensal para o Inter,
            # saindo de outra conta: as duas pernas se achariam.
            livro.perna_solta(gerador.C6_ANA, d(6), 130_000,
                              gerador.NOME_COMPLETO[gerador.ANA],
                              gerador.INTER_ANA_SEM_EXTRATO)

    monkeypatch.setattr(gerador, "_fatos_do_mes", com_coincidencia)
    with pytest.raises(gerador.PerfilNaoFecha, match="par"):
        gerador.gerar()
