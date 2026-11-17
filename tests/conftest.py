# -*- coding: utf-8 -*-
"""
Configuração comum da suíte.

Três camadas, com dados de origem diferente:

- **Unidade** (`tests/unidade/`) — fixtures sintéticas versionadas em
  `tests/fixtures/sinteticos/`. Nomes e números de conta inventados,
  nenhum dado real. Rodam em qualquer máquina, sem pré-requisito.
- **Integração** (`tests/integracao/`) e `tests/test_apelidos.py` — dado
  real, que nunca entra no repositório. Fazem `pytest.skip` quando ele não
  está configurado nesta máquina.
- **Demonstração** (`tests/demonstracao/`) — o pipeline inteiro e o app sobre
  o conjunto fictício versionado em `demonstracao/`. Roda em qualquer máquina.

Onde está o dado real quem diz é `src/ambiente.py`: `FA_DADOS` ou
`fa.local.ini` apontam a raiz, e dela saem as pastas:

- `extratos/`            — conjunto atual (`EXTRATOS_DIR`).
- `extratos-referencia/` — conjunto de referência de junho/2026 contra o qual
  os números do `test_v3.py` e do `test_renda.py` originais foram calibrados
  (`EXTRATOS_REF`).
- `gabarito/`            — estado do app usado pelo benchmark de acurácia
  (`tools/benchmark_categorizacao.py`). A suíte **não** usa o gabarito:
  benchmark não é teste.
- `semente.local.json` e `nao_membros.local.txt` — o pool real e os terceiros.

As variáveis `EXTRATOS_DIR`, `EXTRATOS_REF` e `GABARITO_DIR` continuam valendo
como exceção por pasta. `FA_DEMO=1` desliga tudo, e a suíte roda só com o que
é sintético.
"""

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import src.ambiente as _ambiente  # noqa: E402
from src.ambiente import carregar_semente, resolver  # noqa: E402
from src.data.models import AppConfig, FamilyMember, FamilyAccount  # noqa: E402
from src.data.parser import CSVParser  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SINTETICOS = FIXTURES / "sinteticos"


# ---------------------------------------------------------------------------
# Dado real — sempre por configuração, sempre opcional
# ---------------------------------------------------------------------------

AMBIENTE = resolver()

EXTRATOS_DIR = AMBIENTE.pasta("extratos")
EXTRATOS_REF = AMBIENTE.pasta("extratos-referencia")
GABARITO_DIR = AMBIENTE.pasta("gabarito")


def exigir_diretorio(caminho, variavel: str):
    """Pula o teste quando o dado real não está disponível nesta máquina."""
    if caminho is None:
        pytest.skip(
            f"sem dado real: {AMBIENTE.descrever()}. Aponte a raiz com "
            f"FA_DADOS ou fa.local.ini (ou só esta pasta com {variavel}). "
            f"A camada de unidade continua rodando.")
    if not caminho.is_dir():
        pytest.skip(
            f"{caminho} não existe ({AMBIENTE.descrever()}; exceção "
            f"{variavel}). A camada de unidade continua rodando."
        )


def config_da_semente() -> AppConfig:
    """
    O pool real, de `semente.local.json`. Pula quando a semente não está
    nesta máquina: sem ela, os números de conciliação calibrados contra o
    pool real não fazem sentido.
    """
    semente = carregar_semente(AMBIENTE.arquivo_semente)
    if semente is None:
        pytest.skip(
            f"semente local ausente ({AMBIENTE.descrever()}): rode "
            f"tools/extrair_semente.py. A camada de unidade continua rodando.")
    return semente.config()


def localizar(diretorio: Path, nome_arquivo: str) -> Path:
    """
    Acha um extrato pelo nome em qualquer profundidade do diretório.
    Os extratos reais são organizados por pessoa e por banco, e a
    organização mudou entre os dois conjuntos — o nome é o que estabiliza.
    """
    achados = sorted(diretorio.rglob(nome_arquivo))
    if not achados:
        pytest.skip(f"{nome_arquivo} não encontrado em {diretorio}")
    return achados[0]


# ---------------------------------------------------------------------------
# Durante a suíte, ninguém enxerga o `fa.local.ini` do projeto
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _projeto_sem_ini(tmp_path_factory) -> Path:
    """Uma pasta vazia, que faz as vezes de pasta do projeto para quem
    pergunta onde está o dado durante um teste."""
    return tmp_path_factory.mktemp("projeto_sem_ini")


