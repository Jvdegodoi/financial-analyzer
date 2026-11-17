"""
Transfer Matcher — Pool Familiar (Prioridade 1)

Conciliação de transferências internas entre as contas do casal,
no modelo de eliminação intercompany de uma consolidação contábil:
dinheiro mudando de bolso dentro do grupo não é receita nem despesa.

Princípios:
- Pareamento DETERMINÍSTICO: duas pernas em contas diferentes, valores
  opostos, mesma data (Pix é instantâneo; tolerância configurável) e
  ambas as descrições mencionando um membro do pool. Achou o par,
  ambas viram "Transferência Interna" e ficam vinculadas entre si
  (paired_transfer_id).
- Comportamento CONSERVADOR para perna solta: uma transferência que
  menciona um membro mas não encontrou a contraparte NÃO é
  neutralizada — permanece nas métricas (categoria "Transferências")
  e aparece no painel de pendências. Ou o extrato do outro lado ainda
  não foi importado, ou o dinheiro de fato saiu do pool; nos dois
  casos, esconder o valor seria mentir para o usuário.
- Idempotente: rodar de novo sobre a base completa não muda pares já
  conciliados nem rouba pernas de pares existentes.
"""

from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from datetime import timedelta

from src.data.models import (Transaction, AppConfig, FamilyAccount,
                             ordem_do_mes)
from src.data.validator import DataValidator


class TransferMatcher:
    """Concilia transferências internas do pool familiar"""

    def __init__(self, config: AppConfig):
        self.config = config
        # Apelidos normalizados de todos os membros
        self._aliases = []
        for member in config.members:
            for alias in member.aliases:
                norm = DataValidator.normalize_description(alias)
                if norm:
                    self._aliases.append((norm, member.name))


    # ------------------------------------------------------------------
    # Detecção de menção a membro
    # ------------------------------------------------------------------

    def member_mentioned(self, description: str) -> Optional[str]:
        """
        Retorna o nome do membro mencionado na descrição, ou None.
        Usa o apelido mais longo que casar (mais específico vence).
        """
        norm = DataValidator.normalize_description(description)
        best = None
        best_len = 0
        for alias, member_name in self._aliases:
            if alias in norm and len(alias) > best_len:
                best = member_name
                best_len = len(alias)
        return best

    # ------------------------------------------------------------------
    # Pareamento
    # ------------------------------------------------------------------

    def _is_candidate(self, t: Transaction) -> bool:
        """
        Uma transação é candidata a perna de transferência interna se
        menciona um membro do pool. Categorias definidas manualmente
        pelo usuário são respeitadas, exceto se o próprio usuário já a
        marcou como Transferência Interna.
        """
        if t.is_manual_category and t.category != "Transferência Interna":
            return False
        if t.category == "Estorno":
            return False
        return self.member_mentioned(t.description) is not None

    def pair_transfers(self, transactions: List[Transaction]) -> int:
        """
        Percorre a base completa e concilia pares de transferência.
        Retorna o número de NOVOS pares formados nesta passada.

        Deve ser chamado após cada importação (depois do ReversalMatcher).
        """
        by_id = {t.id: t for t in transactions}

        # Respeita pares existentes que continuam válidos
        already_paired = set()
        for t in transactions:
            pid = getattr(t, 'paired_transfer_id', None)
            if pid and pid in by_id and by_id[pid].paired_transfer_id == t.id:
                already_paired.add(t.id)
            elif pid:
                # vínculo órfão (contraparte apagada) — limpa
                t.paired_transfer_id = None

        candidates = [t for t in transactions
                      if t.id not in already_paired and self._is_candidate(t)]

        # Agrupa por valor absoluto para busca eficiente
        by_abs_value: Dict[float, List[Transaction]] = defaultdict(list)
        for t in candidates:
            by_abs_value[round(abs(t.value), 2)].append(t)

        tolerance = timedelta(
            days=getattr(self.config, 'transfer_date_tolerance_days', 0))

        new_pairs = 0
        used = set()

        for abs_value, group in by_abs_value.items():
            positives = sorted((t for t in group if t.value > 0),
                               key=lambda t: t.date)
            negatives = sorted((t for t in group if t.value < 0),
                               key=lambda t: t.date)

            for neg in negatives:
                if neg.id in used:
                    continue
                for pos in positives:
                    if pos.id in used:
                        continue
                    if not self._legs_match(neg, pos, tolerance):
                        continue

                    # Par encontrado — concilia as duas pernas
                    for leg, other in ((neg, pos), (pos, neg)):
                        leg.paired_transfer_id = other.id
                        if leg.category != "Transferência Interna":
                            leg.update_category("Transferência Interna",
                                                is_manual=False)
                            leg.confidence = 1.0
                    used.add(neg.id)
                    used.add(pos.id)
                    new_pairs += 1
                    break

        return new_pairs

    def _legs_match(self, a: Transaction, b: Transaction,
                    tolerance: timedelta) -> bool:
        """Verifica se duas transações formam um par de transferência"""
        # Valores opostos
        if abs(a.value + b.value) > 0.005:
            return False
        # Datas compatíveis
        if abs((a.date.date() - b.date.date()).days) > tolerance.days:
            return False
        # Contas diferentes e conhecidas — duas pernas na mesma conta
        # (ou ambas sem conta, caso legado) não formam transferência
        acc_a = a.source_account
        acc_b = b.source_account
        if acc_a == acc_b:
            return False
        return True

    # ------------------------------------------------------------------
    # Conservadorismo: demoção de internas não conciliadas
    # ------------------------------------------------------------------

    def reconcile(self, transactions: List[Transaction]) -> Tuple[int, int]:
        """
        Passada completa de conciliação:
        1. Pareia o que for possível.
        2. Demove "Transferência Interna" automática SEM par para
           "Transferências" — o comportamento antigo neutralizava pelo
           nome e escondia dinheiro que saiu do pool sem contraparte.
           Categorias manuais são respeitadas.

        Retorna (novos_pares, demovidas).
        """
        new_pairs = self.pair_transfers(transactions)

        demoted = 0
        for t in transactions:
            if (t.category == "Transferência Interna"
                    and not t.is_manual_category
                    and not getattr(t, 'paired_transfer_id', None)):
                t.update_category("Transferências", is_manual=False)
                demoted += 1

        return new_pairs, demoted

    # ------------------------------------------------------------------
    # Pendências
    # ------------------------------------------------------------------

    def get_pending_transfers(self,
                              transactions: List[Transaction]
                              ) -> List[Transaction]:
        """
        Pernas soltas: mencionam um membro do pool, não estão conciliadas
        e não foram resolvidas manualmente. São o sinal de que falta
        importar o extrato do outro lado — ou de que o dinheiro saiu
        do pool de verdade.
        """
        pending = []
        for t in transactions:
            if getattr(t, 'paired_transfer_id', None):
                continue
            if t.is_manual_category:
                continue
            if t.category in ("Transferência Interna", "Estorno"):
                continue
            if self.member_mentioned(t.description):
                pending.append(t)
        return sorted(pending, key=lambda t: t.date, reverse=True)


