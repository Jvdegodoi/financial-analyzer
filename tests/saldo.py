# -*- coding: utf-8 -*-
"""
Cadeia de saldo — a âncora que o extrato traz e o pipeline joga fora.

Inter e C6 gravam, em cada linha, o saldo da conta. É um número escrito
pelo BANCO, não pelo app, e por isso é juiz externo: se o parser ler o
valor errado, trocar o sinal, perder uma linha ou embaralhar a ordem, a
cadeia deixa de fechar — e deixa de fechar num ponto específico, que é o
que separa "alguma coisa está errada" de "está errada aqui".

O parser descarta a coluna de saldo. Estes leitores a resgatam do arquivo
cru e a alinham com as transações parseadas por `raw_data['row_number']`,
que é a posição da linha no arquivo. O que se compara, portanto, é o
VALOR QUE O PARSER PRODUZIU contra o saldo que o banco escreveu — não o
arquivo contra ele mesmo. É isso que faz disto teste de regressão de
parsing, e não conferência da aritmética do banco.

Duas granularidades, porque os dois bancos gravam coisas diferentes:

- **Inter — saldo APÓS cada transação.** Medido, não suposto: no extrato
  real há muitos dias com mais de um lançamento e em nenhum deles o saldo
  se repete. A cadeia fecha linha a linha. O arquivo vem em ordem
  DECRESCENTE, inclusive dentro do dia, então a ordem cronológica é o
  arquivo lido de baixo para cima — e é sobre a ordem crua que a cadeia
  roda, nunca sobre a base reordenada por data.

- **C6 — saldo DO DIA, e o dia é a Data Contábil.** Também medido: num
  extrato real, agrupando por Data Lançamento um dos grupos com mais de uma
  linha tem saldos diferentes; agrupando por Data Contábil todos os grupos
  têm saldo constante. Uma linha lançada num dia com contábil no dia
  anterior é o caso que separa as duas leituras. A cadeia fecha por dia
  contábil, o que localiza a quebra no dia e não na linha.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

ENCODINGS = ["utf-8-sig", "utf-8", "latin1", "cp1252"]

# Tolerância de comparação. Os dois bancos gravam centavos; meio centavo é
# folga de ponto flutuante, não de arredondamento de negócio.
CENTAVO = 0.005


class Quebra(NamedTuple):
    """Um elo que não fechou. `onde` é a linha (Inter) ou o dia (C6)."""
    onde: str
    anterior: float
    movimento: float
    esperado: float
    extrato: float
    detalhe: str

    def __str__(self) -> str:
        return ("%s: saldo anterior %.2f %+.2f = %.2f, mas o extrato diz "
                "%.2f (diferença %+.2f) | %s"
                % (self.onde, self.anterior, self.movimento, self.esperado,
                   self.extrato, self.extrato - self.esperado, self.detalhe))


# ---------------------------------------------------------------------------
# Leitura da coluna de saldo, direto do arquivo cru
# ---------------------------------------------------------------------------

def _texto(caminho: Path) -> str:
    bruto = Path(caminho).read_bytes()
    for encoding in ENCODINGS:
        try:
            return bruto.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError("encoding não reconhecido: %s" % caminho)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c)).strip()


def _decimal_brasileiro(bruto: str) -> float:
    return float(bruto.strip().replace(".", "").replace(",", "."))


def _decimal_americano(bruto: str) -> float:
    return float(bruto.strip())


def saldos_do_inter(caminho: Path) -> Dict[int, float]:
    """{row_number: saldo após a transação}, na numeração do parser."""
    linhas = _texto(caminho).splitlines()
    cabecalho = next(i for i, l in enumerate(linhas)
                     if "historico" in _normalizar(l)
                     and "data lancamento" in _normalizar(l))
    colunas = [_normalizar(c) for c in linhas[cabecalho].split(";")]
    coluna_saldo = next(k for k, c in enumerate(colunas)
                        if c.startswith("saldo"))

    saldos: Dict[int, float] = {}
    numero = 0
    for linha in linhas[cabecalho + 1:]:
        if not linha.strip():
            continue                 # `skip_blank_lines=True` no parser
        numero += 1
        saldos[numero] = _decimal_brasileiro(linha.split(";")[coluna_saldo])
    return saldos


def dias_do_c6(caminho: Path) -> Dict[int, Dict[str, Any]]:
    """{row_number: {'contabil': 'DD/MM/AAAA', 'saldo': float}}."""
    linhas = _texto(caminho).splitlines()
    cabecalho = next(i for i, l in enumerate(linhas)
                     if _normalizar(l).startswith("data lancamento,"))
    colunas = [_normalizar(c)
               for c in next(csv.reader(io.StringIO(linhas[cabecalho])))]
    coluna_saldo = next(k for k, c in enumerate(colunas)
                        if c.startswith("saldo"))
    coluna_contabil = next(k for k, c in enumerate(colunas) if "contabil" in c)

    corpo = "\n".join(linhas[cabecalho + 1:])
    dias: Dict[int, Dict[str, Any]] = {}
    numero = 0
    for campos in csv.reader(io.StringIO(corpo)):
        if not campos or not campos[0].strip():
            continue
        numero += 1
        dias[numero] = {
            "contabil": campos[coluna_contabil].strip(),
            "saldo": _decimal_americano(campos[coluna_saldo]),
        }
    return dias


def saldo_declarado_do_inter(caminho: Path) -> Optional[float]:
    """O `Saldo ;NNN` do preâmbulo — o fechamento que o banco afirma."""
    achado = re.search(r"Saldo\s*;\s*([-\d.,]+)", _texto(caminho))
    return _decimal_brasileiro(achado.group(1)) if achado else None


# ---------------------------------------------------------------------------
# As duas cadeias
# ---------------------------------------------------------------------------

def _por_linha(transacoes) -> Dict[int, Any]:
    return {t.raw_data["row_number"]: t for t in transacoes}


def cadeia_do_inter(transacoes, saldos: Dict[int, float]) -> List[Quebra]:
    """
    Verifica saldo[n] − saldo[n−1] == valor[n] em toda a cadeia, na ordem
    CRONOLÓGICA — que no Inter é o arquivo lido de baixo para cima.

    N linhas dão N−1 elos: o saldo de abertura não é verificável, porque
    não há linha anterior a que compará-lo.
    """
    indexadas = _por_linha(transacoes)
    numeros = sorted(indexadas)
    assert numeros == sorted(saldos), (
        "as linhas parseadas não são as linhas do arquivo: parser %d, "
        "arquivo %d" % (len(numeros), len(saldos)))

    quebras: List[Quebra] = []
    cronologica = list(reversed(numeros))
    for anterior, atual in zip(cronologica, cronologica[1:]):
        transacao = indexadas[atual]
        esperado = round(saldos[anterior] + transacao.value, 2)
        if abs(esperado - saldos[atual]) > CENTAVO:
            quebras.append(Quebra(
                onde="linha %d" % atual,
                anterior=saldos[anterior], movimento=transacao.value,
                esperado=esperado, extrato=saldos[atual],
                detalhe="%s | %s" % (transacao.date.strftime("%d/%m/%Y"),
                                     transacao.description[:70])))
    return quebras


def cadeia_do_c6(transacoes, dias: Dict[int, Dict[str, Any]]) -> List[Quebra]:
    """
    Verifica, para cada Data Contábil em ordem cronológica, que o saldo do
    dia anterior mais o movimento do dia dá o saldo do dia.

    A ordenação é por `datetime`, nunca pelo texto "DD/MM/AAAA" — a regra
    de data do CLAUDE.md vale aqui como em qualquer outro lugar, e a
    fixture sintética atravessa a virada de ano justamente para que uma
    ordenação textual não passe despercebida.
    """
    indexadas = _por_linha(transacoes)
    assert sorted(indexadas) == sorted(dias), (
        "as linhas parseadas não são as linhas do arquivo: parser %d, "
        "arquivo %d" % (len(indexadas), len(dias)))

    agrupado: Dict[str, List[int]] = {}
    for numero, dado in dias.items():
        agrupado.setdefault(dado["contabil"], []).append(numero)

    quebras: List[Quebra] = []
    anterior: Optional[float] = None
    for contabil in sorted(agrupado,
                           key=lambda d: datetime.strptime(d, "%d/%m/%Y")):
        numeros = agrupado[contabil]
        distintos = {round(dias[n]["saldo"], 2) for n in numeros}
        if len(distintos) != 1:
            quebras.append(Quebra(
                onde="dia contábil %s" % contabil,
                anterior=float("nan"), movimento=float("nan"),
                esperado=float("nan"), extrato=float("nan"),
                detalhe="saldo do dia não é constante: %s" % sorted(distintos)))
            continue

        saldo = distintos.pop()
        movimento = round(sum(indexadas[n].value for n in numeros), 2)
        if anterior is not None:
            esperado = round(anterior + movimento, 2)
            if abs(esperado - saldo) > CENTAVO:
                quebras.append(Quebra(
                    onde="dia contábil %s" % contabil,
                    anterior=anterior, movimento=movimento,
                    esperado=esperado, extrato=saldo,
                    detalhe="%d lançamento(s)" % len(numeros)))
        anterior = saldo
    return quebras


def relatar(quebras: List[Quebra], quantos: int = 10) -> str:
    """Mensagem de falha que diz ONDE quebrou, não só que quebrou."""
    if not quebras:
        return ""
    linhas = ["%d elo(s) da cadeia de saldo não fecharam:" % len(quebras)]
    linhas += ["  " + str(q) for q in quebras[:quantos]]
    if len(quebras) > quantos:
        linhas.append("  (+%d)" % (len(quebras) - quantos))
    return "\n".join(linhas)
