# -*- coding: utf-8 -*-
"""
A demonstração do app: o conjunto fictício de `demonstracao/` montado numa
base.

Sem dado real configurado, o app abre numa base descartável (`app.py`,
`init_storage`). Este módulo é quem a enche: lê os extratos versionados em
`demonstracao/extratos/`, importa-os pelas mesmas duas etapas que o botão de
importação do app usa (`src/importacao.py`), cadastra as fontes de renda
fictícias, aplica a lista de atribuições e grava tudo na pasta que recebeu.

Três regras, e cada uma tem teste:

- **Só monta em pasta sem base.** Se a pasta já tem `transactions.json` ou
  `config.json`, recusa. A montagem nunca escreve por cima de uma base.
- **A atribuição de renda é exata, linha a linha.** Cada item do
  `conjunto.json` aponta um arquivo e uma linha — `raw_data['filename']` e
  `raw_data['row_number']` — e tem de achar exatamente uma transação, com a
  data e o valor que declara. Nunca casa por texto, apelido ou valor. Uma
  atribuição que não acha a sua linha derruba a montagem inteira, com a
  mensagem dizendo qual.
- **Não importa a interface** e não consulta o ambiente: quem decide que é
  demonstração, e onde fica a pasta temporária, é o `app.py`.

AS ATRIBUIÇÕES SIMULAM O TRABALHO MANUAL DO USUÁRIO. No produto, atribuir
uma receita a uma fonte é decisão da pessoa, transação a transação, na aba
Renda. A lista do conjunto faz as vezes dessa pessoa na demonstração. Nada
aqui infere fonte, e nenhum outro código do produto atribui.

A ordem de importação faz parte do contrato: os extratos entram em ordem
crescente de nome de arquivo. A linha que está em dois extratos sobrepostos
sobrevive com o nome do que entrou primeiro, e é com esse nome que o gerador
(`demonstracao/gerar.py`) escreve a atribuição dela.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.business.categorizer import SmartCategorizer
from src.data.models import (AppConfig, IncomeSource, Transaction,
                             TransactionType)
from src.data.storage import StorageManager
from src.importacao import confirmar_importacao, preparar_importacao

# Achada a partir deste arquivo, e não de `ambiente.RAIZ_PROJETO`: durante a
# suíte aquela constante aponta uma pasta vazia, de propósito
# (`tests/conftest.py`).
PASTA = Path(__file__).resolve().parent.parent / "demonstracao"
ARQUIVO_CONJUNTO = "conjunto.json"
PASTA_EXTRATOS = "extratos"


class ConjuntoInvalido(Exception):
    """O conjunto de demonstração não se deixa montar: arquivo faltando ou
    sobrando, extrato que o parser recusa, atribuição que não casa. A
    mensagem diz o quê."""


class MontagemRecusada(Exception):
    """A pasta de destino já tem uma base. A montagem não escreve por cima."""


@dataclass(frozen=True)
class Conjunto:
    pasta: Path
    inicio: date
    fim: date
    data_de_referencia: datetime
    fontes_de_renda: Tuple[IncomeSource, ...]
    atribuicoes: Tuple[Dict[str, Any], ...]
    receitas_sem_fonte: int
    arquivos: Tuple[Dict[str, Any], ...]
    esperado: Dict[str, Any]

    @property
    def pasta_dos_extratos(self) -> Path:
        return self.pasta / PASTA_EXTRATOS

    @property
    def periodo_str(self) -> str:
        return (f"{self.inicio.strftime('%d/%m/%Y')} a "
                f"{self.fim.strftime('%d/%m/%Y')}")

    @property
    def referencia_str(self) -> str:
        return self.data_de_referencia.strftime("%d/%m/%Y")


@dataclass
class Montagem:
    """O que a montagem fez, em números."""
    arquivos: int
    transacoes: int
    duplicatas: int
    pares: int
    atribuidas: int
    receitas_sem_fonte: int


# ---------------------------------------------------------------------------
# Ler o conjunto
# ---------------------------------------------------------------------------

def carregar_conjunto(pasta: Optional[Path] = None) -> Conjunto:
    """Lê e valida `conjunto.json`. Não abre os extratos."""
    pasta = Path(pasta) if pasta is not None else PASTA
    caminho = pasta / ARQUIVO_CONJUNTO
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConjuntoInvalido(f"não consegui ler {caminho}: {e}") from e
    except json.JSONDecodeError as e:
        raise ConjuntoInvalido(f"{caminho} não é JSON válido: {e}") from e

    try:
        inicio, fim = (date.fromisoformat(d) for d in bruto["periodo"])
        referencia = datetime.fromisoformat(bruto["data_de_referencia"])
        fontes = tuple(IncomeSource.from_dict(f)
                       for f in bruto["fontes_de_renda"])
        conjunto = Conjunto(
            pasta=pasta, inicio=inicio, fim=fim,
            data_de_referencia=referencia, fontes_de_renda=fontes,
            atribuicoes=tuple(bruto["atribuicoes"]),
            receitas_sem_fonte=int(bruto["receitas_sem_fonte"]),
            arquivos=tuple(bruto["arquivos"]),
            esperado=dict(bruto.get("esperado", {})))
    except (KeyError, TypeError, ValueError) as e:
        raise ConjuntoInvalido(
            f"{caminho} está incompleto ou malformado: "
            f"{type(e).__name__}: {e}") from e

    if not inicio <= fim < referencia.date():
        raise ConjuntoInvalido(
            f"{caminho}: a data de referência ({referencia.date()}) tem de "
            f"vir depois do período ({inicio} a {fim}).")
    return conjunto


def data_de_referencia(pasta: Optional[Path] = None) -> datetime:
    """
    O "hoje" da demonstração: fixo, declarado junto do conjunto, à
    meia-noite. Não é recalculado da base aberta — se o visitante importar
    um extrato mais novo, o hoje da demonstração não anda.
    """
    return carregar_conjunto(pasta).data_de_referencia


# ---------------------------------------------------------------------------
# As atribuições
# ---------------------------------------------------------------------------

def aplicar_atribuicoes(base: List[Transaction],
                        conjunto: Conjunto) -> int:
    """
    Grava `income_source` nas linhas que a lista aponta. Casamento exato por
    (arquivo, linha); qualquer desencontro levanta `ConjuntoInvalido` ANTES
    de mexer em qualquer transação. Devolve quantas atribuiu.
    """
    fontes = {f.name for f in conjunto.fontes_de_renda}
    por_linha: Dict[Tuple[str, int], List[Transaction]] = {}
    for t in base:
        chave = (t.raw_data.get("filename"), t.raw_data.get("row_number"))
        por_linha.setdefault(chave, []).append(t)

    decididas: List[Tuple[Transaction, str]] = []
    ja_apontadas = set()
    for item in conjunto.atribuicoes:
        chave = (item.get("arquivo"), item.get("linha"))
        onde = f"atribuição de {chave[0]}, linha {chave[1]}"
        fonte = item.get("fonte")
        if fonte not in fontes:
            raise ConjuntoInvalido(
                f"{onde}: a fonte {fonte!r} não está entre as fontes de "
                f"renda do conjunto.")
        achadas = por_linha.get(chave, [])
        if not achadas:
            raise ConjuntoInvalido(
                f"{onde}: não achou a sua linha na base montada.")
        if len(achadas) > 1:
            raise ConjuntoInvalido(
                f"{onde}: achou {len(achadas)} linhas na base montada; tem "
                f"de achar exatamente uma.")
        if chave in ja_apontadas:
            raise ConjuntoInvalido(
                f"{onde}: há mais de uma atribuição para a mesma linha.")
        ja_apontadas.add(chave)

        t = achadas[0]
        if t.date.date().isoformat() != item.get("data"):
            raise ConjuntoInvalido(
                f"{onde}: declara a data {item.get('data')} e a linha é de "
                f"{t.date.date().isoformat()}.")
        if f"{t.value:.2f}" != item.get("valor"):
            raise ConjuntoInvalido(
                f"{onde}: declara o valor {item.get('valor')} e a linha "
                f"vale {t.value:.2f}.")
        if t.type != TransactionType.RECEITA or t.is_neutral:
            raise ConjuntoInvalido(
                f"{onde}: a linha não é uma receita que conte nas métricas "
                f"(categoria {t.category!r}, valor {t.value:.2f}).")
        decididas.append((t, fonte))

    for t, fonte in decididas:
        t.income_source = fonte
    return len(decididas)


def receitas_sem_fonte(base: List[Transaction]) -> int:
    """A população da aba Renda que ainda não tem fonte."""
    return sum(1 for t in base
               if t.type == TransactionType.RECEITA and not t.is_neutral
               and not t.income_source)


# ---------------------------------------------------------------------------
# Montar
# ---------------------------------------------------------------------------

def _extratos_do_conjunto(conjunto: Conjunto) -> List[Path]:
    """Os extratos, em ordem crescente de nome, conferidos contra a lista do
    `conjunto.json`: nem um a mais, nem um a menos."""
    no_disco = sorted(conjunto.pasta_dos_extratos.glob("*.csv"),
                      key=lambda p: p.name)
    declarados = {a["nome"] for a in conjunto.arquivos}
    presentes = {p.name for p in no_disco}
    if presentes != declarados:
        raise ConjuntoInvalido(
            f"os extratos em {conjunto.pasta_dos_extratos} não são os do "
            f"conjunto: sobram {sorted(presentes - declarados)}, faltam "
            f"{sorted(declarados - presentes)}.")
    return no_disco


def montar(storage: StorageManager, pasta: Optional[Path] = None) -> Montagem:
    """
    Monta a base de demonstração na pasta do `storage` e grava. Tudo ou
    nada: qualquer desencontro levanta antes de a primeira linha ir ao disco.
    """
    if storage.data_file.exists() or storage.config_file.exists():
        raise MontagemRecusada(
            f"{storage.data_dir} já tem uma base; a demonstração só é "
            f"montada em pasta vazia.")

    conjunto = carregar_conjunto(pasta)
    extratos = _extratos_do_conjunto(conjunto)

    config = AppConfig()        # o pool fictício do código
    config.income_sources = [IncomeSource(name=f.name, type=f.type,
                                          owner=f.owner)
                             for f in conjunto.fontes_de_renda]
    categorizador = SmartCategorizer(
        members=config.members,
        category_manager=config.get_category_manager())

    base: List[Transaction] = []
    preparacao = preparar_importacao(
        [(p.name, p.read_bytes()) for p in extratos], base, categorizador)
    if preparacao.erros:
        raise ConjuntoInvalido("extrato do conjunto recusado pelo parser: "
                               + "; ".join(preparacao.erros))
    linhas = {a["nome"]: a["linhas"] for a in conjunto.arquivos}
    descartadas = [f"{a.nome}: {a.transacoes} de {linhas[a.nome]}"
                   for a in preparacao.arquivos
                   if a.transacoes != linhas[a.nome]]
    if descartadas:
        raise ConjuntoInvalido(
            "o parser não leu todas as linhas de: " + "; ".join(descartadas)
            + ". Avisos: " + "; ".join(preparacao.avisos[:5]))

    confirmacao = confirmar_importacao(preparacao, base, config)

    atribuidas = aplicar_atribuicoes(base, conjunto)
    sem_fonte = receitas_sem_fonte(base)
    if sem_fonte != conjunto.receitas_sem_fonte:
        raise ConjuntoInvalido(
            f"o conjunto declara {conjunto.receitas_sem_fonte} receitas sem "
            f"fonte e a base montada tem {sem_fonte}.")

    storage.save_transactions(base, create_backup=False)
    storage.save_config(config)
    storage.save_learning_data(categorizador.get_learning_data())

    return Montagem(arquivos=len(extratos), transacoes=len(base),
                    duplicatas=preparacao.duplicatas,
                    pares=confirmacao.pares_novos, atribuidas=atribuidas,
                    receitas_sem_fonte=sem_fonte)
