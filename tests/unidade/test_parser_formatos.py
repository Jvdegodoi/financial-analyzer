# -*- coding: utf-8 -*-
"""
Camada de unidade — as manhas de formato de cada banco.

Cada asserção aqui existe porque a manha correspondente já quebrou o
parser alguma vez: BOM, CRLF, preâmbulo, valor partido em duas colunas,
decimal trocado, conta que só existe no nome do arquivo.
"""

from tests.conftest import (C6_JAN, INTER_JAN, NUBANK_JAN,
                            NUBANK_VALOR_EM_BRANCO, SINTETICOS)


# ---------------------------------------------------------------------------
# Nubank
# ---------------------------------------------------------------------------

def test_nubank_detecta_perfil_e_conta_pelo_nome_do_arquivo(importar):
    """
    O CSV do Nubank não traz a conta em lugar nenhum do conteúdo — só o
    nome do arquivo traz, no padrão NU_<conta>_<datas>.csv. Renomear o
    arquivo antes de importar perde a conta em silêncio.
    """
    r = importar(NUBANK_JAN)
    assert r.profile_name == "Nubank (conta)"
    assert r.source_account == "Nubank (conta) 99887766"
    assert not r.errors


def test_nubank_sem_preambulo_o_cabecalho_e_a_primeira_linha(importar):
    conteudo = (SINTETICOS / NUBANK_JAN).read_text(encoding="utf-8")
    assert conteudo.splitlines()[0] == "Data,Valor,Identificador,Descrição"
    assert len(importar(NUBANK_JAN).transactions) == 6


def test_nubank_captura_o_identificador_como_external_id(importar):
    r = importar(NUBANK_JAN)
    assert all(t.external_id for t in r.transactions)
    assert r.transactions[0].external_id.startswith("aaaa1111")


def test_nubank_decimal_com_ponto_e_sinal_no_valor(importar):
    r = importar(NUBANK_JAN)
    assert r.transactions[0].value == -42.90


# ---------------------------------------------------------------------------
# C6 Bank
# ---------------------------------------------------------------------------

def test_c6_arquivo_tem_bom_e_crlf():
    """
    O C6 grava utf-8-sig com CRLF. É o motivo de 'utf-8-sig' ser o
    primeiro da lista ENCODINGS: em 'utf-8' puro o BOM entra como
    caractere no nome da primeira coluna.
    """
    cru = (SINTETICOS / C6_JAN).read_bytes()
    assert cru.startswith(b"\xef\xbb\xbf"), "fixture perdeu o BOM"
    assert b"\r\n" in cru, "fixture perdeu o CRLF"


def test_c6_pula_preambulo_institucional_e_acha_a_conta(importar):
    r = importar(C6_JAN)
    assert r.profile_name == "C6 Bank (conta)"
    assert r.source_account == "C6 Bank (conta) 12345678"


def test_c6_junta_entrada_e_saida_ambas_positivas_em_um_valor(importar):
    """
    O C6 parte o valor em duas colunas, as duas com número positivo. O
    sinal vem de qual coluna está preenchida: valor = Entrada − Saída.
    """
    r = importar(C6_JAN)
    por_data = {t.date.strftime("%d/%m"): t.value for t in r.transactions}
    assert por_data["08/01"] == -150.00     # veio da coluna Saída
    assert por_data["18/01"] == 1250.75     # veio da coluna Entrada


def test_c6_decimal_americano_com_milhar_sem_separador(importar):
    r = importar(C6_JAN)
    entrada = [t for t in r.transactions if t.value > 0][0]
    assert entrada.value == 1250.75


def test_c6_linha_de_saldo_com_valor_zero_vira_aviso_nao_transacao(importar):
    r = importar(C6_JAN)
    assert len(r.transactions) == 3
    assert any("Valor zero" in a for a in r.warnings)


def test_celula_de_valor_em_branco_vira_aviso_nao_transacao(importar):
    """
    O contraste com o teste acima é o ponto: valor ZERO e valor AUSENTE são
    caminhos diferentes no código. O zero é pego por `if value == 0` no
    parser; o ausente chega como `'nan'`, `float('nan')` não levanta, e
    `nan == 0` é falso — passava direto.
    """
    r = importar(NUBANK_VALOR_EM_BRANCO)

    assert len(r.transactions) == 2
    assert all(t.value == t.value for t in r.transactions), "NaN na base"
    assert any("Valor ausente" in a for a in r.warnings)
    assert not r.errors


def test_c6_compoe_descricao_de_titulo_e_descricao(importar):
    r = importar(C6_JAN)
    perna = [t for t in r.transactions if t.value == -410.00][0]
    assert perna.description == (
        "Pix enviado para Bruno Quintela Moreira - TRANSF ENVIADA PIX")


def test_c6_nao_fornece_identificador_unico(importar):
    r = importar(C6_JAN)
    assert all(t.external_id is None for t in r.transactions)


# ---------------------------------------------------------------------------
# Banco Inter
# ---------------------------------------------------------------------------

def test_inter_separador_ponto_e_virgula_e_conta_no_preambulo(importar):
    r = importar(INTER_JAN)
    assert r.profile_name == "Inter (conta)"
    assert r.source_account == "Inter (conta) 87654321"
    assert len(r.transactions) == 4


def test_inter_decimal_brasileiro_com_ponto_de_milhar(importar):
    """1.230,45 é mil duzentos e trinta — não mil e duzentos e trinta e um."""
    r = importar(INTER_JAN)
    compra = [t for t in r.transactions
              if "Supermercado" in t.description][0]
    assert compra.value == -1230.45


def test_inter_compoe_descricao_de_historico_e_descricao(importar):
    r = importar(INTER_JAN)
    perna = [t for t in r.transactions if t.value == 410.00][0]
    assert perna.description == "Pix recebido - Ana Quintela Moreira"


def test_inter_extrato_vazio_e_aviso_nao_erro(parser):
    """
    Conta parada devolve extrato válido e sem linhas. Isso é aviso, não
    erro: a conta existe e o período simplesmente não teve movimento.
    """
    vazio = (" Extrato Conta Corrente \n"
             "Conta ;87654321\n"
             "Período ;01/01/2026 a 31/01/2026\n"
             "Saldo ;0,00\n"
             "\n"
             "Data Lançamento;Histórico;Descrição;Valor;Saldo\n")
    r = parser.parse_file(vazio.encode("utf-8"), "Extrato-vazio-CSV.csv")
    assert r.transactions == []
    assert not r.errors
    assert r.warnings
    assert r.source_account == "Inter (conta) 87654321"


# ---------------------------------------------------------------------------
# Transversal
# ---------------------------------------------------------------------------

def test_as_tres_contas_sinteticas_saem_com_rotulos_distintos(
        importar, config_sintetica):
    rotulos = {importar(n).source_account
               for n in (NUBANK_JAN, C6_JAN, INTER_JAN)}
    assert rotulos == {a.label for a in config_sintetica.accounts}
