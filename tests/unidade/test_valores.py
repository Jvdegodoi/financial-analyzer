# -*- coding: utf-8 -*-
"""
Camada de unidade — `DataValidator.validate_value`.

O perfilador da revisão mediu 4 de 8 funções de `validator.py` executadas, e
as 4 que rodavam só passavam por caminho feliz: são chamadas linha a linha
pelo parser contra extratos reais, que são bem-comportados. Nenhum teste
passava valor ausente.

O achado 1.1 vive aí. `float('nan')` **não levanta**: uma célula de Valor em
branco chega como `'nan'`, `validate_value` devolvia `(True, nan, "")`, a
guarda seguinte do parser é `if value == 0` e `nan == 0` é falso. O NaN
entrava na base e apagava todas as métricas — `R$ nan` em Receitas, Despesas,
Saldo e em toda categoria, sem erro nem aviso. E `json.dump` grava `NaN` sem
reclamar, produzindo um token que não é JSON válido: qualquer leitor que não
seja Python recusa o arquivo inteiro, o que bloqueia a migração para SQLite.
"""

import json
import math

import pytest

from src.data.validator import DataValidator


# ---------------------------------------------------------------------------
# O caso que motivou a correção
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada", ["nan", "NaN", "NAN", "nAn"])
def test_nan_em_qualquer_caixa_e_rejeitado(entrada):
    ok, valor, motivo = DataValidator.validate_value(entrada)

    assert ok is False
    assert valor is None
    assert "Valor ausente" in motivo
    assert entrada in motivo, "a mensagem precisa dizer o que chegou"


@pytest.mark.parametrize("entrada", ["inf", "-inf", "Infinity", "-Infinity"])
def test_infinito_e_rejeitado(entrada):
    ok, valor, motivo = DataValidator.validate_value(entrada)

    assert ok is False
    assert valor is None
    assert "infinito" in motivo.lower()


def test_a_guarda_de_zero_do_parser_nao_pegaria_o_nan():
    """
    Guarda o motivo de a checagem morar no validador e não no parser: a
    guarda seguinte é `if value == 0`, e `nan == 0` é falso. Se alguém um dia
    achar que a checagem é redundante, este teste explica por que não é.
    """
    assert not (float("nan") == 0)
    assert not (float("nan") < 0)
    assert not (float("nan") > 0)


def test_nan_gravado_em_json_nao_e_json_valido():
    """
    A segunda metade do dano. `json.dump` aceita NaN por padrão (é extensão
    do Python), e o arquivo resultante é recusado por qualquer leitor
    estrito — inclusive o próprio Python com `parse_constant`.
    """
    texto = json.dumps({"value": float("nan")})
    assert "NaN" in texto

    with pytest.raises(ValueError):
        json.loads(texto, parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError("token não é JSON válido")))


# ---------------------------------------------------------------------------
# Ausência e lixo, que já eram rejeitados — para não regredirem junto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada", ["", "   ", None])
def test_vazio_e_rejeitado(entrada):
    ok, valor, motivo = DataValidator.validate_value(entrada)
    assert ok is False and valor is None and motivo == "Valor vazio"


@pytest.mark.parametrize("entrada", ["abc", "R$ ", "--", "1,2,3.4.5"])
def test_texto_que_nao_e_numero_e_rejeitado(entrada):
    ok, valor, _ = DataValidator.validate_value(entrada)
    assert ok is False and valor is None


# ---------------------------------------------------------------------------
# Caminho feliz — os formatos que os três bancos produzem
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("-42.90", -42.90),           # Nubank, decimal americano
    ("1250.75", 1250.75),         # C6, decimal americano
    ("-1.234,56", -1234.56),      # brasileiro com milhar
    ("1,234.56", 1234.56),        # americano com milhar
    ("88,00", 88.00),             # brasileiro sem milhar
    ("R$ 150,00", 150.00),        # com símbolo e espaço
    ("1234", 1234.0),             # inteiro puro
])
def test_formatos_aceitos(entrada, esperado):
    ok, valor, motivo = DataValidator.validate_value(entrada)

    assert ok is True, motivo
    assert math.isfinite(valor)
    assert valor == pytest.approx(esperado)


def test_valor_zero_e_aceito_pelo_validador_e_filtrado_pelo_parser():
    """
    Zero passa aqui de propósito: quem o descarta é o parser, com a mensagem
    'Valor zero (ignorada)'. As linhas de saldo do C6 são zero, e são ruído,
    não erro de validação.
    """
    ok, valor, _ = DataValidator.validate_value("0.00")
    assert ok is True and valor == 0.0


def test_valor_alto_demais_e_rejeitado():
    ok, _, motivo = DataValidator.validate_value(
        str(DataValidator.MAX_VALUE * 10))
    assert ok is False and "muito alto" in motivo


def test_centavo_partido_e_rejeitado():
    ok, _, motivo = DataValidator.validate_value("0.001")
    assert ok is False and "muito baixo" in motivo
