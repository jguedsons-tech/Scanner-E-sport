import streamlit as st
import requests
import pandas as pd
import numpy as np
from datetime import datetime

st.set_page_config(page_title='Esports Scanner PRO', page_icon='🎮', layout='wide')
st.title('🎮 Esports Scanner PRO')
st.caption('CS2 • LoL • Dota 2 • Valorant — partidas globais + forma + H2H + probabilidade + sugestão')

TOKEN = st.secrets.get('PANDASCORE_TOKEN', '')
BASE = 'https://api.pandascore.co'
GAMES = {'Todos': None, 'CS2': 'csgo', 'League of Legends': 'league-of-legends', 'Dota 2': 'dota-2', 'Valorant': 'valorant'}

@st.cache_data(ttl=60)
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
    vals=[]
    for o in ops:
        t=o.get('opponent') or {}
        vals.append({'id':t.get('id'),'name':t.get('name','?')})
    vals += [{'id':None,'name':'?'},{'id':None,'name':'?'}]
    return vals[:2]

def slug(m):
    vg=m.get('videogame') or {}
    return str(vg.get('slug') or '').lower()

def filter_game(rows, game):
    wanted=GAMES[game]
    if not wanted: return rows
    return [m for m in rows if wanted in slug(m)]

def parse_matches(rows):
    out=[]
    for m in rows:
        ts=team_names(m)
        out.append({'id':m.get('id'),'Início':m.get('begin_at') or m.get('scheduled_at') or '', 'Time 1':ts[0]['name'],'Time 2':ts[1]['name'],'Jogo':(m.get('videogame') or {}).get('name',''),'Liga':(m.get('league') or {}).get('name',''),'Torneio':(m.get('tournament') or {}).get('name',''),'Status':m.get('status',''),'Série':(m.get('serie') or {}).get('full_name','')})
    return pd.DataFrame(out)

def team_history(team_id, limit=20):
    if not team_id: return []
    # Endpoint de histórico de partidas de equipe.
    try:
        return api(f'/teams/{team_id}/matches', {'per_page':limit,'sort':'-begin_at'})
    except Exception:
        return []

def team_form(team_id, opponent_id=None, limit=20):
    rows=team_history(team_id, limit)
    wins=losses=0; recent=[]; h2h_w=h2h_l=0
    for m in rows:
        ops=team_names(m)
        if not ops[0]['id'] or not ops[1]['id']: continue
        # tenta descobrir vencedor pelo campo winner ou score dos opponents
        winner=m.get('winner') or {}
        wid=winner.get('id') if isinstance(winner,dict) else None
        if not wid:
            for o in m.get('opponents') or []:
                op=o.get('opponent') or {}
                if op.get('id') and o.get('result')=='win': wid=op.get('id')
        if wid:
            w=(wid==team_id); wins += int(w); losses += int(not w); recent.append(w)
            if opponent_id and opponent_id in [ops[0]['id'],ops[1]['id']]:
                if w: h2h_w += 1
                else: h2h_l += 1
        if len(recent)>=limit: break
    return {'wins':wins,'losses':losses,'recent':recent,'h2h_w':h2h_w,'h2h_l':h2h_l}

def probability(a,b):
    # Modelo conservador: forma recente tem maior peso; H2H menor peso; regressão para 50%.
    n1=a['wins']+a['losses']; n2=b['wins']+b['losses']
    f1=(a['wins']/n1) if n1 else .5; f2=(b['wins']/n2) if n2 else .5
    h1=(a['h2h_w']/(a['h2h_w']+a['h2h_l'])) if (a['h2h_w']+a['h2h_l']) else .5
    h2=1-h1 if (a['h2h_w']+a['h2h_l']) else .5
    # peso adaptativo: mais histórico -> maior confiança, mas limitado.
    wf=min(0.70, 0.35+0.025*min(n1,n2)); wh=0.15 if (a['h2h_w']+a['h2h_l'])>=3 else 0.0; wb=1-wf-wh
    s1=wf*f1+wf*f1*0 + wh*h1 + wb*.5
    s2=wf*f2+wh*h2+wb*.5
    p=s1/(s1+s2) if (s1+s2) else .5
    p=float(np.clip(p,0.05,0.95))
    # reduzir exagero quando amostra é pequena
    sample=min(n1,n2)
    shrink=max(0.55, min(1.0, sample/10))
    p=.5+(p-.5)*shrink
    return p

