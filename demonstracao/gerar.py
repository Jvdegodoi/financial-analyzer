# -*- coding: utf-8 -*-
"""
Gerador do conjunto de demonstração do Financial Analyzer.

TUDO AQUI É INVENTADO: pessoas, contas, empresas, comerciantes, valores e
datas. Nenhuma linha foi desenhada, calibrada ou conferida olhando extrato
real. O conjunto existe para o app abrir mostrando o que faz, sem dado de
ninguém.

O que sai, sempre com os mesmos bytes:

    demonstracao/extratos/*.csv     extratos de quatro contas, na forma de
                                    arquivo de cada banco (Nubank, C6, Inter)
    demonstracao/conjunto.json      período, data de referência, fontes de
                                    renda, lista de atribuições e os números
                                    que os testes esperam

Uso:

    .\\venv\\Scripts\\python.exe demonstracao\\gerar.py             regrava os arquivos
    .\\venv\\Scripts\\python.exe demonstracao\\gerar.py --conferir  compara com o disco

Como o gerador garante o que promete:

- **Um livro só, em centavos inteiros.** Primeiro monta o livro de cada
  conta; só depois escreve arquivos. Cada arquivo é uma fatia do livro, e o
  saldo de cada linha sai do saldo corrente do livro: dois arquivos
  sobrepostos da mesma conta trazem as mesmas linhas, com os mesmos saldos.
- **Uma transferência é um evento com duas pernas**, criadas juntas: mesma
  data, valor oposto, contas diferentes.
- **Reprodução.** O sorteio usa só `random.Random(semente).random()`, cuja
  sequência o Python garante entre versões para a mesma semente, e
  aritmética inteira. Os arquivos são escritos em bytes, com o fim de linha
  explícito. Não depende do sistema nem do relógio.
- **Confere a si mesmo.** Se o perfil declarado não fechar — meses de saldo
  negativo, taxa de poupança, pernas soltas que não podem parear por
  acidente, terceiros que não podem ser lidos como membro —, levanta
  `PerfilNaoFecha` e não escreve nada.

Só biblioteca padrão, e nada de `src/`: quem confere o conjunto contra o
produto são os testes de `tests/demonstracao/`, não o gerador.

AS ATRIBUIÇÕES DE RENDA SIMULAM O TRABALHO MANUAL DO USUÁRIO. No app, quem
atribui uma receita a uma fonte é a pessoa, linha a linha, na aba Renda. A
lista que este gerador emite faz as vezes dessa pessoa na demonstração: cada
item aponta uma linha exata de um arquivo exato. Nenhum código do produto
atribui fonte.
"""

from __future__ import annotations

import argparse
import calendar
import json
import random
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PASTA = Path(__file__).resolve().parent
PASTA_EXTRATOS = "extratos"
ARQUIVO_CONJUNTO = "conjunto.json"

SEMENTE = 20261101
INICIO = date(2025, 9, 1)
FIM = date(2026, 10, 31)
REFERENCIA = FIM + timedelta(days=1)


class PerfilNaoFecha(Exception):
    """O conjunto gerado não cumpre o perfil declarado. A mensagem lista o
    que falhou. Nada é escrito."""


# ---------------------------------------------------------------------------
# O pool fictício — o mesmo de `src/data/models.py`
# ---------------------------------------------------------------------------

ANA, BRUNO = "Ana Quintela", "Bruno Quintela"
NOME_COMPLETO = {ANA: "Ana Quintela Moreira", BRUNO: "Bruno Quintela Moreira"}
APELIDOS = ["ana quintela", "ana quintela moreira",
            "bruno quintela", "bruno quintela moreira"]
ROTULO_DO_BANCO = {"NU": "Nubank (conta)", "C6": "C6 Bank (conta)",
                   "INTER": "Inter (conta)"}


@dataclass(frozen=True)
class Conta:
    banco: str
    numero: str
    dono: str
    abertura: int          # saldo em 31/08/2025, em centavos

    @property
    def rotulo(self) -> str:
        return f"{ROTULO_DO_BANCO[self.banco]} {self.numero}"


NU_ANA = Conta("NU", "99887766", ANA, 350_000)
C6_ANA = Conta("C6", "12345678", ANA, 150_000)
INTER_BRUNO = Conta("INTER", "87654321", BRUNO, 600_000)
NU_BRUNO = Conta("NU", "55667788", BRUNO, 150_000)
CONTAS = [NU_ANA, C6_ANA, INTER_BRUNO, NU_BRUNO]

# Cadastradas no pool, sem extrato no conjunto: quem transfere para elas
# fica com a perna solta.
INTER_ANA_SEM_EXTRATO = "11223344"
C6_BRUNO_SEM_EXTRATO = "44332211"

# O mês em que o extrato de uma conta não foi baixado.
MES_SEM_EXTRATO = (NU_BRUNO, 2026, 3)

# ---------------------------------------------------------------------------
# Quem aparece nos extratos
# ---------------------------------------------------------------------------

INSTITUICAO_DO_POOL = "INSTITUICAO FICTICIA (0999)"
INSTITUICOES = ["PAGAMENTOS AURORA IP (0998)",
                "COOPERATIVA DE CREDITO DO VALE (0997)",
                "FINANCEIRA HORIZONTE SA (0996)"]
# Palavras que, no nome da instituição, levariam um Pix de terceiro para
# "Serviços" pela regra de categorização.
PALAVRAS_VETADAS_NA_INSTITUICAO = ("banco", "bank", "tarifa", "taxa")

CPF_DE_MEMBRO = "•••.111.222-••"
CPF_DE_TERCEIRO = "•••.000.000-••"

EMPREGADOR = "EDITORA PAPEL E TINTA LTDA"
EMPRESA_DO_MEMBRO = "BRUNO QUINTELA TECNOLOGIA LTDA"
CLIENTES = ["MARE ALTA COMUNICACAO LTDA", "NORTE DIGITAL LTDA",
            "ATELIE TRES MARIAS LTDA"]
ALUNOS = ["Marina Duarte Farias", "Rafael Antunes Brito",
          "Livia Sampaio Rocha", "Tiago Bezerra Nunes"]

# Terceiros cujo nome ou sobrenome se sobrepõe ao de um membro. Nenhum pode
# ser lido como membro.
DIARISTA = "Carla Quintela Ramos"
TERCEIROS_PARECIDOS = [DIARISTA, "Ana Paula Ribeiro Lopes",
                       "Bruno Henrique Saldanha", "Felipe Quintela Prado",
                       "Diego Moreira Lopes"]

