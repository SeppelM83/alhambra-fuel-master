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
# WICHTIG: Erfordert streamlit-js-eval in der Datei requirements.txt
from streamlit_js_eval import streamlit_js_eval, get_geolocation

# --- 1. KONFIGURATION & SPEICHERUNG ---
# Diese Sektion verwaltet das Gedächtnis der App (API-Keys und letzte Orte)
CONFIG_FILE = "alhambra_v6194_ultra_config.json"

def save_config(d):
    """Speichert die Benutzereinstellungen in einer lokalen JSON-Datei auf dem Server."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f)

def load_config():
    """Lädt gespeicherte Einstellungen, um Tipparbeit bei Neustart zu minimieren."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def format_de(wert, n=2):
    """Wandelt englische Floats in das deutsche Format mit Komma um."""
    if wert is None: return "0,00"
    try:
        fmt = "{:." + str(n) + "f}"
        return fmt.format(float(wert)).replace(".", ",")
    except:
        return "0,00"

# --- 2. TSI PHYSIK & ROUTING ENGINE (Seat Alhambra 7N Spezifikation) ---
class AlhambraTSIMasterMobile:
    def __init__(self):
        # Fahrzeugspezifische Konstanten für Seat Alhambra 2.0 TSI
        self.tank_kapazitaet = 70.0 
        self.leergewicht = 1790    # kg
        self.stirnflaeche = 2.95   # m²
        self.cw_wert = 0.32
        # Dynamischer User-Agent um Blockaden bei Nominatim zu vermeiden
        self.geolocator = Nominatim(user_agent=f"alhambra_tsi_ultra_v6194_{int(time.time())}")

    def berechne_verbrauch(self, dist_m, dauer_s, personen):
        """
        Berechnet den Kraftstoffverbrauch basierend auf physikalischen Lasten.
        F_total = F_luft + F_roll
        Energie = (F_total * Distanz) / Wirkungsgrad
        """
        # Gewicht inkl. Passagiere (80kg pro Person)
        gesamt_gewicht = self.leergewicht + (personen * 80)
        # Durchschnittsgeschwindigkeit in m/s
        v_avg = (dist_m / dauer_s) if dauer_s > 0 else 0
        
        # Wirkungsgrad-Mapping: TSI Motoren sind bei Last effizienter (Lambda 1 Bereich)
        # Wir nehmen 24% für flüssige Fahrt, 18% für Stop-and-Go/Stadt an.
        effizienz = 0.24 if v_avg > 15 else 0.18 
        
        # Widerstandskräfte
        f_luft = 0.5 * 1.225 * (v_avg ** 2) * self.cw_wert * self.stirnflaeche
        f_roll = gesamt_gewicht * 9.81 * 0.015 # 0.015 = Rollwiderstandskoeffizient
        
        # Energiebedarf in Joule (Wattsekunden)
        energie_j = ((f_luft + f_roll) * dist_m) / effizienz
        
        # Umrechnung in Liter Benzin (Brennwert Super: ca. 32,7 MJ pro Liter)
        liter = energie_j / 32.7e6
        
        # Plausibilitäts-Check: Ein Alhambra TSI verbraucht kaum unter 9,5L/100km im Schnitt
        referenz_liter = (dist_m / 1000) * 0.095
        return max(liter, referenz_liter)

    @st.cache_data(show_spinner=False)
    def get_coords_cached(_self, adresse):
        """Geokodierung mit Cache und künstlicher Verzögerung für API-Compliance."""
        if not adresse: return None
        try:
            time.sleep(1.3) # Nominatim Policy: max 1 Request/Sekunde
            loc = _self.geolocator.geocode(adresse, timeout=12)
            if loc:
                return (loc.latitude, loc.longitude)
            return None
        except:
            return None

    def get_route(self, punkte):
        """Abfrage der OSRM Routing Engine für Distanz, Dauer und Polyline-Geometrie."""
        loc_str = ";".join([f"{p[1]},{p[0]}" for p in punkte])
        url = f"http://router.project-osrm.org/route/v1/driving/{loc_str}?overview=full&geometries=polyline"
        try:
            r = requests.get(url, timeout=12).json()
            if r.get('code') == 'Ok':
                return r['routes'][0]
        except:
            return None

