# -*- coding: utf-8 -*-
"""
Camada de unidade — `StorageManager`, os primeiros testes que o arquivo teve.

O perfilador da revisão de engenharia mediu 0 de 12 funções de
`src/data/storage.py` executadas pela suíte: nenhum teste construía um
`StorageManager`. É a camada que grava o arquivo onde mora tudo, e três
achados do balde 1 moram lá — foi consequência direta da ausência.

Os testes de roundtrip que já existiam (`to_dict`/`from_dict`) nunca passam
pelo disco. Estes passam: cada um monta um `data/` inteiro em `tmp_path`.

Cobertura mínima pedida pela Fase 2f: ciclo de salvar e carregar, registro
inválido preservado, rotação de backup, e restauração a partir de backup.
"""

import json
from datetime import datetime

import pytest

from src.data.models import AppConfig, Transaction
from src.data.storage import StorageManager


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

@pytest.fixture
def storage(tmp_path) -> StorageManager:
    """Um `data/` novo em folha, isolado, por teste."""
    return StorageManager(data_dir=str(tmp_path / "data"))


def _transacao(identificador: str, valor: float = -50.0,
               categoria: str = "Alimentação",
               subcategoria=None) -> Transaction:
    return Transaction(
        id=identificador,
        date=datetime(2026, 1, 15),
        value=valor,
        description="Compra sintética %s" % identificador,
        category=categoria,
        subcategory=subcategoria,
        source_account="Nubank (conta) 99887766",
    )


def _escrever_cru(storage: StorageManager, registros: list) -> None:
    """Escreve `transactions.json` à mão, para poder inserir lixo."""
    storage.data_file.write_text(
        json.dumps({'version': '2.0',
                    'saved_at': datetime.now().isoformat(),
                    'total_transactions': len(registros),
                    'transactions': registros},
                   ensure_ascii=False),
        encoding="utf-8")


# ---------------------------------------------------------------------------
# Ciclo de salvar e carregar
# ---------------------------------------------------------------------------

def test_arquivo_ausente_carrega_lista_vazia(storage):
    assert not storage.data_file.exists()
    assert storage.load_transactions() == []


def test_ciclo_salvar_e_carregar_preserva_os_campos(storage):
    original = _transacao("t-1", valor=-123.45, categoria="Alimentação",
                          subcategoria="Delivery")
    original.is_manual_category = True
    original.income_source = None
    original.external_id = "abc-123"

    storage.save_transactions([original])
    (recarregada,) = storage.load_transactions()

    assert recarregada.id == original.id
    assert recarregada.date == original.date
    assert recarregada.value == original.value
    assert recarregada.description == original.description
    assert recarregada.category == "Alimentação"
    assert recarregada.subcategory == "Delivery"
    assert recarregada.category_path == "Alimentação > Delivery"
    assert recarregada.external_id == "abc-123"
    assert recarregada.source_account == original.source_account
    assert recarregada.is_manual_category is True


def test_salvar_por_cima_substitui_e_nao_acumula(storage):
    storage.save_transactions([_transacao("t-1"), _transacao("t-2")])
    storage.save_transactions([_transacao("t-3")])

    assert [t.id for t in storage.load_transactions()] == ["t-3"]


def test_o_temporario_nao_sobra_depois_do_save(storage):
    """
    A gravação passa por um `.tmp` e o substitui com `os.replace`, que é
    atômico inclusive no Windows. Se o temporário sobrar, a troca não
    aconteceu como se espera.
    """
    storage.save_transactions([_transacao("t-1")])

    assert storage.data_file.exists()
    assert not storage.data_file.with_suffix('.tmp').exists()


def test_a_substituicao_troca_o_arquivo_em_vez_de_copiar_por_cima(storage):
    """
    Achado 1.3, e o teste que separa `os.replace` de `shutil.move`.

    `os.replace` RENOMEIA o temporário por cima do destino: o arquivo que
    fica no lugar é o temporário, com outro índice no sistema de arquivos.
    O `shutil.move` que estava aqui não conseguia renomear — no Windows
    `os.rename` sobre arquivo existente levanta FileExistsError — e caía no
    ramo copy2+unlink, que escreve DENTRO do arquivo vivo, preservando o
    índice. Durante essa cópia o JSON de 1,9 MB fica truncado.

    Comparar o índice antes e depois é o que torna a diferença observável:
    o teste do `.tmp` que não sobra passaria nos dois casos.
    """
    storage.save_transactions([_transacao("t-1")])
    indice_antes = storage.data_file.stat().st_ino

    storage.save_transactions([_transacao("t-2")])
    indice_depois = storage.data_file.stat().st_ino

    assert indice_antes != indice_depois, (
        "o arquivo de destino manteve a identidade: a gravação copiou por "
        "cima do arquivo vivo em vez de substituí-lo atomicamente")


