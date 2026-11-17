# -*- coding: utf-8 -*-
"""
Camada de unidade — `src/ambiente.py`, o único lugar que diz onde está o dado.

Todo teste passa o ambiente e a pasta do projeto explicitamente: nenhum lê
`os.environ` nem o `fa.local.ini` desta máquina. É o que deixa a camada rodar
igual em qualquer computador.
"""

import json

import pytest

from src.ambiente import (ARQUIVO_INI, ConfiguracaoInvalida, MODO_DEMO,
                          MODO_REAL, PASTAS, carregar_nao_membros,
                          carregar_semente, resolver)


@pytest.fixture
def projeto(tmp_path):
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    return pasta


def _ini(projeto, texto, encoding="utf-8"):
    (projeto / ARQUIVO_INI).write_text(texto, encoding=encoding)


def _raiz_com_data(tmp_path, nome="dado"):
    raiz = tmp_path / nome
    (raiz / "data").mkdir(parents=True)
    return raiz


def _listagem(pasta):
    return sorted(str(p.relative_to(pasta)) for p in pasta.rglob("*"))


# ---------------------------------------------------------------------------
# A ordem de decisão
# ---------------------------------------------------------------------------

def test_sem_nada_e_demonstracao_e_nenhuma_pasta_aponta_para_dado(projeto):
    amb = resolver(env={}, raiz_projeto=projeto)

    assert amb.modo == MODO_DEMO
    assert amb.origem == "padrão"
    assert all(amb.pasta(p) is None for p in PASTAS)
    assert amb.dados_do_app is None
    assert amb.arquivo_semente is None
    assert amb.arquivo_nao_membros is None
    assert amb.problema() is None


def test_fa_dados_e_dado_real_com_a_forma_da_raiz(projeto, tmp_path):
    raiz = _raiz_com_data(tmp_path)
    amb = resolver(env={"FA_DADOS": str(raiz)}, raiz_projeto=projeto)

    assert amb.modo == MODO_REAL
    assert amb.origem == "FA_DADOS"
    assert amb.raiz == raiz.resolve()
    assert amb.pasta("data") == raiz.resolve() / "data"
    assert amb.pasta("extratos-referencia") == (
        raiz.resolve() / "extratos-referencia")
    assert amb.dados_do_app == raiz.resolve() / "data"
    assert amb.arquivo_semente.name == "semente.local.json"
    assert amb.arquivo_nao_membros.name == "nao_membros.local.txt"
    assert amb.problema() is None


def test_fa_dados_vence_o_ini(projeto, tmp_path):
    _ini(projeto, "[dados]\nraiz = %s\n" % (tmp_path / "do_ini"))
    raiz = _raiz_com_data(tmp_path, "do_ambiente")

    amb = resolver(env={"FA_DADOS": str(raiz)}, raiz_projeto=projeto)

    assert amb.raiz == raiz.resolve()


def test_fa_demo_vence_tudo_inclusive_as_excecoes(projeto, tmp_path):
    _ini(projeto, "raiz = %s\n" % tmp_path)
    amb = resolver(env={"FA_DEMO": "1", "FA_DADOS": str(tmp_path),
                        "EXTRATOS_DIR": str(tmp_path)},
                   raiz_projeto=projeto)

    assert amb.modo == MODO_DEMO
    assert amb.origem == "FA_DEMO"
    assert all(amb.pasta(p) is None for p in PASTAS)


@pytest.mark.parametrize("valor", ["", "0", "  "])
def test_fa_demo_vazio_ou_zero_nao_conta(projeto, tmp_path, valor):
    amb = resolver(env={"FA_DEMO": valor, "FA_DADOS": str(tmp_path)},
                   raiz_projeto=projeto)
    assert amb.modo == MODO_REAL


# ---------------------------------------------------------------------------
# O fa.local.ini
# ---------------------------------------------------------------------------