# --- 3. UI INITIALISIERUNG ---
st.set_page_config(page_title="Alhambra TSI Master Ultra V6.19.4", layout="wide", page_icon="🚐")
saved_data = load_config()
engine = AlhambraTSIMasterMobile()

# Session State für persistente Ergebnisse während der Interaktion
if 'results' not in st.session_state:
    st.session_state.results = []

# --- 4. SIDEBAR (STEUERZENTRALE) ---
with st.sidebar:
    st.header("⚙️ Konfiguration")
    
    # API-Key Management
    def update_key_callback():
        saved_data["api_key"] = st.session_state.key_input_field
        save_config(saved_data)

    tk_key = st.text_input("Tankerkönig API Key", 
                           value=saved_data.get("api_key", ""), 
                           type="password", 
                           key="key_input_field", 
                           on_change=update_key_callback)
    
    st.divider()
    
    # --- GPS LIVE INTEGRATION ---
    st.subheader("📍 Live GPS-Schnittstelle")
    # Permanente Abfrage des Standorts (lauscht im Hintergrund)
    curr_loc = get_geolocation()
    
    if curr_loc:
        st.success("✅ GPS-Signal empfangen")
        st.caption(f"Präzision: {curr_loc['coords'].get('accuracy', 0):.1f}m")
        if st.button("📍 Standort jetzt übernehmen", use_container_width=True):
            st.session_state.gps_coords = (curr_loc['coords']['latitude'], curr_loc['coords']['longitude'])
            st.rerun()
    else:
        st.info("⌛ Suche GPS-Signal...")
        st.caption("Tipp: Standort am Handy an? Chrome-Berechtigung OK? Maps kurz geöffnet?")
        if st.button("🔄 Signal-Suche erzwingen"):
            st.rerun()

    st.divider()
    
    # --- TSI PARAMETER ---
    st.subheader("Fahrzeug & Strategie")
    ab_aufschlag = st.number_input("Autobahn-Aufschlag (€)", value=0.25, step=0.01, help="Differenz zw. Autobahnstation und lokaler Umgebung")
    max_umweg = st.slider("Max. Zeitumweg (Minuten)", 0, 45, 12)
    tank_stand = st.slider("Aktueller Tankstand (%)", 0, 100, 25)
    sprit_typ = st.selectbox("Benzinsorte", ["Super E5", "Super E10"])
    api_typ = "e5" if sprit_typ == "Super E5" else "e10"
    personen = st.number_input("Personen im Alhambra", 1, 7, 2)
    
    st.markdown("---")
    st.caption("Engine-Status: V6.19.4 Ultra-Full")

# --- 5. HAUPTSEITE ---
st.title("🚐 Alhambra Fuel Master Mobile")
st.info("Optimiertes TSI-Verbrauchsprofil für Langstrecken-Analysen")

c_start, c_ziel = st.columns(2)

# Startpunkt: Bevorzugt GPS-Fix, falls vorhanden
if 'gps_coords' in st.session_state:
    start_input = c_start.text_input("📍 Startpunkt (GPS-Daten fixiert)", 
                                     value=f"{st.session_state.gps_coords[0]}, {st.session_state.gps_coords[1]}")
else:
    start_input = c_start.text_input("📍 Startpunkt (Adresse)", value=saved_data.get("last_start", "Bensheim"))

ziel_input = c_ziel.text_input("🏁 Zielort", value=saved_data.get("last_target", "München"))

