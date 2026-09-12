import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title='Esports Scanner', page_icon='🎮', layout='wide')
st.title('🎮 Esports Scanner')
st.caption('CS2 • LoL • Dota 2 • Valorant — calendário, partidas e análise básica')

TOKEN = st.secrets.get('PANDASCORE_TOKEN', '')
BASE = 'https://api.pandascore.co'

GAMES = {
    'CS2': 'csgo',
    'League of Legends': 'league-of-legends',
    'Dota 2': 'dota-2',
    'Valorant': 'valorant',
}


def api(path, params=None):
    if not TOKEN:
        raise RuntimeError('PANDASCORE_TOKEN não configurado nos Secrets.')
    r = requests.get(
        BASE + path,
        headers={
            'Authorization': f'Bearer {TOKEN}',
            'Accept': 'application/json',
        },
        params=params or {},
        timeout=25,
    )
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f'HTTP {r.status_code}: {detail}')
    return r.json()


def team_names(m):
    ops = m.get('opponents') or []
    names = []
    for o in ops:
        t = o.get('opponent') or {}
        names.append(t.get('name', '?'))
    return (names + ['?', '?'])[:2]


def game_slug(m):
    vg = m.get('videogame') or {}
    return str(vg.get('slug') or vg.get('name') or '').lower()


def parse_matches(rows):
    out = []
    for m in rows:
        a, b = team_names(m)
        begin = m.get('begin_at') or m.get('scheduled_at') or ''
        out.append({
            'id': m.get('id'),
            'Início': begin,
            'Time 1': a,
            'Time 2': b,
            'Jogo': (m.get('videogame') or {}).get('name', ''),
            'Liga': (m.get('league') or {}).get('name', ''),
            'Torneio': (m.get('tournament') or {}).get('name', ''),
            'Status': m.get('status', ''),
            'Série': (m.get('serie') or {}).get('full_name', ''),
        })
    return pd.DataFrame(out)


if not TOKEN:
    st.warning('Configure PANDASCORE_TOKEN em Settings → Secrets antes de usar o scanner.')
    st.code('PANDASCORE_TOKEN = "sua_chave_aqui"', language='toml')
    st.stop()

col1, col2, col3 = st.columns(3)
game = col1.selectbox('Jogo', list(GAMES))
mode = col2.selectbox('Tipo', ['Próximas', 'Ao vivo', 'Finalizadas'])
limit = col3.slider('Quantidade para consultar', 10, 100, 50)

paths = {
    'Próximas': '/matches/upcoming',
    'Ao vivo': '/matches/running',
    'Finalizadas': '/matches/past',
}

# Os endpoints globais /matches/* são disponibilizados para todos os clientes.
# Filtramos o videogame no próprio aplicativo para evitar endpoints específicos
# que podem depender do plano.
params = {'per_page': min(limit, 100)}
if mode == 'Próximas':
    params['sort'] = 'begin_at'
else:
    params['sort'] = '-begin_at'

try:
    rows = api(paths[mode], params)
    wanted = GAMES[game]

    # O campo videogame.slug pode aparecer como csgo, league-of-legends,
    # dota-2 ou valorant. Também aceitamos nomes equivalentes.
    filtered = []
    for m in rows:
        s = game_slug(m)
        name = str((m.get('videogame') or {}).get('name', '')).lower()
        if wanted in s or wanted in name or s in wanted or name in wanted:
            filtered.append(m)

    df = parse_matches(filtered)

    st.success(f'API respondeu corretamente: {len(rows)} partidas recebidas.')

    if df.empty:
        st.info(f'Nenhuma partida de {game} encontrada nesse momento. A API está funcionando.')
    else:
        st.subheader(f'📅 {game} — {mode}')
        st.dataframe(
            df.drop(columns=['id']),
            use_container_width=True,
            hide_index=True,
        )

        opts = {
            f"{r['Time 1']} x {r['Time 2']} — {r['Torneio']} — ID {r['id']}": r['id']
            for _, r in df.iterrows()
        }
        selected = st.selectbox('Analisar partida', list(opts))
        mid = opts[selected]
        m = api(f'/matches/{mid}')

        st.subheader('📊 Detalhes')
        a, b = team_names(m)
        c1, c2, c3 = st.columns(3)
        c1.metric('Time 1', a)
        c2.metric('Time 2', b)
        c3.metric('Status', m.get('status', ''))
        st.write('Liga:', (m.get('league') or {}).get('name', ''))
        st.write('Torneio:', (m.get('tournament') or {}).get('name', ''))
        st.write('Melhor de:', m.get('number_of_games', '—'))
        st.write('Início:', m.get('begin_at') or m.get('scheduled_at') or '—')

        games = m.get('games') or []
        if games:
            results = []
            for g in games:
                winner = g.get('winner') or {}
                results.append({
                    'Mapa/Game': g.get('position'),
                    'Status': g.get('status'),
                    'Vencedor': winner.get('name', '') if isinstance(winner, dict) else '',
                })
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

        st.subheader('🤖 Modelo')
        st.caption('Estimativa estatística simples. Não é garantia de acerto ou lucro.')
        st.info('Nesta versão, o modelo não inventa estatísticas. Para gerar probabilidades de aposta mais úteis, a próxima etapa é adicionar histórico/H2H, desempenho recente, mapas e odds.')

except Exception as e:
    st.error(str(e))
    st.markdown('**Diagnóstico:** se aparecer HTTP 403, normalmente o endpoint/recurso solicitado não está incluído no plano do token. Os endpoints globais `/matches/upcoming`, `/matches/running` e `/matches/past` são documentados pela PandaScore como disponíveis para todos os clientes.')

st.divider()
st.caption('Fonte: PandaScore. O scanner usa autenticação por Bearer token e mantém o token apenas nos Secrets do Streamlit.')