def test_o_arquivo_gravado_e_json_valido_e_declara_o_total(storage):
    storage.save_transactions([_transacao("t-1"), _transacao("t-2")])

    bruto = json.loads(storage.data_file.read_text(encoding="utf-8"))
    assert bruto['total_transactions'] == 2
    assert len(bruto['transactions']) == 2


def test_config_faz_roundtrip_pelo_disco(storage):
    config = AppConfig()
    storage.save_config(config)
    recarregada = storage.load_config()

    assert [m.name for m in recarregada.members] == \
        [m.name for m in config.members]
    assert [a.label for a in recarregada.accounts] == \
        [a.label for a in config.accounts]


def test_aprendizado_faz_roundtrip_pelo_disco(storage):
    storage.save_learning_data({"padaria do zé": "Alimentação > Padaria"})
    assert storage.load_learning_data() == {
        "padaria do zé": "Alimentação > Padaria"}


# ---------------------------------------------------------------------------
# Registro que falha ao carregar — achado 1.4
# ---------------------------------------------------------------------------

def test_registro_invalido_nao_derruba_a_carga_e_e_relatado(storage):
    _escrever_cru(storage, [
        _transacao("ok-1").to_dict(),
        {"id": "ruim", "isto": "não é uma transação"},
        _transacao("ok-2").to_dict(),
    ])

    carregadas = storage.load_transactions()

    assert [t.id for t in carregadas] == ["ok-1", "ok-2"]
    ilegiveis = storage.registros_nao_carregados()
    assert len(ilegiveis) == 1
    assert ilegiveis[0]['registro']['id'] == "ruim"
    assert ilegiveis[0]['motivo']


def test_registro_invalido_sobrevive_ao_save_seguinte(storage):
    """
    O achado 1.4 na íntegra: o registro sumia da memória e era apagado do
    disco no save seguinte — e `save_data()` é chamado em oito lugares de
    `app.py`, então qualquer correção de categoria bastava.
    """
    _escrever_cru(storage, [
        _transacao("ok-1").to_dict(),
        {"id": "ruim", "isto": "não é uma transação"},
    ])

    carregadas = storage.load_transactions()
    assert len(carregadas) == 1

    # Qualquer edição que dispare um save.
    carregadas[0].update_category("Lazer", None, is_manual=True)
    storage.save_transactions(carregadas)

    bruto = json.loads(storage.data_file.read_text(encoding="utf-8"))
    ids = [r.get("id") for r in bruto['transactions']]
    assert "ruim" in ids, "o registro ilegível foi apagado do disco"
    assert "ok-1" in ids
    assert bruto['total_transactions'] == 2

    # E continua ilegível na carga seguinte, sem ter virado outra coisa.
    storage.load_transactions()
    assert len(storage.registros_nao_carregados()) == 1


def test_preservar_ilegiveis_pode_ser_desligado_de_proposito(storage):
    _escrever_cru(storage, [{"id": "ruim", "isto": "não é uma transação"}])
    storage.load_transactions()

    storage.save_transactions([_transacao("t-1")], preservar_ilegiveis=False)

    bruto = json.loads(storage.data_file.read_text(encoding="utf-8"))
    assert [r["id"] for r in bruto['transactions']] == ["t-1"]


def test_carga_nova_limpa_a_lista_de_ilegiveis(storage):
    _escrever_cru(storage, [{"id": "ruim", "isto": "não é uma transação"}])
    storage.load_transactions()
    assert len(storage.registros_nao_carregados()) == 1

    storage.save_transactions([_transacao("t-1")], preservar_ilegiveis=False)
    storage.load_transactions()
    assert storage.registros_nao_carregados() == []