# --- 6. CORE ANALYSE ENGINE ---
if st.button("🚀 Tiefen-Analyse der Route starten", use_container_width=True):
    if not tk_key:
        st.error("Bitte Tankerkönig API-Key in der Sidebar eingeben!")
    else:
        with st.status("Alhambra-Engine arbeitet...", expanded=True) as status:
            # 1. Geokodierung
            status.write("🌐 Suche Koordinaten für Start und Ziel...")
            if 'gps_coords' in st.session_state and start_input.startswith(str(st.session_state.gps_coords[0])[:5]):
                s_coords = st.session_state.gps_coords
            else:
                s_coords = engine.get_coords_cached(start_input)
            
            t_coords = engine.get_coords_cached(ziel_input)
            
            if not s_coords or not t_coords:
                st.error("Fehler: Standorte konnten nicht gefunden werden.")
            else:
                # Speichern für nächsten Besuch
                saved_data.update({"last_start": start_input, "last_target": ziel_input, "api_key": tk_key})
                save_config(saved_data)
                
                # 2. Referenzroute (Direktfahrt ohne Tankstopp)
                status.write("🛣️ Berechne TSI-Referenzroute (Direktfahrt)...")
                direkt = engine.get_route([s_coords, t_coords])
                if not direkt:
                    st.error("Routing-Fehler.")
                else:
                    d_zeit, d_dist = direkt['duration'], direkt['distance']
                    d_verbrauch = engine.berechne_verbrauch(d_dist, d_zeit, personen)
                    route_pfad = polyline.decode(direkt['geometry'])
                    
                    # 3. Tankstellen-Umfeld-Analyse
                    status.write("📡 Scanne Preise im Umkreis von 25km...")
                    tk_url = f"https://creativecommons.tankerkoenig.de/json/list.php?lat={s_coords[0]}&lng={s_coords[1]}&rad=25&sort=dist&type={api_typ}&apikey={tk_key}"
                    try:
                        resp = requests.get(tk_url, timeout=12).json()
                        stationen = resp.get("stations", [])
                    except:
                        stationen = []

                    # 4. Dynamische Preisreferenz (Autobahn vs. Umgebung)
                    v_prices = [s['price'] for s in stationen if s.get('price')]
                    ab_ref = (sum(v_prices)/len(v_prices) + ab_aufschlag) if v_prices else 2.25
                    status.write(f"⚖️ Kalkulierter Autobahn-Referenzpreis: **{format_de(ab_ref, 3)} €**")
                    
                    # 5. Filterung & Korridor-Check
                    status.write("🔎 Analysiere Tankstellen auf Routen-Korridor...")
                    treffer = []
                    pfad_korridor = route_pfad[::12] # Jeden 12. Punkt prüfen für Performance
                    pbar = st.progress(0)
                    
                    for i, s in enumerate(stationen):
                        pbar.progress((i+1)/len(stationen))
                        if not s.get('isOpen') or not s.get('price'): continue
                        
                        # Prüfen ob Station nahe der Hauptroute liegt
                        is_near = False
                        for p in pfad_korridor:
                            if math.sqrt((s['lat']-p[0])**2 + (s['lng']-p[1])**2) < 0.11: # ca. 10km Radius
                                is_near = True; break
                        
                        if is_near:
                            # 6. Umweg-Routing & TSI-Verbrauchskorrektur
                            u_route = engine.get_route([s_coords, (s['lat'], s['lng']), t_coords])
                            if u_route:
                                u_min = (u_route['duration'] - d_zeit) / 60
                                if u_min <= max_umweg:
                                    u_verb = engine.berechne_verbrauch(u_route['distance'], u_route['duration'], personen)
                                    liter_menge = 70.0 - ((tank_stand/100)*70)
                                    
                                    # Wirtschaftlichkeitsrechnung
                                    brutto_ersparnis = (ab_ref - s['price']) * liter_menge
                                    mehrkosten_sprit = (u_verb - d_verbrauch) * s['price']
                                    netto_vorteil = brutto_ersparnis - mehrkosten_sprit
                                    
                                    treffer.append({
                                        "Marke": s['brand'], 
                                        "Preis": s['price'], 
                                        "Netto": netto_vorteil,
                                        "Umweg_M": u_min, 
                                        "Umweg_K": (u_route['distance'] - d_dist) / 1000,
                                        "L_Mehr": (u_verb - d_verbrauch), 
                                        "Kosten_T": liter_menge * s['price'],
                                        "lat": s['lat'], "lon": s['lng'], 
                                        "geom": u_route['geometry'], 
                                        "Strasse": s.get('street', 'k.A.')
                                    })
                    
                    # Sortieren nach Netto-Vorteil
                    st.session_state.results = sorted(treffer, key=lambda x: x['Netto'], reverse=True)
                    status.update(label="Analyse erfolgreich abgeschlossen!", state="complete", expanded=False)

