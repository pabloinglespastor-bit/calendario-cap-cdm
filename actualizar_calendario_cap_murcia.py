#!/usr/bin/env python3
"""
Genera/actualiza un calendario .ics con los partidos del CAP CIUDAD DE MURCIA
(Primera Autonómica, Grupo Segundo, temporada 2026/2027) según la web de la FFRM.

Cómo funciona:
- Recorre las páginas de "Jornada" de la competición en ffrm.es.
- Busca los partidos donde juega el equipo indicado (por su Codigo_Equipo).
- Extrae rival, condición (local/visitante), fecha, hora y campo.
- Reescribe por completo el fichero .ics cada vez que se ejecuta, así que
  si la FFRM confirma o cambia una fecha/hora/campo, el evento se actualiza
  solo (mismo UID = mismo evento, no se duplica).

Este script en sí NO se ejecuta solo: hay que programarlo (ver instrucciones
al final del mensaje) para que el .ics resultante se mantenga al día.
"""

import re
import sys
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

# ---------------------------------------------------------------------------
# CONFIGURACIÓN — ajustar si algo cambia de una temporada a otra
# ---------------------------------------------------------------------------
BASE_URL = "https://www.ffrm.es"  # revisar en el navegador que sea el dominio correcto
COD_PRIMARIA = "1000120"
COD_COMPETICION = "24118555"   # PRIMERA AUTONOMICA
COD_GRUPO = "24118579"         # GRUPO SEGUNDO
COD_TEMPORADA = "22"           # 2026-2027
NUM_JORNADAS = 30              # nº de jornadas de la competición esta temporada

CODIGO_EQUIPO = "12830157"    # CAP CIUDAD DE MURCIA
NOMBRE_EQUIPO = "CAP Ciudad de Murcia"

DURACION_PARTIDO = timedelta(hours=2)  # duración estimada del evento en el calendario
ARCHIVO_SALIDA = "cap_ciudad_de_murcia.ics"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; calendario-personal/1.0)"
}


def url_jornada(jornada: int) -> str:
    return (
        f"{BASE_URL}/pnfg/NPcd/NFG_CmpJornada?"
        f"cod_primaria={COD_PRIMARIA}&CodCompeticion={COD_COMPETICION}"
        f"&CodGrupo={COD_GRUPO}&CodTemporada={COD_TEMPORADA}&CodJornada={jornada}"
    )


def limpiar_texto(txt: str) -> str:
    return re.sub(r"\s+", " ", txt or "").strip()


