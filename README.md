# Controle de Carteira e Imposto de Renda (IR) na B3

Sistema web completo para gerenciamento de custódia de ativos e apuração mensal de Imposto de Renda sobre operações na Bolsa de Valores brasileira (B3), suportando Ações, BDRs, Opções e FIIs.

Hospedado no Streamlit Cloud: [tradersupport.streamlit.app](https://tradersupport.streamlit.app/)

## 🚀 Funcionalidades

1. **Multi-Tenancy**: Isolamento completo dos dados por usuário com autenticação segura.
2. **Controle de Custódia**: CRUD de posições compradas e vendidas com cálculo de Preço Médio (Breakeven) dinâmico, incorporando emolumentos e corretagens.
3. **Leitor de Notas de Corretagem**: Upload e processamento automático de notas no padrão Sinacor via PDF.
4. **Yahoo Finance**: Atualização de cotações de fechamento e ajuste de custódia por eventos corporativos (splits, inplits, bonificações).
5. **Motor Tributário**:
   - Isenção de R$ 20.000,00 para vendas de Ações em Swing Trade.
   - Tributação correta para Day Trade (20%), FIIs (20%) e Swing Trade regular (15%).
   - Compensação de prejuízos passados por categoria (Comum, Day Trade, FIIs).
   - Abatimento de IRRF (Dedo-Duro).
   - Dados de preenchimento para DARF (código 6015).
6. **Relatório IRPF Anual**: Geração consolidada da ficha de Bens e Direitos (B3) e Rendimentos.

## 🛠️ Stack Tecnológico

- **Framework**: Streamlit (Python)
- **Banco de Dados**: SQLite (com schema multi-tenant)
- **Processamento de PDF**: pdfplumber
- **Cotações**: yfinance
- **Gráficos**: Plotly
