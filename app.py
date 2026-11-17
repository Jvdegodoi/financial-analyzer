"""
Financial Analyzer — v3.0
Base limpa (extratos são a fonte da verdade) com:
- Categorias em DOIS NÍVEIS (categoria > subcategoria), opcionais,
  semeadas com regras calibradas em extratos reais
- Pool familiar de contas pré-registradas, com conciliação de
  transferências e painel de cobertura
- Importação multi-banco (Nubank, C6, Inter), dedup determinística,
  neutralização de estornos

Onde está o dado quem diz é `src/ambiente.py`. Sem configuração, o app abre
em DEMONSTRAÇÃO: o conjunto fictício de `demonstracao/`, montado numa pasta
temporária a cada vez que o app sobe (`src/demonstracao.py`), com o pool
fictício e um "hoje" próprio — a data de referência do conjunto. A tela diz
isso no título da aba, numa faixa fixa no topo e na barra lateral.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import List, Optional

from src import ambiente as amb
from src import demonstracao as demo
from src.data.models import (Transaction, CategoryManager, AppConfig,
                             TransactionType, FamilyAccount, FamilyMember,
                             IncomeSource, SementeAusente)
from src.data.storage import StorageManager
from src.business.categorizer import SmartCategorizer
from src.business.transfer_matcher import TransferMatcher, CoverageAnalyzer
from src.business.calculator import FinancialCalculator, TransactionFilter
from src.importacao import confirmar_importacao, preparar_importacao

# ============================================================================
# AMBIENTE E CONFIGURAÇÃO DA PÁGINA
# ============================================================================

# Resolvido a cada rerun, antes de qualquer chamada ao Streamlit: o título da
# aba depende dele, e `set_page_config` tem de ser a primeira.
try:
    AMBIENTE = amb.resolver()
    ERRO_AMBIENTE = None
except amb.ConfiguracaoInvalida as e:
    AMBIENTE = None
    ERRO_AMBIENTE = str(e)

EM_DEMO = AMBIENTE is not None and AMBIENTE.demonstracao

# Só na demonstração: o conjunto fictício, de onde saem o período que a faixa
# anuncia e a data que faz as vezes de "hoje". Em modo real nada disto é
# lido, e HOJE fica None — "Últimos N dias" e "Despesa prevista" contam a
# partir do relógio, como sempre.
CONJUNTO_DEMO = None
ERRO_DEMO = None
if EM_DEMO:
    try:
        CONJUNTO_DEMO = demo.carregar_conjunto()
    except demo.ConjuntoInvalido as e:
        ERRO_DEMO = str(e)
HOJE = CONJUNTO_DEMO.data_de_referencia if CONJUNTO_DEMO else None

st.set_page_config(
    page_title=("💰 Financial Analyzer v3.1 · DEMONSTRAÇÃO" if EM_DEMO
                else "💰 Financial Analyzer v3.1"),
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# INICIALIZAÇÃO
# ============================================================================

def verificar_ambiente():
    """
    Para o app, com a mensagem na tela, quando a configuração está errada ou
    aponta para pasta que não está lá. Não cria nada: cair na demonstração
    calado pareceria perda de dado, e criar a pasta abriria uma base vazia
    no lugar errado.
    """
    if ERRO_AMBIENTE:
        st.error("⛔ A configuração do dado não se deixa ler.\n\n"
                 + ERRO_AMBIENTE)
        st.stop()
    problema = AMBIENTE.problema()
    if problema:
        st.error("⛔ " + problema)
        st.stop()
    if ERRO_DEMO:
        st.error("⛔ O conjunto de demonstração não se deixa ler.\n\n"
                 + ERRO_DEMO)
        st.stop()

@st.cache_resource
def init_storage() -> StorageManager:
    """
    Modo real: a pasta `data/` da raiz configurada, e nada mais — a montagem
    da demonstração não é alcançável por este ramo.

    Demonstração: uma pasta temporária nova a cada vez que o processo sobe,
    apagada ao sair, com o conjunto fictício montado dentro dela
    (`src/demonstracao.py`). O que se importa ou edita na demonstração não
    sobrevive a um reinício.
    """
    if AMBIENTE.real:
        return StorageManager(data_dir=str(AMBIENTE.dados_do_app))
    pasta = Path(tempfile.mkdtemp(prefix="fa_demo_"))
    atexit.register(shutil.rmtree, pasta, ignore_errors=True)
    storage = StorageManager(data_dir=str(pasta / "data"))
    demo.montar(storage)
    return storage

def init_categorizer(config: AppConfig) -> SmartCategorizer:
    """Sem cache_resource: a instância viva mora em st.session_state."""
    categorizer = SmartCategorizer(
        members=config.members,
        category_manager=config.get_category_manager()
    )
    learning_data = init_storage().load_learning_data()
    categorizer.load_learning_data(learning_data)
    return categorizer

def load_data():
    """
    Em modo real, toda queda da configuração — `config.json` ausente,
    ilegível ou sem membros — cai na semente local, nunca na fictícia. Sem
    semente local, o app para e diz o que falta.
    """
    if 'transactions' in st.session_state:
        return
    try:
        storage = init_storage()
    except demo.ConjuntoInvalido as e:
        st.error(f"⛔ O conjunto de demonstração não se deixa montar.\n\n{e}")
        st.stop()
    try:
        if AMBIENTE.real:
            semente = amb.carregar_semente(AMBIENTE.arquivo_semente)
            config = storage.load_config(semente=semente, exigir_semente=True)
        else:
            config = storage.load_config()
    except SementeAusente as e:
        st.error(
            f"⛔ Não abri o dado real: {e}.\n\nSem os membros reais, as "
            f"pendências sumiriam e o próximo ajuste gravaria membros "
            f"fictícios por cima. Crie `{amb.ARQUIVO_SEMENTE}` em "
            f"{AMBIENTE.raiz} — o passo a passo está em "
            f"`docs/mudar-o-dado-de-lugar.md` — e reabra o app.")
        st.stop()
    except amb.ConfiguracaoInvalida as e:
        st.error(f"⛔ A semente local não se deixa ler.\n\n{e}")
        st.stop()

    # Só depois de a configuração carregar: um `st.stop` acima não pode
    # deixar a sessão com transações e sem config.
    st.session_state.aviso_config = storage.aviso_config
    st.session_state.pasta_dos_dados = str(storage.data_dir)
    st.session_state.config = config
    st.session_state.transactions = storage.load_transactions()
    st.session_state.categorizer = init_categorizer(config)

def save_data():
    """Salva transações + config + aprendizado (com backup automático)"""
    storage = init_storage()
    storage.save_transactions(st.session_state.transactions)
    storage.save_config(st.session_state.config)
    storage.save_learning_data(st.session_state.categorizer.get_learning_data())

def save_config_only():
    """Ajustes de config não disparam backup das transações"""
    init_storage().save_config(st.session_state.config)

def category_options() -> List[str]:
    """Caminhos selecionáveis: 'Alimentação > Delivery', 'Serviços'..."""
    return st.session_state.config.get_category_manager().get_all_paths()

def path_of(t: Transaction) -> str:
    """Caminho exibível da transação, com '(geral)' quando o pai tem filhos"""
    manager = st.session_state.config.get_category_manager()
    return CategoryManager.path_of(t.category, t.subcategory,
                                   manager.get_tree())

# ============================================================================
# COMPONENTES DE UI
# ============================================================================

def render_summary_cards(summary, filtered_transactions):
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("💰 Receitas", f"R$ {summary.total_receitas:,.2f}",
                  delta=f"{summary.num_receitas} transações")
    with col2:
        st.metric("💸 Despesas", f"R$ {summary.total_despesas:,.2f}",
                  delta=f"{summary.num_despesas} transações",
                  delta_color="inverse")
    with col3:
        saldo_color = "normal" if summary.saldo >= 0 else "inverse"
        st.metric("💵 Saldo", f"R$ {summary.saldo:,.2f}",
                  delta="Positivo" if summary.saldo >= 0 else "Negativo",
                  delta_color=saldo_color)
    with col4:
        # Derivada do MESMO `summary` dos três cards ao lado — não de uma
        # segunda chamada com outra população. Antes, a taxa reexcluía as
        # neutras por dentro enquanto os vizinhos seguiam o checkbox do
        # usuário, e em parte dos meses os quatro números divergiam.
        savings_rate = FinancialCalculator.savings_rate_from_summary(summary)
        st.metric("📊 Taxa de Poupança", f"{savings_rate:.1f}%",
                  delta=f"{summary.num_transacoes} total",
                  delta_color="off",
                  help="Saldo sobre receitas do período. NEGATIVA quando o "
                       "período gastou mais do que entrou — o sinal é a "
                       "informação, não é erro.")

def render_sunburst_chart(transactions: List[Transaction]):
    """
    Sunburst de dois níveis: anel interno = categorias, externo =
    subcategorias. A fatia "(geral)" mostra o quanto de cada categoria
    ainda está sem detalhamento.
    """
    data = FinancialCalculator.calculate_by_subcategory(
        transactions, exclude_internal=False)

    if not data:
        st.info("Nenhuma despesa para exibir")
        return

    df = pd.DataFrame(data)
    fig = px.sunburst(
        df,
        path=['category', 'subcategory'],
        values='value',
        title="Despesas por Categoria e Subcategoria",
    )
    fig.update_traces(
        textinfo='label+percent parent',
        hovertemplate='<b>%{label}</b><br>R$ %{value:,.2f}<extra></extra>'
    )
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)

def render_monthly_trend_chart(data: list):
    if not data:
        st.info("Dados insuficientes para análise mensal")
        return

    df = pd.DataFrame(data)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['month'], y=df['receitas'],
                             mode='lines+markers', name='Receitas',
                             line=dict(color='green', width=3),
                             marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=df['month'], y=df['despesas'],
                             mode='lines+markers', name='Despesas',
                             line=dict(color='red', width=3),
                             marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=df['month'], y=df['saldo'],
                             mode='lines+markers', name='Saldo',
                             line=dict(color='blue', width=2, dash='dot')))
    fig.update_layout(title="Evolução Mensal", xaxis_title="Mês",
                      yaxis_title="Valor (R$)", hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)

def render_path_evolution_chart(transactions: List[Transaction],
                                paths: List[str]):
    """Evolução mensal por caminho (categoria ou subcategoria)"""
    if not paths:
        st.info("Selecione pelo menos um caminho para visualizar")
        return

    data = FinancialCalculator.calculate_monthly_trend_by_path(
        transactions, paths, exclude_internal=False)

    if not data:
        st.info("Sem despesas para os caminhos selecionados no período")
        return

    df = pd.DataFrame(data)
    colors = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b']

    fig = go.Figure()
    for idx, p in enumerate(paths):
        if p in df.columns:
            fig.add_trace(go.Scatter(
                x=df['month'], y=df[p],
                mode='lines+markers', name=p,
                line=dict(color=colors[idx % len(colors)], width=3),
                marker=dict(size=8),
                hovertemplate=f'<b>{p}</b><br>Mês: %{{x}}<br>'
                              f'Valor: R$ %{{y:,.2f}}<extra></extra>'
            ))

    fig.update_layout(
        title="Evolução Mensal por Categoria/Subcategoria",
        xaxis_title="Mês", yaxis_title="Despesas (R$)",
        hovermode='x unified', height=500, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📊 Resumo Estatístico")
    cols = st.columns(len(paths))
    for idx, p in enumerate(paths):
        if p in df.columns:
            with cols[idx]:
                st.metric(label=p, value=f"R$ {df[p].sum():,.2f}",
                          help="Total no período")
                st.caption(f"Média: R$ {df[p].mean():,.2f}")
                st.caption(f"Máximo: R$ {df[p].max():,.2f}")

def render_transactions_table(transactions: List[Transaction],
                              key_suffix: str = ""):
    """
    Tabela editável. A coluna Categoria usa o caminho achatado
    ('Alimentação > Delivery', 'Alimentação (geral)', 'Serviços'):
    um dropdown só, com a dependência categoria→subcategoria embutida.
    """
    if not transactions:
        st.info("Nenhuma transação para exibir")
        return

    df_data = []
    for t in transactions:
        df_data.append({
            'Data': t.date_str,
            'Descrição': t.description,
            'Conta': t.source_account or '—',
            'Categoria': path_of(t),
            'Valor': t.value,
            'Tipo': '💰' if t.type == TransactionType.RECEITA else '💸'
        })

    df = pd.DataFrame(df_data)

    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        disabled=['Data', 'Descrição', 'Conta', 'Valor', 'Tipo'],
        column_config={
            "Categoria": st.column_config.SelectboxColumn(
                "Categoria",
                options=category_options(),
                required=True
            ),
            "Valor": st.column_config.NumberColumn("Valor",
                                                   format="R$ %.2f")
        },
        key=f"editor_{key_suffix}"
    )

    if st.button("💾 Salvar Alterações", key=f"save_{key_suffix}"):
        changes_made = False
        total_recategorized = 0

        for idx, row in edited_df.iterrows():
            if idx < len(transactions):
                trans = transactions[idx]
                new_path = row['Categoria']

                if new_path != path_of(trans):
                    new_cat, new_sub = CategoryManager.parse_path(new_path)
                    trans.update_category(new_cat, new_sub, is_manual=True)

                    st.session_state.categorizer.learn_from_user(
                        trans, new_cat, new_sub)
                    changes_made = True

                    if st.session_state.config.auto_recategorize_similar:
                        total_recategorized += \
                            st.session_state.categorizer.recategorize_similar(
                                trans, new_cat, new_sub,
                                st.session_state.transactions,
                                st.session_state.config.similarity_threshold)

        # A PÁGINA INTEIRA vira revisada, não só as linhas alteradas.
        # Concordar com a classificação é decisão do usuário tanto quanto
        # corrigi-la, e é assim que ele de fato trabalha: percorre a página e
        # mexe no que está errado. Sem isto, "eu olhei e estava certo" fica
        # indistinguível de "eu nunca vi esta linha", e o gabarito de acurácia
        # perde justamente as linhas em que o motor acertou.
        marcadas = sum(1 for t in transactions if t.marcar_revisada())

        if changes_made or marcadas:
            save_data()
            partes = []
            if changes_made:
                partes.append("Alterações salvas e aprendidas")
                if total_recategorized > 0:
                    partes.append(f"{total_recategorized} similares "
                                  f"recategorizadas")
            if marcadas:
                partes.append(f"{marcadas} linhas marcadas como revisadas")
            st.success("✅ " + " · ".join(partes) + ".")
            st.rerun()
        else:
            st.info("Nenhuma alteração detectada — a página já estava "
                    "revisada por inteiro")

# ============================================================================
# SIDEBAR
# ============================================================================

def render_sidebar():
    with st.sidebar:
        if EM_DEMO:
            st.warning("🧪 **Demonstração.** Extratos, pessoas, contas e "
                       "valores inventados, numa base descartável — nada "
                       "aqui é dado real.")
        st.title("⚙️ Configurações")

        # Estatísticas
        with st.expander("📊 Estatísticas do Sistema", expanded=False):
            if EM_DEMO:
                st.caption("Pasta dos dados: temporária, apagada quando o "
                           "app fecha.")
            else:
                st.caption(f"Pasta dos dados: {init_storage().data_dir}")
            stats = init_storage().get_statistics()
            st.metric("Total de Transações", stats['total_transactions'])
            st.metric("Tamanho dos Dados",
                      f"{stats['storage_size_mb']:.2f} MB")
            st.metric("Backups Disponíveis", stats['num_backups'])
            if stats['oldest_transaction']:
                st.text("Mais antiga: "
                        f"{stats['oldest_transaction'].strftime('%d/%m/%Y')}")
            if stats['newest_transaction']:
                st.text("Mais recente: "
                        f"{stats['newest_transaction'].strftime('%d/%m/%Y')}")

        # Árvore de categorias
        with st.expander("🏷️ Categorias e Subcategorias", expanded=False):
            config = st.session_state.config
            manager = config.get_category_manager()
            tree = manager.get_tree()

            st.caption(
                "Dois níveis, subcategoria sempre opcional. Subcategorize "
                "onde a divisão muda decisão — forçar detalhe em tudo "
                "mata o hábito."
            )

            for cat, subs in tree.items():
                st.markdown(f"**{cat}**")
                for sub in subs:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.text(f"  • {sub}")
                    with col2:
                        if st.button("🗑️", key=f"del_sub_{cat}_{sub}"):
                            # Destrutivo mínimo: transações sobem p/ o pai
                            moved = 0
                            for t in st.session_state.transactions:
                                if (t.category == cat
                                        and t.subcategory == sub):
                                    t.clear_subcategory()
                                    moved += 1
                            manager.remove_subcategory(cat, sub)
                            config.custom_tree = manager.custom_tree
                            save_data()
                            st.success(
                                f"'{sub}' removida; {moved} transações "
                                f"subiram para '{cat}'.")
                            st.rerun()

            st.divider()
            st.subheader("Adicionar subcategoria")
            parent = st.selectbox("Categoria pai",
                                  manager.get_all_categories(),
                                  key="new_sub_parent")
            new_sub = st.text_input("Nome da subcategoria", key="new_sub")
            if st.button("➕ Adicionar subcategoria", key="add_sub"):
                if new_sub and manager.add_subcategory(parent, new_sub):
                    config.custom_tree = manager.custom_tree
                    save_config_only()
                    st.success(f"✅ '{parent} > {new_sub}' criada!")
                    st.rerun()
                else:
                    st.error("❌ Inválida ou já existe")

            st.subheader("Adicionar categoria")
            new_cat = st.text_input("Nome da nova categoria", key="new_cat")
            if st.button("➕ Adicionar categoria", key="add_cat"):
                if new_cat and manager.add_category(new_cat):
                    config.custom_tree = manager.custom_tree
                    save_config_only()
                    st.success(f"✅ Categoria '{new_cat}' criada!")
                    st.rerun()
                else:
                    st.error("❌ Inválida ou já existe")

            st.divider()
            st.subheader("⚙️ Aprendizado Automático")
            auto_recat = st.checkbox(
                "Recategorizar similares automaticamente",
                value=config.auto_recategorize_similar,
                help="Ao corrigir uma categoria, transações similares "
                     "são atualizadas nos dois níveis"
            )
            if auto_recat != config.auto_recategorize_similar:
                config.auto_recategorize_similar = auto_recat
                save_config_only()

            similarity = st.slider(
                "Limite de similaridade", 0.5, 1.0,
                value=config.similarity_threshold, step=0.05
            )
            if similarity != config.similarity_threshold:
                config.similarity_threshold = similarity
                save_config_only()

        # Pool familiar
        with st.expander("👨‍👩‍👦 Pool Familiar", expanded=False):
            config = st.session_state.config

            st.subheader("Membros")
            member_names = [m.name for m in config.members]
            for member in config.members:
                st.markdown(f"**{member.name}**")
                st.caption("Apelidos: " + ", ".join(member.aliases))
                new_alias = st.text_input(
                    f"Novo apelido para {member.name}",
                    key=f"alias_{member.name}",
                    help="Use formas específicas (nome + sobrenome) "
                         "para não casar com terceiros."
                )
                if st.button("➕ Adicionar apelido",
                             key=f"add_alias_{member.name}"):
                    alias = new_alias.strip().lower()
                    if alias and alias not in member.aliases:
                        member.aliases.append(alias)
                        st.session_state.categorizer = init_categorizer(config)
                        save_config_only()
                        st.rerun()

            st.divider()
            st.subheader(f"Contas do Pool ({len(config.accounts)})")
            for account in config.accounts:
                col1, col2 = st.columns([3, 2])
                with col1:
                    st.text(account.label)
                with col2:
                    owner = st.selectbox(
                        "Dono", options=member_names,
                        index=(member_names.index(account.owner)
                               if account.owner in member_names else 0),
                        key=f"owner_{account.label}",
                        label_visibility="collapsed"
                    )
                    if owner != account.owner:
                        account.owner = owner
                        save_config_only()

            discovered = CoverageAnalyzer.discover_accounts(
                st.session_state.transactions, config)
            if discovered:
                st.markdown("**Contas detectadas (não registradas):**")
                for label in discovered:
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        st.text(label)
                    with col2:
                        if st.button("Registrar", key=f"reg_{label}"):
                            config.accounts.append(
                                FamilyAccount(label=label,
                                              owner=member_names[0]))
                            save_config_only()
                            st.rerun()

        # Fontes de renda
        with st.expander("💵 Fontes de Renda", expanded=False):
            config = st.session_state.config
            member_names = [m.name for m in config.members]

            st.caption(
                "O TIPO mora na fonte (mudar o tipo reclassifica todo o "
                "histórico dela). A atribuição de cada receita a uma "
                "fonte é manual, na aba Renda."
            )

            for source in list(config.income_sources):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.text(source.name)
                    st.caption(source.owner or "—")
                with col2:
                    tipo = st.selectbox(
                        "Tipo", options=["fixa", "variavel"],
                        index=0 if source.type == "fixa" else 1,
                        key=f"src_type_{source.name}",
                        label_visibility="collapsed"
                    )
                    if tipo != source.type:
                        source.type = tipo
                        save_config_only()
                        st.rerun()
                with col3:
                    if st.button("🗑️", key=f"del_src_{source.name}"):
                        for t in st.session_state.transactions:
                            if t.income_source == source.name:
                                t.income_source = None
                        config.income_sources.remove(source)
                        save_data()
                        st.rerun()

            st.divider()
            st.subheader("Nova fonte")
            new_src_name = st.text_input("Nome da fonte", key="new_src_name")
            col1, col2 = st.columns(2)
            with col1:
                new_src_type = st.selectbox("Tipo", ["fixa", "variavel"],
                                            key="new_src_type")
            with col2:
                new_src_owner = st.selectbox("Dono", member_names,
                                             key="new_src_owner")
            if st.button("➕ Adicionar fonte", key="add_src"):
                name = new_src_name.strip()
                existing = {s.name for s in config.income_sources}
                if name and name not in existing:
                    config.income_sources.append(
                        IncomeSource(name=name, type=new_src_type,
                                     owner=new_src_owner))
                    save_config_only()
                    st.success(f"✅ Fonte '{name}' ({new_src_type}) criada!")
                    st.rerun()
                else:
                    st.error("❌ Nome vazio ou já existe")

        # Backup e exportação
        st.divider()
        st.subheader("💾 Backup e Exportação")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📥 Exportar CSV", use_container_width=True):
                # Ao lado do dado, nunca na pasta corrente: com o dado fora
                # do projeto, gravar na pasta de onde o app subiu poria dado
                # real de volta dentro dele.
                destino = init_storage().data_dir.parent / \
                    "export_transactions.csv"
                init_storage().export_to_csv(
                    st.session_state.transactions, str(destino))
                st.success(f"✅ Exportado para {destino}")
        with col2:
            if st.button("📦 Criar Backup", use_container_width=True):
                save_data()
                st.success("✅ Backup criado!")

        # Limpeza
        st.divider()
        st.subheader("🗑️ Gerenciar Dados")
        if len(st.session_state.transactions) > 0:
            if st.button("🗑️ Limpar Todas as Transações",
                         type="secondary", use_container_width=True):
                if st.checkbox("⚠️ Confirmar exclusão?",
                               key="confirm_delete"):
                    st.session_state.transactions = []
                    save_data()
                    st.success("Todas as transações foram removidas!")
                    st.rerun()

# ============================================================================
# PÁGINA PRINCIPAL
# ============================================================================

def render_registros_ilegiveis():
    """
    Avisa quando a carga não conseguiu materializar algum registro.

    Antes, esses registros sumiam com um `print` no terminal e eram apagados
    do disco no save seguinte. Agora são preservados — e o aviso é o que
    torna a preservação visível para quem está olhando a tela.
    """
    ilegiveis = init_storage().registros_nao_carregados()
    if not ilegiveis:
        return

    st.warning(f"⚠️ {len(ilegiveis)} registro(s) do arquivo de dados não "
               f"puderam ser lidos. Eles foram PRESERVADOS no disco e não "
               f"aparecem nas análises. Nada foi apagado.")
    with st.expander(f"Ver os {len(ilegiveis)} registros ilegíveis"):
        for item in ilegiveis:
            registro = item['registro']
            identificador = (registro.get('id')
                             if isinstance(registro, dict) else None)
            st.text(f"id={identificador or '—'} · {item['motivo']}")


def render_faixa_demonstracao():
    """
    Faixa fixa no topo, por cima do cabeçalho do Streamlit, que não sai da
    tela ao rolar. O seletor do cabeçalho é interno ao Streamlit: vale para
    a versão travada no lock (1.62.0) e pode mudar com ela.

    O período e a data de referência vêm do conjunto, não deste texto.
    """
    aviso = (f"MODO DEMONSTRAÇÃO · dados fictícios de "
             f"{CONJUNTO_DEMO.periodo_str} · hoje, aqui, é "
             f"{CONJUNTO_DEMO.referencia_str} · o que você mudar some ao "
             f"fechar")
    st.markdown(
        """
        <style>
        .fa-faixa-demo {
            position: fixed; top: 0; left: 0; right: 0; z-index: 1000001;
            background: #b45309; color: #ffffff; text-align: center;
            font-weight: 600; font-size: 0.9rem; line-height: 1.8rem;
            height: 1.8rem; letter-spacing: 0.02em;
        }
        header[data-testid="stHeader"] { top: 1.8rem; }
        </style>
        """ + f'<div class="fa-faixa-demo">{aviso}</div>',
        unsafe_allow_html=True)


def render_aviso_config():
    """Em modo real, avisa quando a configuração caiu na semente local."""
    aviso = st.session_state.get("aviso_config")
    if aviso and not EM_DEMO:
        st.warning(f"⚠️ {aviso} Nada foi gravado; confira os membros na "
                   f"barra lateral antes de mexer em ajustes.")


def main():
    verificar_ambiente()
    if EM_DEMO:
        render_faixa_demonstracao()
    load_data()
    render_sidebar()

    st.title("💰 Financial Analyzer v3.1")
    num_contas = len(st.session_state.config.accounts)
    st.markdown(f"**Pool familiar de {num_contas} contas · categorias em "
                f"dois níveis · multi-banco com conciliação automática**")

    render_aviso_config()
    render_registros_ilegiveis()

    # ========================================================================
    # IMPORTAÇÃO
    # ========================================================================

    st.header("📂 Importar Extratos")

    uploaded_files = st.file_uploader(
        "Selecione arquivos CSV",
        type=['csv'],
        accept_multiple_files=True,
        help="Nubank (NU_conta_....csv), C6 Bank, Inter, ou CSV genérico "
             "com colunas Data, Valor e Descrição"
    )

    if uploaded_files:
        with st.spinner("🔄 Processando arquivos..."):
            # src/importacao.py: ler, categorizar só o que entrou e
            # deduplicar contra a base aberta. Uma vez por rodada — o parser
            # lê o upload até o fim —, e a mesma preparação vai ao botão.
            preparacao = preparar_importacao(
                [(f.name, f) for f in uploaded_files],
                st.session_state.transactions,
                st.session_state.categorizer)

            for arquivo in preparacao.arquivos:
                if arquivo.aceito:
                    st.markdown(
                        f"🏦 **{arquivo.nome}** → {arquivo.conta}"
                        + ("" if arquivo.transacoes
                           else " *(sem movimentações)*"))

            # Novas OU duplicatas: o preview aparece também com zero novas,
            # quando tudo o que se subiu já está na base.
            if preparacao.novas or preparacao.duplicatas:
                unique = preparacao.novas

                st.subheader(f"📊 Preview: {len(unique)} novas transações")

                if preparacao.duplicatas > 0:
                    st.warning(f"⚠️ {preparacao.duplicatas} duplicatas "
                               f"detectadas e removidas")

                preview_df = pd.DataFrame([{
                    'Data': t.date_str,
                    'Descrição': t.description[:45],
                    'Conta': (t.source_account or '—')[:28],
                    'Categoria': t.category_path,
                    'Valor': f"R$ {t.value:.2f}",
                    'Confiança': f"{t.confidence:.0%}"
                } for t in unique[:12]])
                st.dataframe(preview_df, use_container_width=True,
                             hide_index=True)

                if preparacao.avisos:
                    with st.expander(
                            f"⚠️ {len(preparacao.avisos)} avisos (com motivo)",
                            expanded=False):
                        for warning in preparacao.avisos[:30]:
                            st.text(warning)

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Confirmar Importação", type="primary",
                                 use_container_width=True):
                        # Junta à base da sessão, no lugar, e pareia
                        # estornos e concilia sobre a base inteira.
                        confirmacao = confirmar_importacao(
                            preparacao, st.session_state.transactions,
                            st.session_state.config)

                        save_data()

                        msg = (f"✅ {confirmacao.importadas} transações "
                               f"importadas!")
                        if confirmacao.neutralizadas_por_estorno:
                            msg += (f" 🔄 "
                                    f"{confirmacao.neutralizadas_por_estorno}"
                                    f" neutralizadas por estorno.")
                        if confirmacao.pares_novos:
                            msg += (f" 🤝 {confirmacao.pares_novos} pares de "
                                    f"transferência interna conciliados.")
                        st.success(msg)
                        st.rerun()
                with col2:
                    if st.button("❌ Cancelar", use_container_width=True):
                        st.rerun()

        if preparacao.erros:
            st.error("❌ Erros encontrados:")
            for error in preparacao.erros:
                st.text(error)

    # ========================================================================
    # ANÁLISES
    # ========================================================================

    if st.session_state.transactions:
        st.divider()
        st.header("🔍 Filtros")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            exclude_neutral = st.checkbox(
                "Excluir transferências internas e estornos",
                value=True,
                help="Remove das análises transações que não são receita "
                     "nem despesa real do pool"
            )
        with col2:
            period_options = {
                "Tudo": None, "Últimos 7 dias": 7, "Últimos 30 dias": 30,
                "Últimos 90 dias": 90, "Últimos 6 meses": 180,
                "Último ano": 365
            }
            period = st.selectbox("Período", list(period_options.keys()))
        with col3:
            path_filter = st.selectbox(
                "Categoria", ["Todas"] + category_options())
        with col4:
            transaction_type = st.selectbox(
                "Tipo", ["Todos", "Receitas", "Despesas"])

        filtered = st.session_state.transactions.copy()

        if exclude_neutral:
            filtered = [t for t in filtered if not t.is_neutral]

        if period_options[period] is not None:
            filtered = TransactionFilter.filter_by_period(
                filtered, days=period_options[period], hoje=HOJE)

        if path_filter != "Todas":
            f_cat, f_sub = CategoryManager.parse_path(path_filter)
            if f_sub:
                filtered = [t for t in filtered
                            if t.category == f_cat
                            and t.subcategory == f_sub]
            elif path_filter.endswith(CategoryManager.GENERAL_SUFFIX):
                # '(geral)': só as sem subcategoria
                filtered = [t for t in filtered
                            if t.category == f_cat and not t.subcategory]
            else:
                # categoria inteira (pai + todos os filhos)
                filtered = [t for t in filtered if t.category == f_cat]

        if transaction_type != "Todos":
            trans_type = (TransactionType.RECEITA
                          if transaction_type == "Receitas"
                          else TransactionType.DESPESA)
            filtered = TransactionFilter.filter_by_type(filtered, trans_type)

        # ------------------- Resumo -------------------
        st.divider()
        st.header("📊 Resumo Financeiro")
        summary = FinancialCalculator.calculate_summary(
            filtered, exclude_internal=False)
        render_summary_cards(summary, filtered)
        if summary.periodo_inicio and summary.periodo_fim:
            st.caption(f"Período: {summary.periodo_str}")

        # ------------------- Abas -------------------
        st.divider()
        st.header("📈 Análises Visuais")

        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "🌞 Categorias (2 níveis)",
            "📈 Evolução Mensal",
            "📉 Evolução por Categoria",
            "💰 Maiores Despesas",
            "📊 Estatísticas",
            "👨‍👩‍👦 Pool Familiar",
            "💵 Renda"
        ])

        with tab1:
            col1, col2 = st.columns([3, 2])
            with col1:
                render_sunburst_chart(filtered)
            with col2:
                by_path = FinancialCalculator.calculate_by_path(
                    filtered, exclude_internal=False)
                if by_path:
                    total = sum(by_path.values())
                    st.subheader("Percentual por Caminho")
                    for p, value in list(by_path.items())[:14]:
                        pct = value / total * 100 if total else 0
                        st.progress(pct / 100,
                                    text=f"{p}: R$ {value:,.2f} ({pct:.1f}%)")

        with tab2:
            monthly = FinancialCalculator.calculate_monthly_trend(
                filtered, exclude_internal=False)
            render_monthly_trend_chart(monthly)

        with tab3:
            st.subheader("📉 Evolução Mensal por Categoria/Subcategoria")
            st.markdown("Compare até 4 séries — categorias inteiras ou "
                        "subcategorias específicas")

            available = list(FinancialCalculator.calculate_by_path(
                filtered, exclude_internal=False).keys())

            if not available:
                st.info("Sem despesas para exibir")
            else:
                selected = st.multiselect(
                    "Escolha os caminhos (máximo 4)",
                    options=available,
                    default=available[:min(4, len(available))],
                    max_selections=4
                )
                if selected:
                    st.divider()
                    render_path_evolution_chart(filtered, selected)

        with tab4:
            top_expenses = FinancialCalculator.get_top_expenses(
                filtered, top_n=10, exclude_internal=False)
            if top_expenses:
                st.subheader("Top 10 Maiores Despesas")
                for i, t in enumerate(top_expenses, 1):
                    col1, col2, col3, col4 = st.columns([1, 4, 2, 2])
                    with col1:
                        st.markdown(f"**#{i}**")
                    with col2:
                        st.text(t.description[:45])
                    with col3:
                        st.caption(t.category_path)
                    with col4:
                        st.markdown(f"**R$ {t.absolute_value:,.2f}**")

        with tab5:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Estatísticas Gerais")
                st.metric("Média de Receita",
                          f"R$ {summary.media_receita:,.2f}")
                st.metric("Média de Despesa",
                          f"R$ {summary.media_despesa:,.2f}")
                st.metric("Maior Receita",
                          f"R$ {summary.maior_receita:,.2f}")
                st.metric("Maior Despesa",
                          f"R$ {summary.maior_despesa:,.2f}")
            with col2:
                st.subheader("Previsões")
                predicted = FinancialCalculator.predict_monthly_expenses(
                    filtered, hoje=HOJE)
                st.metric("Despesa Prevista (próx. mês)",
                          f"R$ {predicted:,.2f}")
                weekday_avg = \
                    FinancialCalculator.calculate_average_by_weekday(filtered)
                st.subheader("Média por Dia da Semana")
                for day, avg in weekday_avg.items():
                    st.text(f"{day}: R$ {avg:.2f}")

        with tab6:
            matcher = TransferMatcher(st.session_state.config)
            all_trans = st.session_state.transactions

            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.subheader("🤝 Conciliação de Transferências")
                st.markdown(
                    "Transferências entre as contas do pool são "
                    "neutralizadas quando as **duas pernas** são "
                    "encontradas. Perna sem contraparte **continua nas "
                    "métricas** e aparece abaixo como pendência."
                )
            with col_b:
                if st.button("🔄 Reconciliar agora",
                             use_container_width=True):
                    new_pairs, demoted = matcher.reconcile(all_trans)
                    save_data()
                    st.success(f"{new_pairs} novos pares; "
                               f"{demoted} internas sem par demovidas.")
                    st.rerun()

            paired = [t for t in all_trans if t.paired_transfer_id]
            st.metric("Pernas conciliadas", len(paired),
                      delta=f"{len(paired) // 2} pares")

            st.divider()
            pending = matcher.get_pending_transfers(all_trans)
            st.subheader(f"⏳ Pendências ({len(pending)})")

            if pending:
                st.caption(
                    "Cada linha menciona um membro mas não tem contraparte "
                    "importada. Ou falta o extrato do outro lado (veja a "
                    "cobertura), ou o dinheiro saiu do pool — inclusive "
                    "para contas fora dele, como a de uma empresa de um "
                    "dos membros."
                )
                pend_df = pd.DataFrame([{
                    'Data': t.date_str,
                    'Conta': t.source_account or '(sem conta)',
                    'Descrição': t.description[:55],
                    'Valor': f"R$ {t.value:,.2f}",
                } for t in pending[:50]])
                st.dataframe(pend_df, use_container_width=True,
                             hide_index=True)
            else:
                st.success("Nenhuma pendência — todas as transferências "
                           "entre membros estão conciliadas.")

            st.divider()
            st.subheader("📅 Cobertura de Importação")
            st.caption(
                "O pool só é confiável quando todas as contas cadastradas "
                "cobrem o período analisado. Célula vazia = extrato não "
                "importado."
            )

            coverage = CoverageAnalyzer.compute(
                all_trans, st.session_state.config)
            months = CoverageAnalyzer.all_months(coverage)

            if coverage and months:
                cov_rows = []
                for account_label in sorted(coverage.keys()):
                    row = {'Conta': account_label}
                    for m in months:
                        n = coverage[account_label].get(m, 0)
                        row[m] = f"✓ {n}" if n else "—"
                    cov_rows.append(row)
                st.dataframe(pd.DataFrame(cov_rows),
                             use_container_width=True, hide_index=True)
            else:
                st.info("Importe extratos para ver a cobertura por conta.")

        with tab7:
            config = st.session_state.config
            analysis = FinancialCalculator.calculate_income_analysis(
                filtered, config)

            st.subheader("💵 Renda Fixa vs Variável")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Renda Fixa", f"R$ {analysis['fixa']:,.2f}")
            with col2:
                st.metric("Renda Variável",
                          f"R$ {analysis['variavel']:,.2f}")
            with col3:
                st.metric("Não Classificada",
                          f"R$ {analysis['nao_classificada']:,.2f}",
                          help="Receitas sem fonte atribuída — "
                               "classifique-as no painel abaixo")

            st.divider()
            st.markdown("**Necessidade de renda** — os gastos são a "
                        "medida: quanto de renda o período exigiu, e "
                        "quanto disso a renda fixa cobre.")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Renda Necessária (gastos)",
                          f"R$ {analysis['renda_necessaria']:,.2f}")
            with col2:
                st.metric("Cobertura pela Renda Fixa",
                          f"{analysis['cobertura_fixa_pct']:.0f}%")
            with col3:
                st.metric("Gap (a cobrir com variável)",
                          f"R$ {analysis['gap_variavel']:,.2f}",
                          delta_color="inverse")

            # Evolução mensal empilhada + linha de necessidade
            monthly_income = FinancialCalculator.calculate_income_by_month(
                filtered, config)
            if monthly_income:
                df_mi = pd.DataFrame(monthly_income)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df_mi['month'], y=df_mi['fixa'],
                                     name='Fixa', marker_color='#10b981'))
                fig.add_trace(go.Bar(x=df_mi['month'], y=df_mi['variavel'],
                                     name='Variável',
                                     marker_color='#3b82f6'))
                fig.add_trace(go.Bar(x=df_mi['month'],
                                     y=df_mi['nao_classificada'],
                                     name='Não classificada',
                                     marker_color='#9ca3af'))
                fig.add_trace(go.Scatter(
                    x=df_mi['month'], y=df_mi['renda_necessaria'],
                    name='Renda necessária (gastos)', mode='lines+markers',
                    line=dict(color='#ef4444', width=3, dash='dot')))
                fig.update_layout(barmode='stack',
                                  title="Composição da Renda vs Necessidade",
                                  xaxis_title="Mês",
                                  yaxis_title="Valor (R$)",
                                  hovermode='x unified')
                st.plotly_chart(fig, use_container_width=True)

            # ------------------- Renda por dono da fonte ----------------
            st.divider()
            st.subheader("👥 Renda por Pessoa")
            st.caption(
                "Agrupa pela FONTE atribuída, não pela categoria: receita "
                "não tem comerciante, nenhuma regra de conteúdo pontua e "
                "toda ela fica em \"Transferências\". A fonte é o único "
                "eixo que responde quanto cada um faz."
            )

            por_dono = FinancialCalculator.calculate_income_by_owner(
                filtered, config)
            if por_dono:
                cols = st.columns(min(len(por_dono), 4))
                for col, linha in zip(cols, por_dono):
                    with col:
                        st.metric(
                            linha['owner'],
                            f"R$ {linha['total']:,.2f}",
                            delta=f"{linha['pct']:.0f}% · "
                                  f"{linha['num_transacoes']} transações",
                            delta_color="off")

                por_dono_mes = (
                    FinancialCalculator.calculate_income_by_owner_by_month(
                        filtered, config))
                if por_dono_mes:
                    df_pd = pd.DataFrame(por_dono_mes)
                    donos = [c for c in df_pd.columns if c != 'month']
                    fig_d = go.Figure()
                    for dono in donos:
                        fig_d.add_trace(go.Bar(x=df_pd['month'],
                                               y=df_pd[dono], name=dono))
                    fig_d.update_layout(
                        barmode='group',
                        title="Quanto cada um faz por mês",
                        xaxis_title="Mês", yaxis_title="Valor (R$)",
                        hovermode='x unified')
                    st.plotly_chart(fig_d, use_container_width=True)
            else:
                st.info("Nenhuma receita no período.")

            # ------------------- Classificação manual -------------------
            st.divider()
            st.subheader("🖊️ Classificar Receitas")

            source_names = [s.name for s in config.income_sources]
            if not source_names:
                st.info("Cadastre suas fontes de renda na sidebar "
                        "(💵 Fontes de Renda) para começar a classificar.")

            receitas = sorted(
                [t for t in filtered
                 if t.type == TransactionType.RECEITA and not t.is_neutral],
                key=lambda t: t.date, reverse=True)

            so_pendentes = st.checkbox("Mostrar só não classificadas",
                                       value=True)
            if so_pendentes:
                receitas_view = [t for t in receitas if not t.income_source]
            else:
                receitas_view = receitas

            if receitas_view and source_names:
                NONE_LABEL = "— não classificada"
                df_r = pd.DataFrame([{
                    'Data': t.date_str,
                    'Descrição': t.description[:55],
                    'Conta': (t.source_account or '—')[:28],
                    'Valor': t.value,
                    'Fonte': t.income_source or NONE_LABEL,
                } for t in receitas_view])

                edited_r = st.data_editor(
                    df_r,
                    use_container_width=True,
                    hide_index=True,
                    disabled=['Data', 'Descrição', 'Conta', 'Valor'],
                    column_config={
                        "Fonte": st.column_config.SelectboxColumn(
                            "Fonte",
                            options=[NONE_LABEL] + source_names,
                            required=True
                        ),
                        "Valor": st.column_config.NumberColumn(
                            "Valor", format="R$ %.2f")
                    },
                    key="editor_renda"
                )

                if st.button("💾 Salvar Classificação", key="save_renda"):
                    changed = 0
                    for idx, row in edited_r.iterrows():
                        if idx < len(receitas_view):
                            t = receitas_view[idx]
                            new_source = (None if row['Fonte'] == NONE_LABEL
                                          else row['Fonte'])
                            if new_source != t.income_source:
                                t.income_source = new_source
                                changed += 1
                    if changed:
                        save_data()
                        st.success(f"✅ {changed} receitas classificadas!")
                        st.rerun()
                    else:
                        st.info("Nenhuma alteração detectada")
            elif receitas_view:
                pass  # sem fontes cadastradas: aviso já exibido acima
            else:
                st.success("Todas as receitas do período estão "
                           "classificadas. 🎉")

        # ------------------- Tabela -------------------
        st.divider()
        st.header("📋 Transações")

        search_query = st.text_input("🔍 Buscar por descrição", "")
        if search_query:
            filtered = TransactionFilter.search_description(
                filtered, search_query)

        items_per_page = st.selectbox("Itens por página",
                                      [20, 50, 100, 200], index=1)
        total_pages = (len(filtered) + items_per_page - 1) // items_per_page

        if total_pages > 0:
            page = st.number_input("Página", min_value=1,
                                   max_value=total_pages, value=1)
            start_idx = (page - 1) * items_per_page
            end_idx = min(start_idx + items_per_page, len(filtered))
            st.caption(f"Mostrando {start_idx + 1}-{end_idx} "
                       f"de {len(filtered)} transações")
            render_transactions_table(filtered[start_idx:end_idx],
                                      key_suffix=f"page_{page}")
        else:
            st.info("Nenhuma transação encontrada com os filtros aplicados")

    else:
        st.info("👋 Bem-vindo à v3.0! Importe os extratos das contas do "
                "pool para começar.")

        st.markdown("""
        ### 🚀 Como usar:

        1. **Importe os extratos** das contas do pool (Nubank, C6 e Inter)
        2. As transações chegam **classificadas em dois níveis**
           (ex.: Alimentação > Delivery) e as transferências entre vocês
           se conciliam sozinhas
        3. **Corrija categorias** na tabela — o sistema aprende os dois níveis
        4. Acompanhe **pendências e cobertura** na aba Pool Familiar

        ### 🏦 Bancos suportados:

        - **Nubank** — mantenha o nome original do arquivo
          (`NU_<conta>_...csv`): é dele que a conta é identificada
        - **C6 Bank** e **Inter** — conta detectada no cabeçalho do extrato
        - **CSV genérico** — colunas Data, Valor e Descrição

        ### ✨ v3.0:

        - ✅ **Subcategorias em dois níveis**, opcionais, com árvore semeada
          e regras calibradas em extratos reais
        - ✅ **Gráfico sunburst** — anel interno categorias, externo
          subcategorias, com "(geral)" mostrando o que falta detalhar
        - ✅ **Contas pré-registradas** com donos atribuídos
        - ✅ Base limpa: extratos são a fonte da verdade
        """)

# ============================================================================

if __name__ == "__main__":
    main()
