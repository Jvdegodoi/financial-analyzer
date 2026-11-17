"""
Data Models — Financial Analyzer v3.0
Modelos com hierarquia de categorias em dois níveis (categoria > subcategoria).

Decisões de arquitetura:
- subcategory é um CAMPO SEPARADO e OPCIONAL, não um caminho embutido na
  categoria. Isso garante o teto de dois níveis pelo próprio modelo,
  agregação no pai sem parsing de string, e opcionalidade natural — uma
  transação pode viver no nível da categoria para sempre.
- v3.0 é uma base limpa: sem campos ou defaults de compatibilidade com
  versões anteriores. Os extratos são a fonte da verdade; o JSON é
  estado derivado e reconstruível por reimportação.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
import copy
import uuid


class TransactionType(Enum):
    """Tipos de transação"""
    RECEITA = "receita"
    DESPESA = "despesa"


def ordem_do_mes(mes: str) -> tuple:
    """
    Chave de ordenação CRONOLÓGICA para o mês no formato "MM/AAAA".

    `Transaction.month_year` devolve "MM/AAAA", e ordenar essa string como
    texto compara o mês antes do ano: numa base de 08/2025 a 08/2026 a série
    sairia 01/2026...07/2026, 08/2025, 08/2026, 09/2025, 10/2025, 11/2025,
    12/2025. Os valores estariam certos e a ordem errada.

    Toda série temporal que atravesse a virada de ano precisa desta chave. O
    defeito passou despercebido por 211 testes e uma revisão completa porque
    o conjunto de referência é de um único ano civil.
    """
    return (mes[3:], mes[:2])


class CategoryManager:
    """
    Gerenciador da árvore de categorias (dois níveis, teto arquitetural).

    A árvore padrão nasce calibrada nos extratos reais do casal: cada
    subcategoria semeada tem regras de classificação correspondentes no
    SmartCategorizer. Subcategorias e categorias personalizadas vivem na
    AppConfig e são mescladas aqui.
    """

    # Árvore padrão: {categoria: [subcategorias]}
    # Lista vazia = categoria sem subdivisão (subcategorizar onde a
    # divisão muda decisão; forçar detalhe em tudo mata o hábito).
    DEFAULT_TREE: Dict[str, List[str]] = {
        "Alimentação": ["Supermercado", "Delivery", "Padaria e Lanches",
                        "Restaurantes e Bares"],
        # "Manutenção" divide porque as duas metades se corrigem de
        # formas diferentes: combustível é função de quanto se roda,
        # manutenção é da idade do carro. Subdividir manutenção por
        # tipo de reparo não mudaria decisão nenhuma — e por isso não
        # foi feito.
        "Transporte": ["Combustível", "Estacionamento",
                       "App de Transporte", "Manutenção"],
        "Moradia": ["Energia", "Água", "Telefone e Internet",
                    "Aluguel e Condomínio"],
        "Saúde": ["Farmácia", "Consultas e Exames"],
        "Lazer": ["Streaming", "Eventos e Passeios"],
        "Educação": ["Mensalidades", "Cursos e Livros"],
        "Vestuário": [],
        "Serviços": [],
        "Transferências": [],
        "Transferência Interna": [],
        "Estorno": [],
        "Investimentos": [],
        "Outros": [],
    }

    SEPARATOR = " > "
    GENERAL_SUFFIX = " (geral)"

    def __init__(self, custom_tree: Dict[str, List[str]] = None):
        """
        custom_tree: adições do usuário — categorias novas e/ou
        subcategorias novas em categorias existentes.
        """
        self.custom_tree = custom_tree if custom_tree is not None else {}

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def get_tree(self) -> Dict[str, List[str]]:
        """
        Árvore completa: padrão + adições do usuário − supressões.
        Supressão de subcategoria padrão é registrada na custom_tree
        com prefixo '-' (ex.: '-Delivery').
        """
        suppressed = {
            (cat, s[1:])
            for cat, subs in self.custom_tree.items()
            for s in subs if s.startswith('-')
        }
        tree: Dict[str, List[str]] = {}
        for cat, subs in self.DEFAULT_TREE.items():
            tree[cat] = [s for s in subs if (cat, s) not in suppressed]
        for cat, subs in self.custom_tree.items():
            if cat not in tree:
                tree[cat] = []
            for sub in subs:
                if (not sub.startswith('-')
                        and sub not in tree[cat]
                        and (cat, sub) not in suppressed):
                    tree[cat].append(sub)
        return tree

    def get_all_categories(self) -> List[str]:
        return list(self.get_tree().keys())

    def get_subcategories(self, category: str) -> List[str]:
        return self.get_tree().get(category, [])

    def is_valid_category(self, category: str) -> bool:
        return category in self.get_tree()

    def is_valid_pair(self, category: str,
                      subcategory: Optional[str]) -> bool:
        tree = self.get_tree()
        if category not in tree:
            return False
        if subcategory is None:
            return True
        return subcategory in tree[category]

    # ------------------------------------------------------------------
    # Caminhos achatados (para a UI: um dropdown só, com dependência
    # embutida — o Streamlit não suporta dropdown dependente no editor)
    # ------------------------------------------------------------------

    def get_all_paths(self) -> List[str]:
        """
        Todos os caminhos selecionáveis:
        'Alimentação (geral)', 'Alimentação > Delivery', 'Serviços', ...
        Categorias sem filhos aparecem sem sufixo.
        """
        paths = []
        for cat, subs in self.get_tree().items():
            if subs:
                paths.append(f"{cat}{self.GENERAL_SUFFIX}")
                for sub in subs:
                    paths.append(f"{cat}{self.SEPARATOR}{sub}")
            else:
                paths.append(cat)
        return paths

    @classmethod
    def path_of(cls, category: str, subcategory: Optional[str],
                tree: Dict[str, List[str]] = None) -> str:
        """Caminho achatado de um par (categoria, subcategoria)"""
        if subcategory:
            return f"{category}{cls.SEPARATOR}{subcategory}"
        has_children = bool((tree or cls.DEFAULT_TREE).get(category))
        return f"{category}{cls.GENERAL_SUFFIX}" if has_children else category

    @classmethod
    def parse_path(cls, path: str) -> tuple:
        """Decompõe caminho achatado em (categoria, subcategoria|None)"""
        if cls.SEPARATOR in path:
            cat, sub = path.split(cls.SEPARATOR, 1)
            return cat.strip(), sub.strip()
        if path.endswith(cls.GENERAL_SUFFIX):
            return path[:-len(cls.GENERAL_SUFFIX)].strip(), None
        return path.strip(), None

    # ------------------------------------------------------------------
    # Edição (persistida via custom_tree na AppConfig)
    # ------------------------------------------------------------------

    def add_category(self, category: str) -> bool:
        if category in self.get_tree():
            return False
        self.custom_tree[category] = []
        return True

    def add_subcategory(self, category: str, subcategory: str) -> bool:
        tree = self.get_tree()
        if category not in tree or subcategory in tree[category]:
            return False
        self.custom_tree.setdefault(category, [])
        if subcategory not in self.custom_tree[category]:
            self.custom_tree[category].append(subcategory)
        return True

    def remove_subcategory(self, category: str, subcategory: str) -> bool:
        """
        Remove uma subcategoria da árvore. As transações que a usavam
        devem SUBIR PARA O PAI (destrutivo mínimo) — responsabilidade
        do chamador, via Transaction.clear_subcategory().
        Subcategorias padrão também podem ser removidas (ficam
        registradas como remoção na custom_tree com prefixo '-').
        """
        tree = self.get_tree()
        if category not in tree or subcategory not in tree[category]:
            return False
        if subcategory in self.custom_tree.get(category, []):
            self.custom_tree[category].remove(subcategory)
        else:
            # remoção de item padrão: marca supressão
            self.custom_tree.setdefault(category, [])
            self.custom_tree[category].append(f"-{subcategory}")
        return True

    @staticmethod
    def get_default_category() -> str:
        return "Outros"


@dataclass
class Transaction:
    """
    Transação financeira.

    category/subcategory: dois níveis, subcategoria opcional.
    external_id: ID único do banco (ex.: Identificador Nubank).
    source_account: conta de origem estampada pelo parser.
    paired_transfer_id: perna oposta, quando transferência conciliada.
    """
    id: str
    date: datetime
    value: float
    description: str
    category: str
    subcategory: Optional[str] = None
    external_id: Optional[str] = None
    source_account: Optional[str] = None
    paired_transfer_id: Optional[str] = None
    income_source: Optional[str] = None    # fonte de renda atribuída (manual)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    is_manual_category: bool = False
    # Distinto de `is_manual_category`, e o ponto é a distinção:
    # `is_manual_category` só fica True quando o usuário TROCA a categoria.
    # Linha que ele abriu, leu e concordou ficava indistinguível de linha que
    # ele nunca viu. `revisada` registra "eu olhei isto e está certo" — que é
    # o dado de que a medição de acurácia precisa. Padrão False, inclusive
    # para todo registro gravado antes deste campo existir.
    revisada: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if isinstance(self.date, str):
            self.date = datetime.fromisoformat(self.date)
        if not isinstance(self.category, str):
            self.category = str(self.category)

    # ------------------------------------------------------------------

    @property
    def type(self) -> TransactionType:
        return TransactionType.RECEITA if self.value >= 0 else TransactionType.DESPESA

    @property
    def absolute_value(self) -> float:
        return abs(self.value)

    @property
    def is_internal_transfer(self) -> bool:
        return self.category == "Transferência Interna"

    @property
    def is_neutral(self) -> bool:
        """
        Transações neutras não representam receita nem despesa real:
        transferências internas conciliadas e pares de estorno.
        Ficam fora de todas as métricas financeiras.
        """
        return self.category in ("Transferência Interna", "Estorno")

    @property
    def category_path(self) -> str:
        """Caminho legível: 'Alimentação > Delivery' ou 'Serviços'"""
        if self.subcategory:
            return f"{self.category}{CategoryManager.SEPARATOR}{self.subcategory}"
        return self.category

    @property
    def date_str(self) -> str:
        return self.date.strftime("%d/%m/%Y")

    @property
    def month_year(self) -> str:
        return self.date.strftime("%m/%Y")

    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'value': self.value,
            'description': self.description,
            'category': self.category,
            'subcategory': self.subcategory,
            'external_id': self.external_id,
            'source_account': self.source_account,
            'paired_transfer_id': self.paired_transfer_id,
            'income_source': self.income_source,
            'raw_data': self.raw_data,
            'confidence': self.confidence,
            'is_manual_category': self.is_manual_category,
            'revisada': self.revisada,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        return cls(
            id=data['id'],
            date=datetime.fromisoformat(data['date']),
            value=data['value'],
            description=data['description'],
            category=data['category'],
            subcategory=data.get('subcategory'),
            external_id=data.get('external_id'),
            source_account=data.get('source_account'),
            paired_transfer_id=data.get('paired_transfer_id'),
            income_source=data.get('income_source'),
            raw_data=data.get('raw_data', {}),
            confidence=data.get('confidence', 0.0),
            is_manual_category=data.get('is_manual_category', False),
            revisada=data.get('revisada', False),
            created_at=datetime.fromisoformat(
                data.get('created_at', datetime.now().isoformat())),
            updated_at=datetime.fromisoformat(
                data.get('updated_at', datetime.now().isoformat())),
        )

    @staticmethod
    def generate_id() -> str:
        return str(uuid.uuid4())

    def update_category(self, new_category: str,
                        new_subcategory: Optional[str] = None,
                        is_manual: bool = True):
        """Atualiza categoria e subcategoria da transação"""
        self.category = new_category
        self.subcategory = new_subcategory
        self.is_manual_category = is_manual
        self.updated_at = datetime.now()
        if is_manual:
            self.confidence = 1.0

    def marcar_revisada(self) -> bool:
        """
        Registra que o usuário olhou esta linha e a considerou correta.

        Idempotente: devolve True só quando de fato mudou algo, para que
        quem chama saiba se precisa gravar. `updated_at` só se mexe na
        transição — remarcar não deve reescrever o carimbo de tempo.
        """
        if self.revisada:
            return False
        self.revisada = True
        self.updated_at = datetime.now()
        return True

    def clear_subcategory(self):
        """Sobe a transação para o nível do pai (destrutivo mínimo)"""
        self.subcategory = None
        self.updated_at = datetime.now()


@dataclass
class FinancialSummary:
    """Resumo financeiro de um conjunto de transações"""
    total_receitas: float
    total_despesas: float
    saldo: float
    num_transacoes: int
    num_receitas: int
    num_despesas: int
    media_receita: float
    media_despesa: float
    maior_receita: float
    maior_despesa: float
    periodo_inicio: Optional[datetime] = None
    periodo_fim: Optional[datetime] = None

    @property
    def periodo_str(self) -> str:
        if self.periodo_inicio and self.periodo_fim:
            return (f"{self.periodo_inicio.strftime('%d/%m/%Y')} a "
                    f"{self.periodo_fim.strftime('%d/%m/%Y')}")
        return "Período não definido"


@dataclass
class IncomeSource:
    """
    Fonte de renda do pool.

    O TIPO (fixa/variável) é propriedade da FONTE — quem paga é quem
    paga. A ATRIBUIÇÃO de cada receita a uma fonte é decisão manual,
    transação a transação (domínio do usuário, sem carimbo automático).
    Reclassificar o tipo de uma fonte reclassifica todo o histórico
    dela de graça.
    """
    name: str
    type: str = "variavel"   # 'fixa' | 'variavel'
    owner: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'type': self.type, 'owner': self.owner}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IncomeSource':
        return cls(name=data['name'],
                   type=data.get('type', 'variavel'),
                   owner=data.get('owner', ''))


@dataclass
class FamilyMember:
    """
    Membro do pool familiar.

    aliases: formas como o nome aparece nas descrições de contraparte.
    Usar formas específicas (nome + sobrenome) para não casar com
    terceiros: o casamento é por substring, e 'quintela' sozinho casaria
    com qualquer terceiro de mesmo sobrenome, como 'Carla Quintela Ramos'.
    """
    name: str
    aliases: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'aliases': self.aliases}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FamilyMember':
        return cls(name=data['name'], aliases=data.get('aliases', []))


@dataclass
class FamilyAccount:
    """
    Conta do pool familiar.
    label: rótulo estampado pelo parser em source_account.
    owner: nome do FamilyMember dono da conta.
    """
    label: str
    owner: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {'label': self.label, 'owner': self.owner}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FamilyAccount':
        return cls(label=data['label'], owner=data.get('owner', ''))


def _default_members() -> list:
    """
    Pool FICTÍCIO — o padrão do código. É com ele que a demonstração abre e
    que nasce toda base sem semente local. Os membros reais moram em
    `semente.local.json`, na raiz do dado, fora do Git (`src/ambiente.py`).

    Só formas com ao menos um sobrenome. O casamento de apelido é por
    substring, sem fronteira de palavra: um apelido feito só de nome dado
    casa dentro do nome completo de qualquer terceiro homônimo. Foi o que
    aconteceu com o pool real até 02/09/2026, e a medição de então mostrou
    custo zero em recall ao tirar as formas curtas — toda menção legítima a
    um membro trazia pelo menos um sobrenome.
    """
    return [
        FamilyMember(name="Ana Quintela", aliases=[
            "ana quintela",
            "ana quintela moreira",
        ]),
        FamilyMember(name="Bruno Quintela", aliases=[
            "bruno quintela",
            "bruno quintela moreira",
        ]),
    ]


def _default_accounts() -> list:
    """
    As seis contas do pool fictício, uma por banco para cada membro. As três
    que as fixtures de `tests/fixtures/sinteticos/` usam — Nubank 99887766,
    C6 12345678 e Inter 87654321 — têm aqui o mesmo dono que em
    `config_sintetica`, de `tests/conftest.py`.
    """
    return [
        FamilyAccount(label="Nubank (conta) 99887766", owner="Ana Quintela"),
        FamilyAccount(label="C6 Bank (conta) 12345678", owner="Ana Quintela"),
        FamilyAccount(label="Inter (conta) 11223344", owner="Ana Quintela"),
        FamilyAccount(label="Inter (conta) 87654321", owner="Bruno Quintela"),
        FamilyAccount(label="Nubank (conta) 55667788", owner="Bruno Quintela"),
        FamilyAccount(label="C6 Bank (conta) 44332211", owner="Bruno Quintela"),
    ]


@dataclass
class Semente:
    """
    Membros e contas com que uma base nasce, e para onde ela cai quando o
    `config.json` falta ou não diz quem são.

    A semente real mora em `semente.local.json`, na raiz do dado, fora do Git
    (ver `src/ambiente.py`). A do código é o pool fictício de
    `_default_members()` e `_default_accounts()`.
    """
    members: list
    accounts: list

    def config(self) -> 'AppConfig':
        """Uma `AppConfig` nova com esta semente. Cópia profunda: dois
        chamadores não editam a mesma lista."""
        return AppConfig(members=copy.deepcopy(self.members),
                         accounts=copy.deepcopy(self.accounts))


class SementeAusente(Exception):
    """
    A configuração precisou cair na semente, e quem chamou exigiu a semente
    local, que não está lá. Em modo real o app para com esta mensagem em vez
    de abrir o dado do dono com membros fictícios.
    """


@dataclass
class AppConfig:
    """Configurações da aplicação — v3.0, sem campos legados"""
    custom_tree: Dict[str, List[str]] = field(default_factory=dict)
    members: list = field(default_factory=_default_members)
    accounts: list = field(default_factory=_default_accounts)
    income_sources: list = field(default_factory=list)  # IncomeSource
    transfer_date_tolerance_days: int = 0
    learning_enabled: bool = True
    auto_categorize: bool = True
    auto_recategorize_similar: bool = True
    similarity_threshold: float = 0.85
    version: str = "3.1"

    def get_category_manager(self) -> CategoryManager:
        return CategoryManager(self.custom_tree)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'custom_tree': self.custom_tree,
            'members': [m.to_dict() for m in self.members],
            'accounts': [a.to_dict() for a in self.accounts],
            'income_sources': [s.to_dict() for s in self.income_sources],
            'transfer_date_tolerance_days': self.transfer_date_tolerance_days,
            'learning_enabled': self.learning_enabled,
            'auto_categorize': self.auto_categorize,
            'auto_recategorize_similar': self.auto_recategorize_similar,
            'similarity_threshold': self.similarity_threshold,
            'version': self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], semente: 'Semente' = None,
                  exigir_semente: bool = False) -> 'AppConfig':
        """
        `members` ausente ou vazio e `accounts` ausente caem na semente: a
        de `semente`, quando dada, senão a fictícia do código. Com
        `exigir_semente`, cair sem `semente` levanta `SementeAusente` — é o
        modo real, em que membro fictício nunca serve.
        """
        members_raw = data.get('members')
        accounts_raw = data.get('accounts')

        def cair(parte: str):
            if semente is not None:
                return copy.deepcopy(getattr(semente, parte))
            if exigir_semente:
                raise SementeAusente(
                    f"o config.json não traz '{parte}' e a semente local não "
                    f"foi encontrada")
            return (_default_members() if parte == 'members'
                    else _default_accounts())

        return cls(
            custom_tree=data.get('custom_tree', {}),
            members=([FamilyMember.from_dict(m) for m in members_raw]
                     if members_raw else cair('members')),
            accounts=([FamilyAccount.from_dict(a) for a in accounts_raw]
                      if accounts_raw is not None else cair('accounts')),
            income_sources=[IncomeSource.from_dict(s)
                            for s in data.get('income_sources', [])],
            transfer_date_tolerance_days=data.get(
                'transfer_date_tolerance_days', 0),
            learning_enabled=data.get('learning_enabled', True),
            auto_categorize=data.get('auto_categorize', True),
            auto_recategorize_similar=data.get(
                'auto_recategorize_similar', True),
            similarity_threshold=data.get('similarity_threshold', 0.85),
            version=data.get('version', '3.1'),
        )
