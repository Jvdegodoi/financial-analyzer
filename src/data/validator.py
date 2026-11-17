"""
Validação de Dados
Valida e sanitiza dados de transações
"""

from datetime import datetime
from typing import Tuple, Optional
import math
import re


class DataValidator:
    """Validador de dados de transações"""
    
    # Limites de validação
    MAX_VALUE = 1_000_000_000  # 1 bilhão
    MIN_YEAR = 2000
    MAX_YEAR = datetime.now().year + 1
    
    @staticmethod
    def validate_value(value_str: str) -> Tuple[bool, Optional[float], str]:
        """
        Valida e converte valor monetário
        
        Args:
            value_str: String do valor a validar
            
        Returns:
            (sucesso, valor_convertido, mensagem_erro)
        """
        if not value_str or value_str.strip() == '':
            return False, None, "Valor vazio"
        
        try:
            # Remove símbolos comuns e espaços
            clean = str(value_str).strip()
            clean = clean.replace('R$', '').replace('$', '')
            clean = clean.replace(' ', '')
            
            # Detecta formato brasileiro (1.234,56) vs americano (1,234.56)
            if ',' in clean and '.' in clean:
                # Tem ambos - determina qual é decimal
                last_comma = clean.rfind(',')
                last_dot = clean.rfind('.')
                
                if last_comma > last_dot:
                    # Formato brasileiro: 1.234,56
                    clean = clean.replace('.', '').replace(',', '.')
                else:
                    # Formato americano: 1,234.56
                    clean = clean.replace(',', '')
            elif ',' in clean:
                # Só vírgula - pode ser decimal brasileiro ou milhares americano
                # Se tem apenas uma vírgula e está nos últimos 3 dígitos, é decimal
                parts = clean.split(',')
                if len(parts) == 2 and len(parts[1]) <= 2:
                    clean = clean.replace(',', '.')
                else:
                    clean = clean.replace(',', '')
            # Se só tem ponto, assume decimal americano (já está ok)
            
            value = float(clean)

            # NaN e infinito passam pelo float() sem levantar. Uma célula de
            # Valor em branco chega aqui como 'nan' — o pandas lê a célula
            # com dtype=str e devolve NaN, e o parser faz str(NaN). A guarda
            # seguinte do parser é `if value == 0`, e `nan == 0` é falso: o
            # NaN entrava na base e apagava todas as métricas (R$ nan em
            # Receitas, Despesas, Saldo e em toda categoria). Pior, json.dump
            # grava NaN sem reclamar e o token não é JSON válido, o que
            # recusa o arquivo inteiro em qualquer leitor que não seja Python.
            if math.isnan(value):
                return False, None, (
                    f"Valor ausente ou não numérico: '{value_str}' "
                    f"(célula em branco vira NaN)")
            if math.isinf(value):
                return False, None, f"Valor infinito: '{value_str}'"

            # Validações
            if abs(value) > DataValidator.MAX_VALUE:
                return False, None, f"Valor muito alto: R$ {value:,.2f}"
            
            if abs(value) < 0.01 and value != 0:
                return False, None, f"Valor muito baixo: R$ {value:,.2f}"
            
            return True, value, ""
            
        except ValueError:
            return False, None, f"Formato de valor inválido: '{value_str}'"
        except Exception as e:
            return False, None, f"Erro ao processar valor: {str(e)}"
    
    @staticmethod
    def validate_date(date_str: str) -> Tuple[bool, Optional[datetime], str]:
        """
        Valida e converte data
        
        Args:
            date_str: String da data a validar
            
        Returns:
            (sucesso, data_convertida, mensagem_erro)
        """
        if not date_str or date_str.strip() == '':
            return False, None, "Data vazia"
        
        # Formatos suportados
        formats = [
            '%d/%m/%Y',      # 31/12/2025
            '%Y-%m-%d',      # 2025-12-31
            '%d-%m-%Y',      # 31-12-2025
            '%d.%m.%Y',      # 31.12.2025
            '%Y/%m/%d',      # 2025/12/31
            '%d/%m/%y',      # 31/12/25
        ]
        
        date_str = str(date_str).strip()
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                
                # Validações
                if dt.year < DataValidator.MIN_YEAR:
                    return False, None, f"Ano muito antigo: {dt.year}"
                
                if dt.year > DataValidator.MAX_YEAR:
                    return False, None, f"Ano no futuro: {dt.year}"
                
                if dt > datetime.now():
                    # Permite até 7 dias no futuro (para transações programadas)
                    from datetime import timedelta
                    if (dt - datetime.now()) > timedelta(days=7):
                        return False, None, f"Data muito no futuro: {dt.strftime('%d/%m/%Y')}"
                
                return True, dt, ""
                
            except ValueError:
                continue
        
        return False, None, f"Formato de data inválido: '{date_str}'"
    
    @staticmethod
    def validate_description(description: str) -> Tuple[bool, str, str]:
        """
        Valida e sanitiza descrição
        
        Args:
            description: Descrição a validar
            
        Returns:
            (sucesso, descricao_sanitizada, mensagem_erro)
        """
        if not description or description.strip() == '':
            return False, "", "Descrição vazia"
        
        # Sanitiza
        clean = str(description).strip()
        
        # Remove caracteres de controle
        clean = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', clean)
        
        # Limita tamanho
        max_length = 500
        if len(clean) > max_length:
            clean = clean[:max_length] + "..."
        
        if len(clean) < 2:
            return False, "", "Descrição muito curta"
        
        return True, clean, ""
    
    @staticmethod
    def normalize_description(description: str) -> str:
        """
        Normaliza descrição para comparação/matching
        
        Remove acentos, converte para lowercase, remove pontuação extra
        """
        import unicodedata
        
        # Remove acentos
        nfkd = unicodedata.normalize('NFKD', description)
        normalized = ''.join([c for c in nfkd if not unicodedata.combining(c)])
        
        # Lowercase
        normalized = normalized.lower()
        
        # Remove pontuação extra, mantém apenas letras, números e espaços
        normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
        
        # Normaliza espaços
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    @staticmethod
    def detect_duplicate(description: str, existing_descriptions: list[str], 
                        threshold: float = 0.85) -> Tuple[bool, Optional[str]]:
        """
        Detecta possível duplicata usando similaridade de strings
        
        Args:
            description: Descrição a verificar
            existing_descriptions: Lista de descrições existentes
            threshold: Limite de similaridade (0-1)
            
        Returns:
            (is_duplicate, matched_description)
        """
        from difflib import SequenceMatcher
        
        normalized = DataValidator.normalize_description(description)
        
        for existing in existing_descriptions:
            existing_normalized = DataValidator.normalize_description(existing)
            
            # Calcula similaridade
            ratio = SequenceMatcher(None, normalized, existing_normalized).ratio()
            
            if ratio >= threshold:
                return True, existing
        
        return False, None
    
    @staticmethod
    def is_valid_transaction(value: float, description: str, date: datetime) -> Tuple[bool, str]:
        """
        Validação completa de uma transação
        
        Returns:
            (valida, mensagem_erro)
        """
        errors = []
        
        # Valida valor
        if abs(value) < 0.01 and value != 0:
            errors.append("Valor muito baixo")
        
        if abs(value) > DataValidator.MAX_VALUE:
            errors.append("Valor muito alto")
        
        # Valida descrição
        if not description or len(description.strip()) < 2:
            errors.append("Descrição inválida")
        
        # Valida data
        if date.year < DataValidator.MIN_YEAR or date.year > DataValidator.MAX_YEAR:
            errors.append("Data inválida")
        
        if errors:
            return False, "; ".join(errors)
        
        return True, ""


