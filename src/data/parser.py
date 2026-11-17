"""
CSV Parser — v2.2 (Fase 0)
Parser multi-banco baseado em perfis declarativos.

Arquitetura:
- Cada banco é um BankProfile que sabe detectar seu próprio formato
  (assinatura no preâmbulo ou no cabeçalho) e mapear suas colunas para
  o modelo canônico (data, valor, descrição, id_externo).
- Adicionar um banco novo = declarar um novo BankProfile e registrá-lo.
- GenericProfile é o fallback: procura a linha de cabeçalho em qualquer
  posição do arquivo (tolerante a preâmbulos institucionais).

Mudanças da Fase 0:
- Suporte a Nubank (CSV), C6 Bank e extrato genérico com preâmbulo.
- Captura de identificador único do banco (external_id) quando existir.
- Captura da conta de origem (source_account) do preâmbulo.
- Deduplicação determinística: por external_id quando disponível,
  senão por contagem de ocorrências (multiset) — não descarta mais
  transações legítimas repetidas no mesmo dia.
- Erros de validação são propagados com o motivo específico, linha a linha.
"""

import re
from io import StringIO
from typing import List, Tuple, Dict, Any, Optional
from collections import Counter

import pandas as pd

from src.data.models import Transaction, CategoryManager
from src.data.validator import DataValidator


# ============================================================================
# RESULTADO DO PARSING
# ============================================================================

class CSVParseResult:
    """Resultado do parsing de CSV"""

    def __init__(self):
        self.transactions: List[Transaction] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.stats: Dict[str, Any] = {}
        self.profile_name: Optional[str] = None
        self.source_account: Optional[str] = None

    @property
    def success(self) -> bool:
        return len(self.transactions) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def add_error(self, error: str):
        self.errors.append(error)

    def add_warning(self, warning: str):
        self.warnings.append(warning)

    def get_summary(self) -> str:
        lines = [f"✓ {len(self.transactions)} transações importadas"]
        if self.profile_name:
            lines.append(f"🏦 Formato detectado: {self.profile_name}")
        if self.errors:
            lines.append(f"✗ {len(self.errors)} erros")
        if self.warnings:
            lines.append(f"⚠ {len(self.warnings)} avisos")
        return "\n".join(lines)


# ============================================================================
# PERFIS DE BANCO
# ============================================================================

