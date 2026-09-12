import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

st.set_page_config(page_title="Esports Scanner — Últimos Jogos", page_icon="🎮", layout="wide")
st.title("🎮 Esports Scanner — Últimos Jogos")
st.caption("Probabilidades baseadas nos resultados mais recentes de cada equipe + H2H")

TOKEN = st.secrets.get("PANDASCORE_TOKEN", "")
BASE = "https://api.pandascore.co"

GAMES = {
    "Todos": None,
    "CS2": "csgo",
    "League of Legends": "league-of-legends",
    "Dota 2": "dota-2",
    "Valorant": "valorant",
}

if not TOKEN:
    st.error("PANDASCORE_TOKEN não configurado.")
    st.code('PANDASCORE_TOKEN = "sua_chave_aqui"', language="toml")
    st.stop()

@st.cache_data(ttl=120, show_spinner=False)
def api(path, params=None):
    r = requests.get(
        BASE + path,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
        params=params or {},
        timeout=30,
    )
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    return r.json()

def game_slug(match):
    return str((match.get("videogame") or {}).get("slug") or "").lower()

def team_names(match):
    out = []
    for item in match.get("opponents") or []:
        team = item.get("opponent") or {}
        out.append({"id": team.get("id"), "name": team.get("name") or "?"})
    while len(out) < 2:
        out.append({"id": None, "name": "?"})
    return out[:2]

def finished_match(m):
    status = str(m.get("status") or "").lower()
    if status == "finished":
        return True
    begin = m.get("begin_at") or m.get("scheduled_at")
    if begin:
        try:
            dt = datetime.fromisoformat(begin.replace("Z", "+00:00"))
            return dt < datetime.now(timezone.utc) and m.get("winner_id") is not None
        except Exception:
            pass
    return False

@st.cache_data(ttl=300, show_spinner=False)
def team_history(team_id, limit=20):
    if not team_id:
        return []
    # Endpoint oficial de histórico da equipe; disponível em todos os planos.
    rows = api(f"/teams/{team_id}/matches", {
        "per_page": 100,
        "sort": "-begin_at",
    })
    # Mantém somente partidas realmente concluídas e limita após ordenar por data.
    rows = [m for m in rows if finished_match(m)]
    rows.sort(key=lambda x: x.get("begin_at") or x.get("scheduled_at") or "", reverse=True)
    return rows[:limit]

def result_for_team(match, team_id):
    winner_id = match.get("winner_id")
    if winner_id is not None:
        if int(winner_id) == int(team_id):
            return "W"
        return "L"
    # fallback para respostas antigas
    for item in match.get("opponents") or []:
        op = item.get("opponent") or {}
        if op.get("id") == team_id:
            res = item.get("result")
            if res in ("win", "loss"):
                return "W" if res == "win" else "L"
    return None

def form_data(team_id, opponent_id=None, limit=20):
    rows = team_history(team_id, limit)
    results = []
    h2h = []
    for m in rows:
        r = result_for_team(m, team_id)
        if r is None:
            continue
        results.append((m, r))
        if opponent_id:
            ids = [x["id"] for x in team_names(m)]
            if opponent_id in ids:
                h2h.append(r)
        if len(results) >= limit:
            break

    # Peso maior para partidas mais recentes: 1.00, 0.94, 0.88...
    weights = [max(0.45, 1.0 - i * 0.06) for i in range(len(results))]
    weighted_wins = sum(w for w, (_, r) in zip(weights, results) if r == "W")
    weight_total = sum(weights)
    weighted_rate = weighted_wins / weight_total if weight_total else 0.5

    wins = sum(r == "W" for _, r in results)
    losses = sum(r == "L" for _, r in results)

    h2h_wins = sum(r == "W" for r in h2h)
    h2h_losses = sum(r == "L" for r in h2h)

    return {
        "wins": wins,
        "losses": losses,
        "weighted_rate": weighted_rate,
        "results": [r for _, r in results],
        "h2h_wins": h2h_wins,
        "h2h_losses": h2h_losses,
        "h2h_total": len(h2h),
    }

def model_probability(a, b):
    # Forma recente é o fator principal.
    f1, f2 = a["weighted_rate"], b["weighted_rate"]

    # Força relativa: transforma as duas formas em uma probabilidade.
    form_p = f1 / (f1 + f2) if f1 + f2 else 0.5

    # H2H somente quando houver amostra.
    htotal = a["h2h_total"] + b["h2h_total"]
    if htotal >= 2:
        h2h_p = a["h2h_wins"] / htotal
        wh = min(0.20, 0.05 * htotal)
    else:
        h2h_p = 0.5
        wh = 0.0

    # Pequeno ajuste por amostra e regressão para 50%.
    wf = 0.80 if min(a["wins"] + a["losses"], b["wins"] + b["losses"]) >= 10 else 0.65
    wb = 1.0 - wf - wh

    p = wf * form_p + wh * h2h_p + wb * 0.5

    sample = min(a["wins"] + a["losses"], b["wins"] + b["losses"])
    shrink = min(1.0, max(0.35, sample / 10))
    p = 0.5 + (p - 0.5) * shrink

    return float(np.clip(p, 0.05, 0.95))

def suggestion(p, t1, t2, a, b):
    edge = abs(p - 0.5)
    sample = min(a["wins"] + a["losses"], b["wins"] + b["losses"])

    # Não recomenda quando a base é insuficiente.
    if sample < 5:
        return "⚪ Sem aposta — amostra insuficiente", "Baixa"

    if p >= 0.65:
        return f"🟢 Vitória {t1}", "Alta" if sample >= 10 else "Média"
    if p <= 0.35:
        return f"🟢 Vitória {t2}", "Alta" if sample >= 10 else "Média"
    if p >= 0.60:
        return f"🟡 Preferência {t1}", "Média"
    if p <= 0.40:
        return f"🟡 Preferência {t2}", "Média"

    return "⚪ Sem aposta", "Baixa"