CIDADE = "VILA SERENA"

FONTES_DE_RENDA = [
    {"name": "Salário", "type": "fixa", "owner": ANA},
    {"name": "Pró-labore", "type": "fixa", "owner": BRUNO},
    {"name": "Serviços avulsos", "type": "variavel", "owner": BRUNO},
    {"name": "Aulas particulares", "type": "variavel", "owner": ANA},
    {"name": "Rendimentos", "type": "variavel", "owner": ""},
]
SALARIO, PRO_LABORE, AVULSOS, AULAS, RENDIMENTOS = (
    f["name"] for f in FONTES_DE_RENDA)

# Quantos serviços avulsos entram em cada mês, de set/2025 a out/2026. Os
# três zeros são os meses de saldo negativo.
AVULSOS_POR_MES = [2, 1, 2, 2, 0, 1, 2, 3, 1, 0, 2, 1, 2, 0]
MESES_NEGATIVOS = [(2026, 1), (2026, 6), (2026, 10)]

ABREVIATURA_DO_MES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                      "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


# ---------------------------------------------------------------------------
# Sorteio — só `random()`
# ---------------------------------------------------------------------------

class Sorteio:
    def __init__(self, semente: int):
        self._gerador = random.Random(semente)

    def fracao(self) -> float:
        return self._gerador.random()

    def inteiro(self, minimo: int, maximo: int) -> int:
        """Inteiro em [minimo, maximo], extremos incluídos."""
        return minimo + int(self.fracao() * (maximo - minimo + 1))

    def escolher(self, itens: list):
        return itens[int(self.fracao() * len(itens))]

    def chance(self, probabilidade: float) -> bool:
        return self.fracao() < probabilidade

    def hexadecimal(self, digitos: int) -> str:
        return "".join("0123456789abcdef"[self.inteiro(0, 15)]
                       for _ in range(digitos))

    def identificador(self) -> str:
        """Na forma do Identificador do Nubank (um UUID versão 4)."""
        h = self.hexadecimal
        return f"{h(8)}-{h(4)}-4{h(3)}-{'89ab'[self.inteiro(0, 3)]}{h(3)}-{h(12)}"


# ---------------------------------------------------------------------------
# O livro
# ---------------------------------------------------------------------------

@dataclass
class Lancamento:
    conta: Conta
    data: date
    centavos: int
    tipo: str                      # compra | pix | pagamento | credito | estorno | aplicacao | tarifa
    nome: str
    doc: str = ""
    instituicao: str = ""
    fonte: Optional[str] = None    # fonte de renda a atribuir
    membro: bool = False           # a descrição menciona um membro do pool
    evento: Optional[int] = None   # transferência: o mesmo número nas duas pernas
    identificador: str = ""        # Nubank
    contabil: Optional[date] = None    # C6: data contábil, quando difere
    ordem: int = 0
    saldo: int = 0                 # depois deste lançamento
    saldo_do_dia: int = 0          # C6: fechamento do dia contábil

    @property
    def dia_do_livro(self) -> date:
        return self.contabil or self.data


class Livro:
    def __init__(self, sorteio: Sorteio):
        self.s = sorteio
        self.lancamentos: List[Lancamento] = []
        self._evento = 0

    def lancar(self, conta: Conta, data: date, centavos: int, tipo: str,
               nome: str, **campos) -> Lancamento:
        assert INICIO <= data <= FIM, data
        assert centavos != 0
        lanc = Lancamento(conta=conta, data=data, centavos=centavos, tipo=tipo,
                          nome=nome, ordem=len(self.lancamentos), **campos)
        if conta.banco == "NU" and not lanc.identificador:
            lanc.identificador = self.s.identificador()
        self.lancamentos.append(lanc)
        return lanc

    def compra(self, conta: Conta, data: date, reais_centavos: int,
               comerciante: str, **campos) -> Lancamento:
        return self.lancar(conta, data, -reais_centavos, "compra", comerciante,
                           **campos)

    def pagamento(self, conta: Conta, data: date, centavos: int,
                  nome: str) -> Lancamento:
        return self.lancar(conta, data, -centavos, "pagamento", nome)

    def pix_de_terceiro(self, conta: Conta, data: date, centavos: int,
                        nome: str, empresa: bool = False,
                        fonte: Optional[str] = None) -> Lancamento:
        """Pix com alguém de fora do pool. `centavos` com sinal."""
        return self.lancar(
            conta, data, centavos, "pix", nome,
            doc=cnpj_inventado(nome) if empresa else CPF_DE_TERCEIRO,
            instituicao=self._instituicao_de(nome), fonte=fonte)

    def _instituicao_de(self, nome: str) -> str:
        indice = sum(ord(c) for c in nome)
        conta = 1_000_000 + (indice * 7919) % 8_999_999
        return (f"{INSTITUICOES[indice % len(INSTITUICOES)]} "
                f"Agência: 1 Conta: {conta}-{indice % 9}")

    def transferir(self, origem: Conta, destino: Conta, data: date,
                   centavos: int) -> None:
        """Transferência entre duas contas do pool que têm extrato."""
        self._evento += 1
        self.lancar(origem, data, -centavos, "pix", NOME_COMPLETO[destino.dono],
                    doc=CPF_DE_MEMBRO, membro=True, evento=self._evento,
                    instituicao=f"{INSTITUICAO_DO_POOL} Agência: 1 Conta: "
                                f"{destino.numero}-0")
        self.lancar(destino, data, centavos, "pix", NOME_COMPLETO[origem.dono],
                    doc=CPF_DE_MEMBRO, membro=True, evento=self._evento,
                    instituicao=f"{INSTITUICAO_DO_POOL} Agência: 1 Conta: "
                                f"{origem.numero}-0")

    def perna_solta(self, conta: Conta, data: date, centavos: int, nome: str,
                    numero_do_outro_lado: str, empresa: bool = False,
                    fonte: Optional[str] = None) -> Lancamento:
        """
        Movimento com alguém que o pool reconhece — um membro, numa conta
        sem extrato, ou a empresa de um membro — e cuja contraparte não está
        no conjunto. `centavos` com sinal.
        """
        return self.lancar(
            conta, data, centavos, "pix", nome,
            doc=cnpj_inventado(nome) if empresa else CPF_DE_MEMBRO,
            membro=True, fonte=fonte,
            instituicao=f"{INSTITUICAO_DO_POOL} Agência: 1 Conta: "
                        f"{numero_do_outro_lado}-0")