class BankProfile:
    """
    Perfil declarativo de um formato de extrato bancário.

    Subclasses definem:
    - name: nome legível do formato
    - separator: separador de colunas
    - header_signature: colunas (normalizadas) que identificam o cabeçalho
    - matches(text): detecção do formato
    - extract_rows(df): converte o DataFrame em linhas canônicas
    """

    name: str = "Base"
    separator: str = ","
    header_signature: List[str] = []

    # ------------------------------------------------------------------
    # Utilidades compartilhadas
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_header(h: str) -> str:
        """Normaliza nome de coluna para comparação"""
        return DataValidator.normalize_description(str(h))

    def find_header_line(self, lines: List[str]) -> Optional[int]:
        """
        Localiza o índice da linha de cabeçalho, tolerando preâmbulos.
        Retorna None se não encontrar.
        """
        for i, line in enumerate(lines[:30]):  # preâmbulos são curtos
            cols = [self._norm_header(c) for c in line.split(self.separator)]
            if all(any(sig in c for c in cols) for sig in self.header_signature):
                return i
        return None

    def extract_account_from_filename(self, filename: str) -> Optional[str]:
        """Perfis podem extrair a conta do nome do arquivo (ex.: Nubank)"""
        return None

    def extract_account(self, preamble: str) -> Optional[str]:
        """Extrai número da conta do preâmbulo, se presente"""
        m = re.search(r'conta\s*[:;]?\s*([0-9][0-9.\-]*)',
                      preamble, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def matches(self, text: str) -> bool:
        raise NotImplementedError

    def read_dataframe(self, text: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Lê o DataFrame a partir do texto, pulando o preâmbulo.
        Retorna (df, source_account).
        """
        lines = text.splitlines()
        header_idx = self.find_header_line(lines)
        if header_idx is None:
            return None, None

        preamble = "\n".join(lines[:header_idx])
        account = self.extract_account(preamble)

        body = "\n".join(lines[header_idx:])
        try:
            df = pd.read_csv(
                StringIO(body),
                sep=self.separator,
                skip_blank_lines=True,
                on_bad_lines='skip',
                dtype=str,
            )
        except Exception:
            return None, None

        return df, account

    def _col(self, df: pd.DataFrame, *candidates: str) -> Optional[str]:
        """Encontra a coluna real do df cujo nome normalizado contém o candidato"""
        for candidate in candidates:
            for col in df.columns:
                if candidate in self._norm_header(col):
                    return col
        return None

    def extract_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Converte o DataFrame em linhas canônicas:
        {date_str, value_str, description, external_id, row_number}
        """
        raise NotImplementedError


class NubankProfile(BankProfile):
    """
    Nubank — CSV de conta corrente.
    Formato: Data,Valor,Identificador,Descrição
    O Identificador é um UUID único por transação (estornos compartilham
    o UUID da transação original — usado para pareamento).
    """

    name = "Nubank (conta)"
    separator = ","
    header_signature = ["data", "valor", "identificador"]

    def extract_account_from_filename(self, filename: str) -> Optional[str]:
        """O CSV do Nubank não traz a conta no conteúdo; o nome do
        arquivo traz: NU_<conta>_01JUN2026_30JUN2026.csv"""
        m = re.search(r'NU_(\d+)_', filename or '')
        return m.group(1) if m else None

    def matches(self, text: str) -> bool:
        head = "\n".join(text.splitlines()[:5]).lower()
        return "identificador" in head and "valor" in head

    def extract_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        col_date = self._col(df, "data")
        col_value = self._col(df, "valor")
        col_id = self._col(df, "identificador")
        col_desc = self._col(df, "descricao", "descrição")

        rows = []
        for idx, row in df.iterrows():
            rows.append({
                'date_str': str(row[col_date]).strip(),
                'value_str': str(row[col_value]).strip(),
                'description': str(row[col_desc]).strip(),
                'external_id': str(row[col_id]).strip() if col_id else None,
                'row_number': idx + 1,
            })
        return rows


class C6Profile(BankProfile):
    """
    C6 Bank — CSV de conta corrente.
    Preâmbulo institucional de ~8 linhas; valor dividido em duas colunas
    (Entrada e Saída, ambas positivas); decimal americano.
    A coluna Título é mais informativa que Descrição — usamos ambas.
    """

    name = "C6 Bank (conta)"
    separator = ","
    header_signature = ["data lancamento", "entrada", "saida"]

    def matches(self, text: str) -> bool:
        head = "\n".join(text.splitlines()[:10]).lower()
        return "c6 bank" in head or ("entrada(r$)" in head and "saida" in
                                     DataValidator.normalize_description(head))

    def extract_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        col_date = self._col(df, "data lancamento", "data")
        col_in = self._col(df, "entrada")
        col_out = self._col(df, "saida")
        col_title = self._col(df, "titulo")
        col_desc = self._col(df, "descricao")

        rows = []
        for idx, row in df.iterrows():
            entrada = self._to_float(row[col_in]) if col_in else 0.0
            saida = self._to_float(row[col_out]) if col_out else 0.0
            value = entrada - saida

            # Composição da descrição: Título é o campo rico no C6;
            # Descrição complementa quando difere.
            title = str(row[col_title]).strip() if col_title else ""
            desc = str(row[col_desc]).strip() if col_desc else ""
            if desc and desc.lower() != title.lower():
                description = f"{title} - {desc}" if title else desc
            else:
                description = title or desc

            rows.append({
                'date_str': str(row[col_date]).strip(),
                'value_str': f"{value:.2f}",
                'description': description,
                'external_id': None,  # C6 não fornece ID único
                'row_number': idx + 1,
            })
        return rows

    @staticmethod
    def _to_float(raw: Any) -> float:
        ok, value, _ = DataValidator.validate_value(str(raw))
        return value if ok else 0.0


class InterProfile(BankProfile):
    """
    Banco Inter — CSV de conta corrente.
    Separador ponto-e-vírgula, decimal brasileiro, preâmbulo com
    'Conta ;NNNN'. A descrição canônica é 'Histórico - Descrição'.
    (Detecção pela estrutura do cabeçalho — o arquivo não traz o nome
    do banco no preâmbulo.)
    """

    name = "Inter (conta)"
    separator = ";"
    header_signature = ["data lancamento", "historico", "valor"]

    def matches(self, text: str) -> bool:
        lines = [DataValidator.normalize_description(l)
                 for l in text.splitlines()[:15]]
        return any(("historico" in l and "data lancamento" in l and "valor" in l)
                   for l in lines)

    def extract_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        col_date = self._col(df, "data lancamento", "data")
        col_hist = self._col(df, "historico")
        col_desc = self._col(df, "descricao")
        col_value = self._col(df, "valor")

        rows = []
        for idx, row in df.iterrows():
            hist = " ".join(str(row[col_hist]).split()) if col_hist else ""
            desc = " ".join(str(row[col_desc]).split()) if col_desc else ""
            description = f"{hist} - {desc}" if (hist and desc) else (hist or desc)

            rows.append({
                'date_str': str(row[col_date]).strip(),
                'value_str': str(row[col_value]).strip(),
                'description': description,
                'external_id': None,
                'row_number': idx + 1,
            })
        return rows


class GenericProfile(BankProfile):
    """
    Fallback: qualquer CSV com colunas de data, valor e descrição,
    em qualquer separador comum, com ou sem preâmbulo.
    Mantém compatibilidade com o comportamento anterior do app.
    """

    name = "CSV genérico"
    header_signature = ["data", "valor"]

    SEPARATORS = [';', ',', '\t', '|']

    DATE_PATTERNS = ['data', 'date', 'dt', 'fecha']
    VALUE_PATTERNS = ['valor', 'value', 'montante', 'amount']
    DESC_PATTERNS = ['descricao', 'descrição', 'description',
                     'desc', 'historico', 'histórico']

    def matches(self, text: str) -> bool:
        return True  # fallback universal

    def read_dataframe(self, text: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        lines = text.splitlines()

        for sep in self.SEPARATORS:
            self.separator = sep
            header_idx = self.find_header_line(lines)
            if header_idx is None:
                continue

            preamble = "\n".join(lines[:header_idx])
            account = self.extract_account(preamble)

            body = "\n".join(lines[header_idx:])
            try:
                df = pd.read_csv(
                    StringIO(body), sep=sep,
                    skip_blank_lines=True, on_bad_lines='skip', dtype=str,
                )
                if len(df.columns) >= 2 and len(df) > 0:
                    return df, account
            except Exception:
                continue

        return None, None

    def extract_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        col_date = self._find_by_patterns(df, self.DATE_PATTERNS)
        col_value = self._find_by_patterns(df, self.VALUE_PATTERNS)
        col_desc = self._find_by_patterns(df, self.DESC_PATTERNS)

        if not (col_date and col_value and col_desc):
            return []

        # Captura identificador se existir (ex.: Nubank via fallback)
        col_id = self._col(df, "identificador", "identifier")

        rows = []
        for idx, row in df.iterrows():
            rows.append({
                'date_str': str(row[col_date]).strip(),
                'value_str': str(row[col_value]).strip(),
                'description': str(row[col_desc]).strip(),
                'external_id': (str(row[col_id]).strip()
                                if col_id and pd.notna(row[col_id]) else None),
                'row_number': idx + 1,
            })
        return rows

    def _find_by_patterns(self, df: pd.DataFrame,
                          patterns: List[str]) -> Optional[str]:
        for col in df.columns:
            norm = self._norm_header(col)
            for p in patterns:
                if DataValidator.normalize_description(p) in norm:
                    return col
        return None


# ============================================================================
# REGISTRO DE PERFIS
# ============================================================================

# Ordem importa: perfis específicos antes do genérico.
BANK_PROFILES: List[BankProfile] = [
    NubankProfile(),
    C6Profile(),
    InterProfile(),
    GenericProfile(),  # sempre por último
]


# ============================================================================
# PARSER PRINCIPAL
# ============================================================================

class CSVParser:
    """Parser de arquivos CSV bancários com detecção de formato"""

    ENCODINGS = ['utf-8-sig', 'utf-8', 'latin1', 'cp1252']

    def __init__(self):
        self.validator = DataValidator()

    def parse_file(self, file_content: Any, filename: str = "") -> CSVParseResult:
        result = CSVParseResult()

        text = self._decode(file_content)
        if not text or not text.strip():
            result.add_error("Arquivo vazio ou com encoding não reconhecido")
            return result

        # Detecta o perfil do banco
        profile = self._detect_profile(text)
        df, account = profile.read_dataframe(text)

        if account is None:
            account = profile.extract_account_from_filename(filename)

        if df is None:
            result.add_error(
                f"Não foi possível localizar a tabela de transações "
                f"(formato tentado: {profile.name}). Verifique se o arquivo "
                f"contém colunas de data, valor e descrição."
            )
            return result

        result.profile_name = profile.name
        result.source_account = self._compose_account_label(profile, account)

        if df.empty:
            # Extrato válido, período sem movimentações (ex.: conta parada)
            result.add_warning("Extrato sem movimentações no período")
            result.stats['total_rows'] = 0
            return result

        raw_rows = profile.extract_rows(df)
        if not raw_rows:
            result.add_error(
                f"Formato '{profile.name}' detectado, mas as colunas "
                f"obrigatórias não foram mapeadas."
            )
            return result

        result.stats['total_rows'] = len(raw_rows)
        result.stats['filename'] = filename

        for raw in raw_rows:
            transaction, error = self._build_transaction(
                raw, result.source_account, filename
            )
            if transaction:
                result.transactions.append(transaction)
            elif error:
                result.add_warning(f"Linha {raw['row_number']}: {error}")

        result.stats['rows_processed'] = len(result.transactions)
        result.stats['rows_skipped'] = len(raw_rows) - len(result.transactions)

        return result

    # ------------------------------------------------------------------

    def _decode(self, file_content: Any) -> Optional[str]:
        """Decodifica o conteúdo tentando múltiplos encodings"""
        if hasattr(file_content, 'read'):
            content = file_content.read()
        else:
            content = file_content

        if isinstance(content, str):
            return content

        for encoding in self.ENCODINGS:
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, AttributeError):
                continue
        return None

    def _detect_profile(self, text: str) -> BankProfile:
        for profile in BANK_PROFILES:
            try:
                if profile.matches(text):
                    return profile
            except Exception:
                continue
        return BANK_PROFILES[-1]  # genérico

    @staticmethod
    def _compose_account_label(profile: BankProfile,
                               account: Optional[str]) -> str:
        base = profile.name
        return f"{base} {account}" if account else base

    def _build_transaction(self, raw: Dict[str, Any],
                           source_account: str,
                           filename: str) -> Tuple[Optional[Transaction], Optional[str]]:
        """
        Constrói a Transaction validando cada campo.
        Retorna (transaction, None) em sucesso ou (None, motivo) em falha.
        Os motivos específicos são propagados — nada falha em silêncio.
        """
        date_valid, date_obj, date_error = self.validator.validate_date(
            raw['date_str'])
        if not date_valid:
            return None, date_error

        value_valid, value, value_error = self.validator.validate_value(
            raw['value_str'])
        if not value_valid:
            return None, value_error

        # Transações de valor zero são ruído (ex.: linhas de saldo no C6)
        if value == 0:
            return None, "Valor zero (ignorada)"

        desc_valid, description, desc_error = self.validator.validate_description(
            raw['description'])
        if not desc_valid:
            return None, desc_error

        external_id = raw.get('external_id')
        if external_id in ('', 'nan', 'None'):
            external_id = None

        transaction = Transaction(
            id=Transaction.generate_id(),
            date=date_obj,
            value=value,
            description=description,
            category=CategoryManager.get_default_category(),
            external_id=external_id,
            source_account=source_account,
            raw_data={
                'row_number': raw['row_number'],
                'original_date': raw['date_str'],
                'original_value': raw['value_str'],
                'original_description': raw['description'],
                'filename': filename,
            },
        )
        return transaction, None


# ============================================================================
# DEDUPLICAÇÃO
# ============================================================================

class TransactionDeduplicator:
    """
    Remove transações duplicadas de forma determinística.

    Estratégia (Fase 0):
    1. Chave primária: (conta, external_id, valor) quando o banco fornece
       identificador único. O valor entra na chave porque estornos do
       Nubank compartilham o ID da transação original.
    2. Fallback heurístico por CONTAGEM (multiset): (conta, data, valor,
       descrição normalizada). A multiplicidade legítima de uma chave é
       o número de ocorrências dentro de UM MESMO arquivo — bancos não
       duplicam linhas num extrato. Ocorrências além disso (arquivos com
       períodos sobrepostos, reimportação) são duplicatas.
       Isso corrige a perda silenciosa de dados da versão anterior, que
       descartava transações legítimas idênticas no mesmo dia.
    """

    @staticmethod
    def _primary_key(t: Transaction) -> Optional[tuple]:
        if getattr(t, 'external_id', None):
            return ('id', t.source_account or '', t.external_id,
                    round(t.value, 2))
        return None

    @staticmethod
    def _heuristic_key(t: Transaction) -> tuple:
        return (
            'heur',
            t.source_account or '',
            t.date.date().isoformat(),
            round(t.value, 2),
            DataValidator.normalize_description(t.description),
        )

    @classmethod
    def remove_duplicates(cls, transactions: List[Transaction],
                          existing: List[Transaction]
                          ) -> Tuple[List[Transaction], int]:
        # --- Indexa a base existente ---
        existing_ids = set()
        existing_counts: Counter = Counter()

        for t in existing:
            pk = cls._primary_key(t)
            if pk:
                existing_ids.add(pk)
            existing_counts[cls._heuristic_key(t)] += 1

        # --- Multiplicidade legítima por chave heurística ---
        # max de ocorrências da chave dentro de um mesmo arquivo
        per_file: Dict[tuple, Counter] = {}
        for t in transactions:
            if cls._primary_key(t) is not None:
                continue
            key = cls._heuristic_key(t)
            fname = t.raw_data.get('filename', '')
            per_file.setdefault(key, Counter())[fname] += 1

        allowed: Dict[tuple, int] = {}
        for key, files in per_file.items():
            legit = max(files.values())
            already = existing_counts.get(key, 0)
            allowed[key] = max(legit - already, 0)

        # --- Filtra ---
        unique: List[Transaction] = []
        num_duplicates = 0
        seen_ids = set(existing_ids)

        for t in transactions:
            pk = cls._primary_key(t)

            if pk is not None:
                if pk in seen_ids:
                    num_duplicates += 1
                else:
                    seen_ids.add(pk)
                    unique.append(t)
                continue

            key = cls._heuristic_key(t)
            if allowed.get(key, 0) > 0:
                allowed[key] -= 1
                unique.append(t)
            else:
                num_duplicates += 1

        return unique, num_duplicates

    # Mantido por compatibilidade com chamadas antigas
    @classmethod
    def find_duplicates(cls, transactions: List[Transaction],
                        existing: List[Transaction]) -> List[Transaction]:
        unique, _ = cls.remove_duplicates(transactions, existing)
        unique_ids = {t.id for t in unique}
        return [t for t in transactions if t.id not in unique_ids]
