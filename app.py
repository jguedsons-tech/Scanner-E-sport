import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title='Esports Scanner PRO', page_icon='🎮', layout='wide')
st.title('🎮 Esports Scanner PRO')
st.caption('CS2 • LoL • Dota 2 • Valorant — partidas + forma recente + H2H + probabilidade estimada')

TOKEN = st.secrets.get('PANDASCORE_TOKEN', '')
BASE = 'https://api.pandascore.co'

GAMES = {'CS2': 'csgo', 'League of Legends': 'league-of-legends', 'Dota 2': 'dota-2', 'Valorant': 'valorant'}


def api(path, params=None):
    if not TOKEN:
        raise RuntimeError('PANDASCORE_TOKEN não configurado nos Secrets.')
    r = requests.get(BASE + path, headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/json'}, params=params or {}, timeout=25)
    if r.status_code >= 400:
        try: detail = r.json()
        except Exception: detail = r.text[:300]
        raise RuntimeError(f'HTTP {r.status_code}: {detail}')
    return r.json()


def team_names(m):
    ops = m.get('opponents') or []
    names = []
    for o in ops:
        t = o.get('opponent') or {}
        names.append(t.get('name', '?'))
    return (names + ['?', '?'])[:2]


def team_objs(m):
    ops = m.get('opponents') or []
    return [o.get('opponent') or {} for o in ops]


def game_slug(m):
    vg = m.get('videogame') or {}
    return str(vg.get('slug') or vg.get('name') or '').lower()


def parse_matches(rows):
    out=[]
    for m in rows:
        a,b=team_names(m)
        out.append({'id':m.get('id'),'Início':m.get('begin_at') or m.get('scheduled_at') or '', 'Time 1':a,'Time 2':b,
                    'Jogo':(m.get('videogame') or {}).get('name',''),'Liga':(m.get('league') or {}).get('name',''),
                    'Torneio':(m.get('tournament') or {}).get('name',''),'Status':m.get('status',''),
                    'Série':(m.get('serie') or {}).get('full_name','')})
    return pd.DataFrame(out)


def winner_id(match):
    w = match.get('winner') or {}
    return w.get('id') if isinstance(w, dict) else None


def recent_form(team_id, n=10):
    """Uses the public team match-history endpoint. Only completed matches count."""
    try:
        rows = api(f'/teams/{team_id}/matches', {'per_page': min(max(n*2, 20), 100), 'sort': '-begin_at'})
    except Exception:
        return {'wins':0,'losses':0,'games':0,'winrate':0.50,'rows':[]}
    rows = [x for x in rows if x.get('status') == 'finished' and winner_id(x)]
    rows = rows[:n]
    wins = sum(1 for x in rows if winner_id(x) == team_id)
    losses = len(rows)-wins
    return {'wins':wins,'losses':losses,'games':len(rows),'winrate': wins/len(rows) if rows else 0.50,'rows':rows}


def h2h(team_a, team_b, n=20):
    try:
        a = recent_form(team_a, n)
        b = recent_form(team_b, n)
        amap={x.get('id'):x for x in a['rows']}
        common=[]
        for x in b['rows']:
            if x.get('id') in amap:
                common.append(x)
        common.sort(key=lambda x:x.get('begin_at') or '', reverse=True)
        common=common[:10]
        aw=0; bw=0
        for x in common:
            w=winner_id(x)
            if w==team_a: aw+=1
            elif w==team_b: bw+=1
        return aw,bw,len(common)
    except Exception:
        return 0,0,0


def probability(team_a, team_b):
    fa=recent_form(team_a,10); fb=recent_form(team_b,10)
    aw,bw,hn=h2h(team_a,team_b,20)
    # Bayesian-ish shrinkage toward 50% to avoid extreme probabilities with small samples.
    ra=(fa['wins']+5)/(fa['games']+10)
    rb=(fb['wins']+5)/(fb['games']+10)
    if aw+bw:
        ha=(aw+2)/(aw+bw+4)
    else:
        ha=0.50
    # 60% recent form, 25% H2H, 15% neutral prior.
    pa=0.60*ra + 0.25*ha + 0.15*0.50
    pa=max(0.05,min(0.95,pa)); pb=1-pa
    conf='Alta' if min(fa['games'],fb['games'])>=7 and (aw+bw)>=3 else ('Média' if min(fa['games'],fb['games'])>=4 else 'Baixa')
    return {'pa':pa,'pb':pb,'fa':fa,'fb':fb,'aw':aw,'bw':bw,'hn':hn,'conf':conf}


def pct(x): return f'{x*100:.1f}%'

if not TOKEN:
    st.warning('Configure PANDASCORE_TOKEN em Settings → Secrets.')
    st.code('PANDASCORE_TOKEN = "sua_chave_aqui"', language='toml')
    st.stop()

c1,c2,c3=st.columns(3)
game=c1.selectbox('Jogo',list(GAMES))
mode=c2.selectbox('Tipo',['Próximas','Ao vivo','Finalizadas'])
limit=c3.slider('Partidas',10,100,50)

paths={'Próximas':'/matches/upcoming','Ao vivo':'/matches/running','Finalizadas':'/matches/past'}
params={'per_page':min(limit,100), 'sort': 'begin_at' if mode=='Próximas' else '-begin_at'}

try:
    rows=api(paths[mode],params)
    wanted=GAMES[game]
    filtered=[]
    for m in rows:
        s=game_slug(m); name=str((m.get('videogame') or {}).get('name','')).lower()
        if wanted in s or wanted in name or s in wanted or name in wanted: filtered.append(m)
    df=parse_matches(filtered)
    st.success(f'{len(filtered)} partidas de {game} encontradas.')
    if df.empty:
        st.info('Nenhuma partida encontrada nesse momento.')
        st.stop()

    # Rank all upcoming matches by model probability when possible.
    ranked=[]
    for m in filtered[:30] if mode != 'Finalizadas' else []:
        ops=team_objs(m)
        if len(ops)<2 or not ops[0].get('id') or not ops[1].get('id'): continue
        p=probability(ops[0]['id'],ops[1]['id'])
        ranked.append({'Partida':f"{ops[0].get('name','?')} x {ops[1].get('name','?')}",
                       'Prob. T1':pct(p['pa']),'Prob. T2':pct(p['pb']),'Confiança':p['conf'],
                       'Forma T1':f"{p['fa']['wins']}-{p['fa']['losses']}",'Forma T2':f"{p['fb']['wins']}-{p['fb']['losses']}",
                       'H2H':f"{p['aw']}-{p['bw']}" if p['hn'] else 'sem H2H','id':m.get('id')})
    if ranked:
        st.subheader('🔥 Melhores probabilidades estimadas')
        rdf=pd.DataFrame(ranked)
        rdf['ord']=rdf['Prob. T1'].str.rstrip('%').astype(float).clip(lower=rdf['Prob. T2'].str.rstrip('%').astype(float))
        rdf=rdf.sort_values('ord',ascending=False).drop(columns='ord')
        st.dataframe(rdf.drop(columns=['id']),use_container_width=True,hide_index=True)

    st.subheader(f'📅 {game} — {mode}')
    st.dataframe(df.drop(columns=['id']),use_container_width=True,hide_index=True)

    opts={f"{r['Time 1']} x {r['Time 2']} — {r['Torneio']} — ID {r['id']}":r['id'] for _,r in df.iterrows()}
    selected=st.selectbox('Analisar partida',list(opts))
    mid=opts[selected]
    m=api(f'/matches/{mid}')
    ops=team_objs(m)
    a,b=team_names(m)
    st.subheader('📊 Análise da partida')
    if len(ops)>=2 and ops[0].get('id') and ops[1].get('id'):
        p=probability(ops[0]['id'],ops[1]['id'])
        x,y,z=st.columns(3)
        x.metric(a,pct(p['pa'])); y.metric(b,pct(p['pb'])); z.metric('Confiança',p['conf'])
        st.progress(float(p['pa']),text=f'Probabilidade estimada para {a}: {pct(p["pa"])}')
        st.progress(float(p['pb']),text=f'Probabilidade estimada para {b}: {pct(p["pb"])}')
        f1,f2,h=st.columns(3)
        f1.metric(f'Forma {a}',f"{p['fa']['wins']}V / {p['fa']['losses']}D")
        f2.metric(f'Forma {b}',f"{p['fb']['wins']}V / {p['fb']['losses']}D")
        h.metric('H2H',f"{p['aw']} x {p['bw']}" if p['hn'] else 'Sem amostra')
        if p['pa'] >= .60 and p['pa'] >= p['pb']:
            st.success(f'🟢 Modelo favorece {a}: {pct(p["pa"])}')
        elif p['pb'] >= .60:
            st.success(f'🟢 Modelo favorece {b}: {pct(p["pb"])}')
        else:
            st.warning('🟡 Sem vantagem estatística forte no modelo.')
    else:
        st.info('Não foi possível identificar os IDs das equipes para calcular a probabilidade.')

    st.caption('Modelo: forma recente + H2H, com regressão para 50% quando a amostra é pequena. É uma estimativa estatística, não garantia de acerto ou lucro.')

except Exception as e:
    st.error(str(e))
    st.caption('A agenda da PandaScore é acessível nos planos de fixtures; estatísticas pós-jogo detalhadas exigem plano Historical. O modelo desta versão usa histórico de partidas das equipes para estimar a probabilidade.')

st.divider()
st.caption('Fonte de dados: PandaScore. Token mantido nos Secrets do Streamlit.')
