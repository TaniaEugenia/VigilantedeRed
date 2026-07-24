import streamlit as st
import os

st.set_page_config(page_title="Términos y Condiciones")

st.title("📜 Términos y Condiciones")

# En tu archivo pages/Términos_y_condiciones.py
with open("terminos.txt", "r", encoding="utf-8") as f:
    contenido = f.read()

# Usamos markdown con un estilo CSS para forzar el color negro
st.markdown(f'<div style="color: black;">{contenido}</div>', unsafe_allow_html=True)