# ---------------------------------------------------------------------------
# Backup: criação, rotação e restauração
# ---------------------------------------------------------------------------

def test_o_primeiro_save_nao_gera_backup_e_o_segundo_gera(storage):
    storage.save_transactions([_transacao("t-1")])
    assert storage.list_backups() == []

    storage.save_transactions([_transacao("t-2")])
    assert len(storage.list_backups()) == 1


def test_rotacao_de_backup_mantem_no_maximo_dez(storage):
    """
    `_cleanup_old_backups` guarda 10. O timestamp do nome tem resolução de
    segundo, então os backups são forjados à mão: um teste que dependesse do
    relógio para gerar 12 nomes distintos levaria 12 segundos ou seria
    instável.
    """
    storage.save_transactions([_transacao("t-0")])
    for i in range(12):
        (storage.backup_dir /
         f"transactions_backup_202601{i + 10:02d}_120000.json").write_text(
            "{}", encoding="utf-8")
    assert len(storage.list_backups()) == 12

    storage._cleanup_old_backups(max_backups=10)

    restantes = sorted(p.name for p in
                       storage.backup_dir.glob("transactions_backup_*.json"))
    assert len(restantes) == 10
    # Os que ficam são os mais RECENTES: a ordenação é por nome, e o nome
    # começa pelo timestamp.
    assert restantes[0] == "transactions_backup_20260112_120000.json"
    assert restantes[-1] == "transactions_backup_20260121_120000.json"


