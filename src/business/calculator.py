"""
Financial Calculator
Cálculos e análises financeiras
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
from src.data.models import (Transaction, FinancialSummary,
                             TransactionType, ordem_do_mes)


class FinancialCalculator:
    """Calculadora de métricas financeiras"""
    
    @staticmethod
    def calculate_summary(transactions: List[Transaction], 
                         exclude_internal: bool = True) -> FinancialSummary:
        """
        Calcula resumo financeiro
        
        Args:
            transactions: Lista de transações
            exclude_internal: Se True, exclui transações neutras (transferências internas e estornos)
            
        Returns:
            FinancialSummary com todas as métricas
        """
        # Filtra transações se necessário
        if exclude_internal:
            filtered = [t for t in transactions if not t.is_neutral]
        else:
            filtered = transactions
        
        if not filtered:
            return FinancialSummary(
                total_receitas=0.0,
                total_despesas=0.0,
                saldo=0.0,
                num_transacoes=0,
                num_receitas=0,
                num_despesas=0,
                media_receita=0.0,
                media_despesa=0.0,
                maior_receita=0.0,
                maior_despesa=0.0
            )
        
        # Separa receitas e despesas
        receitas = [t for t in filtered if t.type == TransactionType.RECEITA]
        despesas = [t for t in filtered if t.type == TransactionType.DESPESA]
        
        # Calcula totais
        total_receitas = sum(t.value for t in receitas)
        total_despesas = sum(t.absolute_value for t in despesas)
        
        # Calcula médias
        media_receita = total_receitas / len(receitas) if receitas else 0.0
        media_despesa = total_despesas / len(despesas) if despesas else 0.0
        
        # Encontra maiores valores
        maior_receita = max((t.value for t in receitas), default=0.0)
        maior_despesa = max((t.absolute_value for t in despesas), default=0.0)
        
        # Período
        dates = [t.date for t in filtered]
        periodo_inicio = min(dates) if dates else None
        periodo_fim = max(dates) if dates else None
        
        return FinancialSummary(
            total_receitas=total_receitas,
            total_despesas=total_despesas,
            saldo=total_receitas - total_despesas,
            num_transacoes=len(filtered),
            num_receitas=len(receitas),
            num_despesas=len(despesas),
            media_receita=media_receita,
            media_despesa=media_despesa,
            maior_receita=maior_receita,
            maior_despesa=maior_despesa,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim
        )
    
    @staticmethod
    def calculate_by_category(transactions: List[Transaction], 
                             exclude_internal: bool = True) -> Dict[str, float]:
        """
        Calcula despesas por categoria
        
        Returns:
            {categoria: valor_total}
        """
        if exclude_internal:
            filtered = [t for t in transactions 
                       if t.type == TransactionType.DESPESA and not t.is_neutral]
        else:
            filtered = [t for t in transactions if t.type == TransactionType.DESPESA]
        
        by_category = defaultdict(float)
        
        for t in filtered:
            by_category[t.category] += t.absolute_value
        
        # Ordena por valor decrescente
        sorted_dict = dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True))
        return sorted_dict
    
    @staticmethod
    def calculate_by_subcategory(transactions: List[Transaction],
                                 exclude_internal: bool = True
                                 ) -> List[Dict[str, Any]]:
        """
        Despesas agregadas nos dois níveis, no formato do sunburst:
        [{category, subcategory, value}] — subcategory None vira
        "(geral)", aparecendo como fatia própria: o quanto de cada
        categoria ainda está sem detalhamento fica visível.
        """
        if exclude_internal:
            filtered = [t for t in transactions
                        if t.type == TransactionType.DESPESA and not t.is_neutral]
        else:
            filtered = [t for t in transactions
                        if t.type == TransactionType.DESPESA]

        agg = defaultdict(float)
        for t in filtered:
            agg[(t.category, t.subcategory or "(geral)")] += t.absolute_value

        return [
            {'category': cat, 'subcategory': sub, 'value': value}
            for (cat, sub), value in sorted(agg.items(),
                                            key=lambda x: x[1], reverse=True)
        ]

    @staticmethod
    def calculate_by_path(transactions: List[Transaction],
                          exclude_internal: bool = True) -> Dict[str, float]:
        """Despesas por caminho ('Alimentação > Delivery' ou 'Serviços')"""
        if exclude_internal:
            filtered = [t for t in transactions
                        if t.type == TransactionType.DESPESA and not t.is_neutral]
        else:
            filtered = [t for t in transactions
                        if t.type == TransactionType.DESPESA]

        by_path = defaultdict(float)
        for t in filtered:
            by_path[t.category_path] += t.absolute_value

        return dict(sorted(by_path.items(), key=lambda x: x[1], reverse=True))

    @staticmethod
    def calculate_monthly_trend(transactions: List[Transaction],
                               exclude_internal: bool = True) -> List[Dict[str, Any]]:
        """
        Calcula evolução mensal
        
        Returns:
            Lista de dicionários com {month, receitas, despesas, saldo}
        """
        if exclude_internal:
            filtered = [t for t in transactions if not t.is_neutral]
        else:
            filtered = transactions
        
        # Agrupa por mês
        by_month = defaultdict(lambda: {'receitas': 0.0, 'despesas': 0.0})
        
        for t in filtered:
            month_key = t.month_year
            
            if t.type == TransactionType.RECEITA:
                by_month[month_key]['receitas'] += t.value
            else:
                by_month[month_key]['despesas'] += t.absolute_value
        
        # Converte para lista ordenada CRONOLOGICAMENTE — ordenar "MM/AAAA"
        # como texto compararia o mês antes do ano.
        result = []
        for month, values in sorted(by_month.items(),
                                    key=lambda item: ordem_do_mes(item[0])):
            result.append({
                'month': month,
                'receitas': values['receitas'],
                'despesas': values['despesas'],
                'saldo': values['receitas'] - values['despesas']
            })
        
        return result
    
    @staticmethod
    def calculate_monthly_trend_by_path(transactions: List[Transaction],
                                        paths: List[str],
                                        exclude_internal: bool = True
                                        ) -> List[Dict[str, Any]]:
        """
        Evolução mensal de despesas por caminho de categoria — aceita
        tanto 'Alimentação > Delivery' quanto 'Serviços' como série.
        """
        if exclude_internal:
            filtered = [t for t in transactions if not t.is_neutral]
        else:
            filtered = transactions

        paths = paths[:4]
        filtered = [t for t in filtered
                    if t.type == TransactionType.DESPESA
                    and t.category_path in paths]

        by_month_path = defaultdict(lambda: defaultdict(float))
        for t in filtered:
            by_month_path[t.month_year][t.category_path] += t.absolute_value

        result = []
        for month in sorted(by_month_path.keys(), key=ordem_do_mes):
            month_data = {'month': month}
            for p in paths:
                month_data[p] = by_month_path[month].get(p, 0.0)
            result.append(month_data)
        return result

    @staticmethod
    def calculate_daily_balance(transactions: List[Transaction]) -> List[Dict[str, Any]]:
        """
        Calcula saldo diário acumulado
        
        Returns:
            Lista de {date, balance, transactions_count}
        """
        if not transactions:
            return []
        
        # Ordena por data
        sorted_trans = sorted(transactions, key=lambda t: t.date)
        
        # Calcula saldo acumulado
        daily_data = []
        cumulative_balance = 0.0
        current_date = None
        day_transactions = 0
        
        for t in sorted_trans:
            if current_date != t.date.date():
                if current_date is not None:
                    daily_data.append({
                        'date': current_date,
                        'balance': cumulative_balance,
                        'transactions_count': day_transactions
                    })
                current_date = t.date.date()
                day_transactions = 0
            
            cumulative_balance += t.value
            day_transactions += 1
        
        # Adiciona último dia
        if current_date is not None:
            daily_data.append({
                'date': current_date,
                'balance': cumulative_balance,
                'transactions_count': day_transactions
            })
        
        return daily_data
    
    @staticmethod
    def get_top_expenses(transactions: List[Transaction], 
                        top_n: int = 10,
                        exclude_internal: bool = True) -> List[Transaction]:
        """
        Retorna as N maiores despesas
        """
        if exclude_internal:
            despesas = [t for t in transactions 
                       if t.type == TransactionType.DESPESA and not t.is_neutral]
        else:
            despesas = [t for t in transactions if t.type == TransactionType.DESPESA]
        
        return sorted(despesas, key=lambda t: t.absolute_value, reverse=True)[:top_n]
    
    @staticmethod
    def get_top_incomes(transactions: List[Transaction], top_n: int = 10) -> List[Transaction]:
        """Retorna as N maiores receitas"""
        receitas = [t for t in transactions if t.type == TransactionType.RECEITA]
        return sorted(receitas, key=lambda t: t.value, reverse=True)[:top_n]
    
    @staticmethod
    def calculate_category_percentage(transactions: List[Transaction],
                                     exclude_internal: bool = True) -> Dict[str, float]:
        """
        Calcula percentual de cada categoria sobre o total de despesas
        
        Returns:
            {categoria: percentual}
        """
        by_category = FinancialCalculator.calculate_by_category(transactions, exclude_internal)
        
        total = sum(by_category.values())
        
        if total == 0:
            return {}
        
        percentages = {cat: (value / total) * 100 for cat, value in by_category.items()}
        return percentages
    
    @staticmethod
    def calculate_average_by_weekday(transactions: List[Transaction]) -> Dict[str, float]:
        """
        Calcula média de gastos por dia da semana
        
        Returns:
            {dia_da_semana: media_gasto}
        """
        weekday_names = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
        
        by_weekday = defaultdict(list)
        
        for t in transactions:
            if t.type == TransactionType.DESPESA and not t.is_neutral:
                weekday = t.date.weekday()  # 0=Monday, 6=Sunday
                by_weekday[weekday].append(t.absolute_value)
        
        averages = {}
        for weekday in range(7):
            values = by_weekday[weekday]
            averages[weekday_names[weekday]] = sum(values) / len(values) if values else 0.0
        
        return averages
    
    @staticmethod
    def predict_monthly_expenses(transactions: List[Transaction],
                                months_to_predict: int = 1,
                                hoje: Optional[datetime] = None) -> float:
        """
        Predição simples de despesas futuras baseada em média móvel

        Args:
            transactions: Lista de transações
            months_to_predict: Quantos meses prever
            hoje: de que instante contar os 90 dias para trás. O padrão,
                None, é o relógio — o comportamento de sempre. A
                demonstração passa a sua data de referência, fixa, para
                que a previsão não esvazie com o passar do tempo.

        Returns:
            Valor previsto de despesas
        """
        agora = hoje if hoje is not None else datetime.now()

        # Calcula média dos últimos 3 meses
        three_months_ago = agora - timedelta(days=90)
        recent = [t for t in transactions 
                 if t.date >= three_months_ago 
                 and t.type == TransactionType.DESPESA
                 and not t.is_neutral]
        
        if not recent:
            return 0.0
        
        # Calcula despesa mensal média
        total_days = (agora - three_months_ago).days
        total_despesas = sum(t.absolute_value for t in recent)
        
        if total_days == 0:
            return 0.0
        
        daily_average = total_despesas / total_days
        monthly_average = daily_average * 30
        
        return monthly_average * months_to_predict
    
    # ------------------------------------------------------------------
    # Renda fixa vs variável (v3.1)
    # ------------------------------------------------------------------

    @staticmethod
    def _income_type_map(config) -> Dict[str, str]:
        """{nome_da_fonte: 'fixa'|'variavel'}"""
        return {s.name: s.type for s in getattr(config, 'income_sources', [])}

    @staticmethod
    def classify_income(t: Transaction, type_map: Dict[str, str]) -> str:
        """
        'fixa' | 'variavel' | 'nao_classificada' para uma receita,
        resolvendo o tipo pela fonte atribuída manualmente.
        """
        source = getattr(t, 'income_source', None)
        if source and source in type_map:
            return type_map[source]
        return 'nao_classificada'

    @staticmethod
    def calculate_income_analysis(transactions: List[Transaction],
                                  config) -> Dict[str, float]:
        """
        Análise de renda do período (exclui neutras):
        - fixa / variavel / nao_classificada: receitas por tipo de fonte
        - renda_necessaria: total de despesas do período — a métrica
          pedida: quanto de renda é preciso para cobrir os gastos
        - cobertura_fixa_pct: % da renda necessária coberta pela fixa
        - gap_variavel: o que falta cobrir com renda variável
        """
        ativos = [t for t in transactions if not t.is_neutral]
        receitas = [t for t in ativos if t.type == TransactionType.RECEITA]
        despesas = sum(t.absolute_value for t in ativos
                       if t.type == TransactionType.DESPESA)

        type_map = FinancialCalculator._income_type_map(config)
        totals = {'fixa': 0.0, 'variavel': 0.0, 'nao_classificada': 0.0}
        for t in receitas:
            totals[FinancialCalculator.classify_income(t, type_map)] += t.value

        cobertura = (totals['fixa'] / despesas * 100) if despesas > 0 else 0.0
        gap = max(despesas - totals['fixa'], 0.0)

        return {
            'fixa': totals['fixa'],
            'variavel': totals['variavel'],
            'nao_classificada': totals['nao_classificada'],
            'renda_necessaria': despesas,
            'cobertura_fixa_pct': cobertura,
            'gap_variavel': gap,
        }

    @staticmethod
    def calculate_income_by_month(transactions: List[Transaction],
                                  config) -> List[Dict[str, Any]]:
        """
        Evolução mensal: renda fixa/variável/não classificada empilhadas
        + renda necessária (despesas) como linha de referência.
        """
        ativos = [t for t in transactions if not t.is_neutral]
        type_map = FinancialCalculator._income_type_map(config)

        by_month = defaultdict(lambda: {'fixa': 0.0, 'variavel': 0.0,
                                        'nao_classificada': 0.0,
                                        'renda_necessaria': 0.0})
        for t in ativos:
            m = by_month[t.month_year]
            if t.type == TransactionType.RECEITA:
                m[FinancialCalculator.classify_income(t, type_map)] += t.value
            else:
                m['renda_necessaria'] += t.absolute_value

        return [{'month': month, **vals}
                for month, vals in sorted(by_month.items(),
                                          key=lambda item: ordem_do_mes(item[0]))]

    # ------------------------------------------------------------------
    # Renda por dono da fonte (v3.1 — sessão 5)
    # ------------------------------------------------------------------

    # Rótulos das duas ausências, distintas de propósito: a receita sem
    # fonte atribuída é trabalho de classificação que o dono ainda não fez
    # (decisão nº 2: atribuição é manual, transação a transação); a fonte
    # sem dono é cadastro incompleto na sidebar. Somar as duas num "outros"
    # esconderia qual das duas ações resolve.
    SEM_FONTE = "Sem fonte atribuída"
    FONTE_SEM_DONO = "Fonte sem dono"

    @staticmethod
    def _income_owner_map(config) -> Dict[str, str]:
        """{nome_da_fonte: dono}"""
        return {s.name: (getattr(s, 'owner', '') or '')
                for s in getattr(config, 'income_sources', [])}

    @staticmethod
    def attribute_income_owner(t: Transaction,
                               owner_map: Dict[str, str]) -> str:
        """
        Dono de uma receita, resolvido pela fonte atribuída manualmente.

        Para linha de RECEITA a categoria não responde nada — receita não
        tem comerciante, nenhuma regra de conteúdo pontua e ela fica em
        "Transferências". A fonte é o único eixo que responde, e o dono é o
        agrupamento dela.
        """
        source = getattr(t, 'income_source', None)
        if not source:
            return FinancialCalculator.SEM_FONTE
        if source not in owner_map:
            # Fonte atribuída que sumiu do cadastro: é ausência de dono,
            # não ausência de atribuição.
            return FinancialCalculator.FONTE_SEM_DONO
        return owner_map[source] or FinancialCalculator.FONTE_SEM_DONO

    @staticmethod
    def calculate_income_by_owner(transactions: List[Transaction],
                                  config) -> List[Dict[str, Any]]:
        """
        Renda do período agregada por dono da fonte (exclui neutras).

        Returns:
            [{owner, total, num_transacoes, pct}] ordenado por total
            decrescente. `pct` é a fatia sobre a renda total do período.
        """
        receitas = [t for t in transactions
                    if not t.is_neutral and t.type == TransactionType.RECEITA]
        owner_map = FinancialCalculator._income_owner_map(config)

        agg = defaultdict(lambda: {'total': 0.0, 'num_transacoes': 0})
        for t in receitas:
            dono = FinancialCalculator.attribute_income_owner(t, owner_map)
            agg[dono]['total'] += t.value
            agg[dono]['num_transacoes'] += 1

        total_geral = sum(v['total'] for v in agg.values())
        return [
            {'owner': dono,
             'total': v['total'],
             'num_transacoes': v['num_transacoes'],
             'pct': (v['total'] / total_geral * 100) if total_geral else 0.0}
            for dono, v in sorted(agg.items(),
                                  key=lambda item: item[1]['total'],
                                  reverse=True)
        ]

    @staticmethod
    def calculate_income_by_owner_by_month(transactions: List[Transaction],
                                           config) -> List[Dict[str, Any]]:
        """
        "Quanto cada um faz por mês" — uma linha por mês, uma coluna por
        dono. Meses sem receita de um dono vêm com 0.0, para a série não
        ter buraco.

        Ordenado CRONOLOGICAMENTE por `ordem_do_mes`: "MM/AAAA" como texto
        compara o mês antes do ano.
        """
        receitas = [t for t in transactions
                    if not t.is_neutral and t.type == TransactionType.RECEITA]
        owner_map = FinancialCalculator._income_owner_map(config)

        donos = set()
        by_month = defaultdict(lambda: defaultdict(float))
        for t in receitas:
            dono = FinancialCalculator.attribute_income_owner(t, owner_map)
            donos.add(dono)
            by_month[t.month_year][dono] += t.value

        ordenados = sorted(donos)
        return [
            {'month': mes, **{d: vals.get(d, 0.0) for d in ordenados}}
            for mes, vals in sorted(by_month.items(),
                                    key=lambda item: ordem_do_mes(item[0]))
        ]

    @staticmethod
    def savings_rate_from_summary(summary: FinancialSummary) -> float:
        """
        Taxa de poupança a partir de um resumo JÁ calculado.

        Existe para que a taxa e os três cards ao lado saiam da MESMA
        população por construção, não por coincidência de argumento: o
        chamador passa o resumo que já está na tela.

        PODE SER NEGATIVA, de propósito. O clamp `max(0.0, ...)` que
        existia aqui zerava todo mês que gastou mais do que entrou, e o
        negativo É a informação.
        """
        if summary.total_receitas == 0:
            return 0.0
        return (summary.saldo / summary.total_receitas) * 100

    @staticmethod
    def calculate_savings_rate(transactions: List[Transaction],
                               exclude_internal: bool = True) -> float:
        """
        Taxa de poupança (percentual de receitas que sobra).

        `exclude_internal` precisa espelhar o que o chamador usou para
        montar os outros números da mesma tela. Antes ele era fixo em True
        por dentro enquanto os cards vizinhos seguiam o checkbox do
        usuário, e em parte dos meses os quatro números da mesma linha
        saíam de populações diferentes.

        Pode devolver valor NEGATIVO — ver `savings_rate_from_summary`.
        """
        summary = FinancialCalculator.calculate_summary(
            transactions, exclude_internal=exclude_internal)
        return FinancialCalculator.savings_rate_from_summary(summary)


class TransactionFilter:
    """Filtros para transações"""
    
    @staticmethod
    def filter_by_period(transactions: List[Transaction], 
                        days: Optional[int] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None,
                        hoje: Optional[datetime] = None) -> List[Transaction]:
        """
        Filtra transações por período

        Args:
            transactions: Lista de transações
            days: Últimos N dias (alternativa a start/end)
            start_date: Data inicial
            end_date: Data final
            hoje: de que dia contar os N dias para trás. O padrão, None, é
                o relógio — o comportamento de sempre. A demonstração passa
                a sua data de referência, fixa. Só vale com `days`.
        """
        if days is not None:
            agora = hoje if hoje is not None else datetime.now()
            # O corte é normalizado para o INÍCIO DO DIA de propósito.
            # `datetime.now()` carrega a hora, e toda transação é gravada à
            # meia-noite: às 14h de 05/09, um corte de 30 dias caía em
            # 06/08 às 14h e descartava as transações de 06/08 inteiras.
            # "Últimos N dias" conta dias de calendário, não janelas de
            # 24h a partir do instante do clique.
            cutoff = (agora - timedelta(days=days)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            return [t for t in transactions if t.date >= cutoff]
        
        filtered = transactions
        
        if start_date:
            filtered = [t for t in filtered if t.date >= start_date]
        
        if end_date:
            filtered = [t for t in filtered if t.date <= end_date]
        
        return filtered
    
    @staticmethod
    def filter_by_category(transactions: List[Transaction], 
                          category: str) -> List[Transaction]:
        """Filtra por categoria"""
        return [t for t in transactions if t.category == category]
    
    @staticmethod
    def filter_by_type(transactions: List[Transaction], 
                      transaction_type: TransactionType) -> List[Transaction]:
        """Filtra por tipo (receita/despesa)"""
        return [t for t in transactions if t.type == transaction_type]
    
    @staticmethod
    def filter_by_value_range(transactions: List[Transaction],
                             min_value: Optional[float] = None,
                             max_value: Optional[float] = None) -> List[Transaction]:
        """Filtra por faixa de valores"""
        filtered = transactions
        
        if min_value is not None:
            filtered = [t for t in filtered if t.absolute_value >= min_value]
        
        if max_value is not None:
            filtered = [t for t in filtered if t.absolute_value <= max_value]
        
        return filtered
    
    @staticmethod
    def search_description(transactions: List[Transaction], 
                          query: str) -> List[Transaction]:
        """Busca por descrição"""
        query_lower = query.lower()
        return [t for t in transactions if query_lower in t.description.lower()]
