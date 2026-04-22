import streamlit as st
import requests
import time
import pandas as pd
import polyline
import json
import os
import math
import pydeck as pdk
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from streamlit_js_eval import streamlit_js_eval, get_geolocation

# --- 1. KONFIGURATION & SPEICHERUNG ---
CONFIG_FILE = "alhambra_v6192_mobile_fix_config.json"


def save_config(d):
    """Speichert die Konfiguration in einer lokalen JSON-Datei."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f)


def load_config():
    """Lädt die gespeicherte Konfiguration oder gibt ein leeres Dictionary zurück."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def format_de(wert, n=2):
    """Formatiert Zahlen nach deutschem Standard (Komma statt Punkt)."""
    if wert is None: return "0,00"
    try:
        fmt = "{:." + str(n) + "f}"
        return fmt.format(float(wert)).replace(".", ",")
    except:
        return "0,00"


# --- 2. TSI PHYSIK & ROUTING ENGINE (Seat Alhambra 7N) ---
class AlhambraTSIMasterMobile:
    def __init__(self):
        self.tank_kapazitaet = 70.0
        self.leergewicht = 1790
        self.stirnflaeche = 2.95
        self.cw_wert = 0.32
        # Eindeutiger User-Agent für API-Stabilität
        self.geolocator = Nominatim(user_agent=f"alhambra_tsi_mobile_v6192_{int(time.time())}")

    def berechne_verbrauch(self, dist_m, dauer_s, personen):
        """
        Physikalische Berechnung des TSI-Verbrauchs unter Berücksichtigung
        von Luftwiderstand, Rollwiderstand und Motor-Effizienz.
        """
        gewicht = self.leergewicht + (personen * 80)
        v_avg = (dist_m / dauer_s) if dauer_s > 0 else 0

        # Wirkungsgrad TSI (Benzin) ca. 18-24%
        effizienz = 0.24 if v_avg > 15 else 0.18

        f_luft = 0.5 * 1.225 * (v_avg ** 2) * self.cw_wert * self.stirnflaeche
        f_roll = gewicht * 9.81 * 0.015

        # Energieaufwand in Joule -> Liter Benzin (32,7 MJ/L)
        energie_j = ((f_luft + f_roll) * dist_m) / effizienz
        liter = energie_j / 32.7e6

        # Realitätsnaher Mindestverbrauch für den schweren Alhambra
        return max(liter, (dist_m / 1000) * 0.095)

    @st.cache_data(show_spinner=False)
    def get_coords_cached(_self, adresse):
        if not adresse: return None
        try:
            time.sleep(1.3)  # Einhaltung der Nominatim Usage Policy
            loc = _self.geolocator.geocode(adresse, timeout=12)
            return (loc.latitude, loc.longitude) if loc else None
        except:
            return None

    def get_route(self, punkte):
        """Abfrage der Route über die OSRM API."""
        loc_str = ";".join([f"{p[1]},{p[0]}" for p in punkte])
        url = f"http://router.project-osrm.org/route/v1/driving/{loc_str}?overview=full&geometries=polyline"
        try:
            r = requests.get(url, timeout=12).json()
            if r.get('code') == 'Ok':
                return r['routes'][0]
        except:
            return None


# --- 3. UI SETUP ---
st.set_page_config(page_title="Alhambra TSI Mobile Master", layout="wide", page_icon="🚐")
saved_data = load_config()
engine = AlhambraTSIMasterMobile()

if 'results' not in st.session_state:
    st.session_state.results = []