def test_restaura_do_backup_quando_o_json_esta_quebrado(storage):
    storage.save_transactions([_transacao("t-1"), _transacao("t-2")])
    storage.save_transactions([_transacao("t-1"), _transacao("t-2"),
                               _transacao("t-3")])
    assert len(storage.list_backups()) == 1

    # O arquivo vivo fica truncado no meio — o cenário do achado 1.3.
    conteudo = storage.data_file.read_text(encoding="utf-8")
    storage.data_file.write_text(conteudo[:len(conteudo) // 2],
                                 encoding="utf-8")

    recuperadas = storage.load_transactions()

    # O backup é o estado ANTERIOR ao último save: duas transações.
    assert [t.id for t in recuperadas] == ["t-1", "t-2"]


def test_restauracao_sem_nenhum_backup_devolve_vazio(storage):
    storage.data_file.write_text("{isto não é json", encoding="utf-8")
    assert storage.load_transactions() == []


def test_restauracao_tambem_relata_registro_ilegivel(storage):
    """
    O caminho de restauração usa o mesmo materializador do caminho normal —
    antes ele engolia o registro inválido com um `continue` mudo.
    """
    storage.save_transactions([_transacao("t-1")])
    backup = storage.backup_dir / "transactions_backup_20260101_120000.json"
    backup.write_text(json.dumps({'transactions': [
        _transacao("t-1").to_dict(),
        {"id": "ruim", "isto": "não é uma transação"},
    ]}), encoding="utf-8")
    storage.data_file.write_text("{isto não é json", encoding="utf-8")

    recuperadas = storage.load_transactions()

    assert [t.id for t in recuperadas] == ["t-1"]
    assert len(storage.registros_nao_carregados()) == 1


# ---------------------------------------------------------------------------
# Estatísticas e listagem
# ---------------------------------------------------------------------------

def test_estatisticas_da_base_vazia(storage):
    stats = storage.get_statistics()
    assert stats['total_transactions'] == 0
    assert stats['num_backups'] == 0
    assert stats['oldest_transaction'] is None


def test_estatisticas_contam_transacoes_e_faixa_de_datas(storage):
    antiga = _transacao("t-1")
    antiga.date = datetime(2025, 8, 1)
    nova = _transacao("t-2")
    nova.date = datetime(2026, 8, 31)
    storage.save_transactions([antiga, nova])

    stats = storage.get_statistics()
    assert stats['total_transactions'] == 2
    assert stats['oldest_transaction'] == datetime(2025, 8, 1)
    assert stats['newest_transaction'] == datetime(2026, 8, 31)
    assert stats['storage_size_mb'] > 0


# ---------------------------------------------------------------------------
# Somente leitura (sessão 1a, item 6.7)
# ---------------------------------------------------------------------------

def test_somente_leitura_nao_cria_pasta_nenhuma(tmp_path):
    StorageManager(data_dir=str(tmp_path / "data"), somente_leitura=True)
    assert list(tmp_path.iterdir()) == []


def test_somente_leitura_recusa_toda_gravacao(storage, tmp_path):
    storage.save_transactions([_transacao("t-1")], create_backup=False)
    storage.save_config(AppConfig())
    antes = {p: p.read_bytes() for p in storage.data_dir.rglob("*")
             if p.is_file()}

    leitor = StorageManager(data_dir=str(storage.data_dir),
                            somente_leitura=True)
    assert [t.id for t in leitor.load_transactions()] == ["t-1"]

    for gravar in (lambda: leitor.save_transactions([_transacao("t-2")]),
                   lambda: leitor.save_config(AppConfig()),
                   lambda: leitor.save_learning_data({}),
                   lambda: leitor.export_to_csv([], str(tmp_path / "x.csv"))):
        with pytest.raises(PermissionError):
            gravar()

    depois = {p: p.read_bytes() for p in storage.data_dir.rglob("*")
              if p.is_file()}
    assert depois == antes
    assert not (tmp_path / "x.csv").exists()


# ---------------------------------------------------------------------------
# Queda da configuração para a semente (sessão 1a, item 6.3)
# ---------------------------------------------------------------------------

def _semente():
    from src.data.models import FamilyAccount, FamilyMember, Semente
    return Semente(
        members=[FamilyMember(name="Helena Varanda",
                              aliases=["helena varanda"])],
        accounts=[FamilyAccount(label="Inter (conta) 10203040",
                                owner="Helena Varanda")])


def test_config_ausente_cai_na_semente_dada(storage):
    config = storage.load_config(semente=_semente(), exigir_semente=True)

    assert [m.name for m in config.members] == ["Helena Varanda"]
    assert "não existe" in storage.aviso_config


def test_config_ilegivel_cai_na_semente_e_nao_regrava(storage):
    storage.config_file.write_text("{isto não é json", encoding="utf-8")

    config = storage.load_config(semente=_semente(), exigir_semente=True)

    assert [m.name for m in config.members] == ["Helena Varanda"]
    assert "não se deixa ler" in storage.aviso_config
    assert storage.config_file.read_text(encoding="utf-8") == "{isto não é json"


def test_config_ilegivel_sem_semente_exigida_levanta(storage):
    from src.data.models import SementeAusente
    storage.config_file.write_text("{isto não é json", encoding="utf-8")

    with pytest.raises(SementeAusente):
        storage.load_config(semente=None, exigir_semente=True)


def test_config_sem_membros_cai_na_semente_e_mantem_o_resto(storage):
    storage.config_file.write_text(json.dumps({
        "members": [], "income_sources": [
            {"name": "Fonte Inventada", "type": "fixa", "owner": "x"}]}),
        encoding="utf-8")

    config = storage.load_config(semente=_semente(), exigir_semente=True)

    assert [m.name for m in config.members] == ["Helena Varanda"]
    assert [s.name for s in config.income_sources] == ["Fonte Inventada"]


def test_config_sem_membros_e_sem_semente_exigida_levanta(storage):
    from src.data.models import SementeAusente
    storage.config_file.write_text(json.dumps({"members": []}),
                                   encoding="utf-8")

    with pytest.raises(SementeAusente, match="members"):
        storage.load_config(exigir_semente=True)


def test_sem_exigir_a_queda_e_o_pool_ficticio(storage):
    """O padrão do código, e o da demonstração."""
    assert ([m.name for m in storage.load_config().members]
            == [m.name for m in AppConfig().members])


def test_config_integro_ignora_a_semente(storage):
    storage.save_config(AppConfig())

    config = storage.load_config(semente=_semente(), exigir_semente=True)

    assert [m.name for m in config.members] == [
        m.name for m in AppConfig().members]
    assert storage.aviso_config is None


def test_estatisticas_nao_apagam_o_aviso_da_carga(storage):
    storage.config_file.write_text("{isto não é json", encoding="utf-8")
    storage.load_config(semente=_semente(), exigir_semente=True)
    aviso = storage.aviso_config

    storage.get_statistics()

    assert storage.aviso_config == aviso
