"""
Smart Categorizer — v3.0
Categorização em dois níveis (categoria > subcategoria) com aprendizado.

As regras foram calibradas nos extratos reais do casal (Nubank, C6 e
Inter): cada padrão pode apontar direto para uma subcategoria, e o
aprendizado grava os dois níveis quando o usuário corrige.
"""

import re
from typing import Tuple, Dict, List, Optional
from src.data.models import Transaction, CategoryManager, FamilyMember
from src.data.validator import DataValidator


class SmartCategorizer:
    """Categorizador inteligente de transações"""

    def __init__(self, members: List[FamilyMember] = None,
                 category_manager: CategoryManager = None):
        self.members = members or []
        self.category_manager = category_manager or CategoryManager()
        # learning_data v3: {descricao_normalizada: {"category": c, "subcategory": s|None}}
        self.learning_data: Dict[str, Dict[str, Optional[str]]] = {}
        self.rules = self._initialize_rules()
        self._member_aliases = [
            DataValidator.normalize_description(alias)
            for m in self.members for alias in m.aliases
        ]

    # ------------------------------------------------------------------
    # Regras: {categoria: [(pattern, peso, subcategoria|None), ...]}
    # Calibradas nos estabelecimentos reais dos extratos do casal.
    # ------------------------------------------------------------------

    def _initialize_rules(self) -> Dict[str, List[Tuple[str, int, Optional[str]]]]:
        return {
            'Alimentação': [
                # Supermercado / hortifruti / açougue
                (r'\b(supermercado|mercado)\b(?!.*financeiro)', 10, 'Supermercado'),
                (r'\b(atacadao|atacadista)\b', 9, 'Supermercado'),
                (r'supercei', 10, 'Supermercado'),
                (r'oba\s*hortifruti|hortifruti', 9, 'Supermercado'),
                (r'\b(frutas|verduras)\b', 9, 'Supermercado'),
                (r'\b(carne|acougue|peixaria)\b', 9, 'Supermercado'),
                (r'seara\s*alimentos|comercio\s+de\s+alimentos', 8, 'Supermercado'),
                # Delivery (ifood sem fronteira final: casa 'Ifoodcom' do Inter)
                (r'ifood|99\s*food|uber\s*eats|rappi', 10, 'Delivery'),
                # Padaria e lanches
                (r'\b(lanchonete|padaria|panificadora)\b', 9, 'Padaria e Lanches'),
                (r'\b(paes|pao)\b', 8, 'Padaria e Lanches'),
                (r'\b(lanches|hamburger|pizza(?:ria)?)\b', 9, 'Padaria e Lanches'),
                (r'\b(acai|sorvete|gelato|cafeteria|cafe)\b', 8, 'Padaria e Lanches'),
                (r'quitutes|petiscaria', 8, 'Padaria e Lanches'),
                # Restaurantes e bares
                (r'\brestaurante\b', 10, 'Restaurantes e Bares'),
                (r'\bmadero\b', 10, 'Restaurantes e Bares'),
                (r'\b(bar|pub|boteco)\b', 7, 'Restaurantes e Bares'),
                (r'\b(cerveja|bebidas|conveniencia)\b', 8, 'Restaurantes e Bares'),
                (r'\b(sushi|churrascaria)\b', 9, 'Restaurantes e Bares'),
                # Genéricos (ficam no pai)
                (r'\b(food|comida|alimentacao)\b', 7, None),
            ],

            'Transporte': [
                (r'\b(combustivel|gasolina|etanol|diesel)\b', 10, 'Combustível'),
                (r'\b(posto|gas\s*station)\b', 9, 'Combustível'),
                (r'allpark|estapar|\b(estacionamento|parking)\b', 10, 'Estacionamento'),
                (r'\b(uber|99|taxi)\b(?!\s*food)', 10, 'App de Transporte'),
                (r'\b(pedagio|toll)\b', 8, None),
                (r'\b(onibus|metro|trem)\b', 9, None),
                (r'\b(manutencao\s*veiculo|mecanica)\b', 8, 'Manutenção'),
                (r'\b(oficina|autocenter|pneus?)\b|auto\s*center', 8, 'Manutenção'),
                (r'\b(seguro\s*auto|ipva)\b', 9, None),
            ],

            'Moradia': [
                (r'\b(energia|eletrica|neoenergia|light|enel)\b', 10, 'Energia'),
                (r'\b(agua|saneamento|caesb)\b', 10, 'Água'),
                (r'\b(internet|banda\s*larga|wifi)\b', 9, 'Telefone e Internet'),
                (r'\b(telefonica|celular|claro|vivo|tim)\b', 9, 'Telefone e Internet'),
                (r'\b(aluguel|rent)\b', 10, 'Aluguel e Condomínio'),
                (r'\b(condominio|cond)\b', 10, 'Aluguel e Condomínio'),
                (r'\b(gas|gás)\b', 8, None),
                (r'\b(iptu|imposto\s*predial)\b', 10, None),
                (r'\b(reform|pintura)\b', 7, None),
            ],

            'Saúde': [
                (r'\b(farmacia|pharmacy|drogaria|drogasil|drogas?il)\b', 10, 'Farmácia'),
                (r'rd\s*saude|raia\s*drogasil', 10, 'Farmácia'),
                (r'\b(medicamento|remedio)\b', 9, 'Farmácia'),
                (r'\b(medico|doctor|clinica|consultorio)\b', 10, 'Consultas e Exames'),
                (r'\b(exame|laboratorio|sabin|biomedicina)\b', 9, 'Consultas e Exames'),
                (r'\b(dentista|odonto)\b', 10, 'Consultas e Exames'),
                (r'\b(psicolog|psiquiatr|fisioterapia|terapia)\b', 9, 'Consultas e Exames'),
                (r'\b(hospital|pronto\s*socorro)\b', 10, None),
                (r'\b(plano\s*saude|unimed|amil)\b', 10, None),
            ],

            'Lazer': [
                (r'\b(netflix|spotify|disney|prime\s*video|hbo|max)\b', 10, 'Streaming'),
                (r'\b(streaming|subscription)\b', 8, 'Streaming'),
                (r'\b(cinema|theater|filme)\b', 10, 'Eventos e Passeios'),
                (r'\b(show|concert|festival|producoes)\b', 9, 'Eventos e Passeios'),
                (r'\b(parque|zoo|museu|entretenimento)\b', 8, 'Eventos e Passeios'),
                (r'\b(viagem|hotel|hospedagem|airbnb)\b', 9, 'Eventos e Passeios'),
                (r'\b(game|steam|playstation|xbox|nintendo)\b', 10, None),
                (r'\b(academia|gym|fitness)\b', 9, None),
            ],

            'Educação': [
                (r'\b(mensalidade|tuition)\b', 10, 'Mensalidades'),
                (r'educacao\s*catolica|ubec|\b(faculdade|universidade)\b', 10, 'Mensalidades'),
                (r'\b(escola|colegio)\b', 10, 'Mensalidades'),
                (r'\b(curso|training|capacitacao)\b', 10, 'Cursos e Livros'),
                (r'\b(livr|book|livraria)\b', 9, 'Cursos e Livros'),
                (r'\b(material\s*escolar|papelaria)\b', 9, 'Cursos e Livros'),
            ],

            'Vestuário': [
                (r'\b(roupa|cloth|vestuar)\b', 10, None),
                (r'\b(calcado|sapato|tenis|shoes)\b', 10, None),
                (r'\b(moda|fashion|boutique)\b', 8, None),
                (r'\b(loja|store|shop)\b', 6, None),
            ],

            'Serviços': [
                (r'\b(banco|bank|tarifa|taxa)\b', 10, None),
                (r'\b(cartorio|notario)\b', 9, None),
                (r'\b(correio|sedex|pac|postais)\b', 9, None),
                (r'\b(advogado|juridico|contador|contabil)\b', 9, None),
                (r'\b(seguro|insurance)\b', 8, None),
                (r'\b(passaporte|visto|policia\s*federal)\b', 10, None),
            ],

            'Transferências': [
                (r'\b(transfer|pix|ted|doc)\b', 10, None),
                (r'\b(transferencia|enviada|recebida)\b', 10, None),
                (r'\b(deposito|saque)\b', 8, None),
            ],

            'Investimentos': [
                (r'\b(investimento|aplicacao|resgate)\b', 10, None),
                (r'\b(fundo|cdb|lci|lca|tesouro)\b', 10, None),
                (r'\b(acao|bolsa|corretora)\b', 10, None),
            ],
        }

    # ------------------------------------------------------------------
    # Categorização
    # ------------------------------------------------------------------

    def categorize(self, transaction: Transaction
                   ) -> Tuple[str, Optional[str], float]:
        """
        Categoriza uma transação.
        Retorna (categoria, subcategoria|None, confiança).
        """
        description = transaction.description

        # 0. Estornos são neutros — antes de qualquer outra regra
        if self._is_reversal(description):
            return "Estorno", None, 1.0

        # 1. Aprendizado do usuário (override absoluto)
        normalized = DataValidator.normalize_description(description)
        if normalized in self.learning_data:
            learned = self.learning_data[normalized]
            return learned['category'], learned.get('subcategory'), 1.0

        # 2. Menção a membro do pool + palavra de transferência →
        # "Transferências". Quem promove a "Transferência Interna" é o
        # TransferMatcher, ao achar a perna oposta em outra conta.
        if self._is_member_transfer(description):
            return "Transferências", None, 0.9

        # 3. Regras com scoring por categoria; a subcategoria vem do
        # padrão de maior peso que casou dentro da categoria vencedora.
        #
        # IMPORTANTE: "Transferências" é FALLBACK DE MECANISMO. Nos
        # extratos brasileiros, quase toda linha carrega "Transferência
        # enviada pelo Pix - <comerciante>" — se as palavras do
        # mecanismo (pix, enviada...) pontuassem junto com as demais,
        # venceriam qualquer comerciante e tudo viraria Transferências.
        # Elas só valem quando nenhuma categoria de conteúdo pontuou.
        desc_lower = description.lower()
        scores: Dict[str, float] = {}
        best_sub: Dict[str, Tuple[int, Optional[str]]] = {}

        for category, patterns in self.rules.items():
            if category == 'Transferências':
                continue  # avaliada só como fallback, abaixo
            category_score = 0
            top_weight, top_sub = 0, None
            for pattern, weight, sub in patterns:
                if re.search(pattern, desc_lower, re.IGNORECASE):
                    category_score += weight
                    if sub and weight > top_weight:
                        top_weight, top_sub = weight, sub
            if category_score > 0:
                scores[category] = category_score
                best_sub[category] = (top_weight, top_sub)

        scores = self._adjust_scores_by_value(scores, transaction.value)

        if not scores:
            # Fallback de mecanismo: é movimentação bancária sem
            # comerciante reconhecido?
            for pattern, weight, _ in self.rules.get('Transferências', []):
                if re.search(pattern, desc_lower, re.IGNORECASE):
                    return 'Transferências', None, 0.6
            return self.category_manager.get_default_category(), None, 0.0

        best_category = max(scores, key=scores.get)
        total_score = sum(scores.values())
        confidence = scores[best_category] / total_score if total_score > 0 else 0.0
        subcategory = best_sub.get(best_category, (0, None))[1]

        return best_category, subcategory, confidence

    @staticmethod
    def _is_reversal(description: str) -> bool:
        """Detecta estornos/devoluções pela descrição"""
        desc = DataValidator.normalize_description(description)
        return desc.startswith('estorno') or ' estorno ' in f' {desc} ' \
            or desc.startswith('devolucao pix') or desc.startswith('reembolso')

    def _is_member_transfer(self, description: str) -> bool:
        """Transferência que menciona um membro do pool familiar"""
        desc_norm = DataValidator.normalize_description(description)
        if not any(alias in desc_norm for alias in self._member_aliases):
            return False
        transfer_words = ['transfer', 'pix', 'ted', 'doc',
                          'enviada', 'recebida']
        return any(word in desc_norm for word in transfer_words)

    def _adjust_scores_by_value(self, scores: Dict[str, float],
                                value: float) -> Dict[str, float]:
        """Ajusta scores baseado no valor da transação"""
        abs_value = abs(value)
        adjusted = scores.copy()

        if abs_value > 2000:
            for cat in ('Moradia', 'Transferências',
                        'Investimentos', 'Educação'):
                if cat in adjusted:
                    adjusted[cat] *= 1.2

        if abs_value < 20:
            for cat in ('Alimentação', 'Lazer', 'Transporte'):
                if cat in adjusted:
                    adjusted[cat] *= 1.1

        return adjusted

    # ------------------------------------------------------------------
    # Aprendizado
    # ------------------------------------------------------------------

    def learn_from_user(self, transaction: Transaction,
                        correct_category: str,
                        correct_subcategory: Optional[str] = None):
        """Aprende com correção do usuário (dois níveis)"""
        normalized = DataValidator.normalize_description(
            transaction.description)
        self.learning_data[normalized] = {
            'category': correct_category,
            'subcategory': correct_subcategory,
        }

    def find_similar_transactions(self, transaction: Transaction,
                                  all_transactions: List[Transaction],
                                  threshold: float = 0.85
                                  ) -> List[Transaction]:
        """Encontra transações com descrição similar"""
        from difflib import SequenceMatcher

        similar = []
        ref = DataValidator.normalize_description(transaction.description)

        for trans in all_transactions:
            if trans.id == transaction.id:
                continue
            other = DataValidator.normalize_description(trans.description)
            if SequenceMatcher(None, ref, other).ratio() >= threshold:
                similar.append(trans)

        return similar

    def recategorize_similar(self, reference: Transaction,
                             new_category: str,
                             new_subcategory: Optional[str],
                             all_transactions: List[Transaction],
                             threshold: float = 0.85) -> int:
        """Recategoriza transações similares (respeita manuais)"""
        similar = self.find_similar_transactions(
            reference, all_transactions, threshold)

        count = 0
        for trans in similar:
            if not trans.is_manual_category:
                trans.update_category(new_category, new_subcategory,
                                      is_manual=False)
                count += 1
        return count

    def load_learning_data(self, learning_data: Dict):
        self.learning_data = learning_data or {}

    def get_learning_data(self) -> Dict:
        return self.learning_data

    def categorize_batch(self, transactions: List[Transaction]
                         ) -> List[Transaction]:
        for transaction in transactions:
            if not transaction.is_manual_category:
                category, subcategory, confidence = self.categorize(transaction)
                transaction.category = category
                transaction.subcategory = subcategory
                transaction.confidence = confidence
        return transactions

    def get_statistics(self) -> Dict[str, any]:
        return {
            'num_learning_entries': len(self.learning_data),
            'num_categories': len(self.category_manager.get_all_categories()),
            'num_rules': sum(len(p) for p in self.rules.values()),
            'num_members': len(self.members),
        }


class ReversalMatcher:
    """
    Pareia estornos com suas transações originais.

    No Nubank, o estorno compartilha o Identificador (external_id) da
    transação original — pareamento determinístico. Quando os dois lados
    são encontrados (valores opostos, mesmo external_id), AMBOS recebem
    a categoria "Estorno" e saem das métricas.
    """

    @staticmethod
    def pair_reversals(transactions: List[Transaction]) -> int:
        """
        Neutraliza pares de estorno na base completa. Retorna o número
        de transações neutralizadas nesta passada. Chamar após cada
        importação — o estorno pode chegar em arquivo posterior.
        """
        from collections import defaultdict

        by_external_id = defaultdict(list)
        for t in transactions:
            if t.external_id:
                by_external_id[t.external_id].append(t)

        neutralized = 0
        for ext_id, group in by_external_id.items():
            if len(group) < 2:
                continue

            has_marker = any(
                SmartCategorizer._is_reversal(t.description) for t in group
            )
            values_cancel = abs(sum(t.value for t in group)) < 0.005

            if has_marker and values_cancel:
                for t in group:
                    if t.category != "Estorno":
                        t.update_category("Estorno", None, is_manual=False)
                        t.confidence = 1.0
                        neutralized += 1

        return neutralized
