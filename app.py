"""SolarGuru (Wanda) - dashboard de geracao solar via SolarZ.

Como rodar:
    streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from solarz_client import SolarZClient

load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(page_title="SolarGuru · Wanda", page_icon="☀️", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        html, body, .stApp, [class*="css"] { font-family: "Inter", -apple-system, sans-serif !important; -webkit-font-smoothing: antialiased; }
        /* esconde toda a moldura do Streamlit (barra branca do topo, menu, rodape) */
        header[data-testid="stHeader"], [data-testid="stHeader"], .stApp > header { display: none !important; }
        [data-testid="stDecoration"] { display: none !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stStatusWidget"] { display: none !important; }
        #MainMenu { visibility: hidden; }
        footer { display: none !important; }
        .block-container { padding: 0 !important; max-width: 100% !important; }
        .stApp { margin-top: 0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

DIAS_PT = {0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira", 3: "Quinta-feira",
           4: "Sexta-feira", 5: "Sábado", 6: "Domingo"}
MESES_PT = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
            7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"}
MESES_ABBR = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
              7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}


def cfg(key: str, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def fmt_num(v: float, d: int = 1) -> str:
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def saudacao(h: int) -> str:
    return "Bom dia" if h < 12 else ("Boa tarde" if h < 18 else "Boa noite")


def weather_emoji(desc: str) -> str:
    d = (desc or "").lower()
    if any(k in d for k in ["sun", "sol", "clear", "limpo"]):
        return "☀️"
    if any(k in d for k in ["part", "parcial"]):
        return "⛅"
    if any(k in d for k in ["overcast", "cloud", "nubl", "encob"]):
        return "☁️"
    if any(k in d for k in ["thunder", "trovo", "storm", "tempest"]):
        return "⛈️"
    if any(k in d for k in ["rain", "chuv", "drizzle", "garoa", "shower"]):
        return "🌧️"
    if any(k in d for k in ["fog", "mist", "nevoa", "neblin"]):
        return "🌫️"
    return "🌤️"


def norm_date(s: str) -> str:
    """'2026-05-06T03:00:00.000+00:00' -> '2026-05-06'."""
    return (s or "")[:10]


@st.cache_data
def lula_data_uri() -> str:
    """Le assets/lula.jpg e devolve como data URI (embutido no HTML)."""
    import base64
    p = Path(__file__).parent / "assets" / "lula.jpg"
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"


def now_br() -> dt.datetime:
    """Horario de Brasilia (UTC-3, sem horario de verao). O servidor do
    Streamlit Cloud roda em UTC; isso garante data/saudacao corretas."""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).replace(tzinfo=None)


@st.cache_resource
def get_client():
    user = cfg("SOLARZ_USERNAME")
    pw = cfg("SOLARZ_PASSWORD")
    if not user or not pw:
        return None
    # NAO captura excecao: se o login falhar (transitorio), o cache_resource
    # nao guarda o erro e a proxima execucao tenta de novo.
    c = SolarZClient(user, pw)
    c.login()
    return c


# Loaders SEM try/except: se a API falhar, a excecao sobe e o st.cache_data
# NAO cacheia o erro -> o proximo refresh (60s) tenta de novo. O fallback
# para zeros acontece so na renderizacao (build_vars), nunca no cache.
@st.cache_data(ttl=60)
def load_day(_c, date_iso):
    return _c.day(dt.date.fromisoformat(date_iso))


@st.cache_data(ttl=300)
def load_month(_c, ref_iso):
    return _c.month_total(dt.date.fromisoformat(ref_iso))


@st.cache_data(ttl=600)
def load_all(_c, ref_iso):
    return _c.all_time(dt.date.fromisoformat(ref_iso))


TEMPLATE = Path(__file__).parent / "dashboard_template.html"


def build_vars() -> dict:
    now = now_br()
    today = now.date()

    try:
        client = get_client()
    except Exception:
        client = None
    ok = client is not None

    plant_name = client.usina.nome if (ok and client.usina) else "Usina solar"
    nome_user = cfg("NOME_USUARIO", "Wanda")

    # cada fonte e independente: se uma falhar, as outras ainda aparecem,
    # e a que falhou NAO fica em cache (tenta de novo no proximo refresh)
    def _try(fn, fallback):
        if not ok:
            return fallback
        try:
            return fn()
        except Exception:
            return fallback

    day = _try(lambda: load_day(client, today.isoformat()),
               {"curva": {}, "total_kwh": 0, "potencia_atual": 0, "prognostico": 0, "inversor": ""})
    month = _try(lambda: load_month(client, today.isoformat()),
                 {"dias": [], "total_kwh": 0, "total_prognostico": 0, "desempenho": 0, "inversor": ""})
    allt = _try(lambda: load_all(client, today.isoformat()),
                {"dias": [], "total_kwh": 0})

    # --- curva do dia -> pontos [hora_decimal, kw] ---
    curva = day["curva"]
    pts = []
    for hm, kw in sorted(curva.items()):
        try:
            h, m = hm.split(":")
            pts.append([round(int(h) + int(m) / 60, 3), round(float(kw), 3)])
        except (ValueError, AttributeError):
            continue
    pac = day["potencia_atual"]
    is_gen = pac > 0.05
    day_max = max([p[1] for p in pts], default=1.0)
    day_max = max(1.0, round(day_max * 1.25, 1))

    # pico
    if pts:
        peak = max(pts, key=lambda p: p[1])
        ph, pm = int(peak[0]), int((peak[0] - int(peak[0])) * 60)
        peak_str = f"{fmt_num(peak[1], 2)} kW"
        peak_time = f"{ph:02d}:{pm:02d}"
    else:
        peak_str, peak_time = "—", "—"

    today_kwh = day["total_kwh"]
    today_forecast = day["prognostico"]

    # clima de hoje: do ultimo dia do historico (se for hoje)
    today_weather = ""
    dias_all = allt["dias"]
    if dias_all and norm_date(dias_all[-1].data) == today.isoformat():
        today_weather = dias_all[-1].clima
    today_emoji = weather_emoji(today_weather)

    # --- mes ---
    month_kwh = month["total_kwh"]
    month_forecast = month["total_prognostico"]
    desempenho = month["desempenho"]
    dias_mes = [d for d in month["dias"] if d.kwh > 0]
    avg_daily = (month_kwh / len(dias_mes)) if dias_mes else 0
    if month["dias"]:
        best = max(month["dias"], key=lambda d: d.kwh)
        bd = norm_date(best.data)
        best_day = f"{fmt_num(best.kwh,1)} kWh ({bd[8:10]}/{bd[5:7]})" if best.kwh else "—"
    else:
        best_day = "—"

    if desempenho >= 100:
        perf_verdict = "Acima do previsto! ☀️"
    elif desempenho >= 90:
        perf_verdict = "Praticamente no previsto 👍"
    elif desempenho >= 70:
        perf_verdict = "Um pouco abaixo (clima)"
    else:
        perf_verdict = "Abaixo do previsto"

    # --- total historico ---
    total_kwh = allt["total_kwh"]
    if total_kwh >= 1000:
        total_value, total_unit = fmt_num(total_kwh / 1000, 2), "MWh"
    else:
        total_value, total_unit = fmt_num(total_kwh, 0), "kWh"

    install_short = ""
    if dias_all:
        d0 = norm_date(dias_all[0].data)
        try:
            install_short = f"desde {MESES_ABBR[int(d0[5:7])]}/{d0[2:4]}"
        except Exception:
            install_short = ""

    # --- barras: ultimos 14 dias ---
    ult = dias_all[-14:] if dias_all else []
    day_bars = []
    for d in ult:
        nd = norm_date(d.data)
        day_bars.append({
            "label": f"{nd[8:10]}/{nd[5:7]}",
            "kwh": round(d.kwh, 1),
            "prog": round(d.prognostico, 1),
            "emoji": weather_emoji(d.clima),
        })

    # --- barras mensais (agrega historico por mes) ---
    mensal = defaultdict(float)
    for d in dias_all:
        nd = norm_date(d.data)
        if len(nd) >= 7:
            mensal[nd[:7]] += d.kwh
    month_bars = [{"label": f"{MESES_ABBR[int(k[5:7])]}/{k[2:4]}", "kwh": round(v, 1)}
                  for k, v in sorted(mensal.items())]

    inversor = month.get("inversor") or day.get("inversor") or "—"

    # --- status / cores ---
    if not ok:
        pcolor, ppbg, ppfg, ppdot, pptext = "#8e8e93", "#f0f0f5", "#6e6e73", "#8e8e93", "Sem conexão"
        sbg, sfg, sdot, stext = "#fff4e5", "#a15c00", "#ff9f0a", "Offline"
    elif is_gen:
        pcolor, ppbg, ppfg, ppdot, pptext = "#ff9f0a", "#e8f9ee", "#117a3d", "#30d158", "Gerando"
        sbg, sfg, sdot, stext = "#e8f9ee", "#117a3d", "#30d158", "Online"
    else:
        pcolor, ppbg, ppfg, ppdot, pptext = "#8e8e93", "#f0f0f5", "#6e6e73", "#8e8e93", "Em repouso"
        sbg, sfg, sdot, stext = "#e8f9ee", "#117a3d", "#30d158", "Online"

    if pac >= 1:
        power_value, power_unit = fmt_num(pac, 2), "kW"
    else:
        power_value, power_unit = fmt_num(pac * 1000, 0), "W"

    history_note = f"Instalada em {install_short.replace('desde ','')}" if install_short else ""

    return {
        "GREETING": saudacao(now.hour), "NAME": nome_user,
        "DATE_FULL": f"{DIAS_PT[today.weekday()]}, {today.day} de {MESES_PT[today.month]} de {today.year}",
        "PLANT_NAME": plant_name,
        "STATUS_BG": sbg, "STATUS_FG": sfg, "STATUS_DOT": sdot, "STATUS_TEXT": stext,
        "POWER_VALUE": power_value, "POWER_UNIT": power_unit, "POWER_COLOR": pcolor,
        "POWER_PILL_BG": ppbg, "POWER_PILL_FG": ppfg, "POWER_PILL_DOT": ppdot, "POWER_PILL_TEXT": pptext,
        "TODAY_KWH": fmt_num(today_kwh, 1), "TODAY_FORECAST": fmt_num(today_forecast, 1),
        "TODAY_DAY_MONTH": f"{today.day:02d}/{today.month:02d}",
        "TODAY_WEATHER": today_weather or "—", "TODAY_WEATHER_EMOJI": today_emoji,
        "MONTH_NAME": MESES_PT[today.month], "MONTH_KWH": fmt_num(month_kwh, 1),
        "MONTH_FORECAST": fmt_num(month_forecast, 1), "MONTH_PERF": fmt_num(desempenho, 1),
        "MONTH_PERF_NOTE": f"{fmt_num(desempenho,0)}% da previsão",
        "PERF_VERDICT": perf_verdict, "AVG_DAILY": fmt_num(avg_daily, 1), "BEST_DAY": best_day,
        "TOTAL_VALUE": total_value, "TOTAL_UNIT": total_unit, "TOTAL_CO2_KG": fmt_num(total_kwh * 0.0817, 0),
        "INSTALL_DATE_SHORT": install_short,
        "DAY_PEAK": peak_str, "DAY_PEAK_TIME": peak_time,
        "INVERTER": inversor,
        "LAST_SYNC": now.strftime("%H:%M:%S") if ok else "sem conexão",
        "HISTORY_NOTE": history_note,
        "MONTHLY_NOTE": f"Total desde a instalação: {fmt_num(total_kwh,1)} kWh",
        "DAY_CURVE_JSON": json.dumps(pts),
        "DAY_MAX_KW": f"{day_max:.2f}",
        "DAY_BARS_JSON": json.dumps(day_bars),
        "MONTH_BARS_JSON": json.dumps(month_bars),
        "LULA_IMG": lula_data_uri(),
    }


def render():
    template = TEMPLATE.read_text(encoding="utf-8")
    try:
        v = build_vars()
    except Exception as e:
        st.error(f"Não consegui montar o painel: {e}")
        st.info("Tente recarregar. A plataforma SolarZ pode estar instável.")
        return
    for k, val in v.items():
        template = template.replace("{{" + k + "}}", str(val))
    components.html(template, height=2360, scrolling=False)


render()
st.markdown("<script>setTimeout(function(){window.location.reload();},60000);</script>", unsafe_allow_html=True)