# --- 4. SIDEBAR (EINSTELLUNGEN) ---
with st.sidebar:
    st.header("⚙️ Mobile Zentrale")


    def update_key_callback():
        saved_data["api_key"] = st.session_state.key_input_field
        save_config(saved_data)


    tk_key = st.text_input("Tankerkönig API Key",
                           value=saved_data.get("api_key", ""),
                           type="password",
                           key="key_input_field",
                           on_change=update_key_callback)

    st.divider()
    st.subheader("📍 Ortung")
    if st.button("🗺️ Aktuellen Standort (GPS)", use_container_width=True):
        loc = get_geolocation()
        if loc:
            st.session_state.gps_coords = (loc['coords']['latitude'], loc['coords']['longitude'])
            st.success("GPS Position fixiert!")
        else:
            st.error("GPS-Signal konnte nicht empfangen werden.")

    st.divider()
    st.subheader("Analyse-Parameter")
    ab_aufschlag = st.number_input("Autobahn-Aufschlag (€)", value=0.25, step=0.01)
    max_umweg = st.slider("Max. Zeitumweg (Min)", 0, 45, 12)
    tank_stand = st.slider("Tankfüllung (%)", 0, 100, 25)
    sprit_typ = st.selectbox("Benzinsorte", ["Super E5", "Super E10"])
    api_typ = "e5" if sprit_typ == "Super E5" else "e10"
    personen = st.number_input("Personen an Bord", 1, 7, 2)

    st.caption("Optimiert für Seat Alhambra TSI")

# --- 5. HAUPTSEITE ---
st.title("🚐 Alhambra Fuel Master Mobile V6.19.2")
st.markdown("---")

c_start, c_ziel = st.columns(2)

# Startpunkt-Logik: Priorisiere GPS-Daten falls vorhanden
if 'gps_coords' in st.session_state:
    start_input = c_start.text_input("📍 Startpunkt (GPS aktiv)",
                                     value=f"{st.session_state.gps_coords[0]}, {st.session_state.gps_coords[1]}")
else:
    start_input = c_start.text_input("📍 Startpunkt", value=saved_data.get("last_start", "Bensheim"))

ziel_input = c_ziel.text_input("🏁 Zielort", value=saved_data.get("last_target", "München"))

# --- 6. BERECHNUNGS-ENGINE ---
if st.button("🚀 Tiefen-Analyse starten", use_container_width=True):
    if not tk_key:
        st.error("Bitte API-Key in der Sidebar eingeben!")
    else:
        with st.status("Alhambra-Engine analysiert Markt & Route...", expanded=True) as status:
            # Geokodierung
            if 'gps_coords' in st.session_state and start_input.startswith(str(st.session_state.gps_coords[0])[:5]):
                s_coords = st.session_state.gps_coords
            else:
                s_coords = engine.get_coords_cached(start_input)

            t_coords = engine.get_coords_cached(ziel_input)

            if s_coords and t_coords:
                saved_data.update({"last_start": start_input, "last_target": ziel_input, "api_key": tk_key})
                save_config(saved_data)

                status.write("🛣️ Berechne TSI-Referenzroute...")
                direkt = engine.get_route([s_coords, t_coords])
                if direkt:
                    d_zeit, d_dist = direkt['duration'], direkt['distance']
                    d_verbrauch = engine.berechne_verbrauch(d_dist, d_zeit, personen)
                    route_pfad = polyline.decode(direkt['geometry'])

                    status.write("📡 Scanne Echtzeit-Preise im Umkreis...")
                    tk_url = f"https://creativecommons.tankerkoenig.de/json/list.php?lat={s_coords[0]}&lng={s_coords[1]}&rad=25&sort=dist&type={api_typ}&apikey={tk_key}"
                    try:
                        resp = requests.get(tk_url, timeout=12).json()
                        stationen = resp.get("stations", [])
                    except:
                        stationen = []

                    # Ermittlung des dynamischen Autobahnpreises
                    v_prices = [s['price'] for s in stationen if s.get('price')]
                    ab_ref = (sum(v_prices) / len(v_prices) + ab_aufschlag) if v_prices else 2.25
                    status.write(f"⚖️ Autobahn-Referenz: **{format_de(ab_ref, 3)} €**")

                    treffer = []
                    pfad_v = route_pfad[::12]
                    pbar = st.progress(0)

                    for i, s in enumerate(stationen):
                        pbar.progress((i + 1) / len(stationen))
                        if not s.get('isOpen') or not s.get('price'): continue

                        is_near = False
                        for p in pfad_v:
                            if math.sqrt((s['lat'] - p[0]) ** 2 + (s['lng'] - p[1]) ** 2) < 0.11:
                                is_near = True;
                                break

                        if is_near:
                            u_route = engine.get_route([s_coords, (s['lat'], s['lng']), t_coords])
                            if u_route:
                                u_min = (u_route['duration'] - d_zeit) / 60
                                if u_min <= max_umweg:
                                    u_verb = engine.berechne_verbrauch(u_route['distance'], u_route['duration'],
                                                                       personen)
                                    l_menge = 70.0 - ((tank_stand / 100) * 70)
                                    brutto = (ab_ref - s['price']) * l_menge
                                    u_kost = (u_verb - d_verbrauch) * s['price']

                                    treffer.append({
                                        "Marke": s['brand'],
                                        "Preis": s['price'],
                                        "Netto": brutto - u_kost,
                                        "Umweg_M": u_min,
                                        "Umweg_K": (u_route['distance'] - d_dist) / 1000,
                                        "L_Mehr": (u_verb - d_verbrauch),
                                        "Kosten_T": l_menge * s['price'],
                                        "lat": s['lat'],
                                        "lon": s['lng'],
                                        "geom": u_route['geometry'],
                                        "Strasse": s.get('street', 'k.A.')
                                    })

                    st.session_state.results = sorted(treffer, key=lambda x: x['Netto'], reverse=True)
                    status.update(label="Analyse komplett abgeschlossen!", state="complete", expanded=False)
                else:
                    st.error("Route konnte nicht berechnet werden.")
            else:
                st.error("Koordinaten konnten nicht ermittelt werden.")

