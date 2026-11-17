"""
Storage Manager para persistência de dados
Gerencia leitura/escrita de dados em JSON com backup automático
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import shutil
from src.data.models import Transaction, AppConfig, Semente, SementeAusente


class StorageManager:
    """Gerenciador de persistência de dados"""

    def __init__(self, data_dir: str, somente_leitura: bool = False):
        """
        data_dir: a pasta `data/`. Sem padrão de propósito: o padrão antigo,
            "data" relativo à pasta corrente, abria o dado real de quem
            subisse o processo na pasta do projeto. Quem decide a pasta é
            `src/ambiente.py`.
        somente_leitura: não cria pasta nenhuma e recusa toda gravação. É o
            modo de quem só mede — o ensaio da mudança, o `--simular`.
        """
        self.data_dir = Path(data_dir)
        self.somente_leitura = somente_leitura
        if not somente_leitura:
            self.data_dir.mkdir(exist_ok=True)

        self.data_file = self.data_dir / "transactions.json"
        self.config_file = self.data_dir / "config.json"
        self.backup_dir = self.data_dir / "backups"
        if not somente_leitura:
            self.backup_dir.mkdir(exist_ok=True)

        self.learning_file = self.data_dir / "learning_data.json"

        # Registros que falharam ao carregar. Ficam aqui em vez de sumirem:
        # a interface pode avisar, e `save_transactions` os grava de volta.
        self.registros_ilegiveis: List[Dict[str, Any]] = []

        # Por que a última `load_config` caiu na semente, ou None. A
        # interface mostra; nada aqui grava por causa disso.
        self.aviso_config: Optional[str] = None

    def _exigir_escrita(self):
        if self.somente_leitura:
            raise PermissionError(
                f"StorageManager em somente leitura: nada é gravado em "
                f"{self.data_dir}")

    def load_transactions(self) -> List[Transaction]:
        """
        Carrega transações do arquivo.

        Registro que falha ao virar `Transaction` NÃO é descartado: fica em
        `self.registros_ilegiveis`, com o motivo, e `save_transactions` o
        grava de volta. Antes, o registro sumia da memória e era apagado do
        disco no save seguinte — qualquer correção de categoria bastava.

        Returns:
            Lista de objetos Transaction. Os registros que não carregaram
            saem por `registros_nao_carregados()`.
        """
        self.registros_ilegiveis = []

        if not self.data_file.exists():
            return []
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return self._materializar(data.get('transactions', []))
        
        except json.JSONDecodeError as e:
            print(f"Erro ao decodificar JSON: {e}")
            # Tenta recuperar do backup
            return self._restore_from_backup()
        except Exception as e:
            print(f"Erro ao carregar transações: {e}")
            return []
    
    def _materializar(self, registros: List[Dict[str, Any]]) -> List[Transaction]:
        """
        Converte registros crus em `Transaction`, guardando os que falharem.

        O que falha vai para `self.registros_ilegiveis` com o motivo, em vez
        de ser descartado com um `print` que ninguém lê.
        """
        transacoes = []
        for item in registros:
            try:
                transacoes.append(Transaction.from_dict(item))
            except Exception as e:
                self.registros_ilegiveis.append({
                    'registro': item,
                    'motivo': f"{type(e).__name__}: {e}",
                })
        return transacoes

    def registros_nao_carregados(self) -> List[Dict[str, Any]]:
        """
        Registros que a última carga não conseguiu materializar.

        Cada item é `{'registro': <dado cru>, 'motivo': <str>}`. A interface
        usa isto para avisar; eles continuam no disco de qualquer forma.
        """
        return list(self.registros_ilegiveis)

    def save_transactions(self, transactions: List[Transaction],
                          create_backup: bool = True,
                          preservar_ilegiveis: bool = True):
        """
        Salva transações no arquivo.

        Args:
            transactions: Lista de transações
            create_backup: Se True, cria backup antes de salvar
            preservar_ilegiveis: Se True, regrava os registros que a última
                carga não conseguiu materializar. Sem isso, um save por cima
                os apagaria do disco — que era o comportamento anterior.
        """
        self._exigir_escrita()

        # Cria backup antes de salvar
        if create_backup and self.data_file.exists():
            self._create_backup()

        registros = [t.to_dict() for t in transactions]
        if preservar_ilegiveis and self.registros_ilegiveis:
            registros.extend(item['registro']
                             for item in self.registros_ilegiveis)

        # Prepara dados
        data = {
            'version': '2.0',
            'saved_at': datetime.now().isoformat(),
            'total_transactions': len(registros),
            'transactions': registros
        }

        # Salva em arquivo temporário primeiro
        temp_file = self.data_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # `os.replace` é ATÔMICO, inclusive no Windows. O `shutil.move`
            # que estava aqui não é: `os.rename` sobre arquivo existente
            # levanta FileExistsError no Windows, e o move cai no ramo
            # copy2+unlink. Durante a cópia de 1,9 MB o arquivo fica
            # truncado, e um processo que morra nessa janela deixa o JSON
            # quebrado.
            os.replace(str(temp_file), str(self.data_file))

        except Exception as e:
            # Remove arquivo temporário em caso de erro
            if temp_file.exists():
                temp_file.unlink()
            raise Exception(f"Erro ao salvar transações: {e}")
    
    def load_config(self, semente: Optional[Semente] = None,
                    exigir_semente: bool = False) -> AppConfig:
        """
        Carrega configurações da aplicação.

        Três quedas — `config.json` ausente, ilegível, ou sem membros ou sem
        contas — e todas caem na mesma semente: a de `semente`, quando dada,
        senão a fictícia do código. Com `exigir_semente`, cair sem `semente`
        levanta `SementeAusente`.

        Antes, as três caíam em `AppConfig()`, que era o casal real. Com a
        semente fora do código, cair em `AppConfig()` abriria uma base real
        com membros fictícios, sem aviso, e o primeiro ajuste na barra
        lateral os gravaria por cima. `exigir_semente` é o que fecha isso em
        modo real.

        Ler nunca grava. O motivo da queda fica em `self.aviso_config`.
        """
        self.aviso_config = None

        if not self.config_file.exists():
            motivo = f"{self.config_file} não existe"
            return self._config_da_semente(semente, exigir_semente, motivo)

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return AppConfig.from_dict(data, semente=semente,
                                       exigir_semente=exigir_semente)
        except SementeAusente:
            raise
        except Exception as e:
            motivo = (f"{self.config_file} não se deixa ler "
                      f"({type(e).__name__}: {e})")
            print(f"Erro ao carregar config: {motivo}")
            return self._config_da_semente(semente, exigir_semente, motivo)

    def _config_da_semente(self, semente: Optional[Semente],
                           exigir_semente: bool, motivo: str) -> AppConfig:
        if semente is not None:
            self.aviso_config = (f"{motivo}. Membros e contas vieram da "
                                 f"semente local.")
            return semente.config()
        if exigir_semente:
            raise SementeAusente(f"{motivo}, e a semente local não foi "
                                 f"encontrada")
        self.aviso_config = f"{motivo}. Membros e contas são os do padrão."
        return AppConfig()

    def save_config(self, config: AppConfig):
        """Salva configurações da aplicação"""
        self._exigir_escrita()
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise Exception(f"Erro ao salvar config: {e}")
    
    def load_learning_data(self) -> Dict[str, str]:
        """
        Carrega dados de aprendizado (overrides de categorização)
        
        Returns:
            Dicionário {descrição_normalizada: categoria}
        """
        if not self.learning_file.exists():
            return {}
        
        try:
            with open(self.learning_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar learning data: {e}")
            return {}
    
    def save_learning_data(self, learning_data: Dict[str, str]):
        """Salva dados de aprendizado"""
        self._exigir_escrita()
        try:
            with open(self.learning_file, 'w', encoding='utf-8') as f:
                json.dump(learning_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Erro ao salvar learning data: {e}")
    
    def _create_backup(self):
        """Cria backup do arquivo de dados atual"""
        if not self.data_file.exists():
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"transactions_backup_{timestamp}.json"
        
        try:
            shutil.copy2(self.data_file, backup_file)
            
            # Mantém apenas os últimos 10 backups
            self._cleanup_old_backups(max_backups=10)
        except Exception as e:
            print(f"Erro ao criar backup: {e}")
    
    def _cleanup_old_backups(self, max_backups: int = 10):
        """Remove backups antigos, mantendo apenas os mais recentes"""
        backups = sorted(self.backup_dir.glob("transactions_backup_*.json"))
        
        if len(backups) > max_backups:
            for old_backup in backups[:-max_backups]:
                try:
                    old_backup.unlink()
                except Exception as e:
                    print(f"Erro ao remover backup antigo: {e}")
    
    def _restore_from_backup(self) -> List[Transaction]:
        """Restaura dados do backup mais recente"""
        backups = sorted(self.backup_dir.glob("transactions_backup_*.json"))
        
        if not backups:
            return []
        
        latest_backup = backups[-1]
        print(f"Restaurando do backup: {latest_backup.name}")
        
        try:
            with open(latest_backup, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return self._materializar(data.get('transactions', []))
        except Exception as e:
            print(f"Erro ao restaurar backup: {e}")
            return []
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """Lista todos os backups disponíveis"""
        backups = sorted(self.backup_dir.glob("transactions_backup_*.json"), reverse=True)
        
        result = []
        for backup in backups:
            try:
                stats = backup.stat()
                result.append({
                    'filename': backup.name,
                    'path': str(backup),
                    'size': stats.st_size,
                    'modified': datetime.fromtimestamp(stats.st_mtime)
                })
            except Exception:
                continue
        
        return result
    
    def export_to_csv(self, transactions: List[Transaction], output_path: str):
        """Exporta transações para CSV"""
        import csv

        self._exigir_escrita()

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Data', 'Valor', 'Descrição', 'Categoria',
                             'Tipo', 'Conta', 'ID Externo'])

            for t in transactions:
                writer.writerow([
                    t.date_str,
                    t.value,
                    t.description,
                    t.category,            # categoria é string desde a v2.1
                    t.type.value,
                    t.source_account or '',
                    t.external_id or '',
                ])
    
    def _versao_config(self) -> str:
        """
        A versão gravada no `config.json`, sem passar por `load_config`: as
        estatísticas não podem disparar a queda para a semente nem apagar o
        `aviso_config` da carga de verdade.
        """
        padrao = AppConfig().version
        if not self.config_file.exists():
            return padrao
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f).get('version', padrao)
        except Exception:
            return padrao

    def get_statistics(self) -> Dict[str, Any]:
        """Retorna estatísticas sobre os dados armazenados"""
        transactions = self.load_transactions()
        backups = self.list_backups()
        
        if transactions:
            dates = [t.date for t in transactions]
            values = [t.value for t in transactions]
        else:
            dates = []
            values = []
        
        return {
            'total_transactions': len(transactions),
            'storage_size_mb': self.data_file.stat().st_size / (1024 * 1024) if self.data_file.exists() else 0,
            'num_backups': len(backups),
            'oldest_transaction': min(dates) if dates else None,
            'newest_transaction': max(dates) if dates else None,
            'config_version': self._versao_config(),
            'last_modified': datetime.fromtimestamp(self.data_file.stat().st_mtime) if self.data_file.exists() else None
        }