class CoverageAnalyzer:
    """
    Cobertura de importação por conta: quais meses de cada conta do
    pool já foram importados. O pool só é confiável quando todas as
    contas cobrem o período analisado — este painel torna o buraco
    visível em vez de deixá-lo distorcer as métricas em silêncio.
    """

    @staticmethod
    def compute(transactions: List[Transaction],
                config: AppConfig) -> Dict[str, Dict[str, int]]:
        """
        Retorna {conta: {"MM/YYYY": num_transacoes}}.
        Inclui contas registradas sem nenhuma transação (linha vazia
        no painel = extrato nunca importado).
        """
        coverage: Dict[str, Dict[str, int]] = {}

        for account in getattr(config, 'accounts', []):
            coverage[account.label] = {}

        for t in transactions:
            label = t.source_account or "(importações antigas, sem conta)"
            coverage.setdefault(label, {})
            coverage[label][t.month_year] = \
                coverage[label].get(t.month_year, 0) + 1

        return coverage

    @staticmethod
    def all_months(coverage: Dict[str, Dict[str, int]]) -> List[str]:
        """Lista ordenada de todos os meses presentes em qualquer conta"""
        months = set()
        for acc_months in coverage.values():
            months.update(acc_months.keys())
        return sorted(months, key=ordem_do_mes)

    @staticmethod
    def discover_accounts(transactions: List[Transaction],
                          config: AppConfig) -> List[str]:
        """
        Contas presentes nos dados mas ainda não registradas na config —
        para o app oferecer o registro (atribuição de dono) na UI.
        """
        registered = {a.label for a in getattr(config, 'accounts', [])}
        seen = {t.source_account for t in transactions if t.source_account}
        return sorted(seen - registered)