# --- 7. DYNAMISCHE ERGEBNIS-ANZEIGE ---
if st.session_state.results:
    res = st.session_state.results

    st.subheader("🏁 Tankstellen-Auswahl & Live-Daten")
    # Auswahl der Tankstelle steuert alle folgenden Metriken
    idx = st.selectbox("Bitte Station wählen:", range(len(res)),
                       format_func=lambda
                           x: f"{x + 1}. {res[x]['Marke']} ({format_de(res[x]['Preis'], 3)} €) - Ersparnis: {format_de(res[x]['Netto'])} €")

    sel = res[idx]

    # Dynamische Hero-Metriken: Diese passen sich nun der Auswahl 'sel' an
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Netto-Vorteil", f"{format_de(sel['Netto'])} €")
    m2.metric("Preis / L", f"{format_de(sel['Preis'], 3)} €")
    m3.metric("Umweg (Zeit)", f"{format_de(sel['Umweg_M'], 1)} Min")
    m4.metric("Mehrverbrauch", f"{format_de(sel['L_Mehr'], 2)} L")
    m5.metric("Kosten Tankung", f"{format_de(sel['Kosten_T'])} €")

    st.divider()

    col_map, col_info = st.columns([2, 1])

    with col_info:
        st.info(f"**{sel['Marke']}**\n\n{sel['Strasse']}")
        if idx > 0:
            st.warning(f"💡 Platz 1 wäre {format_de(res[0]['Netto'] - sel['Netto'])} € günstiger.")
        else:
            st.success("✅ Beste Wahl für deine Route!")

    with col_map:
        st.pydeck_chart(pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=sel['lat'], longitude=sel['lon'], zoom=13),
            layers=[
                pdk.Layer("PathLayer", [{"path": [[p[1], p[0]] for p in polyline.decode(sel['geom'])]}],
                          get_path="path", get_color=[255, 100, 0, 180], width_min_pixels=5),
                pdk.Layer("ScatterplotLayer", [sel], get_position="[lon, lat]",
                          get_color=[255, 0, 0, 255], get_radius=200)
            ],
            tooltip={"text": "{Marke}\n{Strasse}"}
        ))

    st.divider()
    st.subheader("📋 Komplette Rangliste")

    # Erstellung der Tabelle
    tab_data = []
    for i, r in enumerate(res):
        tab_data.append({
            "Rang": i + 1,
            "Marke": r['Marke'],
            "Preis/L": format_de(r['Preis'], 3),
            "Netto-Vorteil": f"{format_de(r['Netto'])} €",
            "Umweg (Min)": format_de(r['Umweg_M'], 1),
            "Umweg (km)": format_de(r['Umweg_K'], 1),
            "Tank-Kosten": f"{format_de(r['Kosten_T'])} €"
        })

    st.table(pd.DataFrame(tab_data).set_index("Rang"))