def test_ini_com_secao_e_caminho_absoluto(projeto, tmp_path):
    raiz = _raiz_com_data(tmp_path)
    _ini(projeto, "[dados]\nraiz = %s\n" % raiz)

    amb = resolver(env={}, raiz_projeto=projeto)

    assert amb.modo == MODO_REAL
    assert amb.raiz == raiz.resolve()
    assert amb.origem.endswith(ARQUIVO_INI)


def test_ini_sem_cabecalho_com_bom_e_com_aspas(projeto, tmp_path):
    """As três coisas que um iniciante faz no Bloco de Notas: esquecer o
    [dados], salvar com BOM e colar o caminho com as aspas do 'Copiar como
    caminho' do Windows."""
    raiz = _raiz_com_data(tmp_path, "com espaço")
    _ini(projeto, 'raiz = "%s"\n' % raiz, encoding="utf-8-sig")

    amb = resolver(env={}, raiz_projeto=projeto)

    assert amb.raiz == raiz.resolve()


def test_ini_relativo_vale_a_partir_do_projeto(projeto):
    (projeto / "data").mkdir()
    _ini(projeto, "raiz = .\n")

    amb = resolver(env={}, raiz_projeto=projeto)

    assert amb.raiz == projeto.resolve()
    assert amb.problema() is None


def test_ini_com_referencia_fora_da_raiz(projeto, tmp_path):
    raiz = _raiz_com_data(tmp_path)
    referencia = tmp_path / "Documents" / "Extratos"
    _ini(projeto, "raiz = %s\nextratos_referencia = %s\n" % (raiz, referencia))

    amb = resolver(env={}, raiz_projeto=projeto)

    assert amb.pasta("extratos-referencia") == referencia.resolve()
    assert amb.pasta("extratos") == raiz.resolve() / "extratos"


@pytest.mark.parametrize("texto, trecho", [
    ("[dados]\n", "falta a linha"),
    ("raiz =\n", "falta a linha"),
    ("raiz = x\nextratos_ref = y\n", "desconhecida"),
    ("[dados]\nraiz = x\n[outra]\nchave = y\n", "só a seção"),
    ("raiz = x\nraiz = y\n", "não é um arquivo de configuração válido"),
])
def test_ini_malformado_e_erro_e_nao_demonstracao(projeto, texto, trecho):
    _ini(projeto, texto)
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        resolver(env={}, raiz_projeto=projeto)


# ---------------------------------------------------------------------------
# As variáveis antigas, como exceção por pasta
# ---------------------------------------------------------------------------

def test_variavel_antiga_vale_sem_raiz_configurada(projeto, tmp_path):
    amb = resolver(env={"EXTRATOS_DIR": str(tmp_path / "ext")},
                   raiz_projeto=projeto)

    assert amb.modo == MODO_DEMO
    assert amb.pasta("extratos") == (tmp_path / "ext").resolve()
    assert amb.pasta("gabarito") is None


def test_variavel_antiga_vence_a_raiz_so_na_pasta_dela(projeto, tmp_path):
    raiz = _raiz_com_data(tmp_path)
    amb = resolver(env={"FA_DADOS": str(raiz),
                        "EXTRATOS_REF": str(tmp_path / "ref")},
                   raiz_projeto=projeto)

    assert amb.pasta("extratos-referencia") == (tmp_path / "ref").resolve()
    assert amb.pasta("extratos") == raiz.resolve() / "extratos"


def test_data_dir_nao_abre_dado_real_no_app(projeto, tmp_path):
    """O nome é genérico demais: outro programa pode tê-lo definido. Vale
    para as ferramentas, nunca para o app."""
    amb = resolver(env={"DATA_DIR": str(tmp_path)}, raiz_projeto=projeto)

    assert amb.pasta("data") == tmp_path.resolve()
    assert amb.dados_do_app is None
    assert amb.modo == MODO_DEMO


