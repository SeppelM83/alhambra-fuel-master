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
# WICHTIG: Die Library streamlit-js-eval muss in der requirements.txt stehen
from streamlit_js_eval import streamlit_js_eval, get_geolocation

# --- 1. DATENMANAGEMENT & KONFIGURATION ---
# Wir nutzen einen eindeutigen Dateinamen für diese Cloud-Version
CONFIG_FILE = "alhambra_tsi_v6195_full_cloud.json"

def save_config(config_data):
    """Speichert Benutzereinstellungen wie den API-Key lokal."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f)

def load_config():
    """Lädt gespeicherte Daten oder gibt ein leeres Template zurück."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def format_de(wert, n=2):
    """Konvertiert Floats in das deutsche Zahlenformat (Komma-Trennung)."""
    if wert is None:
        return "0,00"
    try:
        format_string = "{:." + str(n) + "f}"
        return format_string.format(float(wert)).replace(".", ",")
    except:
        return "0,00"

# --- 2. PHYSIKALISCHE TSI-ENGINE ---
class AlhambraTSIMasterMobile:
    """
    Diese Klasse bildet die Fahrphysik eines Seat Alhambra 7N 2.0 TSI nach.
    Berechnet Luftwiderstand, Rollwiderstand und energetischen Wirkungsgrad.
    """
    def __init__(self):
        # Basis-Konstanten des Fahrzeugs
        self.tank_kapazitaet = 70.0 
        self.leergewicht = 1790    # kg
        self.stirnflaeche = 2.95   # m²
        self.cw_wert = 0.32
        # Dynamischer User-Agent für Cloud-Umgebungen (Nominatim Schutz)
        timestamp = int(time.time())
        self.geolocator = Nominatim(user_agent=f"alhambra_tsi_pro_v6195_{timestamp}")

    def berechne_verbrauch(self, dist_m, dauer_s, personen):
        """
        Physikalische Verbrauchsermittlung (Benzin).
        """
        # Gesamtgewicht inkl. Insassen (ca. 80kg pro Person)
        gesamt_gewicht = self.leergewicht + (personen * 80)
        
        # Durchschnittsgeschwindigkeit in m/s
        v_avg = (dist_m / dauer_s) if dauer_s > 0 else 0
        
        # Wirkungsgrad des TSI-Aggregats (Benzin ca. 18-24%)
        # Bei höheren Lasten/Geschwindigkeiten ist der Wirkungsgrad meist besser
        effizienz = 0.24 if v_avg > 15 else 0.18 
        
        # Berechnung der Widerstandskräfte
        # Luftwiderstand: 0.5 * rho * v² * cw * A
        f_luft = 0.5 * 1.225 * (v_avg ** 2) * self.cw_wert * self.stirnflaeche
        # Rollwiderstand: m * g * Cr
        f_roll = gesamt_gewicht * 9.81 * 0.015
        
        # Benötigte Energie in Joule (Wattsekunden)
        energie_j = ((f_luft + f_roll) * dist_m) / effizienz
        
        # Umrechnung in Liter (Brennwert Super benzin: ca. 32,7 MJ/Liter)
        liter = energie_j / 32.7e6
        
        # Untergrenze (Alhambra TSI verbraucht real selten unter 9,5L/100km)
        mindest_verbrauch = (dist_m / 1000) * 0.095
        
        return max(liter, mindest_verbrauch)

    @st.cache_data(show_spinner=False)
    def get_coords_cached(_self, adresse):
        """Geokodierung mit Timeout-Sicherung für Cloud-Server."""
        if not adresse:
            return None
        try:
            # Nominatim erlaubt nur 1 Request/Sekunde -> Wir warten 1.6s zur Sicherheit
            time.sleep(1.6)
            location = _self.geolocator.geocode(adresse, timeout=15)
            if location:
                return (location.latitude, location.longitude)
            return None
        except Exception as e:
            st.error(f"Geokodierung fehlgeschlagen: {e}")
            return None

    def get_route(self, punkte):
        """Abfrage der OSRM Routing-Engine."""
        # Punkte in Lng,Lat Format umwandeln
        loc_str = ";".join([f"{p[1]},{p[0]}" for p in punkte])
        url = f"http://router.project-osrm.org/route/v1/driving/{loc_str}?overview=full&geometries=polyline"
        try:
            response = requests.get(url, timeout=15)
            data = response.json()
            if data.get('code') == 'Ok':
                return data['routes'][0]
            return None
        except Exception as e:
            st.error(f"Routing-Fehler (OSRM): {e}")
            return None

# --- 3. STREAMLIT UI KONFIGURATION ---
st.set_page_config(
    page_title="Alhambra TSI Fuel Master Pro",
    layout="wide",
    page_icon="🚐"
)

# Initialisierung der Engine und laden gespeicherter Daten
saved_data = load_config()
engine = AlhambraTSIMasterMobile()

# WICHTIG: Session State für Cloud-Stabilität
if 'results' not in st.session_state:
    st.session_state.results = None

