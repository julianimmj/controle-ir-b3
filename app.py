import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import os

from src.database import (
    init_db, register_user, authenticate_user,
    add_transaction, get_transactions, delete_transaction,
    get_custody, add_provento, get_proventos, delete_provento,
    get_darfs, set_darf_paid_status, get_losses_carryover
)
from src.tax_engine import compute_portfolio
from src.parser import parse_sinacor_pdf
from src.market_data import get_current_prices, suggest_corporate_events

# Initialize Database
init_db()

# ─────────────────────────────────────────
# Page Setup
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Controle de Carteira & IR B3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Premium Styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .stApp {
        background: #060613;
        background-image:
            radial-gradient(circle at 10% 20%, rgba(124, 77, 255, 0.05) 0%, transparent 40%),
            radial-gradient(circle at 90% 80%, rgba(0, 200, 255, 0.04) 0%, transparent 40%);
    }

    /* Cards */
    .kpi-card {
        background: rgba(13, 13, 33, 0.6);
        border: 1px solid rgba(124, 77, 255, 0.15);
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        margin-bottom: 1rem;
    }
    .kpi-label {
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.55);
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .kpi-value {
        font-size: 1.8rem;
        font-weight: 800;
        color: #ffffff;
        margin-top: 0.2rem;
    }
    .kpi-diff {
        font-size: 0.85rem;
        font-weight: 600;
        margin-top: 0.4rem;
    }
    
    /* Tables styling */
    .styled-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    .styled-table th {
        background-color: rgba(124, 77, 255, 0.15);
        color: #ffffff;
        text-align: left;
        padding: 12px 15px;
        font-weight: 700;
        border-bottom: 2px solid rgba(124, 77, 255, 0.3);
    }
    .styled-table td {
        padding: 10px 15px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        color: rgba(255, 255, 255, 0.85);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0c0c1d !important;
        border-right: 1px solid rgba(124, 77, 255, 0.1) !important;
    }
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

# ─────────────────────────────────────────
# AUTHENTICATION SCREEN
# ─────────────────────────────────────────
if not st.session_state.logged_in:
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; font-weight:900;'>📈 B3 Portfolio & IR</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: rgba(255,255,255,0.6);'>Controle tributário completo e custódia inteligente</p>", unsafe_allow_html=True)
        
        tab_login, tab_register = st.tabs(["🔑 Acessar Conta", "📝 Criar Conta"])
        
        with tab_login:
            email_log = st.text_input("E-mail", key="log_email")
            pass_log = st.text_input("Senha", type="password", key="log_pass")
            if st.button("Entrar", use_container_width=True):
                user = authenticate_user(email_log, pass_log)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user["id"]
                    st.session_state.user_email = user["email"]
                    st.toast(f"Bem-vindo, {user['email']}!")
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos.")
                    
        with tab_register:
            email_reg = st.text_input("E-mail", key="reg_email")
            pass_reg = st.text_input("Senha", type="password", key="reg_pass")
            pass_reg_conf = st.text_input("Confirmar Senha", type="password", key="reg_pass_conf")
            
            if st.button("Registrar", use_container_width=True):
                if not email_reg or not pass_reg:
                    st.error("Preencha todos os campos.")
                elif pass_reg != pass_reg_conf:
                    st.error("As senhas não coincidem.")
                else:
                    user_id = register_user(email_reg, pass_reg)
                    if user_id:
                        st.success("Conta criada com sucesso! Faça login na aba acima.")
                    else:
                        st.error("Este e-mail já está cadastrado.")
    st.stop()

# ─────────────────────────────────────────
# PORTAL SIDEBAR NAVIGATION
# ─────────────────────────────────────────
user_id = st.session_state.user_id

