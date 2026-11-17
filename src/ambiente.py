# -*- coding: utf-8 -*-
"""
Onde mora o dado — o único módulo que sabe.

App, testes e ferramentas perguntam aqui, e em nenhum outro lugar, onde está
o dado real. Sem configuração, a resposta é "em lugar nenhum": o app abre
numa base de demonstração descartável, a camada de integração dos testes é
pulada e as ferramentas de medição param com uma mensagem.

Ordem de decisão — a primeira que valer, vence:

1. ``FA_DEMO`` no ambiente, com qualquer valor que não seja vazio nem ``0``:
   demonstração, mesmo que haja configuração. É o que uma sessão do Code usa
   para subir o app sem tocar no dado do dono.
2. ``FA_DADOS`` no ambiente: o dado real está nessa pasta.
3. ``fa.local.ini`` na pasta do projeto, fora do Git::

       [dados]
       raiz = D:\\FA-dados

   O cabeçalho ``[dados]`` é opcional. Caminho relativo vale a partir da pasta
   do projeto (``raiz = .`` é o dado dentro dela, como era antes). Aspas em
   volta do caminho — o que o "Copiar como caminho" do Windows produz — são
   aceitas. Uma segunda chave, ``extratos_referencia``, aponta o conjunto de
   referência quando ele não está dentro da raiz.
4. Nada disso: demonstração.

A raiz do dado tem esta forma, com os nomes de pasta de sempre::

    <raiz>/data/                   estado do app (transactions.json, config.json…)
    <raiz>/extratos/               extratos atuais
    <raiz>/extratos-referencia/    conjunto de referência de junho/2026
    <raiz>/gabarito/               congelamentos do benchmark
    <raiz>/medicoes/               saídas nominais das medições
    <raiz>/semente.local.json      membros e contas reais
    <raiz>/nao_membros.local.txt   terceiros que não podem ser membros

As variáveis antigas continuam valendo como exceção POR PASTA, inclusive sem
raiz configurada: ``DATA_DIR`` (data), ``EXTRATOS_DIR`` (extratos),
``EXTRATOS_REF`` (extratos-referencia) e ``GABARITO_DIR`` (gabarito). Duas
restrições, de propósito:

- ``FA_DEMO`` desliga também as exceções.
- ``DATA_DIR`` não vale para o app. Ele só abre dado real por ``FA_DADOS`` ou
  por ``fa.local.ini``: o nome ``DATA_DIR`` é genérico demais para que outro
  programa da máquina não o tenha definido.

Nada aqui cria pasta ou arquivo. Configuração malformada levanta
``ConfiguracaoInvalida`` em vez de cair na demonstração em silêncio: cair
calado pareceria perda de dado.
"""

from __future__ import annotations

import configparser
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

ARQUIVO_INI = "fa.local.ini"
ARQUIVO_SEMENTE = "semente.local.json"
ARQUIVO_NAO_MEMBROS = "nao_membros.local.txt"

MODO_DEMO = "demonstracao"
MODO_REAL = "real"

PASTAS = ("data", "extratos", "extratos-referencia", "gabarito", "medicoes")

# Variável herdada -> pasta que ela aponta.
VARIAVEIS_ANTIGAS = {
    "DATA_DIR": "data",
    "EXTRATOS_DIR": "extratos",
    "EXTRATOS_REF": "extratos-referencia",
    "GABARITO_DIR": "gabarito",
}

SECAO_INI = "dados"
CHAVES_INI = ("raiz", "extratos_referencia")


class ConfiguracaoInvalida(Exception):
    """Configuração local que existe mas não se deixa ler. A mensagem diz o
    arquivo e o que corrigir."""


