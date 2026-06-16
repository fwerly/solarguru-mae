"""Cliente para a API do SolarZ (app.solarz.com.br).

Plataforma brasileira de monitoramento solar (Solarz Tecnologia LTDA), usada em
white-label pela integradora Efitec. Login simples por email+senha -> token Bearer.

API nao-oficial (engenharia reversa). Endpoints podem mudar sem aviso.
Referencia: github.com/opastorello/SolarZAPI
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None

BASE_URL = "https://app.solarz.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


@dataclass
class Usina:
    id: int
    uuid: str
    nome: str


@dataclass
class DiaGeracao:
    """Geracao de um dia: data ISO, kWh gerado, prognostico, clima."""
    data: str
    kwh: float
    prognostico: float
    clima: str
    desligada: bool = False


class SolarZClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": UA,
        })
        # repete automaticamente em falhas transitorias (5xx, timeout, conexao)
        if Retry is not None:
            retry = Retry(total=3, backoff_factor=0.6,
                          status_forcelist=[429, 500, 502, 503, 504],
                          allowed_methods=["GET", "POST"])
            adapter = HTTPAdapter(max_retries=retry)
            self.s.mount("https://", adapter)
            self.s.mount("http://", adapter)
        self._logged_in = False
        self.usina: Usina | None = None
        self.context: dict[str, Any] = {}

    # ------------------------------------------------------------------ auth
    def login(self) -> None:
        r = self.s.post(
            f"{BASE_URL}/cliente/authenticate",
            json={"username": self.username, "password": self.password},
            timeout=20,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Falha no login SolarZ (HTTP {r.status_code}): {r.text[:200]}")
        data = r.json()
        token = data.get("token")
        if not token:
            raise RuntimeError(f"Login SolarZ sem token na resposta: {data}")
        self.s.headers["Authorization"] = f"Bearer {token}"
        self._logged_in = True
        self._load_context()

    def _ensure(self) -> None:
        if not self._logged_in:
            self.login()

    def _get(self, path: str, params: dict | None = None) -> Any:
        """GET autenticado. Re-loga uma vez se o token expirou. Levanta excecao
        em falha persistente (para NAO cachear erro na camada de cima)."""
        self._ensure()
        r = self.s.get(f"{BASE_URL}{path}", params=params, timeout=25)
        if r.status_code in (401, 403):
            # token expirou — re-loga e tenta de novo
            self._logged_in = False
            self.login()
            r = self.s.get(f"{BASE_URL}{path}", params=params, timeout=25)
        r.raise_for_status()
        return r.json()

    def _load_context(self) -> None:
        r = self.s.get(f"{BASE_URL}/cliente/context", timeout=20)
        if r.status_code != 200:
            return
        ctx = r.json()
        self.context = ctx if isinstance(ctx, dict) else {}
        usinas = self.context.get("usinas", [])
        if usinas:
            u = usinas[0]
            self.usina = Usina(
                id=u.get("id"),
                uuid=u.get("uuid", ""),
                nome=u.get("denominacao") or u.get("nome") or "Usina",
            )

    @property
    def cliente_nome(self) -> str:
        return self.context.get("nome", "") if self.context else ""

    # ------------------------------------------------------------------ dados
    def day(self, date: dt.date) -> dict[str, Any]:
        """Geracao do dia. Retorna dict com: curva {'HH:MM': kW}, total_kwh,
        potencia_atual (kW), prognostico (kWh), inversor (str)."""
        self._ensure()
        if not self.usina:
            return {"curva": {}, "total_kwh": 0.0, "potencia_atual": 0.0, "prognostico": 0.0, "inversor": ""}
        data = self._get(
            "/api-sz/generation/day",
            params={"usinaId": self.usina.id, "day": date.isoformat(), "unitePortals": "true"},
        )

        curva: dict[str, float] = {}
        for d in data.get("dados", []):
            t = d.get("time")
            lv = d.get("labeledValue") or {}
            v = lv.get("value")
            if t is None or v is None:
                continue
            try:
                curva[t] = float(v)
            except (TypeError, ValueError):
                continue
        curva = dict(sorted(curva.items()))

        # potencia atual = ultimo ponto > 0 (ou ultimo ponto)
        potencia_atual = 0.0
        for t in sorted(curva.keys(), reverse=True):
            if curva[t] > 0:
                potencia_atual = curva[t]
                break

        total = float(data.get("totalGerado") or 0)
        prog = 0.0
        prognosticos = data.get("prognosticos") or {}
        if isinstance(prognosticos, dict) and prognosticos:
            try:
                prog = float(next(iter(prognosticos.values())))
            except (TypeError, ValueError, StopIteration):
                prog = 0.0

        # nome do inversor/portal aparece em status ou geracoes
        inversor = ""
        status = data.get("status") or {}
        if isinstance(status, dict) and status:
            first_st = next(iter(status.values()), {})
            inversor = (first_st or {}).get("descricao") or ""

        return {
            "curva": curva,
            "total_kwh": total,
            "potencia_atual": potencia_atual,
            "prognostico": prog,
            "inversor": inversor,
        }

    def period(self, start: dt.date, end: dt.date, period: str = "year") -> dict[str, Any]:
        """Geracao por periodo (pontos diarios). Retorna dict com: dias [DiaGeracao],
        total_kwh, total_prognostico, desempenho (%)."""
        self._ensure()
        if not self.usina:
            return {"dias": [], "total_kwh": 0.0, "total_prognostico": 0.0, "desempenho": 0.0}
        data = self._get(
            "/api-sz/generation/period",
            params={
                "usinaId": self.usina.id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "period": period,
                "uniteMonths": "false",
                "unitePortals": "true",
            },
        )
        dias: list[DiaGeracao] = []
        for d in data.get("dados", []):
            clima = ""
            ic = d.get("informacaoClima") or {}
            if isinstance(ic, dict):
                clima = ic.get("descricao", "") or ""
            try:
                kwh = float(d.get("quantidade") or 0)
            except (TypeError, ValueError):
                kwh = 0.0
            try:
                prog = float(d.get("prognostico") or 0)
            except (TypeError, ValueError):
                prog = 0.0
            dias.append(DiaGeracao(
                data=d.get("data", ""),
                kwh=kwh,
                prognostico=prog,
                clima=clima,
                desligada=bool(d.get("plantShutdown", False)),
            ))
        dias.sort(key=lambda x: x.data)
        # marca do inversor/portal aparece em geracoes[].descricao (ex: "Sungrow API Wanda/Felipe")
        inversor = ""
        for d in data.get("dados", []):
            for g in (d.get("geracoes") or []):
                desc = g.get("descricao", "")
                if desc:
                    # primeira palavra costuma ser a marca/portal
                    inversor = desc.split(" API")[0].split(" ")[0]
                    break
            if inversor:
                break
        return {
            "dias": dias,
            "total_kwh": float(data.get("totalGerado") or 0),
            "total_prognostico": float(data.get("totalPrognostico") or 0),
            "desempenho": float(data.get("desempenho") or 0),
            "inversor": inversor,
        }

    def month_total(self, ref: dt.date | None = None) -> dict[str, Any]:
        ref = ref or dt.date.today()
        return self.period(ref.replace(day=1), ref, period="month")

    def all_time(self, ref: dt.date | None = None) -> dict[str, Any]:
        """Total historico — consulta de uma data bem antiga ate hoje."""
        ref = ref or dt.date.today()
        return self.period(dt.date(2019, 1, 1), ref, period="year")

    def credits(self) -> list[dict[str, Any]]:
        """Credito corrente das unidades (kWh)."""
        self._ensure()
        try:
            r = self.s.get(f"{BASE_URL}/api-sz/app/cliente/unidades/credit", timeout=20)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []
