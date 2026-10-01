import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.express as px
import io

# ==========================================
# CONFIGURAÇÃO DA PÁGINA E IDENTIDADE VISUAL
# ==========================================
st.set_page_config(page_title="Revisão do Teto - ECs 20 e 41", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&display=swap');
        html, body, [class*="css"]  {
            font-family: 'Montserrat', sans-serif;
        }
        .stButton>button {
            background-color: #33009A;
            color: white;
            border-radius: 8px;
            font-weight: 600;
        }
        .stButton>button:hover {
            background-color: #FF8A05;
            color: white;
            border-color: #FF8A05;
        }
        h1, h2, h3 {
            color: #33009A;
        }
        .metric-card {
            background-color: #E2E2E2;
            padding: 15px;
            border-radius: 8px;
            border-left: 5px solid #FFCC00;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# MOTOR DE CÁLCULO PREVIDENCIÁRIO
# ==========================================
def gerar_simulacao_historica(dib, sb_real, teto_dib, coeficiente, data_pedido):
    """
    Simula a evolução da RMR Paga vs RMR Readequada (Tema 76 STF).
    """
    hoje = datetime.today()
    meses = pd.date_range(start=dib, end=hoje, freq='MS')
    
    df = pd.DataFrame({'Competencia': meses})
    df['Ano'] = df['Competencia'].dt.year
    df['Mes'] = df['Competencia'].dt.month
    
    # 1. Tetos Constitucionais (Parametrizado para as ECs)
    def get_teto(data):
        if data < datetime(1998, 12, 1): return teto_dib 
        elif data < datetime(2004, 1, 1): return 1200.00 # EC 20/98
        elif data < datetime(2024, 1, 1): return 2400.00 # EC 41/03 (base inicial, sofreria reajustes anuais reais)
        else: return 7786.02 # Teto atual de 2024
        
    df['Teto_Vigente'] = df['Competencia'].apply(get_teto)
    
    # 2. Índices de Reajuste (Simulação contínua com média estimada)
    df['Indice_Reajuste'] = 1.004 # Reajuste diluído estimado
    
    # A glosa aconteceu no Salário de Benefício, antes do coeficiente.
    renda_pura = sb_real
    renda_glosada_antiga = min(sb_real, teto_dib)
    
    historico_readequada = []
    historico_paga = []
    
    for index, row in df.iterrows():
        # Evolução da média pura (Sem travas)
        renda_pura = renda_pura * row['Indice_Reajuste']
        
        # Evolução do valor que o INSS manteve travado no teto da DIB
        renda_glosada_antiga = renda_glosada_antiga * row['Indice_Reajuste']
        
        # APLICAÇÃO DO TEMA 76 STF (Ordem correta TRF4)
        
        # Cenário Readequado: Pega a renda pura atualizada, limita ao novo teto e, SÓ ENTÃO, aplica o coeficiente.
        rmr_readequada = min(renda_pura, row['Teto_Vigente']) * coeficiente
        
        # Cenário Efetivamente Pago: O INSS pegava a renda antiga (já limitada na DIB), evoluía, limitava ao teto e aplicava o coeficiente.
        rmr_paga = min(renda_glosada_antiga, row['Teto_Vigente']) * coeficiente
        
        historico_readequada.append(rmr_readequada)
        historico_paga.append(rmr_paga)
        
    df['RMR_Readequada'] = historico_readequada
    df['RMR_Paga'] = historico_paga
    df['Diferenca_Mensal'] = df['RMR_Readequada'] - df['RMR_Paga']
    df['Diferenca_Mensal'] = df['Diferenca_Mensal'].apply(lambda x: max(x, 0))
    
    # 3. Prescrição Quinquenal (Art. 103, parágrafo único da Lei 8.213/91)
    data_limite_prescricao = data_pedido - pd.DateOffset(years=5)
    df['Prescrita'] = df['Competencia'] < data_limite_prescricao
    
    # 4. Correção Monetária (CM + Juros estimado para projeção)
    df['Fator_Correcao'] = np.where(df['Prescrita'], 0, 1.15) 
    df['Valor_Corrigido'] = df['Diferenca_Mensal'] * df['Fator_Correcao']
    
    return df

# ==========================================
# INTERFACE DE USUÁRIO (FRONT-END)
# ==========================================
st.title("⚖️ Calculadora de Revisão do Teto Previdenciário")
st.markdown("**(ECs 20/1998 e 41/2003 | STF Tema 76)**")

col_sidebar, col_main = st.columns([1, 3])

with col_sidebar:
    st.header("Dados da Concessão")
    with st.form("form_calculo"):
        nome = st.text_input("Nome do Segurado", value="Silvana Dias de Brito")
        nb = st.text_input("Número do Benefício (NB)")
        dib = st.date_input("Data de Início do Benefício (DIB)", datetime(1996, 7, 23))
        
        st.markdown("---")
        # INPUT CORRIGIDO: O usuário insere o SB Real (antes do coeficiente)
        sb_real = st.number_input("Salário de Benefício (Real Puro)", value=963.97, step=10.00, help="Soma dos SC / divisor. Sem corte.")
        teto_dib = st.number_input("Teto na época da DIB", value=957.56, step=10.00)
        
        coef_input = st.number_input("Coeficiente de Proporcionalidade (%)", min_value=1.0, max_value=100.0, value=94.0)
        data_pedido = st.date_input("Data do Pedido (Marco Prescricional)", datetime.today())
        
        submit = st.form_submit_button("Calcular Revisão", use_container_width=True)

with col_main:
    if submit:
        # VALIDAÇÃO CORRIGIDA: A glosa avalia apenas a média antes do coeficiente.
        # SB Real de R$ 963,97 vs Teto de R$ 957,56 = Glosa confirmada (R$ 6,41).
        indice_teto = sb_real / teto_dib if teto_dib > 0 else 0
        
        if sb_real <= teto_dib:
            st.warning("⚠️ O Salário de Benefício Real (Média Pura) é inferior ou igual ao Teto da época. A tese não se aplica, pois não houve parcela retida.")
        else:
            coeficiente = coef_input / 100.0
            
            df_resultado = gerar_simulacao_historica(
                pd.to_datetime(dib), sb_real, teto_dib, coeficiente, pd.to_datetime(data_pedido)
            )
            
            df_nao_prescrito = df_resultado[~df_resultado['Prescrita']]
            total_atrasados = df_nao_prescrito['Valor_Corrigido'].sum()
            rmr_atual_readequada = df_resultado.iloc[-1]['RMR_Readequada']
            rmr_atual_paga = df_resultado.iloc[-1]['RMR_Paga']
            ganho_mensal = rmr_atual_readequada - rmr_atual_paga
            
            st.markdown("### Resumo da Readequação (Com Aplicação de Coeficiente)")
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"<div class='metric-card'><b>Índice-Teto Apurado</b><br><h3 style='margin:0;'>{indice_teto:.4f}</h3></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='metric-card'><b>Nova RMR (Devida)</b><br><h3 style='margin:0;'>R$ {rmr_atual_readequada:,.2f}</h3></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='metric-card'><b>Ganho Mensal</b><br><h3 style='margin:0;'>R$ {ganho_mensal:,.2f}</h3></div>", unsafe_allow_html=True)
            c4.markdown(f"<div class='metric-card'><b>Atrasados (Últ. 5 anos)</b><br><h3 style='margin:0;'>R$ {total_atrasados:,.2f}</h3></div>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Gráfico Comparativo Plotly
            fig = px.line(
                df_resultado, x='Competencia', y=['RMR_Readequada', 'RMR_Paga'],
                labels={'value': 'Renda Mensal Proporcional (R$)', 'Competencia': 'Ano', 'variable': 'Curva'},
                title=f"Evolução da Renda Mensal (Considerando Coeficiente de {coef_input}%)",
                color_discrete_sequence=['#FF8A05', '#33009A']
            )
            fig.update_layout(hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            fig.add_vline(x=datetime(1998, 12, 1), line_dash="dash", line_color="#FFCC00", annotation_text="EC 20/98")
            fig.add_vline(x=datetime(2004, 1, 1), line_dash="dash", line_color="#FFCC00", annotation_text="EC 41/03")
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Memória de Cálculo Mensal
            st.markdown("### Memória de Cálculo Mensal (Não Prescrita)")
            df_display = df_nao_prescrito[['Competencia', 'Teto_Vigente', 'RMR_Readequada', 'RMR_Paga', 'Diferenca_Mensal', 'Valor_Corrigido']].copy()
            df_display['Competencia'] = df_display['Competencia'].dt.strftime('%m/%Y')
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # Geração do arquivo Excel (xlsxwriter)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_resultado['Competencia'] = df_resultado['Competencia'].dt.strftime('%m/%Y')
                df_resultado.to_excel(writer, index=False, sheet_name='Memória de Cálculo')
            processed_data = output.getvalue()
            
            st.download_button(
                label="📥 Baixar Planilha Pronta para Peticionamento (.xlsx)",
                data=processed_data,
                file_name=f"Calculo_Teto_{nome.replace(' ', '_')}_{nb}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.info("👈 Insira os valores puros (antes do coeficiente) no painel e clique em 'Calcular Revisão'.")