# --- 4. SIDEBAR (STEUERUNG) ---
with st.sidebar:
    st.header("⚙️ Zentrale Steuerung")
    
    # API-Key Management
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
    
    # GPS Schnittstelle
    st.subheader("📍 Live-Ortung")
    if st.button("🛰️ GPS-Standort abrufen", use_container_width=True):
        geo_data = get_geolocation()
        if geo_data:
            st.session_state.gps_coords = (
                geo_data['coords']['latitude'], 
                geo_data['coords']['longitude']
            )
            st.success("Standort fixiert!")
        else:
            st.error("Kein Signal. Bitte Berechtigung prüfen.")

    st.divider()
    
    # Parameter
    st.subheader("Fahrzeug-Parameter")
    ab_aufschlag = st.number_input("Autobahn-Aufschlag (€)", value=0.25, step=0.01)
    max_umweg = st.slider("Max. Umweg (Minuten)", 0, 45, 12)
    tank_füllung = st.slider("Aktueller Tank (%)", 0, 100, 25)
    sprit_typ = st.selectbox("Kraftstoff", ["Super E5", "Super E10"])
    api_typ = "e5" if sprit_typ == "Super E5" else "e10"
    anzahl_personen = st.number_input("Personen", 1, 7, 2)
    
    st.markdown("---")
    st.caption("Engine: V6.19.5-ULTRA-FULL")

# --- 5. HAUPTSEITE EINGABE ---
st.title("🚐 Alhambra Fuel Master")
st.info("Präzise Kraftstoff-Analyse für Seat Alhambra 2.0 TSI (7N)")

col_l, col_r = st.columns(2)

# Startpunkt Logik
if 'gps_coords' in st.session_state:
    start_val = f"{st.session_state.gps_coords[0]}, {st.session_state.gps_coords[1]}"
    start_point = col_l.text_input("📍 Startpunkt (GPS aktiv)", value=start_val)
else:
    start_point = col_l.text_input("📍 Startpunkt (Adresse)", value=saved_data.get("last_start", "Bensheim"))

ziel_point = col_r.text_input("🏁 Zielort (Adresse)", value=saved_data.get("last_target", "München"))

# --- 6. CORE CALCULATION ENGINE ---
if st.button("🚀 Tiefen-Analyse starten", use_container_width=True):
    if not tk_key:
        st.error("Fehler: API-Key fehlt in der Sidebar!")
    else:
        with st.status("Alhambra-Engine berechnet...", expanded=True) as status:
            
            # A. Geokodierung
            status.write("🌐 Ermittle Koordinaten...")
            if 'gps_coords' in st.session_state and start_point.startswith(str(st.session_state.gps_coords[0])[:5]):
                s_coords = st.session_state.gps_coords
            else:
                s_coords = engine.get_coords_cached(start_point)
            
            t_coords = engine.get_coords_cached(ziel_point)
            
            if s_coords and t_coords:
                # B. Referenzroute berechnen
                status.write("🛣️ Erstelle Referenzroute (Direktfahrt)...")
                route_direkt = engine.get_route([s_coords, t_coords])
                
                if route_direkt:
                    d_zeit = route_direkt['duration']
                    d_dist = route_direkt['distance']
                    d_verbrauch = engine.berechne_verbrauch(d_dist, d_zeit, anzahl_personen)
                    # Hauptroute dekodieren für Korridor-Check
                    main_path = polyline.decode(route_direkt['geometry'])
                    
                    # C. Tankerkönig API Abfrage
                    status.write("📡 Suche Preise im 25km Umkreis...")
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
                    
                    # D. Wirtschaftlichkeits-Berechnung
                    # Wir ermitteln den Autobahn-Durchschnittspreis als Referenz
                    preise_umgebung = [s['price'] for s in stationen if s.get('price')]
                    if preise_umgebung:
                        avg_umgebung = sum(preise_umgebung) / len(preise_umgebung)
                        ref_preis_autobahn = avg_umgebung + ab_aufschlag
                    else:
                        ref_preis_autobahn = 2.25 # Fallback
                    
                    status.write(f"⚖️ Autobahn-Referenzpreis: {format_de(ref_preis_autobahn, 3)} €")
                    
                    gefundene_treffer = []
                    korridor_punkte = main_path[::12] # Jeden 12. Punkt prüfen
                    fortschritt = st.progress(0)
                    
                    for i, stat in enumerate(stationen):
                        fortschritt.progress((i+1) / len(stationen))
                        if not stat.get('isOpen') or not stat.get('price'):
                            continue
                        
                        # Prüfen, ob die Tankstelle in der Nähe der Route liegt
                        in_korridor = False
                        for p in korridor_punkte:
                            dist_lat_lng = math.sqrt(
                                (stat['lat'] - p[0])**2 + (stat['lng'] - p[1])**2
                            )
                            if dist_lat_lng < 0.11: # ca. 10km
                                in_korridor = True
                                break
                        
                        if in_korridor:
                            # Umweg-Routing berechnen
                            u_route = engine.get_route([s_coords, (stat['lat'], stat['lng']), t_coords])
                            if u_route:
                                u_min = (u_route['duration'] - d_zeit) / 60
                                if u_min <= max_umweg:
                                    # TSI Physik anwenden
                                    u_verb = engine.berechne_verbrauch(u_route['distance'], u_route['duration'], anzahl_personen)
                                    # Zu tankende Menge (70L Tank abzüglich aktuellem Stand)
                                    liter_zu_tanken = 70.0 * (1 - (tank_füllung/100))
                                    
                                    # Kostenrechnung
                                    ersparnis_brutto = (ref_preis_autobahn - stat['price']) * liter_zu_tanken
                                    kosten_umweg = (u_verb - d_verbrauch) * stat['price']
                                    vorteil_netto = ersparnis_brutto - kosten_umweg
                                    
                                    gefundene_treffer.append({
                                        "Marke": stat['brand'],
                                        "Preis": stat['price'],
                                        "Netto": vorteil_netto,
                                        "Umweg_M": u_min,
                                        "Umweg_K": (u_route['distance'] - d_dist) / 1000,
                                        "L_Mehr": (u_verb - d_verbrauch),
                                        "Kosten_T": liter_zu_tanken * stat['price'],
                                        "lat": stat['lat'],
                                        "lon": stat['lng'],
                                        "geom": u_route['geometry'],
                                        "Strasse": stat.get('street', 'k.A.')
                                    })
                    
                    # Ergebnisse sortieren und sichern
                    st.session_state.results = sorted(gefundene_treffer, key=lambda x: x['Netto'], reverse=True)
                    
                    # Config Update
                    saved_data.update({"last_start": start_point, "last_target": ziel_point})
                    save_config(saved_data)
                    
                    status.update(label="Analyse erfolgreich!", state="complete", expanded=False)
                    # WICHTIG: Rerun erzwingen um Session State Anzeige zu aktualisieren
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Route konnte nicht berechnet werden.")
            else:
                st.error("Koordinaten konnten nicht gefunden werden.")

