# -*- coding: utf-8 -*-
"""
Importação de extratos, fora da tela — em duas etapas.

A sequência é a que o `main()` do `app.py` executa entre o upload e o botão
de confirmar, e a ordem importa:

1. **preparar** — ler os arquivos, categorizar SÓ o que entrou e deduplicar
   contra a base. Não toca na base. É o que o preview mostra.
2. **confirmar** — juntar à base o que a preparação trouxe e, sobre a BASE
   INTEIRA, parear estornos e conciliar transferências.

Categorizar só o que entrou não é detalhe: `categorize_batch` sobre a base
inteira desfaz a conciliação, porque devolve a "Transferências" as pernas que
o `TransferMatcher` já tinha promovido a "Transferência Interna".

Nenhuma das duas etapas grava, e este módulo não importa a interface. Quem
chama decide onde e quando gravar.

Quem chama: o bloco de importação do `main()` (`app.py`) —
`preparar_importacao` a cada rodada com upload, para o preview, e
`confirmar_importacao` no clique de "Confirmar Importação" — e a montagem da
demonstração (`src/demonstracao.py`). Os testes de
`tests/unidade/test_importacao.py` comparam a função e o botão do app com uma
sequência escrita à mão, que não passa por este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Tuple

from src.business.categorizer import ReversalMatcher, SmartCategorizer
from src.business.transfer_matcher import TransferMatcher
from src.data.models import AppConfig, Transaction
from src.data.parser import CSVParser, TransactionDeduplicator


@dataclass
class ArquivoLido:
    """O que a leitura de um arquivo deu, para o preview dizer."""
    nome: str
    conta: Optional[str]
    perfil: Optional[str]
    transacoes: int
    avisos: List[str] = field(default_factory=list)
    erros: List[str] = field(default_factory=list)

    @property
    def aceito(self) -> bool:
        """Só entra na importação o arquivo reconhecido e sem erro."""
        return bool(self.perfil) and not self.erros


@dataclass
class Preparacao:
    """
    Resultado de `preparar_importacao`.

    novas: as transações que entrariam — categorizadas e já sem as
        duplicatas, na ordem em que os arquivos foram dados.
    duplicatas: quantas linhas lidas já estavam na base ou se repetiam entre
        os arquivos.
    arquivos: um registro por arquivo dado, aceito ou não, na mesma ordem.
    """
    novas: List[Transaction]
    duplicatas: int
    arquivos: List[ArquivoLido]

    @property
    def erros(self) -> List[str]:
        return [f"[{a.nome}] {e}" for a in self.arquivos for e in a.erros]

    @property
    def avisos(self) -> List[str]:
        return [f"[{a.nome}] {w}" for a in self.arquivos if a.aceito
                for w in a.avisos]


@dataclass
class Confirmacao:
    """Resultado de `confirmar_importacao`, com o que a tela anuncia."""
    importadas: int
    neutralizadas_por_estorno: int
    pares_novos: int
    demovidas: int


def preparar_importacao(arquivos: Iterable[Tuple[str, Any]],
                        base: List[Transaction],
                        categorizador: SmartCategorizer,
                        parser: Optional[CSVParser] = None) -> Preparacao:
    """
    Lê os arquivos, categoriza só o que entrou e deduplica contra `base`.

    arquivos: pares (nome, conteúdo). O conteúdo é o que `CSVParser.parse_file`
        aceita: bytes, texto, ou um objeto com `.read()` — a forma em que a
        interface entrega um upload. O nome importa: é dele que sai a conta
        do Nubank.
    base: a base aberta. Não é alterada.
    categorizador: o da sessão, com o aprendizado do usuário carregado.
    """
    parser = parser or CSVParser()
    lidas: List[Transaction] = []
    registros: List[ArquivoLido] = []

    for nome, conteudo in arquivos:
        resultado = parser.parse_file(conteudo, nome)
        registro = ArquivoLido(
            nome=nome,
            conta=resultado.source_account,
            perfil=resultado.profile_name,
            transacoes=len(resultado.transactions),
            avisos=list(resultado.warnings),
            erros=list(resultado.errors),
        )
        if registro.aceito:
            lidas.extend(resultado.transactions)
        registros.append(registro)

    if lidas:
        categorizador.categorize_batch(lidas)
    novas, duplicatas = TransactionDeduplicator.remove_duplicates(lidas, base)

    return Preparacao(novas=novas, duplicatas=duplicatas, arquivos=registros)


def confirmar_importacao(preparacao: Preparacao, base: List[Transaction],
                         config: AppConfig) -> Confirmacao:
    """
    Junta `preparacao.novas` a `base`, NO LUGAR, e roda sobre a base inteira
    o pareamento de estornos e a conciliação — nessa ordem. Não grava.
    """
    base.extend(preparacao.novas)

    neutralizadas = ReversalMatcher.pair_reversals(base)
    pares_novos, demovidas = TransferMatcher(config).reconcile(base)

    return Confirmacao(importadas=len(preparacao.novas),
                       neutralizadas_por_estorno=neutralizadas,
                       pares_novos=pares_novos,
                       demovidas=demovidas)