def extraer_partidos_equipo(html: str, jornada: int):
    """Devuelve una lista de dicts con los partidos del equipo en esta jornada."""
    soup = BeautifulSoup(html, "html.parser")
    partidos = []

    # Cada partido vive en una tabla propia con este patrón de anchos de columna
    for tabla in soup.find_all("table", width="100%"):
        celdas = tabla.find_all("td", class_="td_widget")
        if len(celdas) != 2:
            continue  # no es una fila de partido reconocible

        celda_local, celda_visitante = celdas
        enlace_local = celda_local.find("a", href=re.compile(r"Codigo_Equipo="))
        enlace_visitante = celda_visitante.find("a", href=re.compile(r"Codigo_Equipo="))
        if not enlace_local or not enlace_visitante:
            continue

        id_local = re.search(r"Codigo_Equipo=(\d+)", enlace_local["href"]).group(1)
        id_visitante = re.search(r"Codigo_Equipo=(\d+)", enlace_visitante["href"]).group(1)

        if CODIGO_EQUIPO not in (id_local, id_visitante):
            continue  # este partido no es del equipo que nos interesa

        es_local = id_local == CODIGO_EQUIPO
        nombre_local = limpiar_texto(enlace_local.get_text())
        nombre_visitante = limpiar_texto(enlace_visitante.get_text())
        rival = nombre_visitante if es_local else nombre_local

        # Fecha y hora: dos <span class="horario"> dentro de la celda central
        horarios = tabla.find_all("span", class_="horario")
        fecha_txt = limpiar_texto(horarios[0].get_text()) if len(horarios) > 0 else ""
        hora_txt = limpiar_texto(horarios[1].get_text()) if len(horarios) > 1 else ""

        # Campo y árbitro: fila siguiente, colspan=9
        campo = ""
        arbitro = ""
        fila_info = tabla.find("td", colspan="9")
        if fila_info:
            enlace_campo = fila_info.find("a", href=re.compile(r"NFG_VisCampos"))
            if enlace_campo:
                campo = limpiar_texto(enlace_campo.get_text())
            texto_info = fila_info.get_text(" ", strip=True)
            m = re.search(r"Árbitro:\s*(.+)$", texto_info)
            if m:
                arbitro = limpiar_texto(m.group(1))

        # UID estable: se basa en la jornada y en los dos equipos, no en fecha/hora,
        # así si la FFRM aplaza el partido el evento se ACTUALIZA en vez de duplicarse
        uid_base = f"ffrm-{COD_COMPETICION}-{COD_GRUPO}-{jornada}-{id_local}-{id_visitante}"

        partidos.append({
            "jornada": jornada,
            "es_local": es_local,
            "local": nombre_local,
            "visitante": nombre_visitante,
            "rival": rival,
            "fecha_txt": fecha_txt,
            "hora_txt": hora_txt,
            "campo": campo,
            "arbitro": arbitro,
            "uid": uid_base,
        })

    return partidos


def parsear_fecha_hora(fecha_txt: str, hora_txt: str):
    """Devuelve un datetime o None si la fecha/hora aún no está confirmada."""
    if not fecha_txt or not hora_txt:
        return None
    try:
        return datetime.strptime(f"{fecha_txt} {hora_txt}", "%d-%m-%Y %H:%M")
    except ValueError:
        return None


def construir_calendario(todos_los_partidos):
    cal = Calendar()
    cal.add("prodid", "-//Calendario CAP Ciudad de Murcia//ffrm.es//ES")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"{NOMBRE_EQUIPO} - Primera Autonómica G2 26/27")

    for p in todos_los_partidos:
        inicio = parsear_fecha_hora(p["fecha_txt"], p["hora_txt"])
        if inicio is None:
            # Partido aún sin fecha/hora confirmada por la FFRM: se omite
            # (volverá a aparecer solo en cuanto la federación la publique)
            continue

        evento = Event()
        evento.add("uid", p["uid"] + "@ffrm-calendar")
        titulo = f"{p['local']} vs {p['visitante']}"
        evento.add("summary", titulo)
        evento.add("dtstart", inicio)
        evento.add("dtend", inicio + DURACION_PARTIDO)
        evento.add("dtstamp", datetime.utcnow())
        if p["campo"]:
            evento.add("location", p["campo"])
        descripcion = f"Jornada {p['jornada']} - Primera Autonómica, Grupo Segundo"
        if p["arbitro"]:
            descripcion += f"\nÁrbitro: {p['arbitro']}"
        evento.add("description", descripcion)
        cal.add_component(evento)

    return cal


def main():
    todos_los_partidos = []
    for jornada in range(1, NUM_JORNADAS + 1):
        url = url_jornada(jornada)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[aviso] No se pudo descargar la jornada {jornada}: {e}", file=sys.stderr)
            continue
        partidos = extraer_partidos_equipo(resp.text, jornada)
        todos_los_partidos.extend(partidos)

    cal = construir_calendario(todos_los_partidos)
    with open(ARCHIVO_SALIDA, "wb") as f:
        f.write(cal.to_ical())

    confirmados = sum(1 for p in todos_los_partidos if parsear_fecha_hora(p["fecha_txt"], p["hora_txt"]))
    print(f"Listo: {confirmados} partidos con fecha/hora confirmada de {len(todos_los_partidos)} encontrados.")
    print(f"Calendario escrito en: {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