# ---------------------------------------------------------------------------
# Utilidades de texto e de dinheiro
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Sem acento, minúsculo, só letras, dígitos e espaço simples — a mesma
    normalização que o produto aplica antes de procurar um apelido."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", sem_acento.lower()).split())


def titulo(nome: str) -> str:
    return " ".join(p.capitalize() for p in nome.split())


def digitos_verificadores_do_cnpj(doze: str) -> str:
    base = doze
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                  [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        base += str(0 if resto < 2 else 11 - resto)
    return base[12:]


def cnpj_inventado(nome: str) -> str:
    """Um CNPJ que NÃO EXISTE: o dígito verificador é errado de propósito."""
    semente = sum((i + 1) * ord(c) for i, c in enumerate(nome))
    doze = f"{10_000_000 + semente * 104_729 % 89_999_999:08d}0001"
    certos = digitos_verificadores_do_cnpj(doze)
    errados = f"{(int(certos) + 37) % 100:02d}"
    assert errados != certos
    return f"{doze[:2]}.{doze[2:5]}.{doze[5:8]}/{doze[8:12]}-{errados}"


def reais_com_ponto(centavos: int) -> str:
    """12345 -> '123.45'; -5 -> '-0.05'."""
    sinal = "-" if centavos < 0 else ""
    return f"{sinal}{abs(centavos) // 100}.{abs(centavos) % 100:02d}"


def reais_com_virgula(centavos: int) -> str:
    """123456 -> '1.234,56'; -1000 -> '-10,00'."""
    sinal = "-" if centavos < 0 else ""
    inteiro = f"{abs(centavos) // 100:,}".replace(",", ".")
    return f"{sinal}{inteiro},{abs(centavos) % 100:02d}"


def dia_do_mes(ano: int, mes: int, dia: int) -> date:
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def meses_do_periodo() -> List[Tuple[int, int]]:
    meses, ano, mes = [], INICIO.year, INICIO.month
    while (ano, mes) <= (FIM.year, FIM.month):
        meses.append((ano, mes))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def chave_do_mes(d: date) -> str:
    """'MM/AAAA', como o app nomeia o mês."""
    return f"{d.month:02d}/{d.year}"


# ---------------------------------------------------------------------------
# O que acontece em cada mês
# ---------------------------------------------------------------------------

def montar_livro() -> Livro:
    s = Sorteio(SEMENTE)
    livro = Livro(s)

    def valor(minimo_reais: int, maximo_reais: int) -> int:
        """Um valor em centavos entre os dois limites, em reais."""
        return s.inteiro(minimo_reais * 100, maximo_reais * 100)

    def varias(conta, ano, mes, quantas, minimo, maximo, comerciantes):
        ultimo = calendar.monthrange(ano, mes)[1]
        for _ in range(quantas):
            livro.compra(conta, date(ano, mes, s.inteiro(1, ultimo)),
                         valor(minimo, maximo), s.escolher(comerciantes))

    for indice, (ano, mes) in enumerate(meses_do_periodo()):
        d = lambda dia: dia_do_mes(ano, mes, dia)  # noqa: E731
        ultimo = calendar.monthrange(ano, mes)[1]
        mes_do_buraco = (ano, mes) == MES_SEM_EXTRATO[1:]

        # --- Ana, Nubank: o salário e o dia a dia -------------------------
        livro.pix_de_terceiro(NU_ANA, d(5), 520_000, EMPREGADOR, empresa=True,
                              fonte=SALARIO)
        livro.transferir(NU_ANA, INTER_BRUNO, d(6), 130_000)
        livro.pix_de_terceiro(NU_ANA, d(8), -48_000, "PLANO SAUDE VIDA PLENA",
                              empresa=True)
        livro.pix_de_terceiro(NU_ANA, d(10), -42_000,
                              "ESCOLA DE IDIOMAS HORIZONTE", empresa=True)
        livro.compra(NU_ANA, d(12), 3_990, "CLARAVISTA STREAMING")
        livro.compra(NU_ANA, d(15), 9_990, "ACADEMIA CORPO ATIVO")
        livro.pix_de_terceiro(NU_ANA, d(18), -19_000, DIARISTA)
        livro.transferir(NU_ANA, C6_ANA, d(20), 50_000)
        varias(NU_ANA, ano, mes, s.inteiro(5, 7), 90, 330,
               ["SUPERMERCADO BOA SAFRA", "HORTIFRUTI BOA COLHEITA",
                "ACOUGUE DO VALE"])
        varias(NU_ANA, ano, mes, s.inteiro(4, 6), 9, 38,
               ["PADARIA FLOR DE TRIGO", "ACAI LUA CHEIA"])
        varias(NU_ANA, ano, mes, s.inteiro(1, 3), 22, 140,
               ["DROGARIA SAO JUDAS", "FARMACIA BEM ESTAR"])
        varias(NU_ANA, ano, mes, s.inteiro(0, 2), 18, 120,
               ["ARMARINHO TRES PONTAS", "FLORICULTURA JARDIM SECRETO",
                "CHAVEIRO DO BAIRRO"])
        if s.chance(0.35):
            livro.compra(NU_ANA, d(s.inteiro(1, ultimo)), valor(150, 350),
                         "CLINICA BEM VIVER")

        # --- Ana, C6: cartão e aulas --------------------------------------
        restaurantes = ["RESTAURANTE VALE VERDE", "BAR DO MIRANTE",
                        "CHURRASCARIA BRASA VIVA"]
        for n in range(s.inteiro(2, 3)):
            quando = d(s.inteiro(2, ultimo - 2))
            compra = livro.compra(C6_ANA, quando, valor(55, 160),
                                  s.escolher(restaurantes))
            if n == 0 and (ano, mes) in ((2026, 2), (2026, 8)):
                # Lançada num dia e contabilizada na véspera: é o caso que
                # separa a Data Lançamento da Data Contábil no extrato do C6.
                compra.contabil = compra.data - timedelta(days=1)
        varias(C6_ANA, ano, mes, s.inteiro(0, 2), 70, 260,
               ["LOJA DE ROUPAS AURORA", "MODA E ESTILO BOUTIQUE"])
        if s.chance(0.5):
            livro.compra(C6_ANA, d(s.inteiro(1, ultimo)), valor(35, 120),
                         "LIVRARIA PAGINA VIRADA")
        livro.lancar(C6_ANA, d(25), -20_000, "aplicacao",
                     "Aplicacao Fundo Reserva")
        for _ in range(s.inteiro(0, 4)):
            livro.pix_de_terceiro(C6_ANA, d(s.inteiro(1, ultimo)),
                                  s.inteiro(8, 24) * 1_000, s.escolher(ALUNOS),
                                  fonte=AULAS)

        # --- Bruno, Inter: a casa e o pró-labore --------------------------
        livro.lancar(INTER_BRUNO, d(2), -1_200, "tarifa",
                     "PACOTE DE SERVICOS MENSAL")
        livro.pagamento(INTER_BRUNO, d(7), 190_000,
                        "ALUGUEL IMOBILIARIA HORIZONTE")
        livro.pagamento(INTER_BRUNO, d(7), 62_000,
                        "CONDOMINIO JARDIM DAS ACACIAS")
        livro.perna_solta(INTER_BRUNO, d(10), 280_000, EMPRESA_DO_MEMBRO,
                          "70010020", empresa=True, fonte=PRO_LABORE)
        livro.transferir(INTER_BRUNO, NU_BRUNO, d(12), 60_000)
        livro.pagamento(INTER_BRUNO, d(14), valor(180, 320),
                        "COMPANHIA DE ENERGIA DO VALE")
        livro.pagamento(INTER_BRUNO, d(14), valor(85, 150),
                        "SANEAMENTO DO VALE")
        livro.pagamento(INTER_BRUNO, d(16), 11_990, "INTERNET FIBRA VELOZ")
        livro.pagamento(INTER_BRUNO, d(16), 11_980, "CELULAR LINHA MOVEL")
        livro.lancar(INTER_BRUNO, d(28), s.inteiro(1_800, 5_800), "credito",
                     "RENDIMENTO DA CONTA", fonte=RENDIMENTOS)

        # --- Bruno, Nubank: rua -------------------------------------------
        varias(NU_BRUNO, ano, mes, s.inteiro(2, 3), 150, 240,
               ["POSTO ESTRELA DALVA", "POSTO TREVO DOURADO"])
        varias(NU_BRUNO, ano, mes, s.inteiro(2, 4), 14, 42,
               ["LANCHONETE PONTO CERTO", "PADARIA FLOR DE TRIGO"])
        varias(NU_BRUNO, ano, mes, s.inteiro(1, 3), 8, 25,
               ["ESTACIONAMENTO PATIO CENTRAL"])
        varias(NU_BRUNO, ano, mes, s.inteiro(0, 2), 18, 48,
               ["COOPERATIVA DE TAXI AURORA"])
        varias(NU_BRUNO, ano, mes, s.inteiro(0, 2), 40, 160,
               ["CINEMA ESTACAO DAS ARTES", "MUSEU DA IMAGEM VIVA"])
        varias(NU_BRUNO, ano, mes, s.inteiro(0, 2), 20, 150,
               ["BARBEARIA NAVALHA DE OURO", "BANCA DE REVISTAS CENTRAL"])
        if s.chance(0.4):
            livro.compra(NU_BRUNO, d(s.inteiro(1, ultimo)), valor(9, 28),
                         "PEDAGIO RODOVIA DAS FLORES")

        # --- Serviços avulsos do Bruno ------------------------------------
        for n in range(AVULSOS_POR_MES[indice]):
            # Mais recebimentos pequenos do que grandes, entre R$ 400 e R$ 2.500.
            recebido = (40 + int(s.fracao() ** 2 * 210)) * 1_000
            conta = INTER_BRUNO if (n % 2 == 0 or mes_do_buraco) else NU_BRUNO
            livro.pix_de_terceiro(conta, d(s.inteiro(3, ultimo - 2)), recebido,
                                  s.escolher(CLIENTES), empresa=True,
                                  fonte=AVULSOS)

        _fatos_do_mes(livro, ano, mes, d)

    return livro


def _fatos_do_mes(livro: Livro, ano: int, mes: int, d) -> None:
    """O que não se repete: os meses de saldo negativo, os aportes na
    empresa, os estornos, as pernas soltas e os Pix de terceiros."""
    quando = (ano, mes)

    if quando == (2025, 9):
        livro.compra(NU_ANA, INICIO, 1_450, "PADARIA FLOR DE TRIGO")

    if quando == (2025, 11):
        compra = livro.compra(NU_ANA, d(11), 18_990, "LOJA DE ROUPAS AURORA")
        livro.lancar(NU_ANA, d(14), 18_990, "estorno", "LOJA DE ROUPAS AURORA",
                     identificador=compra.identificador)
        livro.perna_solta(INTER_BRUNO, d(18), -150_000, EMPRESA_DO_MEMBRO,
                          "70010020", empresa=True)

    if quando == (2025, 12):
        livro.perna_solta(NU_ANA, d(15), -100_000, NOME_COMPLETO[ANA],
                          INTER_ANA_SEM_EXTRATO)
        livro.pix_de_terceiro(NU_ANA, d(22), 12_000, "Ana Paula Ribeiro Lopes")

    if quando == (2026, 1):          # saldo negativo: impostos e seguro
        livro.pagamento(INTER_BRUNO, d(9), 148_000, "IPVA COTA UNICA")
        livro.pagamento(INTER_BRUNO, d(13), 195_000,
                        "SEGURO AUTO ESTRADA SEGURA")
        livro.pagamento(INTER_BRUNO, d(20), 115_000,
                        "IPTU PREFEITURA MUNICIPAL")
        livro.compra(NU_ANA, d(22), 42_000, "PAPELARIA PONTO E VIRGULA")

    if quando == (2026, 2):
        livro.perna_solta(INTER_BRUNO, d(17), 45_000, NOME_COMPLETO[BRUNO],
                          C6_BRUNO_SEM_EXTRATO)
        livro.pagamento(INTER_BRUNO, d(24), 8_640, "CARTORIO PRIMEIRO OFICIO")

    if quando == (2026, 3):
        livro.pix_de_terceiro(INTER_BRUNO, d(8), 35_000, "Diego Moreira Lopes")
        livro.transferir(NU_ANA, NU_BRUNO, d(21), 25_000)

    if quando == (2026, 4):
        livro.perna_solta(INTER_BRUNO, d(22), -200_000, EMPRESA_DO_MEMBRO,
                          "70010020", empresa=True)

    if quando == (2026, 5):
        livro.pix_de_terceiro(NU_BRUNO, d(10), -7_500, "Felipe Quintela Prado")
        livro.perna_solta(INTER_BRUNO, d(26), -30_000, NOME_COMPLETO[BRUNO],
                          C6_BRUNO_SEM_EXTRATO)

    if quando == (2026, 6):          # saldo negativo: viagem
        livro.transferir(NU_ANA, C6_ANA, d(2), 250_000)
        livro.pix_de_terceiro(NU_ANA, d(4), -179_000,
                              "AGENCIA DE VIAGEM ROTA SUL", empresa=True)
        livro.compra(C6_ANA, d(12), 238_000, "HOTEL PRAIA DO SOSSEGO")
        livro.compra(C6_ANA, d(13), 18_000, "RESTAURANTE VALE VERDE")
        livro.compra(C6_ANA, d(14), 14_500, "CHURRASCARIA BRASA VIVA")

    if quando == (2026, 7):
        livro.perna_solta(NU_ANA, d(9), 80_000, NOME_COMPLETO[ANA],
                          INTER_ANA_SEM_EXTRATO)

    if quando == (2026, 8):
        compra = livro.compra(NU_BRUNO, d(5), 7_450, "CINEMA ESTACAO DAS ARTES")
        livro.lancar(NU_BRUNO, d(6), 7_450, "estorno",
                     "CINEMA ESTACAO DAS ARTES",
                     identificador=compra.identificador)
        livro.pix_de_terceiro(INTER_BRUNO, d(19), 8_000,
                              "Bruno Henrique Saldanha")

    if quando == (2026, 9):
        livro.perna_solta(INTER_BRUNO, d(15), -120_000, EMPRESA_DO_MEMBRO,
                          "70010020", empresa=True)

    if quando == (2026, 10):         # saldo negativo: o carro
        livro.transferir(INTER_BRUNO, NU_BRUNO, d(7), 400_000)
        livro.compra(NU_BRUNO, d(8), 290_000, "OFICINA TRES IRMAOS")
        livro.compra(NU_BRUNO, d(9), 138_000, "CASA DOS PNEUS RODA VIVA")
        livro.compra(NU_ANA, d(16), 64_000, "CLINICA BEM VIVER")
        livro.compra(NU_ANA, FIM, 21_730, "SUPERMERCADO BOA SAFRA")


# ---------------------------------------------------------------------------
# Do livro aos arquivos
# ---------------------------------------------------------------------------

@dataclass
class Arquivo:
    nome: str
    conta: Conta
    inicio: date
    fim: date
    linhas: List[Lancamento] = field(default_factory=list)   # na ordem do arquivo


def fechar_saldos(livro: Livro) -> Dict[str, List[Lancamento]]:
    """Ordena o livro de cada conta e calcula o saldo linha a linha."""
    por_conta: Dict[str, List[Lancamento]] = {}
    for conta in CONTAS:
        linhas = sorted((l for l in livro.lancamentos if l.conta is conta),
                        key=lambda l: (l.dia_do_livro, l.ordem))
        saldo = conta.abertura
        for l in linhas:
            saldo += l.centavos
            l.saldo = saldo
        fechamento: Dict[date, int] = {}
        for l in linhas:
            fechamento[l.dia_do_livro] = l.saldo
        for l in linhas:
            l.saldo_do_dia = fechamento[l.dia_do_livro]
        por_conta[conta.numero] = linhas
    return por_conta


def planejar_arquivos() -> List[Arquivo]:
    arquivos: List[Arquivo] = []

    def nubank(conta: Conta, inicio: date, fim: date) -> Arquivo:
        def parte(x: date) -> str:
            return f"{x.day:02d}{ABREVIATURA_DO_MES[x.month - 1]}{x.year}"
        return Arquivo(f"NU_{conta.numero}_{parte(inicio)}_{parte(fim)}.csv",
                       conta, inicio, fim)

    def com_a_conta(conta: Conta, inicio: date, fim: date) -> Arquivo:
        # C6 e Inter: nome próprio da demonstração, com a conta. Não é a
        # forma que esses bancos dão aos arquivos de verdade, de propósito.
        return Arquivo(f"{conta.banco}_{conta.numero}_{inicio.isoformat()}"
                       f"_a_{fim.isoformat()}.csv", conta, inicio, fim)

    for ano, mes in meses_do_periodo():
        inicio = date(ano, mes, 1)
        fim = dia_do_mes(ano, mes, 31)
        arquivos.append(nubank(NU_ANA, inicio, fim))
        if (NU_BRUNO, ano, mes) != MES_SEM_EXTRATO:
            arquivos.append(nubank(NU_BRUNO, inicio, fim))
    # Um extrato pedido no meio do mês, por cima de dois mensais.
    arquivos.append(nubank(NU_ANA, date(2026, 6, 15), date(2026, 7, 15)))

    for inicio, fim in ((INICIO, date(2025, 12, 31)),
                        (date(2025, 12, 1), date(2026, 3, 31)),   # sobrepõe dezembro
                        (date(2026, 4, 1), date(2026, 7, 31)),
                        (date(2026, 8, 1), FIM)):
        arquivos.append(com_a_conta(C6_ANA, inicio, fim))

    for inicio, fim in ((INICIO, date(2025, 12, 15)),
                        (date(2025, 12, 1), date(2026, 3, 31)),   # sobrepõe 1 a 15/12
                        (date(2026, 4, 1), date(2026, 6, 30)),
                        (date(2026, 7, 1), FIM)):
        arquivos.append(com_a_conta(INTER_BRUNO, inicio, fim))

    return sorted(arquivos, key=lambda a: a.nome)


def preencher(arquivos: List[Arquivo],
              por_conta: Dict[str, List[Lancamento]]) -> None:
    for arquivo in arquivos:
        fatia = [l for l in por_conta[arquivo.conta.numero]
                 if arquivo.inicio <= l.dia_do_livro <= arquivo.fim]
        # O Inter entrega o extrato do mais novo para o mais velho.
        arquivo.linhas = (list(reversed(fatia))
                          if arquivo.conta.banco == "INTER" else fatia)


def _data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _descricao_nubank(l: Lancamento) -> str:
    if l.tipo == "compra":
        return f"Compra no débito - {l.nome}"
    if l.tipo == "estorno":
        return f"Estorno - Compra no débito - {l.nome}"
    if l.tipo == "pix":
        sentido = "enviada" if l.centavos < 0 else "recebida"
        return (f"Transferência {sentido} pelo Pix - {l.nome} - {l.doc} - "
                f"{l.instituicao}")
    raise AssertionError(l.tipo)


def _campos_inter(l: Lancamento) -> Tuple[str, str]:
    if l.tipo == "compra":
        return "Compra no débito", titulo(l.nome)
    if l.tipo == "pagamento":
        return "Pagamento efetuado", titulo(l.nome)
    if l.tipo == "pix":
        return ("Pix enviado " if l.centavos < 0 else "Pix recebido",
                titulo(l.nome))
    if l.tipo == "tarifa":
        return "Tarifa", titulo(l.nome)
    if l.tipo == "credito":
        return "Crédito de rendimento", titulo(l.nome)
    raise AssertionError(l.tipo)


def _campos_c6(l: Lancamento) -> Tuple[str, str]:
    if l.tipo == "compra":
        return '"DEBITO DE CARTAO "', f"{l.nome}    {CIDADE}      BRA"
    if l.tipo == "aplicacao":
        return l.nome, l.nome
    if l.tipo == "pix" and l.centavos < 0:
        return f"Pix enviado para {l.nome}", "TRANSF ENVIADA PIX"
    if l.tipo == "pix":
        return f"Pix recebido de {l.nome}", f"Pix recebido de {l.nome}"
    raise AssertionError(l.tipo)


def bytes_do_arquivo(arquivo: Arquivo) -> bytes:
    banco = arquivo.conta.banco
    if banco == "NU":
        linhas = ["Data,Valor,Identificador,Descrição"]
        for l in arquivo.linhas:
            descricao = _descricao_nubank(l)
            assert "," not in descricao and '"' not in descricao, descricao
            linhas.append(f"{_data(l.data)},{reais_com_ponto(l.centavos)},"
                          f"{l.identificador},{descricao}")
        return ("\n".join(linhas) + "\n").encode("utf-8")

    if banco == "INTER":
        fechamento = arquivo.linhas[0].saldo
        linhas = [" Extrato Conta Corrente ",
                  f"Conta ;{arquivo.conta.numero}",
                  f"Período ;{_data(arquivo.inicio)} a {_data(arquivo.fim)}",
                  f"Saldo ;{reais_com_virgula(fechamento)}",
                  "",
                  "Data Lançamento;Histórico;Descrição;Valor;Saldo"]
        for l in arquivo.linhas:
            historico, descricao = _campos_inter(l)
            assert ";" not in historico + descricao
            linhas.append(f"{_data(l.data)};{historico};{descricao};"
                          f"{reais_com_virgula(l.centavos)};"
                          f"{reais_com_virgula(l.saldo)}")
        return ("\n".join(linhas) + "\n").encode("utf-8")

    if banco == "C6":
        linhas = ["EXTRATO DE CONTA CORRENTE C6 BANK", "",
                  f"Agência: 1 / Conta: {arquivo.conta.numero}",
                  f"Extrato gerado em {_data(REFERENCIA)} - as 09:00:00", "",
                  f"Extrato de {_data(arquivo.inicio)} a {_data(arquivo.fim)}",
                  "", "",
                  "Data Lançamento,Data Contábil,Título,Descrição,"
                  "Entrada(R$),Saída(R$),Saldo do Dia(R$)"]
        for l in arquivo.linhas:
            titulo_c6, descricao = _campos_c6(l)
            assert "," not in titulo_c6 + descricao
            entrada = max(l.centavos, 0)
            saida = max(-l.centavos, 0)
            linhas.append(f"{_data(l.data)},{_data(l.dia_do_livro)},"
                          f"{titulo_c6},{descricao},"
                          f"{reais_com_ponto(entrada)},{reais_com_ponto(saida)},"
                          f"{reais_com_ponto(l.saldo_do_dia)}")
        # BOM e CRLF, como o C6 grava.
        return b"\xef\xbb\xbf" + ("\r\n".join(linhas) + "\r\n").encode("utf-8")

    raise AssertionError(banco)


# ---------------------------------------------------------------------------
# O que o conjunto tem de dar — a conta feita pelo gerador
# ---------------------------------------------------------------------------

def _descricao_como_o_produto_le(l: Lancamento) -> str:
    """A descrição que o parser monta de cada linha, para as checagens de
    apelido. Aproximação suficiente: o que importa é o nome da contraparte."""
    if l.conta.banco == "NU":
        return _descricao_nubank(l)
    if l.conta.banco == "INTER":
        return " - ".join(p.strip() for p in _campos_inter(l))
    campos = _campos_c6(l)
    return " - ".join(p.strip().strip('"').strip() for p in campos)


def menciona_membro(l: Lancamento) -> bool:
    texto = normalizar(_descricao_como_o_produto_le(l))
    return any(apelido in texto for apelido in APELIDOS)


def calcular(livro: Livro, arquivos: List[Arquivo]) -> dict:
    """Os números do conjunto, pelo modelo do gerador — sem o produto."""
    exportadas: List[Lancamento] = []
    vistos = set()
    for arquivo in arquivos:
        for l in arquivo.linhas:
            if id(l) not in vistos:
                vistos.add(id(l))
                exportadas.append(l)

    por_evento: Dict[int, List[Lancamento]] = {}
    for l in exportadas:
        if l.evento is not None:
            por_evento.setdefault(l.evento, []).append(l)
    pareadas = {id(l) for pernas in por_evento.values() if len(pernas) == 2
                for l in pernas}

    por_identificador: Dict[str, List[Lancamento]] = {}
    for l in exportadas:
        if l.identificador:
            por_identificador.setdefault(l.identificador, []).append(l)
    em_estorno = {id(l) for grupo in por_identificador.values()
                  if len(grupo) == 2 for l in grupo}
    avulsos = [l for l in exportadas
               if l.tipo == "estorno" and id(l) not in em_estorno]

    neutras = pareadas | em_estorno
    contam = [l for l in exportadas if id(l) not in neutras]
    candidatas = [l for l in exportadas if menciona_membro(l)]
    pendentes = [l for l in candidatas if id(l) not in pareadas]
    da_empresa = [l for l in pendentes if l.nome == EMPRESA_DO_MEMBRO]

    receitas = [l for l in contam if l.centavos > 0]
    despesas = [l for l in contam if l.centavos < 0]
    saldo_por_mes: Dict[str, int] = {}
    for ano, mes in meses_do_periodo():
        saldo_por_mes[f"{mes:02d}/{ano}"] = 0
    for l in contam:
        saldo_por_mes[chave_do_mes(l.data)] += l.centavos

    renda_por_fonte = {f["name"]: 0 for f in FONTES_DE_RENDA}
    for l in receitas:
        if l.fonte:
            renda_por_fonte[l.fonte] += l.centavos
    tipo_da_fonte = {f["name"]: f["type"] for f in FONTES_DE_RENDA}
    renda_fixa = sum(v for n, v in renda_por_fonte.items()
                     if tipo_da_fonte[n] == "fixa")
    renda_variavel = sum(v for n, v in renda_por_fonte.items()
                         if tipo_da_fonte[n] == "variavel")

    cobertura: Dict[str, Dict[str, int]] = {}
    for l in exportadas:
        meses = cobertura.setdefault(l.conta.rotulo, {})
        meses[chave_do_mes(l.data)] = meses.get(chave_do_mes(l.data), 0) + 1

    return {
        "_exportadas": exportadas, "_pareadas": pareadas, "_neutras": neutras,
        "_candidatas": candidatas, "_pendentes": pendentes,
        "_estornos_avulsos": avulsos,
        "linhas_nos_arquivos": sum(len(a.linhas) for a in arquivos),
        "transacoes": len(exportadas),
        "duplicatas": sum(len(a.linhas) for a in arquivos) - len(exportadas),
        "pares_conciliados": len(pareadas) // 2,
        "pendencias": len(pendentes),
        "pendencias_da_empresa": len(da_empresa),
        "pendencias_de_outras_origens": len(pendentes) - len(da_empresa),
        "transacoes_em_estorno": len(em_estorno),
        "receitas_sem_fonte": sum(1 for l in receitas if not l.fonte),
        "total_receitas_centavos": sum(l.centavos for l in receitas),
        "total_despesas_centavos": -sum(l.centavos for l in despesas),
        "saldo_por_mes_centavos": saldo_por_mes,
        "meses_negativos": [m for m, v in saldo_por_mes.items() if v < 0],
        "renda_por_fonte_centavos": renda_por_fonte,
        "renda_fixa_centavos": renda_fixa,
        "renda_variavel_centavos": renda_variavel,
        "transacoes_por_conta_e_mes": cobertura,
        "primeiro_lancamento": min(l.data for l in exportadas).isoformat(),
        "ultimo_lancamento": max(l.data for l in exportadas).isoformat(),
    }


def deixar_receitas_sem_fonte(livro: Livro, arquivos: List[Arquivo]) -> None:
    """
    Parte das receitas fica sem fonte de propósito: as mais recentes de três
    fontes, como numa base em que o usuário ainda não classificou o fim do
    último mês.
    """
    exportadas = {id(l) for a in arquivos for l in a.linhas}
    for fonte in (AVULSOS, AULAS, RENDIMENTOS):
        da_fonte = [l for l in livro.lancamentos
                    if l.fonte == fonte and id(l) in exportadas]
        max(da_fonte, key=lambda l: (l.data, l.ordem)).fonte = None


def atribuicoes(arquivos: List[Arquivo]) -> List[dict]:
    """
    Uma atribuição por receita com fonte: o arquivo e a linha em que ela
    SOBREVIVE quando os arquivos são importados em ordem crescente de nome.
    A linha é a posição entre as linhas de dados, a partir de 1 — a mesma
    numeração de `raw_data['row_number']` no produto.
    """
    lista, vistos = [], set()
    for arquivo in sorted(arquivos, key=lambda a: a.nome):
        for numero, l in enumerate(arquivo.linhas, 1):
            if id(l) in vistos:
                continue
            vistos.add(id(l))
            if l.fonte:
                lista.append({"arquivo": arquivo.nome, "linha": numero,
                              "data": l.data.isoformat(),
                              "valor": reais_com_ponto(l.centavos),
                              "fonte": l.fonte})
    return sorted(lista, key=lambda a: (a["data"], a["arquivo"], a["linha"]))


def conferir_perfil(livro: Livro, arquivos: List[Arquivo],
                    por_conta: Dict[str, List[Lancamento]],
                    numeros: dict) -> None:
    falhas: List[str] = []

    def exigir(condicao: bool, mensagem: str):
        if not condicao:
            falhas.append(mensagem)

    nomes = [a.nome for a in arquivos]
    exigir(len(set(nomes)) == len(nomes), "nome de arquivo repetido")
    exigir(all(a.linhas for a in arquivos),
           "arquivo sem linha: %s" % [a.nome for a in arquivos if not a.linhas])
    exigir(numeros["primeiro_lancamento"] == INICIO.isoformat(),
           "o primeiro lançamento não é o início do período")
    exigir(numeros["ultimo_lancamento"] == FIM.isoformat(),
           "o último lançamento não é o fim do período")
    exigir(600 <= numeros["transacoes"] <= 900,
           "volume fora de 600 a 900: %d" % numeros["transacoes"])

    for conta in CONTAS:
        minimo = min(l.saldo for l in por_conta[conta.numero])
        exigir(minimo >= 0, "saldo negativo na conta %s: %s" % (
            conta.numero, reais_com_virgula(minimo)))

    esperados = [f"{m:02d}/{a}" for a, m in MESES_NEGATIVOS]
    exigir(numeros["meses_negativos"] == esperados,
           "meses de saldo negativo: %s (queria %s); saldos: %s" % (
               numeros["meses_negativos"], esperados,
               {m: reais_com_virgula(v)
                for m, v in numeros["saldo_por_mes_centavos"].items()}))

    receitas, despesas = (numeros["total_receitas_centavos"],
                          numeros["total_despesas_centavos"])
    poupanca = (receitas - despesas) / receitas * 100
    exigir(5 <= poupanca <= 15, "taxa de poupança fora de 5%% a 15%%: %.2f%%" % poupanca)

    atribuida = numeros["renda_fixa_centavos"] + numeros["renda_variavel_centavos"]
    fixa = numeros["renda_fixa_centavos"] / atribuida * 100
    exigir(75 <= fixa <= 85, "renda fixa fora de 75%% a 85%%: %.2f%%" % fixa)

    exigir(6 <= numeros["receitas_sem_fonte"] <= 10,
           "receitas sem fonte fora de 6 a 10: %d" % numeros["receitas_sem_fonte"])
    exigir(numeros["pares_conciliados"] >= 20,
           "menos de 20 pares: %d" % numeros["pares_conciliados"])
    exigir(numeros["pendencias_da_empresa"] >= 16,
           "pernas da empresa: %d" % numeros["pendencias_da_empresa"])
    exigir(4 <= numeros["pendencias_de_outras_origens"] <= 8,
           "pernas soltas de outras origens fora de 4 a 8: %d"
           % numeros["pendencias_de_outras_origens"])
    exigir(numeros["transacoes_em_estorno"] == 4, "estornos pareados: %d linhas"
           % numeros["transacoes_em_estorno"])
    exigir(not numeros["_estornos_avulsos"], "há estorno avulso")

    # Só quem deve mencionar membro menciona.
    for l in numeros["_exportadas"]:
        exigir(menciona_membro(l) == l.membro,
               "menção a membro inesperada em %s: %s" % (
                   l.data, _descricao_como_o_produto_le(l)))
    for nome in TERCEIROS_PARECIDOS + ALUNOS + CLIENTES + [EMPREGADOR]:
        exigir(not any(a in normalizar(nome) for a in APELIDOS),
               "terceiro que seria lido como membro: %s" % nome)

    # Nenhuma perna pode achar par por acidente: o produto pareia duas
    # candidatas de contas diferentes, na mesma data, com valores opostos.
    for l in numeros["_candidatas"]:
        iguais = [o for o in numeros["_candidatas"]
                  if o is not l and o.data == l.data
                  and o.centavos == -l.centavos and o.conta is not l.conta]
        if id(l) in numeros["_pareadas"]:
            exigir(len(iguais) == 1 and iguais[0].evento == l.evento,
                   "perna de %s com mais de um par possível" % l.data)
        else:
            exigir(not iguais, "perna solta de %s parearia por acidente" % l.data)

    for nome in [INSTITUICAO_DO_POOL] + INSTITUICOES:
        exigir(not any(p in normalizar(nome).split()
                       for p in PALAVRAS_VETADAS_NA_INSTITUICAO),
               "instituição com palavra vetada: %s" % nome)

    # Estorno e reembolso só nas duas linhas de estorno.
    for l in numeros["_exportadas"]:
        texto = normalizar(_descricao_como_o_produto_le(l))
        marca = (texto.startswith("estorno") or " estorno " in f" {texto} "
                 or texto.startswith("devolucao pix")
                 or texto.startswith("reembolso"))
        exigir(marca == (l.tipo == "estorno"),
               "marca de estorno inesperada: %s" % texto)

    if falhas:
        raise PerfilNaoFecha("o perfil não fecha:\n  - " + "\n  - ".join(falhas))


# ---------------------------------------------------------------------------
# Gerar, escrever, conferir
# ---------------------------------------------------------------------------

def gerar() -> Dict[str, bytes]:
    """{caminho relativo: bytes} do conjunto inteiro. Não toca no disco."""
    livro = montar_livro()
    por_conta = fechar_saldos(livro)
    arquivos = planejar_arquivos()
    preencher(arquivos, por_conta)
    deixar_receitas_sem_fonte(livro, arquivos)
    numeros = calcular(livro, arquivos)
    conferir_perfil(livro, arquivos, por_conta, numeros)

    conjunto = {
        "o_que_e": ("Conjunto de demonstração do Financial Analyzer. Tudo aqui "
                    "é inventado: pessoas, contas, empresas, comerciantes, "
                    "valores e datas."),
        "gerado_por": "demonstracao/gerar.py",
        "semente": SEMENTE,
        "periodo": [INICIO.isoformat(), FIM.isoformat()],
        "data_de_referencia": REFERENCIA.isoformat(),
        "contas_com_extrato": [c.rotulo for c in CONTAS],
        "arquivos": [{"nome": a.nome, "conta": a.conta.rotulo,
                      "linhas": len(a.linhas)} for a in arquivos],
        "fontes_de_renda": FONTES_DE_RENDA,
        "sobre_as_atribuicoes": (
            "Simulam o trabalho manual do usuário, que no app atribui cada "
            "receita a uma fonte, linha a linha, na aba Renda. Cada item "
            "aponta uma linha exata de um arquivo exato; data e valor são "
            "conferência. Nenhum código do produto atribui fonte."),
        "atribuicoes": atribuicoes(arquivos),
        "receitas_sem_fonte": numeros["receitas_sem_fonte"],
        "esperado": {k: v for k, v in numeros.items()
                     if not k.startswith("_") and k != "receitas_sem_fonte"},
    }

    saida = {f"{PASTA_EXTRATOS}/{a.nome}": bytes_do_arquivo(a) for a in arquivos}
    saida[ARQUIVO_CONJUNTO] = (json.dumps(conjunto, ensure_ascii=False, indent=2)
                               + "\n").encode("utf-8")
    return saida


def escrever(destino: Path, saida: Dict[str, bytes]) -> None:
    """Grava o conjunto em `destino`, tirando extrato que não é mais dele."""
    destino = Path(destino)
    pasta = destino / PASTA_EXTRATOS
    pasta.mkdir(parents=True, exist_ok=True)
    esperados = {Path(rel).name for rel in saida
                 if rel.startswith(PASTA_EXTRATOS + "/")}
    for velho in pasta.glob("*.csv"):
        if velho.name not in esperados:
            velho.unlink()
    for relativo, conteudo in saida.items():
        (destino / relativo).write_bytes(conteudo)


def diferencas(destino: Path, saida: Dict[str, bytes]) -> List[str]:
    """O que no disco difere do que o gerador produz."""
    destino = Path(destino)
    achadas = []
    for relativo, conteudo in sorted(saida.items()):
        caminho = destino / relativo
        if not caminho.is_file():
            achadas.append(f"falta {relativo}")
        elif caminho.read_bytes() != conteudo:
            achadas.append(f"difere {relativo}")
    esperados = {Path(rel).name for rel in saida
                 if rel.startswith(PASTA_EXTRATOS + "/")}
    for sobra in sorted((destino / PASTA_EXTRATOS).glob("*.csv")):
        if sobra.name not in esperados:
            achadas.append(f"sobra {PASTA_EXTRATOS}/{sobra.name}")
    return achadas


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--conferir", action="store_true",
                    help="não grava: compara o que geraria com o que está no "
                         "disco e sai com código 1 se diferir")
    args = ap.parse_args(argv)

    saida = gerar()
    if args.conferir:
        achadas = diferencas(PASTA, saida)
        print("\n".join(achadas) if achadas else
              f"IGUAL: {len(saida)} arquivos conferem byte a byte.")
        return 1 if achadas else 0

    escrever(PASTA, saida)
    conjunto = json.loads(saida[ARQUIVO_CONJUNTO].decode("utf-8"))
    esperado = conjunto["esperado"]
    print(f"{len(saida) - 1} extratos e {ARQUIVO_CONJUNTO} gravados em {PASTA}")
    print(f"  linhas nos arquivos: {esperado['linhas_nos_arquivos']}; "
          f"transações: {esperado['transacoes']}; "
          f"duplicatas: {esperado['duplicatas']}")
    print(f"  pares: {esperado['pares_conciliados']}; "
          f"pendências: {esperado['pendencias']}; "
          f"atribuições: {len(conjunto['atribuicoes'])}; "
          f"receitas sem fonte: {conjunto['receitas_sem_fonte']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