# ---------------------------------------------------------------------------
# O ambiente resolvido
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ambiente:
    modo: str
    origem: str                         # quem decidiu: FA_DEMO, FA_DADOS, fa.local.ini, padrão
    raiz: Optional[Path] = None
    referencia: Optional[Path] = None   # chave extratos_referencia do ini
    excecoes: Tuple[Tuple[str, Path], ...] = ()

    @property
    def real(self) -> bool:
        return self.modo == MODO_REAL

    @property
    def demonstracao(self) -> bool:
        return self.modo == MODO_DEMO

    def pasta(self, nome: str) -> Optional[Path]:
        """
        Onde está a pasta `nome` desta máquina, ou None quando não há dado
        real configurado para ela. Não confere se existe.
        """
        if nome not in PASTAS:
            raise ValueError(f"pasta desconhecida: {nome!r}; use uma de {PASTAS}")
        for pasta, caminho in self.excecoes:
            if pasta == nome:
                return caminho
        if not self.real:
            return None
        if nome == "extratos-referencia" and self.referencia is not None:
            return self.referencia
        return self.raiz / nome

    @property
    def dados_do_app(self) -> Optional[Path]:
        """A pasta `data/` que o app abre. Só a raiz configurada vale aqui."""
        return self.raiz / "data" if self.real else None

    @property
    def arquivo_semente(self) -> Optional[Path]:
        return self.raiz / ARQUIVO_SEMENTE if self.real else None

    @property
    def arquivo_nao_membros(self) -> Optional[Path]:
        return self.raiz / ARQUIVO_NAO_MEMBROS if self.real else None

    def problema(self) -> Optional[str]:
        """
        Por que o app não pode abrir este dado real, ou None se pode. Em
        demonstração, sempre None.
        """
        if not self.real:
            return None
        if not self.raiz.is_dir():
            return (f"A pasta do dado configurada não existe: {self.raiz}\n"
                    f"(definida por {self.origem}). Se ela fica num disco "
                    f"externo, ligue o disco e reabra o app. Se o caminho "
                    f"mudou, corrija {self.origem}. Nada foi criado.")
        if not (self.raiz / "data").is_dir():
            return (f"A pasta do dado existe, mas não tem a subpasta data/: "
                    f"{self.raiz}\n(definida por {self.origem}). Confira se o "
                    f"caminho aponta para a raiz do dado e não para outra "
                    f"pasta. Se é uma base nova de propósito, crie a pasta "
                    f"data dentro dela. Nada foi criado.")
        return None

    def descrever(self) -> str:
        if self.real:
            return f"dado real em {self.raiz} (por {self.origem})"
        if self.origem == "FA_DEMO":
            return "demonstração (forçada por FA_DEMO)"
        return "demonstração (nenhum dado real configurado)"


# ---------------------------------------------------------------------------
# Resolução
# ---------------------------------------------------------------------------

def _limpar_caminho(texto: str) -> str:
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        texto = texto[1:-1].strip()
    return texto


def _caminho(texto: str, base: Path) -> Path:
    caminho = Path(_limpar_caminho(texto)).expanduser()
    if not caminho.is_absolute():
        caminho = base / caminho
    return caminho.resolve()


def ler_ini(caminho: Path, raiz_projeto: Path) -> Tuple[Path, Optional[Path]]:
    """Lê `fa.local.ini` e devolve (raiz, extratos_referencia|None)."""
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfiguracaoInvalida(
            f"Não consegui ler {caminho}: {type(e).__name__}: {e}") from e

    if not any(l.strip().startswith("[") for l in texto.splitlines()):
        texto = f"[{SECAO_INI}]\n" + texto

    leitor = configparser.ConfigParser(interpolation=None)
    try:
        leitor.read_string(texto, source=str(caminho))
    except configparser.Error as e:
        raise ConfiguracaoInvalida(
            f"{caminho} não é um arquivo de configuração válido: {e}") from e

    secoes = leitor.sections()
    if secoes != [SECAO_INI]:
        raise ConfiguracaoInvalida(
            f"{caminho} deve ter só a seção [{SECAO_INI}]; tem {secoes}.")
    chaves = dict(leitor[SECAO_INI])
    desconhecidas = sorted(set(chaves) - set(CHAVES_INI))
    if desconhecidas:
        raise ConfiguracaoInvalida(
            f"{caminho}: chave(s) desconhecida(s) {desconhecidas}. "
            f"As aceitas são {list(CHAVES_INI)}.")
    if not _limpar_caminho(chaves.get("raiz", "")):
        raise ConfiguracaoInvalida(
            f"{caminho} não diz onde está o dado: falta a linha "
            f"'raiz = <pasta>'.")

    raiz = _caminho(chaves["raiz"], raiz_projeto)
    referencia = (_caminho(chaves["extratos_referencia"], raiz_projeto)
                  if _limpar_caminho(chaves.get("extratos_referencia", ""))
                  else None)
    return raiz, referencia