# --- 7. DYNAMISCHE ERGEBNIS-ANZEIGE ---
if st.session_state.results:
    res = st.session_state.results
    
    st.subheader("🏁 Tankstellen-Vergleich & Live-Metriken")
    # Das Dropdown steuert alle Metriken und die Karte
    idx = st.selectbox("Wähle eine Station zur Detail-Analyse:", range(len(res)), 
                       format_func=lambda x: f"{x+1}. {res[x]['Marke']} ({format_de(res[x]['Preis'], 3)} €) - Vorteil: {format_de(res[x]['Netto'])} €")
    
    sel = res[idx]

    # Dynamische Hero-Metriken (Reagieren auf 'sel')
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Netto-Vorteil", f"{format_de(sel['Netto'])} €", delta=f"{format_de(sel['Netto'], 2)} €", delta_color="normal")
    m2.metric("TSI Benzinpreis", f"{format_de(sel['Preis'], 3)} €")
    m3.metric("Zeit-Umweg", f"{format_de(sel['Umweg_M'], 1)} Min")
    m4.metric("Mehrverbrauch", f"{format_de(sel['L_Mehr'], 2)} L")
    m5.metric("Gesamtkosten", f"{format_de(sel['Kosten_T'])} €")
    
    st.divider()
    
    col_map, col_info = st.columns([2, 1])
    
    with col_info:
        st.success(f"**Gewählte Station:**\n\n**{sel['Marke']}**\n\n{sel['Strasse']}")
        if idx > 0:
            st.warning(f"💡 Info: Station #1 wäre nochmals {format_de(res[0]['Netto'] - sel['Netto'])} € günstiger.")
        else:
            st.balloons()
            st.info("🏆 Das ist die wirtschaftlichste Option für deinen Alhambra.")

    with col_map:
        # Karten-Visualisierung mit Pydeck
        st.pydeck_chart(pdk.Deck(
            map_style="light", 
            initial_view_state=pdk.ViewState(latitude=sel['lat'], longitude=sel['lon'], zoom=12, pitch=45),
            layers=[
                pdk.Layer("PathLayer", [{"path": [[p[1], p[0]] for p in polyline.decode(sel['geom'])]}], 
                          get_path="path", get_color=[255, 100, 0, 200], width_min_pixels=5),
                pdk.Layer("ScatterplotLayer", [sel], get_position="[lon, lat]", 
                          get_color=[255, 0, 0, 255], get_radius=150, pickable=True)
            ]
        ))
    
    st.divider()
    st.subheader("📋 Vollständige Rangliste (Top Treffer)")
    
    # Tabelle für den schnellen Überblick
    tab_data = []
    for i, r in enumerate(res):
        tab_data.append({
            "Rang": i+1,
            "Marke": r['Marke'],
            "Preis/L": format_de(r['Preis'], 3),
            "Netto-Ersparnis": f"{format_de(r['Netto'])} €",
            "Zeit-Umweg": f"{format_de(r['Umweg_M'], 1)} Min",
            "Mehr-Distanz": f"{format_de(r['Umweg_K'], 1)} km",
            "Tank-Summe": f"{format_de(r['Kosten_T'])} €"
        })
    
    st.table(pd.DataFrame(tab_data).set_index("Rang"))
else:
    st.write("Warte auf Analyse-Start...")