# --- 7. ERGEBNIS-ANZEIGE ---
if st.session_state.results is not None:
    all_res = st.session_state.results
    if not all_res:
        st.warning("Keine Stationen innerhalb der Umweg-Parameter gefunden.")
    else:
        st.subheader("🏁 Tank-Empfehlungen")
        
        # Dropdown zur Auswahl der Station
        station_labels = [f"{i+1}. {r['Marke']} ({format_de(r['Preis'], 3)} €)" for i, r in enumerate(all_res)]
        auswahl_idx = st.selectbox("Station im Detail anzeigen:", range(len(all_res)), format_func=lambda x: station_labels[x])
        
        station_sel = all_res[auswahl_idx]
        
        # Dashboard-Metriken
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Netto-Vorteil", f"{format_de(station_sel['Netto'])} €")
        m2.metric("Preis pro Liter", f"{format_de(station_sel['Preis'], 3)} €")
        m3.metric("Zeit-Umweg", f"{format_de(station_sel['Umweg_M'], 1)} Min")
        m4.metric("Mehrverbrauch", f"{format_de(station_sel['L_Mehr'], 2)} L")
        m5.metric("Gesamtpreis", f"{format_de(station_sel['Kosten_T'])} €")
        
        st.divider()
        
        # Karte und Info
        c_map, c_text = st.columns([2, 1])
        with c_text:
            st.success(f"**Station:** {station_sel['Marke']}\n\n**Adresse:** {station_sel['Strasse']}")
            st.info("Die Route zeigt die Anfahrt inklusive Umweg zum Ziel.")
        
        with c_map:
            # Pydeck Visualisierung
            st.pydeck_chart(pdk.Deck(
                map_style="light",
                initial_view_state=pdk.ViewState(
                    latitude=station_sel['lat'], 
                    longitude=station_sel['lon'], 
                    zoom=13,
                    pitch=45
                ),
                layers=[
                    pdk.Layer(
                        "PathLayer", 
                        [{"path": [[p[1], p[0]] for p in polyline.decode(station_sel['geom'])]}],
                        get_path="path", 
                        get_color=[255, 100, 0, 180], 
                        width_min_pixels=5
                    ),
                    pdk.Layer(
                        "ScatterplotLayer", 
                        [station_sel], 
                        get_position="[lon, lat]", 
                        get_color=[255, 0, 0, 255], 
                        get_radius=200
                    )
                ]
            ))
        
        # Rangliste
        st.subheader("📋 Alle Treffer im Überblick")
        liste_final = []
        for i, r in enumerate(all_res):
            liste_final.append({
                "Rang": i+1,
                "Marke": r['Marke'],
                "Preis (€)": format_de(r['Preis'], 3),
                "Ersparnis (€)": format_de(r['Netto']),
                "Umweg (Min)": format_de(r['Umweg_M'], 1),
                "Tanksumme (€)": format_de(r['Kosten_T'])
            })
        st.table(pd.DataFrame(liste_final).set_index("Rang"))

else:
    st.write("Bereit für die Analyse. Bitte oben auf 'Analyse starten' klicken.")