@pytest.fixture(autouse=True)
def suite_nao_enxerga_o_ini_do_projeto(monkeypatch, _projeto_sem_ini):
    """
    Trava de segurança, ligada em todo teste: `src.ambiente.resolver()`
    chamado sem `raiz_projeto` — é como o `app.py` e as ferramentas o chamam
    — procura o `fa.local.ini` numa pasta vazia, e não na pasta do projeto.

    Por quê: os testes que abrem o app em modo real tiram `FA_DEMO` de
    propósito e apontam `FA_DADOS` para um `tmp_path`. Na máquina do dono há
    um `fa.local.ini` apontando o dado real; sem esta trava, um `FA_DADOS`
    esquecido ou escrito errado abriria o dado real, com gravação. Com ela, o
    erro cai na demonstração.

    O que NÃO muda: o `AMBIENTE` deste arquivo, resolvido na importação, antes
    de qualquer teste. É por ele que a integração, o teste de apelidos e a
    varredura acham o dado real, e ele continua lendo o `fa.local.ini`.

    Quem passa `raiz_projeto` explícito (`tests/unidade/test_ambiente.py`)
    também não é afetado. E nenhum código de `src/` pode localizar arquivo
    versionado por `ambiente.RAIZ_PROJETO`: dentro de um teste ele é esta
    pasta vazia.
    """
    monkeypatch.setattr(_ambiente, "RAIZ_PROJETO", _projeto_sem_ini)


# ---------------------------------------------------------------------------
# Camada de unidade — pool sintético, sem nenhum dado real
# ---------------------------------------------------------------------------

@pytest.fixture
def config_sintetica() -> AppConfig:
    """
    Pool familiar inventado, espelhando a forma do real: dois membros com
    apelidos de comprimentos diferentes e três contas em bancos distintos.
    Nenhum nome ou número aqui corresponde a pessoa ou conta de verdade.
    """
    return AppConfig(
        members=[
            FamilyMember(name="Ana Quintela",
                         aliases=["ana quintela", "ana quintela moreira"]),
            FamilyMember(name="Bruno Quintela",
                         aliases=["bruno quintela", "bruno quintela moreira"]),
        ],
        accounts=[
            FamilyAccount(label="Nubank (conta) 99887766",
                          owner="Ana Quintela"),
            FamilyAccount(label="C6 Bank (conta) 12345678",
                          owner="Ana Quintela"),
            FamilyAccount(label="Inter (conta) 87654321",
                          owner="Bruno Quintela"),
        ],
    )


@pytest.fixture
def parser() -> CSVParser:
    return CSVParser()


@pytest.fixture
def importar(parser):
    """
    Importa uma fixture sintética pelo nome do arquivo.

    Passa o arquivo como binário de propósito: é assim que o Streamlit
    entrega o upload, e é o caminho onde o encoding (BOM do C6) importa.
    """
    def _importar(nome_arquivo: str):
        caminho = SINTETICOS / nome_arquivo
        assert caminho.exists(), f"fixture ausente: {caminho}"
        with open(caminho, "rb") as f:
            return parser.parse_file(f, nome_arquivo)
    return _importar


# Nomes das fixtures sintéticas, para os testes não repetirem string solta.
NUBANK_JAN = "NU_99887766_01JAN2026_31JAN2026.csv"
NUBANK_SOBREPOSTO = "NU_99887766_20JAN2026_20FEV2026.csv"
# Uma linha com a célula de Valor EM BRANCO — o pandas lê com dtype=str
# e devolve NaN, e float('nan') não levanta. Ver test_valores.py.
NUBANK_VALOR_EM_BRANCO = "NU_99887766_01FEV2026_28FEV2026.csv"
C6_JAN = "C6_extrato_sintetico_012026.csv"
INTER_JAN = "Extrato-01-01-2026-a-31-01-2026-CSV.csv"
INTER_SOBREPOSTO = "Extrato-15-01-2026-a-15-02-2026-CSV.csv"
# Fixtures da cadeia de saldo (sessão 6). Reproduzem a forma que a
# cadeia exige e que as antigas não têm: o Inter em ordem DECRESCENTE
# com saldo coerente linha a linha, o C6 com uma linha cuja Data
# Contábil difere da Data Lançamento. As duas atravessam a virada de
# ano, pela regra de data do CLAUDE.md.
INTER_CADEIA = "Extrato-28-12-2025-a-20-01-2026-CSV.csv"
C6_CADEIA = "C6_extrato_sintetico_cadeia.csv"
