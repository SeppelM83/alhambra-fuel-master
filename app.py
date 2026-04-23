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
# WICHTIG: Die Library streamlit-js-eval muss zwingend in der requirements.txt stehen
from streamlit_js_eval import streamlit_js_eval, get_geolocation

# --- 1. DATENMANAGEMENT & KONFIGURATION ---
# Eindeutiger Dateiname für diese Version zur Vermeidung von Cache-Konflikten
CONFIG_FILE = "alhambra_tsi_v6197_gps_fix_full.json"

def save_config(config_data):
    """Speichert Benutzereinstellungen wie den API-Key lokal auf der Instanz."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f)

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
    """Formatiert Zahlenwerte nach deutschem Standard (Komma statt Punkt)."""
    if wert is None:
        return "0,00"
    try:
        format_string = "{:." + str(n) + "f}"
        return format_string.format(float(wert)).replace(".", ",")
    except:
        return "0,00"

# --- 2. PHYSIKALISCHE TSI-ENGINE (Seat Alhambra 7N Spezifikation) ---
class AlhambraTSIMasterMobile:
    """
    Diese Klasse bildet die Fahrphysik eines Seat Alhambra 2.0 TSI nach.
    Berechnet Luftwiderstand, Rollwiderstand und energetischen Wirkungsgrad.
    """
    def __init__(self):
        # Fahrzeugspezifische Konstanten
        self.tank_kapazitaet = 70.0 
        self.leergewicht = 1790    # kg
        self.stirnflaeche = 2.95   # m²
        self.cw_wert = 0.32
        # Dynamischer User-Agent für Cloud-Umgebungen zur Vermeidung von IP-Sperren
        timestamp_id = int(time.time())
        self.geolocator = Nominatim(user_agent=f"alhambra_tsi_enforcer_v6197_{timestamp_id}")

    def berechne_verbrauch(self, dist_m, dauer_s, personen):
        """
        Physikalische Verbrauchsermittlung basierend auf Lastzuständen.
        """
        # Gesamtgewicht inkl. Insassen (ca. 80kg pro Person inkl. Gepäck)
        gesamt_gewicht = self.leergewicht + (personen * 80)
        
        # Durchschnittsgeschwindigkeit in m/s ermitteln
        v_avg = (dist_m / dauer_s) if dauer_s > 0 else 0
        
        # Wirkungsgrad des TSI-Aggregats (Benzinmotor-Kennfeld-Vereinfachung)
        effizienz = 0.24 if v_avg > 15 else 0.18 
        
        # Berechnung der Widerstände: Luft- und Rollwiderstand
        f_luft = 0.5 * 1.225 * (v_avg ** 2) * self.cw_wert * self.stirnflaeche
        f_roll = gesamt_gewicht * 9.81 * 0.015
        
        # Energetischer Gesamtaufwand in Joule
        energie_j = ((f_luft + f_roll) * dist_m) / effizienz
        
        # Umrechnung von Joule in Liter (Brennwert Super: ca. 32,7 MJ/L)
        liter = energie_j / 32.7e6
        
        # Realistischer Mindestverbrauch für den Alhambra (9.5L/100km Referenz)
        mindest_v = (dist_m / 1000) * 0.095
        
        return max(liter, mindest_v)

    @st.cache_data(show_spinner=False)
    def get_coords_cached(_self, adresse):
        """Geokodierung mit künstlicher Verzögerung für API-Compliance."""
        if not adresse:
            return None
        try:
            # Nominatim Policy: Max 1 Request/Sekunde
            time.sleep(1.6)
            location = _self.geolocator.geocode(adresse, timeout=15)
            if location:
                return (location.latitude, location.longitude)
            return None
        except Exception as e:
            st.error(f"📍 Geokodierungs-Fehler: {e}")
            return None

    def get_route(self, punkte):
        """Abfrage der OSRM Routing Engine für Fahrzeit und Distanz."""
        # Koordinaten für OSRM im Format Lng,Lat zusammenfügen
        loc_str = ";".join([f"{p[1]},{p[0]}" for p in punkte])
        url = f"http://router.project-osrm.org/route/v1/driving/{loc_str}?overview=full&geometries=polyline"
        try:
            response = requests.get(url, timeout=15)
            data = response.json()
            if data.get('code') == 'Ok':
                return data['routes'][0]
            return None
        except Exception as e:
            st.error(f"🛣️ Routing-Verbindungsfehler: {e}")
            return None

# --- 3. STREAMLIT UI SETUP ---
st.set_page_config(
    page_title="Alhambra TSI Pro V6.19.7",
    layout="wide",
    page_icon="🚐"
)

# Initialisierung
saved_data = load_config()
engine = AlhambraTSIMasterMobile()

# Persistenz des Session States für Cloud-Deployment
if 'results' not in st.session_state:
    st.session_state.results = None

# --- 4. SIDEBAR (GPS-ENFORCER & PARAMETER) ---
with st.sidebar:
    st.header("⚙️ System-Steuerung")
    
    # API-Key Management mit Callback
    def on_key_change():
        saved_data["api_key"] = st.session_state.api_key_input
        save_config(saved_data)

    tk_key = st.text_input(
        "Tankerkönig API Key", 
        value=saved_data.get("api_key", ""), 
        type="password", 
        key="api_key_input", 
        on_change=on_key_change
    )
    
    st.divider()
    
    # --- GPS FIX SEKTION ---
    st.subheader("📍 Standort-Ermittlung")
    
    current_loc = get_geolocation()
    
    if current_loc:
        st.success("✅ GPS-Signal aktiv")
        lat_found = current_loc['coords']['latitude']
        lon_found = current_loc['coords']['longitude']
        st.caption(f"Aktuelle Pos: {lat_found:.4f}, {lon_found:.4f}")
        
        if st.button("📍 Standort als Startpunkt setzen", use_container_width=True):
            st.session_state.gps_coords = (lat_found, lon_found)
            st.rerun()
    else:
        st.warning("⚠️ GPS wird gesucht...")
        st.info("Falls blockiert: 'Standort' im Browser freigeben und Seite neu laden.")
        if st.button("🔄 GPS-Suche erneuern"):
            st.rerun()

    st.divider()
    
    # Berechnungsparameter
    st.subheader("Analyse-Parameter")
    ab_aufschlag = st.number_input("Autobahn-Aufschlag (€)", value=0.25, step=0.01)
    
    # Konfiguration gemäß Vorgabe: 0-15 Min, Standard 5 Min
    max_umweg = st.slider("Max. Umweg (Minuten)", 0, 15, 5)
    
    tank_füllung = st.slider("Aktueller Tankstand (%)", 0, 100, 25)
    sprit_typ = st.selectbox("Kraftstoff-Sorte", ["Super E5", "Super E10"])
    api_typ = "e5" if sprit_typ == "Super E5" else "e10"
    personen_anzahl = st.number_input("Personen an Bord", 1, 7, 2)
    
    st.markdown("---")
    st.caption("Engine: V6.19.7-FULL-GPS")

# --- 5. HAUPTSEITE EINGABE ---
st.title("🚐 Alhambra Fuel Master Mobile")
st.markdown("---")

col_start, col_ziel = st.columns(2)

# Startpunkt Logik (GPS Priorisierung)
if 'gps_coords' in st.session_state:
    gps_val = f"{st.session_state.gps_coords[0]}, {st.session_state.gps_coords[1]}"
    start_point = col_start.text_input("📍 Startpunkt (GPS-Modus)", value=gps_val)
else:
    start_point = col_start.text_input("📍 Startpunkt (Adresse)", value=saved_data.get("last_start", "Bensheim"))

ziel_point = col_ziel.text_input("🏁 Zielort (Adresse)", value=saved_data.get("last_target", "München"))

# --- 6. CORE CALCULATION ENGINE ---
if st.button("🚀 Tiefen-Analyse starten", use_container_width=True):
    if not tk_key:
        st.error("Fehler: Bitte Tankerkönig API-Key in der Sidebar eintragen!")
    else:
        with st.status("Alhambra-Engine berechnet...", expanded=True) as status:
            
            # A. Geokodierung der Punkte
            status.write("🌐 Koordinaten werden aufgelöst...")
            if 'gps_coords' in st.session_state and start_point.startswith(str(st.session_state.gps_coords[0])[:5]):
                s_coords = st.session_state.gps_coords
            else:
                s_coords = engine.get_coords_cached(start_point)
            
            t_coords = engine.get_coords_cached(ziel_point)
            
            if s_coords and t_coords:
                # B. Referenzroute (Direktfahrt)
                status.write("🛣️ Berechne TSI-Referenzroute...")
                route_direkt = engine.get_route([s_coords, t_coords])
                
                if route_direkt:
                    d_zeit = route_direkt['duration']
                    d_dist = route_direkt['distance']
                    d_verbrauch_ref = engine.berechne_verbrauch(d_dist, d_zeit, personen_anzahl)
                    path_poly = polyline.decode(route_direkt['geometry'])
                    
                    # C. Preis-Scan über Tankerkönig
                    status.write("📡 Scanne Echtzeit-Preise im Umkreis...")
                    tk_url = (
                        f"https://creativecommons.tankerkoenig.de/json/list.php?"
                        f"lat={s_coords[0]}&lng={s_coords[1]}&rad=25&sort=dist"
                        f"&type={api_typ}&apikey={tk_key}"
                    )
                    
                    try:
                        resp = requests.get(tk_url, timeout=15).json()
                        stationen = resp.get("stations", [])
                    except:
                        stationen = []
                    
                    # Ermittlung der Preis-Benchmarks
                    preise_umkreis = [s['price'] for s in stationen if s.get('price')]
                    ref_preis_ab = (sum(preise_umkreis)/len(preise_umkreis) + ab_aufschlag) if preise_umkreis else 2.25
                    
                    status.write(f"⚖️ Analyse läuft (Autobahn-Ref: {format_de(ref_preis_ab, 3)} €)...")
                    
                    ergebnisse = []
                    korridor_check = path_poly[::12] # Stichproben alle ~10km
                    p_bar = st.progress(0)
                    
                    # D. Umweg-Wirtschaftlichkeits-Check
                    for idx_s, stat in enumerate(stationen):
                        p_bar.progress((idx_s + 1) / len(stationen))
                        if not stat.get('isOpen') or not stat.get('price'):
                            continue
                        
                        # Liegt die Station grob auf dem Weg?
                        is_near_route = any(
                            math.sqrt((stat['lat'] - p[0])**2 + (stat['lng'] - p[1])**2) < 0.11 
                            for p in korridor_check
                        )
                        
                        if is_near_route:
                            # Präzises Routing über die Station
                            u_route = engine.get_route([s_coords, (stat['lat'], stat['lng']), t_coords])
                            if u_route:
                                u_min_delta = (u_route['duration'] - d_zeit) / 60
                                if u_min_delta <= max_umweg:
                                    # TSI Physik für die Umweg-Route
                                    u_verbrauch = engine.berechne_verbrauch(u_route['distance'], u_route['duration'], personen_anzahl)
                                    # Tankmenge berechnen
                                    liter_menge = 70.0 * (1 - (tank_füllung / 100))
                                    
                                    # Wirtschaftlicher Vorteil
                                    ersparnis_preis = (ref_preis_ab - stat['price']) * liter_menge
                                    mehrkosten_sprit = (u_verbrauch - d_verbrauch_ref) * stat['price']
                                    netto_vorteil = ersparnis_preis - mehrkosten_sprit
                                    
                                    ergebnisse.append({
                                        "Marke": stat['brand'], 
                                        "Preis": stat['price'], 
                                        "Netto": netto_vorteil,
                                        "Umweg_M": u_min_delta, 
                                        "Umweg_K": (u_route['distance'] - d_dist) / 1000,
                                        "L_Mehr": (u_verbrauch - d_verbrauch_ref), 
                                        "Kosten_T": liter_menge * stat['price'],
                                        "lat": stat['lat'], "lon": stat['lng'], 
                                        "geom": u_route['geometry'], "Strasse": stat.get('street', 'k.A.')
                                    })
                    
                    # Resultate sichern und Rerun triggern für UI-Update
                    st.session_state.results = sorted(ergebnisse, key=lambda x: x['Netto'], reverse=True)
                    saved_data.update({"last_start": start_point, "last_target": ziel_point})
                    save_config(saved_data)
                    
                    status.update(label="Analyse abgeschlossen!", state="complete", expanded=False)
                    st.rerun()
                else:
                    st.error("Routing-Fehler (OSRM antwortet nicht korrekt).")
            else:
                st.error("Geokodierung fehlgeschlagen. Bitte Adressen prüfen.")

# --- 7. ERGEBNIS-PRÄSENTATION ---
if st.session_state.results is not None:
    res_list = st.session_state.results
    if not res_list:
        st.warning("Keine passenden Stationen gefunden.")
    else:
        st.subheader("🏁 Tankstellen-Empfehlungen")
        
        # Selektor für die Detailansicht
        select_labels = [f"{i+1}. {r['Marke']} ({format_de(r['Preis'], 3)} €) - Vorteil: {format_de(r['Netto'])} €" for i, r in enumerate(res_list)]
        final_idx = st.selectbox("Detail-Ansicht wählen:", range(len(res_list)), format_func=lambda x: select_labels[x])
        
        sel_station = res_list[final_idx]
        
        # Metriken Dashboard
        met1, met2, met3, met4, met5 = st.columns(5)
        met1.metric("Netto-Vorteil", f"{format_de(sel_station['Netto'])} €")
        met2.metric("Preis / L", f"{format_de(sel_station['Preis'], 3)} €")
        met3.metric("Umweg (Zeit)", f"{format_de(sel_station['Umweg_M'], 1)} Min")
        met4.metric("Mehrverbrauch", f"{format_de(sel_station['L_Mehr'], 2)} L")
        met5.metric("Gesamtkosten", f"{format_de(sel_station['Kosten_T'])} €")
        
        st.divider()
        
        # Karte und Standort-Info
        map_col, text_col = st.columns([2, 1])
        with text_col:
            st.success(f"**Gewählte Station:**\n{sel_station['Marke']}\n\n{sel_station['Strasse']}")
            if final_idx > 0:
                diff = res_list[0]['Netto'] - sel_station['Netto']
                st.warning(f"💡 Platz 1 ist {format_de(diff)} € lukrativer.")

        with map_col:
            st.pydeck_chart(pdk.Deck(
                map_style="light",
                initial_view_state=pdk.ViewState(latitude=sel_station['lat'], longitude=sel_station['lon'], zoom=13),
                layers=[
                    pdk.Layer("PathLayer", [{"path": [[p[1], p[0]] for p in polyline.decode(sel_station['geom'])]}], get_path="path", get_color=[255, 100, 0, 180], width_min_pixels=5),
                    pdk.Layer("ScatterplotLayer", [sel_station], get_position="[lon, lat]", get_color=[255, 0, 0, 255], get_radius=200)
                ]
            ))
        
        # Tabellarische Übersicht
        st.subheader("📋 Gesamtranking")
        table_final = []
        for i, r in enumerate(res_list):
            table_final.append({
                "Rang": i+1, "Marke": r['Marke'], 
                "Preis (€)": format_de(r['Preis'], 3), 
                "Vorteil (€)": format_de(r['Netto']), 
                "Umweg (Min)": format_de(r['Umweg_M'], 1)
            })
        st.table(pd.DataFrame(table_final).set_index("Rang"))
else:
    st.write("Warte auf Eingabe der Route und Analyse-Start...")