def resolver(env: Optional[Mapping[str, str]] = None,
             raiz_projeto: Optional[Path] = None) -> Ambiente:
    """
    Resolve o ambiente desta execução. `env` e `raiz_projeto` existem para
    o teste; o padrão é `os.environ` e a pasta do projeto.
    """
    env = os.environ if env is None else env
    raiz_projeto = RAIZ_PROJETO if raiz_projeto is None else Path(raiz_projeto)

    if env.get("FA_DEMO", "").strip() not in ("", "0"):
        return Ambiente(modo=MODO_DEMO, origem="FA_DEMO")

    excecoes = tuple(
        (pasta, _caminho(env[var], Path.cwd()))
        for var, pasta in VARIAVEIS_ANTIGAS.items()
        if _limpar_caminho(env.get(var, "")))

    fa_dados = _limpar_caminho(env.get("FA_DADOS", ""))
    if fa_dados:
        return Ambiente(modo=MODO_REAL, origem="FA_DADOS",
                        raiz=_caminho(fa_dados, Path.cwd()),
                        excecoes=excecoes)

    ini = raiz_projeto / ARQUIVO_INI
    if ini.is_file():
        raiz, referencia = ler_ini(ini, raiz_projeto)
        return Ambiente(modo=MODO_REAL, origem=str(ini), raiz=raiz,
                        referencia=referencia, excecoes=excecoes)

    return Ambiente(modo=MODO_DEMO, origem="padrão", excecoes=excecoes)


# ---------------------------------------------------------------------------
# Os dois arquivos locais da raiz
# ---------------------------------------------------------------------------

def carregar_semente(caminho: Optional[Path]):
    """
    Lê `semente.local.json`. Devolve None quando o caminho é None ou o
    arquivo não existe; levanta `ConfiguracaoInvalida` quando existe e está
    errado.

    Formato — as mesmas chaves `members` e `accounts` do `config.json`::

        {"members":  [{"name": "...", "aliases": ["...", "..."]}],
         "accounts": [{"label": "Nubank (conta) 0000", "owner": "..."}]}
    """
    from src.data.models import FamilyAccount, FamilyMember, Semente

    if caminho is None or not Path(caminho).is_file():
        return None
    try:
        bruto = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ConfiguracaoInvalida(
            f"{caminho} não se deixa ler: {type(e).__name__}: {e}") from e

    def recusar(motivo: str):
        raise ConfiguracaoInvalida(f"{caminho}: {motivo}")

    if not isinstance(bruto, dict):
        recusar("o conteúdo tem de ser um objeto JSON com 'members' e 'accounts'.")
    membros_crus = bruto.get("members")
    contas_cruas = bruto.get("accounts")
    if not isinstance(membros_crus, list) or not membros_crus:
        recusar("'members' tem de ser uma lista com pelo menos um membro.")
    if not isinstance(contas_cruas, list):
        recusar("'accounts' tem de ser uma lista.")

    membros = []
    for m in membros_crus:
        if (not isinstance(m, dict) or not isinstance(m.get("name"), str)
                or not m["name"].strip()
                or not isinstance(m.get("aliases", []), list)
                or not all(isinstance(a, str) for a in m.get("aliases", []))):
            recusar(f"membro malformado: precisa de 'name' e de 'aliases' "
                    f"(lista de texto). Recebido: {sorted(m) if isinstance(m, dict) else type(m).__name__}")
        membros.append(FamilyMember.from_dict(m))

    nomes = {m.name for m in membros}
    contas = []
    for a in contas_cruas:
        if (not isinstance(a, dict) or not isinstance(a.get("label"), str)
                or not a["label"].strip()):
            recusar("conta malformada: precisa de 'label'.")
        conta = FamilyAccount.from_dict(a)
        if conta.owner and conta.owner not in nomes:
            recusar(f"a conta {conta.label!r} tem dono {conta.owner!r}, que "
                    f"não está entre os membros.")
        contas.append(conta)

    return Semente(members=membros, accounts=contas)


def carregar_nao_membros(caminho: Optional[Path]) -> Optional[List[str]]:
    """Um nome por linha; linhas em branco e iniciadas por # são ignoradas.
    None quando o caminho é None ou o arquivo não existe."""
    if caminho is None or not Path(caminho).is_file():
        return None
    linhas = Path(caminho).read_text(encoding="utf-8-sig").splitlines()
    return [l.strip() for l in linhas
            if l.strip() and not l.lstrip().startswith("#")]
