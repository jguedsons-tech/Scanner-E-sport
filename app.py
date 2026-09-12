import streamlit as st
import requests, pandas as pd, numpy as np
from datetime import datetime, timezone

st.set_page_config(page_title='Esports Scanner', page_icon='🎮', layout='wide')
st.title('🎮 Esports Scanner')
st.caption('CS2 • LoL • Dota 2 • Valorant — calendário, partidas e análise estatística básica')

TOKEN = st.secrets.get('PANDASCORE_TOKEN','')
BASE='https://api.pandascore.co'

GAMES={
 'CS2':'csgo',
 'League of Legends':'lol',
 'Dota 2':'dota2',
 'Valorant':'valorant'
}

def api(path, params=None):
    if not TOKEN: raise RuntimeError('PANDASCORE_TOKEN não configurado nos Secrets.')
    r=requests.get(BASE+path, headers={'Authorization':f'Bearer {TOKEN}'}, params=params or {}, timeout=25)
    if r.status_code>=400: raise RuntimeError(f'HTTP {r.status_code}: {r.text[:250]}')
    return r.json()

def team_names(m):
    ops=m.get('opponents') or []
    names=[]
    for o in ops:
        t=o.get('opponent') or {}
        names.append(t.get('name','?'))
    return names+['?']*2

def parse_matches(rows):
    out=[]
    for m in rows:
        a,b=team_names(m)[:2]
        begin=m.get('begin_at') or m.get('scheduled_at') or ''
        out.append({
            'id':m.get('id'), 'Início':begin, 'Mandante/Time 1':a,
            'Time 2':b, 'Liga':(m.get('league') or {}).get('name',''),
            'Torneio':(m.get('tournament') or {}).get('name',''),
            'Status':m.get('status',''), 'Série':(m.get('serie') or {}).get('full_name','')
        })
    return pd.DataFrame(out)

if not TOKEN:
    st.warning('Configure PANDASCORE_TOKEN em Settings → Secrets antes de usar o scanner.')
    st.code('PANDASCORE_TOKEN = "sua_chave_aqui"', language='toml')
    st.stop()

col1,col2,col3=st.columns(3)
game=col1.selectbox('Jogo', list(GAMES))
mode=col2.selectbox('Tipo',['Próximas','Ao vivo','Finalizadas'])
limit=col3.slider('Quantidade',5,100,30)
slug=GAMES[game]

paths={'Próximas':f'/{slug}/matches/upcoming','Ao vivo':f'/{slug}/matches/running','Finalizadas':f'/{slug}/matches/past'}
params={'per_page':limit,'sort':'begin_at'}

try:
    rows=api(paths[mode],params)
    df=parse_matches(rows)
    if df.empty:
        st.info('Nenhuma partida encontrada.')
    else:
        st.dataframe(df.drop(columns=['id']), use_container_width=True, hide_index=True)
        opts={f"{r['Mandante/Time 1']} x {r['Time 2']} — {r['Torneio']}":r['id'] for _,r in df.iterrows()}
        selected=st.selectbox('Analisar partida', list(opts))
        mid=opts[selected]
        m=api(f'/{slug}/matches/{mid}')
        st.subheader('📊 Detalhes')
        a,b=team_names(m)[:2]
        c1,c2,c3=st.columns(3)
        c1.metric('Time 1',a); c2.metric('Time 2',b); c3.metric('Status',m.get('status',''))
        st.write('Liga:',(m.get('league') or {}).get('name',''))
        st.write('Torneio:',(m.get('tournament') or {}).get('name',''))
        st.write('Melhor de:', m.get('number_of_games','—'))
        results=[]
        for g in (m.get('games') or []):
            results.append({'Mapa/Game':g.get('position'), 'Status':g.get('status'), 'Winner':(g.get('winner') or {}).get('name','') if isinstance(g.get('winner'),dict) else ''})
        if results: st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
        st.subheader('🤖 Modelo')
        st.caption('Estimativa heurística, não garantia de acerto. O modelo não inventa estatísticas ausentes.')
        # Only a transparent baseline from available opponent/score information.
        scores=[]
        for o in (m.get('opponents') or []):
            op=o.get('opponent') or {}; sc=o.get('score')
            if sc is not None: scores.append((op.get('name',''),sc))
        if len(scores)==2 and all(isinstance(x[1],(int,float)) for x in scores):
            total=sum(x[1] for x in scores)
            probs=[scores[0][1]/total if total else .5, scores[1][1]/total if total else .5]
            st.write(f'Probabilidade baseada apenas no placar disponível: **{probs[0]:.1%} x {probs[1]:.1%}**')
        else:
            st.info('Sem dados numéricos suficientes para calcular uma probabilidade responsável nesta partida.')
except Exception as e:
    st.error(str(e))

st.divider()
st.caption('Fonte de dados: PandaScore. O plano gratuito atual fornece calendário, resultados e contexto básico; estatísticas históricas detalhadas podem exigir plano pago.')
