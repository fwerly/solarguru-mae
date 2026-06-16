# SolarGuru — Wanda ☀️

Dashboard de geração solar da Wanda (inversor Sungrow, monitorado via plataforma SolarZ).
Mostra geração em tempo real, histórico com clima, desempenho vs. previsão.

## Rodar localmente
1. `setup.bat` (uma vez)
2. `run.bat`

Credenciais no `.env` (não versionado).

## Publicar no Streamlit Community Cloud

1. Este repositório já está no GitHub.
2. Acesse https://share.streamlit.io → **New app** → **Deploy a public app from GitHub**.
3. Escolha:
   - **Repository:** `fwerly/solarguru-mae`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. **Advanced settings → Secrets** e cole (formato TOML):

   ```toml
   SOLARZ_USERNAME = "email_do_app_solarz"
   SOLARZ_PASSWORD = "senha_do_app_solarz"
   NOME_USUARIO = "Wanda"
   ```
   (email e senha reais você cola só no painel do Streamlit, nunca aqui no repositório)
5. **Deploy**.

> Senhas só nos Secrets da plataforma. A foto do Lula (`assets/lula.jpg`) viaja no repositório.