def analyze_match(m):
    teams = team_names(m)
    ateam, bteam = teams[0], teams[1]
    a = form_data(ateam["id"], bteam["id"], 20)
    b = form_data(bteam["id"], ateam["id"], 20)
    p = model_probability(a, b)
    sug, conf = suggestion(p, ateam["name"], bteam["name"], a, b)
    return ateam, bteam, a, b, p, sug, conf

# Filtros
c1, c2, c3 = st.columns(3)
game = c1.selectbox("E-sport", list(GAMES.keys()))
mode = c2.selectbox("Partidas", ["Próximas", "Ao vivo"])
limit = c3.slider("Quantidade", 10, 100, 50)

path = "/matches/upcoming" if mode == "Próximas" else "/matches/running"

try:
    rows = api(path, {"per_page": min(limit, 100), "sort": "begin_at"})
    wanted = GAMES[game]
    if wanted:
        rows = [m for m in rows if wanted in game_slug(m)]

    if not rows:
        st.info("Nenhuma partida encontrada.")
        st.stop()

    st.success(f"{len(rows)} partidas encontradas.")

    analysis = []
    progress = st.progress(0)
    for i, m in enumerate(rows):
        try:
            t1, t2, a, b, p, sug, conf = analyze_match(m)
            analysis.append({
                "id": m.get("id"),
                "Partida": f"{t1['name']} x {t2['name']}",
                "Prob. T1": round(p * 100, 1),
                "Prob. T2": round((1-p) * 100, 1),
                "Últimos T1": f"{a['wins']}V-{a['losses']}D",
                "Últimos T2": f"{b['wins']}V-{b['losses']}D",
                "H2H": f"{a['h2h_wins']}V-{a['h2h_losses']}D",
                "Sugestão": sug,
                "Confiança": conf,
                "Início": m.get("begin_at") or "",
            })
        except Exception as e:
            teams = team_names(m)
            analysis.append({
                "id": m.get("id"),
                "Partida": f"{teams[0]['name']} x {teams[1]['name']}",
                "Prob. T1": None,
                "Prob. T2": None,
                "Últimos T1": "erro",
                "Últimos T2": "erro",
                "H2H": "-",
                "Sugestão": "⚠️ Dados insuficientes",
                "Confiança": "Baixa",
                "Início": m.get("begin_at") or "",
            })
        progress.progress((i + 1) / len(rows))
    progress.empty()

    adf = pd.DataFrame(analysis)

    # Ranking: primeiro sinais fortes; depois sem aposta.
    adf["_edge"] = (adf["Prob. T1"].fillna(50) - 50).abs()
    adf = adf.sort_values("_edge", ascending=False).drop(columns="_edge")

    st.subheader("🔥 Sugestões baseadas nos últimos jogos")
    st.dataframe(adf.drop(columns=["id"]), use_container_width=True, hide_index=True)

    # Filtro rápido para só mostrar recomendações.
    only = st.checkbox("Mostrar somente sugestões", value=False)
    if only:
        rec = adf[adf["Sugestão"].astype(str).str.startswith(("🟢", "🟡"))]
        st.subheader("🎯 Oportunidades encontradas")
        st.dataframe(rec.drop(columns=["id"]), use_container_width=True, hide_index=True)

    options = {
        f"{r['Partida']} — {r['Início']} — ID {r['id']}": r["id"]
        for _, r in adf.iterrows()
    }
    selected = st.selectbox("Analisar partida", list(options.keys()))
    mid = options[selected]
    match = api(f"/matches/{mid}")

    t1, t2, a, b, p, sug, conf = analyze_match(match)

    st.subheader("📊 Análise detalhada")
    x, y, z = st.columns(3)
    x.metric(t1["name"], f"{p*100:.1f}%")
    y.metric(t2["name"], f"{(1-p)*100:.1f}%")
    z.metric("Confiança", conf)

    if sug.startswith("🟢"):
        st.success(f"**Sugestão:** {sug}")
    elif sug.startswith("🟡"):
        st.warning(f"**Sugestão:** {sug}")
    else:
        st.info(f"**Sugestão:** {sug}")

    d1, d2 = st.columns(2)
    with d1:
        st.write(f"**{t1['name']} — últimos {a['wins']+a['losses']} jogos:** {a['wins']} vitórias / {a['losses']} derrotas")
        st.write("Sequência:", " ".join(a["results"]) if a["results"] else "sem dados")
        st.write(f"Forma ponderada: **{a['weighted_rate']*100:.1f}%**")
    with d2:
        st.write(f"**{t2['name']} — últimos {b['wins']+b['losses']} jogos:** {b['wins']} vitórias / {b['losses']} derrotas")
        st.write("Sequência:", " ".join(b["results"]) if b["results"] else "sem dados")
        st.write(f"Forma ponderada: **{b['weighted_rate']*100:.1f}%**")

    st.write(f"**H2H encontrado:** {a['h2h_wins']} x {a['h2h_losses']} em {a['h2h_total']} confrontos.")

    st.caption(
        "O modelo usa resultados dos últimos jogos, dando mais peso aos mais recentes, "
        "e H2H quando há amostra. A porcentagem é uma estimativa estatística, não garantia."
    )

except Exception as e:
    st.error(str(e))
    st.info(
        "A lista de partidas usa os endpoints globais da PandaScore. "
        "O histórico da equipe usa GET /teams/{id}/matches, disponível para todos os clientes."
    )

st.divider()
st.caption("PandaScore • resultados recentes + H2H • probabilidades estimadas")