st.sidebar.markdown(f"<h3 style='margin-bottom:0;'>👨‍💻 {st.session_state.user_email}</h3>", unsafe_allow_html=True)
st.sidebar.markdown("<span style='font-size:0.8rem; color:rgba(255,255,255,0.4);'>Tenant Isolado</span>", unsafe_allow_html=True)
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navegação",
    ["📊 Dashboard", "📝 Lançamentos", "📂 Upload Notas PDF", "🧮 Apuração de IR", "📅 Declaração IRPF"]
)

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Sair", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.user_email = ""
    st.rerun()

# Rebuild database calculations once per session to ensure correct values
if "recalculated" not in st.session_state:
    compute_portfolio(user_id)
    st.session_state.recalculated = True

# Helper to trigger recalculation
def trigger_rebuild():
    compute_portfolio(user_id)
    st.toast("Custódia e impostos recalculados com sucesso!")

# ─────────────────────────────────────────
# 1. DASHBOARD VIEW
# ─────────────────────────────────────────
if menu == "📊 Dashboard":
    st.title("📊 Painel de Controle de Custódia")
    st.markdown("Visão geral dos ativos e valuation atualizados da carteira.")
    
    # Load custody positions
    pos = get_custody(user_id)
    
    if not pos:
        st.info("Nenhum ativo sob custódia atualmente. Vá em 'Upload Notas PDF' ou 'Lançamentos' para começar.")
    else:
        # Fetch current market prices via yfinance
        tickers = [p["ticker"] for p in pos]
        with st.spinner("Atualizando preços de fechamento com Yahoo Finance..."):
            prices = get_current_prices(tickers)
            
        # Calculate valuation metrics
        total_cost = 0.0
        total_value = 0.0
        
        pos_rows = []
        for p in pos:
            t = p["ticker"]
            qty = p["quantity"]
            avg_price = p["average_price"]
            curr_price = prices.get(t, 0.0)
            
            # If current price fetch failed, fallback to average price for valuation
            if curr_price <= 0.0:
                curr_price = avg_price
                
            cost_basis = qty * avg_price
            curr_value = qty * curr_price
            
            # Short position valuation logic
            if qty < 0:
                # For short: profit is if current price goes below selling price
                profit_loss = cost_basis - curr_value
            else:
                profit_loss = curr_value - cost_basis
                
            total_cost += cost_basis
            total_value += curr_value
            
            pos_rows.append({
                "Ativo": t,
                "Tipo": p["market_type"],
                "Qtd": qty,
                "Preço Médio": f"R$ {avg_price:,.2f}",
                "Custo Total": cost_basis,
                "Preço Atual": f"R$ {curr_price:,.2f}",
                "Valor Atual": curr_value,
                "Lucro/Prejuízo": profit_loss,
                "Retorno %": (profit_loss / cost_basis * 100) if cost_basis != 0 else 0.0
            })
            
        net_profit_loss = total_value - total_cost
        ret_pct = (net_profit_loss / total_cost * 100) if total_cost != 0 else 0.0
        
        # KPI Cards Row
        kpi_cols = st.columns(3)
        with kpi_cols[0]:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Patrimônio Investido (Custo)</div>
                <div class="kpi-value">R$ {total_cost:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_cols[1]:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Valuation da Carteira</div>
                <div class="kpi-value">R$ {total_value:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_cols[2]:
            color = "#00e676" if net_profit_loss >= 0 else "#ff1744"
            sign = "+" if net_profit_loss >= 0 else ""
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Lucro/Prejuízo Estimado</div>
                <div class="kpi-value" style="color: {color};">{sign}R$ {net_profit_loss:,.2f}</div>
                <div class="kpi-diff" style="color: {color};">{sign}{ret_pct:.2f}% de retorno</div>
            </div>
            """, unsafe_allow_html=True)
            
        # Assets Table
        st.subheader("📋 Posições Ativas")
        df_pos = pd.DataFrame(pos_rows)
        
        # Format styling for visualization
        df_disp = df_pos.copy()
        df_disp["Custo Total"] = df_disp["Custo Total"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Valor Atual"] = df_disp["Valor Atual"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Lucro/Prejuízo"] = df_disp["Lucro/Prejuízo"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Retorno %"] = df_disp["Retorno %"].apply(lambda x: f"{x:.2f}%")
        
        st.dataframe(df_disp, use_container_width=True, hide_index=True)
        
        # Suggested Actions (Corporate Events check)
        st.subheader("⚡ Sugestões de Eventos Corporativos")
        st.markdown("Eventos recentes de desdobramentos ou dividendos encontrados no Yahoo Finance:")
        for p in pos:
            sug_events = suggest_corporate_events(p["ticker"], (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
            for e in sug_events:
                col_e1, col_e2 = st.columns([4, 1])
                with col_e1:
                    st.write(f"🔹 **{e['ticker']}**: {e['description']} em {e['record_date']}")
                with col_e2:
                    if st.button("Aplicar Evento", key=f"btn_sug_{e['ticker']}_{e['record_date']}_{e['event_type']}"):
                        add_provento(user_id, e['ticker'], e['event_type'], e['amount'], e['record_date'], e['ratio'], e['unit_cost'])
                        trigger_rebuild()
                        st.rerun()

# ─────────────────────────────────────────
# 2. LANÇAMENTOS (TRANSACTIONS CRUD)
# ─────────────────────────────────────────
elif menu == "📝 Lançamentos":
    st.title("📝 Gestão Manual de Transações & Proventos")
    st.markdown("Adicione, edite ou remova transações manuais ou eventos corporativos de sua carteira.")
    
    t_opt = st.selectbox("Escolha o tipo de registro", ["Operações (Compras/Vendas)", "Eventos Corporativos (Dividendos/Splits/Bonificações)"])
    
    if t_opt == "Operações (Compras/Vendas)":
        # Form to add manual transaction
        with st.expander("➕ Lançar Nova Operação Manual"):
            f_col1, f_col2, f_col3 = st.columns(3)
            with f_col1:
                ticker = st.text_input("Ativo (ex: PETR4, MXRF11)").upper().strip()
                op_type = st.selectbox("Operação", ["COMPRA", "VENDA"])
                mkt_type = st.selectbox("Tipo de Mercado", ["VISTA", "OPCOES", "BDR", "FII"])
            with f_col2:
                qty = st.number_input("Quantidade", min_value=1, step=1)
                price = st.number_input("Preço Unitário (R$)", min_value=0.01, step=0.01)
                fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, step=0.01)
            with f_col3:
                trade_date = st.date_input("Data do Pregão")
                broker = st.text_input("Corretora")
                is_day_trade = st.checkbox("Operação Day Trade?")
                
            if st.button("Gravar Operação", use_container_width=True):
                if not ticker:
                    st.error("Digite o código do ativo.")
                else:
                    add_transaction(
                        user_id=user_id,
                        ticker=ticker,
                        operation_type=op_type,
                        quantity=qty,
                        price=price,
                        fees=fees,
                        trade_date=trade_date.strftime("%Y-%m-%d"),
                        market_type=mkt_type,
                        broker=broker or "Manual",
                        is_day_trade=1 if is_day_trade else 0
                    )
                    trigger_rebuild()
                    st.rerun()

        # Display transactions ledger
        st.subheader("📋 Registro de Operações")
        txs = get_transactions(user_id)
        if not txs:
            st.info("Nenhuma operação registrada.")
        else:
            df_txs = pd.DataFrame(txs)
            # Display formatted columns
            df_txs_disp = df_txs.copy()
            df_txs_disp = df_txs_disp.drop(columns=["user_id"])
            st.dataframe(df_txs_disp, use_container_width=True, hide_index=True)
            
            # Row deletion control
            st.markdown("### 🗑️ Excluir Lançamento")
            del_id = st.number_input("ID do Lançamento para Exclusão", min_value=1, step=1)
            if st.button("Excluir", type="primary"):
                delete_transaction(user_id, del_id)
                trigger_rebuild()
                st.rerun()

    else: # Eventos Corporativos
        with st.expander("➕ Lançar Novo Evento Corporativo Manual"):
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                ticker = st.text_input("Ativo (ex: PETR4, MXRF11)").upper().strip()
                event_type = st.selectbox("Evento", ["DIVIDENDO", "JCP", "BONIFICACAO", "SPLIT", "INPLIT"])
                amount = st.number_input("Valor Recebido (Total R$) ou Qtd de Bonificação", min_value=0.0, step=0.01)
            with e_col2:
                record_date = st.date_input("Data com/registro")
                ratio = st.number_input("Proporção / Fator multiplicador (para Splits/Bonif)", min_value=0.0, value=1.0, step=0.0001)
                unit_cost = st.number_input("Custo Unitário da Bonificação (Atribuído pela RF)", min_value=0.0, step=0.01)

            if st.button("Gravar Evento", use_container_width=True):
                if not ticker:
                    st.error("Digite o código do ativo.")
                else:
                    add_provento(
                        user_id=user_id,
                        ticker=ticker,
                        event_type=event_type,
                        amount=amount,
                        record_date=record_date.strftime("%Y-%m-%d"),
                        ratio=ratio,
                        unit_cost=unit_cost
                    )
                    trigger_rebuild()
                    st.rerun()

        st.subheader("📋 Registro de Eventos e Proventos")
        provs = get_proventos(user_id)
        if not provs:
            st.info("Nenhum evento corporativo registrado.")
        else:
            df_provs = pd.DataFrame(provs)
            df_provs_disp = df_provs.copy().drop(columns=["user_id"])
            st.dataframe(df_provs_disp, use_container_width=True, hide_index=True)

            st.markdown("### 🗑️ Excluir Evento")
            del_p_id = st.number_input("ID do Evento para Exclusão", min_value=1, step=1)
            if st.button("Excluir Evento", type="primary"):
                delete_provento(user_id, del_p_id)
                trigger_rebuild()
                st.rerun()

# ─────────────────────────────────────────
# 3. UPLOAD NOTAS PDF (SINACOR PARSER)
# ─────────────────────────────────────────
elif menu == "📂 Upload Notas PDF":
    st.title("📂 Processamento Automatizado de Notas de Corretagem")
    st.markdown("Carregue suas Notas de Corretagem no padrão B3 / Sinacor em formato PDF para importação automatizada.")
    
    uploaded_files = st.file_uploader("Selecione um ou mais PDFs de notas de corretagem", type="pdf", accept_multiple_files=True)
    
    if uploaded_files:
        st.subheader("🔍 Pré-visualização dos dados extraídos")
        
        parsed_notes = []
        for f in uploaded_files:
            # Parse note content
            note_data = parse_sinacor_pdf(f)
            if note_data:
                parsed_notes.append((f.name, note_data))
                st.write(f"📄 **Nota nº {note_data['note_number']}** ({note_data['broker']}) — Pregão: **{note_data['trade_date']}**")
                
                # Show parsed transactions
                df_parsed_t = pd.DataFrame(note_data["transactions"])
                if not df_parsed_t.empty:
                    df_parsed_t["fees"] = df_parsed_t["fees"].apply(lambda x: f"R$ {x:.2f}")
                    df_parsed_t["price"] = df_parsed_t["price"].apply(lambda x: f"R$ {x:.2f}")
                    df_parsed_t["total"] = df_parsed_t["total"].apply(lambda x: f"R$ {x:.2f}")
                    st.dataframe(df_parsed_t, use_container_width=True, hide_index=True)
                else:
                    st.warning("Nenhuma transação identificada na nota.")
                st.markdown("---")
            else:
                st.error(f"Não foi possível extrair dados estruturados de {f.name}.")
                
        if parsed_notes:
            if st.button("📥 Salvar Todas as Transações no Banco de Dados", use_container_width=True):
                success_count = 0
                for fname, nd in parsed_notes:
                    for t in nd["transactions"]:
                        add_transaction(
                            user_id=user_id,
                            ticker=t["ticker"],
                            operation_type=t["operation_type"],
                            quantity=t["quantity"],
                            price=t["price"],
                            fees=t["fees"],
                            trade_date=nd["trade_date"],
                            market_type=t["market_type"],
                            note_number=nd["note_number"],
                            broker=nd["broker"],
                            is_day_trade=0 # Calculated dynamically during portfolio rebuilding
                        )
                        success_count += 1
                
                # Recalculate portfolio calculations immediately
                trigger_rebuild()
                st.success(f"{success_count} operações importadas com sucesso!")
                st.rerun()

# ─────────────────────────────────────────
# 4. APURAÇÃO DE IR (MONTHLY TAX / DARF)
# ─────────────────────────────────────────
elif menu == "🧮 Apuração de IR":
    st.title("🧮 Demonstrativo Mensal e Apuração de DARF")
    st.markdown("Acompanhe o volume de vendas, lucros isentos, prejuízos compensados e guias DARF calculadas.")
    
    darfs = get_darfs(user_id)
    losses = get_losses_carryover(user_id)
    
    if not darfs:
        st.info("Nenhuma apuração tributária gerada ainda. Registre operações em 'Lançamentos' para ver impostos.")
    else:
        # Month selector dropdown
        months = [d["month"] for d in darfs]
        selected_month = st.selectbox("Selecione o mês de competência", months)
        
        darf_info = next(d for d in darfs if d["month"] == selected_month)
        loss_info = next((l for l in losses if l["month"] == selected_month), {"common_loss": 0, "day_trade_loss": 0, "fii_loss": 0})
        
        # Details layout
        st.markdown(f"## Competência: {selected_month}")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("#### 📦 Volume de Vendas")
            st.write(f"🔹 Operações Comuns: **R$ {darf_info['swing_trade_sales']:.2f}**")
            st.write(f"🔹 Fundos Imobiliários: **R$ {darf_info['fii_sales']:.2f}**")
            
        with c2:
            st.markdown("#### 💰 Resultado Líquido")
            st.write(f"🔹 Lucro Comum: **R$ {darf_info['swing_trade_profit']:.2f}**")
            st.write(f"🔹 Lucro Day Trade: **R$ {darf_info['day_trade_profit']:.2f}**")
            st.write(f"🔹 Lucro FII: **R$ {darf_info['fii_profit']:.2f}**")
            
        with c3:
            st.markdown("#### 📉 Prejuízo Acumulado (Próximo Mês)")
            st.write(f"🔹 Swing Trade (Comum): **R$ {loss_info['common_loss']:.2f}**")
            st.write(f"🔹 Day Trade: **R$ {loss_info['day_trade_loss']:.2f}**")
            st.write(f"🔹 Fundos Imobiliários: **R$ {loss_info['fii_loss']:.2f}**")

        st.markdown("---")
        
        # DARF guidance details
        st.subheader("💵 Imposto Devido (DARF)")
        
        tax_due = darf_info["tax_due"]
        if tax_due <= 0.0:
            st.success("🎉 Não há imposto a pagar para este mês.")
        else:
            st.warning(f"⚠️ DARF calculada para pagamento: **R$ {tax_due:.2f}** (IRRF dedo-duro abatido: R$ {darf_info['irrf_dedo_duro']:.2f})")
            
            # Print DARF Details fields
            st.markdown(f"""
            <div class="kpi-card" style="max-width: 500px;">
                <h3 style="margin-top:0; color:#7c4dff;">Guia DARF de Pagamento</h3>
                <table style="width:100%; border:none;">
                    <tr><td><b>Código da Receita:</b></td><td>6015 (Pessoa Física B3)</td></tr>
                    <tr><td><b>Mês de Referência:</b></td><td>{selected_month}</td></tr>
                    <tr><td><b>Valor Total:</b></td><td>R$ {tax_due:.2f}</td></tr>
                    <tr><td><b>Vencimento Limite:</b></td><td>Último dia útil do mês subsequente</td></tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
            
            # Payment toggler
            is_paid = darf_info["paid"]
            if is_paid:
                st.success("✅ Esta DARF foi marcada como PAGA.")
                if st.button("Marcar como Não Paga"):
                    set_darf_paid_status(user_id, selected_month, 0)
                    trigger_rebuild()
                    st.rerun()
            else:
                if st.button("Confirmar Pagamento da DARF"):
                    set_darf_paid_status(user_id, selected_month, 1)
                    trigger_rebuild()
                    st.rerun()

# ─────────────────────────────────────────
# 5. DECLARAÇÃO IRPF (ANNUAL DECLARATION)
# ─────────────────────────────────────────
elif menu == "📅 Declaração IRPF":
    st.title("📅 Auxiliar para Declaração Anual de IRPF")
    st.markdown("Dados consolidados para preenchimento fácil da declaração de ajuste anual do Imposto de Renda.")
    
    darfs = get_darfs(user_id)
    if not darfs:
        st.info("Nenhuma transação para consolidar relatórios anuais.")
    else:
        # Extract years from database months
        years = sorted(list(set([d["month"][:4] for d in darfs])))
        selected_year = st.selectbox("Selecione o ano fiscal", years)
        
        # 1. Bens e Direitos (Assets custody on 31/12)
        st.subheader("💼 Ficha de Bens e Direitos (B3)")
        st.markdown(f"Custódia em **31/12/{selected_year}** com quantidade e custo médio histórico (com taxas inclusas).")
        
        cust = get_custody(user_id)
        if not cust:
            st.info("Nenhum ativo em custódia no final do ano.")
        else:
            cust_rows = []
            for c in cust:
                ticker = c["ticker"]
                qty = c["quantity"]
                avg_p = c["average_price"]
                cost_basis = qty * avg_p
                
                # FII mapping or stocks group codes
                group_code = "03 (Participações societárias)" if c["market_type"] != "FII" else "07 (Fundos)"
                
                cust_rows.append({
                    "Código": group_code,
                    "Ativo": ticker,
                    "Quantidade": qty,
                    "Preço Médio": f"R$ {avg_p:,.2f}",
                    "Situação em 31/12 (Custo Total)": f"R$ {cost_basis:,.2f}"
                })
            st.dataframe(pd.DataFrame(cust_rows), use_container_width=True, hide_index=True)
            
        st.markdown("---")
        
        # 2. Resumo Mensal para Ficha de Renda Variável
        st.subheader("📊 Ficha de Renda Variável (Operações Comuns / Day Trade)")
        st.markdown(f"Consolidação mensal de resultados líquidos do ano de **{selected_year}**:")
        
        year_darfs = [d for d in darfs if d["month"].startswith(selected_year)]
        
        var_rows = []
        for y_d in year_darfs:
            month = y_d["month"]
            
            var_rows.append({
                "Mês": month,
                "Resultado Comum (R$)": y_d["swing_trade_profit"],
                "Resultado Day Trade (R$)": y_d["day_trade_profit"],
                "Resultado FII (R$)": y_d["fii_profit"],
                "Dedo-Duro Retido (R$)": y_d["irrf_dedo_duro"],
                "Imposto Devido (R$)": y_d["tax_due"],
                "DARF Paga": "Sim" if y_d["paid"] else "Não"
            })
            
        if var_rows:
            st.dataframe(pd.DataFrame(var_rows), use_container_width=True, hide_index=True)
        else:
            st.info(f"Nenhuma apuração mensal disponível para o ano fiscal {selected_year}.")