def test_pasta_desconhecida_e_erro(projeto):
    with pytest.raises(ValueError):
        resolver(env={}, raiz_projeto=projeto).pasta("dados")


# ---------------------------------------------------------------------------
# Pasta configurada que não está lá
# ---------------------------------------------------------------------------

def test_raiz_que_nao_existe_e_problema_e_nada_e_criado(projeto, tmp_path):
    antes = _listagem(tmp_path)
    amb = resolver(env={"FA_DADOS": str(tmp_path / "hd_desligado")},
                   raiz_projeto=projeto)

    assert "não existe" in amb.problema()
    assert _listagem(tmp_path) == antes


def test_raiz_sem_data_e_problema(projeto, tmp_path):
    raiz = tmp_path / "pasta_errada"
    raiz.mkdir()
    amb = resolver(env={"FA_DADOS": str(raiz)}, raiz_projeto=projeto)

    assert "não tem a subpasta data" in amb.problema()
    assert not (raiz / "data").exists()


def test_resolver_nao_cria_nada(projeto, tmp_path):
    _ini(projeto, "raiz = %s\n" % (tmp_path / "x"))
    antes = _listagem(tmp_path)
    resolver(env={}, raiz_projeto=projeto)
    assert _listagem(tmp_path) == antes


# ---------------------------------------------------------------------------
# Os dois arquivos locais
# ---------------------------------------------------------------------------

def _semente(tmp_path, conteudo):
    caminho = tmp_path / "semente.local.json"
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False),
                       encoding="utf-8")
    return caminho


SEMENTE_OK = {
    "members": [{"name": "Ana Quintela", "aliases": ["ana quintela"]}],
    "accounts": [{"label": "Nubank (conta) 99887766", "owner": "Ana Quintela"}],
}


def test_semente_ausente_e_none(tmp_path):
    assert carregar_semente(None) is None
    assert carregar_semente(tmp_path / "nao_existe.json") is None


def test_semente_valida(tmp_path):
    semente = carregar_semente(_semente(tmp_path, SEMENTE_OK))

    assert [m.name for m in semente.members] == ["Ana Quintela"]
    assert semente.accounts[0].owner == "Ana Quintela"
    config = semente.config()
    config.members[0].aliases.append("outra")
    assert semente.members[0].aliases == ["ana quintela"], (
        "config() tem de devolver cópia, não a lista da semente")


@pytest.mark.parametrize("conteudo, trecho", [
    ([], "objeto JSON"),
    ({"members": [], "accounts": []}, "pelo menos um membro"),
    ({"members": [{"aliases": []}], "accounts": []}, "membro malformado"),
    ({"members": SEMENTE_OK["members"], "accounts": "x"}, "'accounts'"),
    ({"members": SEMENTE_OK["members"],
      "accounts": [{"label": "C6 Bank (conta) 1", "owner": "Fulano"}]},
     "não está entre os membros"),
])
def test_semente_malformada_e_erro(tmp_path, conteudo, trecho):
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        carregar_semente(_semente(tmp_path, conteudo))


def test_semente_que_nao_e_json_e_erro(tmp_path):
    caminho = tmp_path / "semente.local.json"
    caminho.write_text("{isto não é json", encoding="utf-8")
    with pytest.raises(ConfiguracaoInvalida, match="não se deixa ler"):
        carregar_semente(caminho)


def test_nao_membros_ignora_comentario_e_linha_em_branco(tmp_path):
    caminho = tmp_path / "nao_membros.local.txt"
    caminho.write_text("# cabeçalho\n\nCarla Quintela Ramos\n  # outro\n"
                       "  Diego Moreira Lopes  \n", encoding="utf-8")

    assert carregar_nao_membros(caminho) == ["Carla Quintela Ramos",
                                             "Diego Moreira Lopes"]
    assert carregar_nao_membros(tmp_path / "nao_existe.txt") is None
    assert carregar_nao_membros(None) is None