class CSVValidator:
    """Validador específico para arquivos CSV"""
    
    @staticmethod
    def validate_headers(headers: list[str]) -> Tuple[bool, dict, list[str]]:
        """
        Valida e mapeia headers do CSV
        
        Returns:
            (valido, mapeamento, erros)
        """
        required_patterns = {
            'date': ['data', 'date', 'dt', 'fecha'],
            'value': ['valor', 'value', 'val', 'montante', 'amount'],
            'description': ['descricao', 'descrição', 'description', 'desc', 'historico']
        }
        
        headers_lower = [h.lower().strip() for h in headers]
        mapping = {}
        errors = []
        
        for field, patterns in required_patterns.items():
            found = False
            for i, header in enumerate(headers_lower):
                for pattern in patterns:
                    if pattern in header:
                        mapping[field] = headers[i]  # Nome original
                        found = True
                        break
                if found:
                    break
            
            if not found:
                errors.append(f"Coluna '{field}' não encontrada. Padrões esperados: {patterns}")
        
        valid = len(errors) == 0
        return valid, mapping, errors
    
    @staticmethod
    def validate_csv_row(row: dict, row_number: int) -> Tuple[bool, dict, list[str]]:
        """
        Valida uma linha do CSV
        
        Returns:
            (valida, dados_validados, avisos)
        """
        warnings = []
        validated = {}
        
        # Valida cada campo
        for key, value in row.items():
            if not value or str(value).strip() == '':
                warnings.append(f"Linha {row_number}: Campo '{key}' vazio")
        
        return len(warnings) == 0, validated, warnings
