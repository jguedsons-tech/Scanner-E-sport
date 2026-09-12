# Esports Scanner — Streamlit

Scanner para CS2, League of Legends, Dota 2 e Valorant usando PandaScore.

## Secret
No Streamlit Cloud → Settings → Secrets:

```toml
PANDASCORE_TOKEN = "SUA_CHAVE"
```

Nunca coloque a chave no código ou no GitHub.

## Deploy
1. Crie um repositório no GitHub.
2. Envie `app.py` e `requirements.txt`.
3. No Streamlit Cloud, escolha `app.py` como arquivo principal.
4. Em Settings → Secrets, adicione `PANDASCORE_TOKEN`.
5. Salve/reinicie.

O plano gratuito da PandaScore oferece calendário, resultados e contexto básico, com limite de 1.000 requisições/hora; não exige cartão para cadastro. Estatísticas históricas detalhadas são um produto pago.

As probabilidades exibidas são apenas estimativas e não garantem acerto ou lucro.