def suggestion(p, a_name, b_name, n1, n2):
    conf=max(n1,n2)
    if p>=0.62:
        return f'🟢 Vitória {a_name}', 'Alta' if conf>=8 else 'Média'
    if p<=0.38:
        return f'🟢 Vitória {b_name}', 'Alta' if conf>=8 else 'Média'
    if p>=0.56:
        return f'🟡 Leve preferência: {a_name}', 'Baixa'
    if p<=0.44:
        return f'🟡 Leve preferência: {b_name}', 'Baixa'
    return '⚪ Sem aposta', 'Baixa'

if not TOKEN:
    st.warning('Configure PANDASCORE_TOKEN em Settings → Secrets.')
    st.code('PANDASCORE_TOKEN = "sua_chave_aqui"', language='toml'); st.stop()

c1,c2,c3=st.columns(3)
game=c1.selectbox('E-sport',list(GAMES))
mode=c2.selectbox('Tipo',['Próximas','Ao vivo','Finalizadas'])
limit=c3.slider('Partidas',10,100,50)
paths={'Próximas':'/matches/upcoming','Ao vivo':'/matches/running','Finalizadas':'/matches/past'}
params={'per_page':min(limit,100),'sort':'begin_at' if mode=='Próximas' else '-begin_at'}

try:
    rows=filter_game(api(paths[mode],params),game)
    df=parse_matches(rows)
    st.success(f'{len(rows)} partidas encontradas.')
    if df.empty:
        st.info('Nenhuma partida encontrada para esse filtro.')
        st.stop()

    # Pré-calcula sugestões. O cache evita repetir chamadas durante a navegação.
    analysis=[]
    for m in rows:
        ts=team_names(m); t1,t2=ts[0],ts[1]
        f1=team_form(t1['id'],t2['id'],20); f2=team_form(t2['id'],t1['id'],20)
        p=probability(f1,f2)
        sug,conf=suggestion(p,t1['name'],t2['name'],len(f1['recent']),len(f2['recent']))
        analysis.append({'id':m.get('id'),'Partida':f"{t1['name']} x {t2['name']}",'Prob. T1':round(p*100,1),'Prob. T2':round((1-p)*100,1),'Forma T1':f"{f1['wins']}-{f1['losses']}",'Forma T2':f"{f2['wins']}-{f2['losses']}",'Sugestão':sug,'Confiança':conf,'Início':m.get('begin_at') or ''})
    adf=pd.DataFrame(analysis)
    if mode!='Finalizadas':
        # ranking por maior distância de 50%, para destacar sinais mais fortes
        adf['forca']=(adf['Prob. T1']-50).abs()
        adf=adf.sort_values('forca',ascending=False).drop(columns='forca')

    st.subheader('🔥 Sugestões')
    st.dataframe(adf.drop(columns=['id']),use_container_width=True,hide_index=True)

    options={f"{r['Partida']} — {r['Início']} — ID {r['id']}":r['id'] for _,r in adf.iterrows()}
    selected=st.selectbox('Analisar partida',list(options))
    mid=options[selected]
    m=api(f'/matches/{mid}')
    ts=team_names(m); t1,t2=ts[0],ts[1]
    f1=team_form(t1['id'],t2['id'],20); f2=team_form(t2['id'],t1['id'],20)
    p=probability(f1,f2); sug,conf=suggestion(p,t1['name'],t2['name'],len(f1['recent']),len(f2['recent']))

    st.subheader('📊 Análise da partida')
    a,b,c=st.columns(3); a.metric(t1['name'],f'{p*100:.1f}%'); b.metric(t2['name'],f'{(1-p)*100:.1f}%'); c.metric('Confiança',conf)
    st.success(f'**Sugestão do modelo:** {sug}') if '🟢' in sug else st.warning(f'**Sugestão do modelo:** {sug}')
    st.write(f"Forma últimos jogos: **{t1['name']} {f1['wins']}-{f1['losses']}** | **{t2['name']} {f2['wins']}-{f2['losses']}**")
    h2h=f1['h2h_w']+f1['h2h_l']
    st.write(f"H2H encontrado na amostra: **{f1['h2h_w']} x {f1['h2h_l']}** ({h2h} confrontos)")
    st.caption('Probabilidades são estimativas estatísticas, não garantia de acerto ou lucro. O modelo evita sugerir aposta quando a vantagem estimada é pequena.')

except Exception as e:
    st.error(str(e))
    st.info('Se a lista aparece, mas as sugestões ficam sem dados, verifique se o plano/token permite histórico de equipes. A PandaScore separa dados de fixtures dos dados históricos detalhados.')

st.divider()
st.caption('Fonte: PandaScore. O token fica somente nos Secrets do Streamlit.')
