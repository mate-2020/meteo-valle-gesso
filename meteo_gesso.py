#!/usr/bin/env python3
"""
METEO MULTIMODELLO - STAZIONI ARPA VALLE GESSO (AUTOMATED VERSION)
Versione: 10.2 - Automazione GitHub Actions + esecuzioni manuali
Modelli: ECMWF IFS, ICON-D2, AROME France HD
Fonte: Open-Meteo API (gratuita, senza chiave)
OUTPUT: cartella YYYY_MM_DD/nome_report_YYYYMMDD_HHMMSS.{txt,json}
Coordinate: convertite da UTM Zona 32N a WGS84
"""

import requests
import json
import os
import sys
import argparse
from datetime import datetime
from typing import Dict, Optional, List

# ============================================================
#  CONFIGURAZIONE — STAZIONI ARPA VALLE GESSO
# ============================================================

LOCATIONS = {
    "1": ("Valdieri (Terme)",     {"lat": 44.2047, "lon": 7.2681}, 1390),
    "2": ("Diga La Piastra",       {"lat": 44.2250, "lon": 7.3894},  950),
    "3": ("Diga del Chiotas",      {"lat": 44.1600, "lon": 7.3329}, 2020),
    "4": ("Andonno Gesso",         {"lat": 44.2888, "lon": 7.4366},  712),
    "5": ("Palanfrè",              {"lat": 44.1901, "lon": 7.4886}, 1625),
}

DETERMINISTIC_MODELS = {
    "ECMWF":   "ecmwf_ifs025",
    "ICON-D2": "icon_d2",
    "AROME":   "meteofrance_arome_france_hd",
}

BASE_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_VARS = "temperature_2m,wind_speed_10m,precipitation"
HOURLY_VARS  = "temperature_2m,precipitation,rain,wind_speed_10m"
DAILY_VARS   = "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum"

# ============================================================
#  SELEZIONE LOCALITÀ
# ============================================================

def select_locations(interactive: bool, selection_arg: str = None) -> Dict[str, dict]:
    """
    Restituisce le stazioni selezionate.
    
    Se interactive=True: mostra menu e attende input utente
    Se interactive=False: restituisce tutte le stazioni
    Se selection_arg: filtra per numeri specifici (es. "1,3,5")
    """
    print()
    print("=" * 78)
    print("  SELEZIONE STAZIONI ARPA — VALLE GESSO")
    print("=" * 78)
    print()
    for key, (name, coords, quota) in LOCATIONS.items():
        print(f"    {key}. {name:<22} ({coords['lat']:.4f}°N, {coords['lon']:.4f}°E) {quota:>5} m")
    print()
    print("    0. TUTTE le stazioni")
    print()

    if not interactive:
        # Modalità automatica: usa tutte le stazioni
        selected = {name: coords for _, (name, coords, _) in LOCATIONS.items()}
        print(f"[AUTO] Selezionate tutte le {len(selected)} stazioni.")
        return selected

    # Modalità interattiva con possibile selezione da arg
    if selection_arg:
        choice = selection_arg
        print(f"[CLI] Scelta da riga comandi: {choice}")
    else:
        print("  Inserisci i numeri separati da virgola (es: 1,3,5)")
        print("  oppure '0' per selezionarle tutte.")
        print("  Premi Invio senza digitare nulla = tutte le stazioni.")
        print()
        choice = input("  Scelta: ").strip()

    if choice == "" or choice == "0":
        selected = {name: coords for _, (name, coords, _) in LOCATIONS.items()}
        print(f"\n  Selezionate TUTTE le {len(selected)} stazioni.")
        return selected

    tokens = [t.strip() for t in choice.split(",")]
    invalid = [t for t in tokens if t not in LOCATIONS]

    if invalid:
        print(f"  Input non valido: {invalid}")
        print(f"  Usa numeri da 1 a 5 separati da virgola, oppure 0.")
        return {}

    selected = {}
    for token in tokens:
        name, coords, _ = LOCATIONS[token]
        selected[name] = coords

    print(f"\n  Selezionate {len(selected)} stazioni:")
    for i, name in enumerate(selected, 1):
        print(f"    {i}. {name}")

    confirm = input(f"\n  Confermi? (s/n, default=s): ").strip().lower()
    if confirm == "" or confirm == "s" or confirm == "si":
        return selected
    else:
        print("  Selezione annullata. Uscita.")
        return {}

# ============================================================
#  SETUP CARTELLA GIORNALIERA
# ============================================================

def setup_daily_folder():
    today_str = datetime.now().strftime("%Y_%m_%d")
    folder_path = today_str

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"\n[INFO] Cartella creata: {folder_path}/")
    else:
        print(f"\n[INFO] Cartella esistente: {folder_path}/")

    return folder_path

# ============================================================
#  UTILITY
# ============================================================

def safe_float(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def safe_round(value, decimals=1):
    f = safe_float(value, None)
    if f is None:
        return None
    return round(f, decimals)

def calculate_spread(values):
    clean = [v for v in values if v is not None]
    if len(clean) < 1:
        return {"mean": None, "spread": 0, "min": None, "max": None, "count": 0}
    if len(clean) < 2:
        return {"mean": safe_round(clean[0]), "spread": 0, "min": safe_round(clean[0]),
                "max": safe_round(clean[0]), "count": len(clean)}
    return {
        "mean": safe_round(sum(clean) / len(clean)),
        "spread": safe_round(max(clean) - min(clean)),
        "min": safe_round(min(clean)),
        "max": safe_round(max(clean)),
        "count": len(clean)
    }

# ============================================================
#  FETCH DETERMINISTICO
# ============================================================

def fetch_det_model(model_label: str, model_id: str, lat: float, lon: float) -> Optional[Dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": CURRENT_VARS,
        "hourly": HOURLY_VARS,
        "daily": DAILY_VARS,
        "timezone": "Europe/Rome",
        "forecast_days": 3,
        "models": model_id,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None

def extract_det_metrics(data) -> Optional[Dict]:
    if not data:
        return None

    current = data.get("current", {})
    daily = data.get("daily", {})

    fcst_temp_now = safe_round(current.get("temperature_2m"))
    fcst_wind_now = safe_round(current.get("wind_speed_10m"))
    fcst_precip_now = safe_round(current.get("precipitation"))

    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    precip_sum = daily.get("precipitation_sum", [])

    fcst_temp_max_today = safe_round(t_max[0]) if len(t_max) > 0 else None
    fcst_temp_min_today = safe_round(t_min[0]) if len(t_min) > 0 else None
    fcst_precip_today = safe_round(precip_sum[0]) if len(precip_sum) > 0 else None
    fcst_precip_tomorrow = safe_round(precip_sum[1]) if len(precip_sum) > 1 else None

    return {
        "fcst_temp_now": fcst_temp_now,
        "fcst_wind_now": fcst_wind_now,
        "fcst_precip_now": fcst_precip_now,
        "fcst_temp_max_today": fcst_temp_max_today,
        "fcst_temp_min_today": fcst_temp_min_today,
        "fcst_precip_today": fcst_precip_today,
        "fcst_precip_tomorrow": fcst_precip_tomorrow,
    }

# ============================================================
#  SPREAD TRA MODELLI
# ============================================================

def compute_model_spread(det_results: Dict) -> Dict:
    temps_today = []
    precips_today = []

    for label, m in det_results.items():
        if m:
            if m.get("fcst_temp_max_today") is not None:
                temps_today.append(m["fcst_temp_max_today"])
            if m.get("fcst_precip_today") is not None:
                precips_today.append(m["fcst_precip_today"])

    temp_spread = calculate_spread(temps_today)
    precip_spread = calculate_spread(precips_today)

    ts = temp_spread["spread"] or 0
    ps = precip_spread["spread"] or 0

    if ts < 3 and ps < 5:
        confidence = "ALTA"
        marker = "[ + ]"
    elif ts < 6 and ps < 15:
        confidence = "MEDIA"
        marker = "[ ~ ]"
    else:
        confidence = "BASSA"
        marker = "[ ! ]"

    return {
        "temp_spread": temp_spread,
        "precip_spread": precip_spread,
        "confidence": confidence,
        "marker": marker,
    }

# ============================================================
#  GENERAZIONE REPORT
# ============================================================

def fmt(val, suffix="", width=8):
    if val is None:
        return f"{'--':>{width}}"
    s = f"{val}{suffix}"
    return f"{s:>{width}}"

def generate_report(loc_name, coords, det_results, spread):
    L = []
    L.append("")
    L.append("=" * 78)
    L.append(f"  {loc_name.upper()} — {coords['lat']:.4f}°N, {coords['lon']:.4f}°E")
    L.append("=" * 78)
    L.append("")

    L.append("  MODELLI DETERMINISTICI (PREVISIONI, non osservazioni)")
    L.append("-" * 78)
    L.append(f"  {'Modello':<10} {'T ora':>7} {'Vento':>7} {'Pioggia':>8} {'Precip':>8} {'Precip':>8} {'T max':>7} {'T min':>7}")
    L.append(f"  {'':<10} {'(°C)':>7} {'(km/h)':>7} {'ora(mm)':>8} {'oggi(mm)':>8} {'domani':>8} {'oggi':>7} {'oggi':>7}")
    L.append("-" * 78)

    for label in DETERMINISTIC_MODELS:
        m = det_results.get(label)
        if not m:
            L.append(f"  {label:<10}  {'--':>6}  {'--':>6}  {'--':>7}  {'--':>7}  {'--':>7}  {'--':>6}  {'--':>6}")
            continue
        L.append(
            f"  {label:<10} "
            f"{fmt(m.get('fcst_temp_now'), '°C'):>7} "
            f"{fmt(m.get('fcst_wind_now')):>7} "
            f"{fmt(m.get('fcst_precip_now')):>8} "
            f"{fmt(m.get('fcst_precip_today')):>8} "
            f"{fmt(m.get('fcst_precip_tomorrow')):>8} "
            f"{fmt(m.get('fcst_temp_max_today'), '°C'):>7} "
            f"{fmt(m.get('fcst_temp_min_today'), '°C'):>7}"
        )
    L.append("-" * 78)
    L.append("")

    ts = spread["temp_spread"]
    ps = spread["precip_spread"]

    L.append("  SPREAD TRA MODELLI (divergenza)")
    L.append("-" * 78)
    L.append(f"  Temperatura max oggi:")
    L.append(f"    Media:  {fmt(ts.get('mean'), '°C')}")
    L.append(f"    Spread: {fmt(ts.get('spread'), '°C')}")
    L.append("")
    L.append(f"  Precipitazione oggi:")
    L.append(f"    Media:  {fmt(ps.get('mean'), 'mm')}")
    L.append(f"    Spread: {fmt(ps.get('spread'), 'mm')}")
    L.append("")

    L.append(f"  {spread['marker']} AFFIDABILITÀ: {spread['confidence']}")
    if spread["confidence"] == "BASSA":
        L.append(f"      Modelli discordanti — previsione incerta")
    elif spread["confidence"] == "MEDIA":
        L.append(f"      Moderata divergenza tra modelli")
    else:
        L.append(f"      Modelli concordanti")

    L.append("")
    L.append("=" * 78)
    return "\n".join(L)

def generate_summary(selected_locations, all_results):
    L = []
    L.append("")
    L.append("=" * 78)
    L.append("  RIASSUNTO COMPARATIVO")
    L.append("=" * 78)
    L.append(f"  {'Stazione':<22} {'T ora':>7} {'Precip':>11} {'T max':>7} {'Spread T':>9} {'Conf.':>7}")
    L.append("-" * 78)

    for loc_name in selected_locations:
        res = all_results[loc_name]
        det = res["deterministic"]
        spread = res["spread"]

        first = next(iter(det.values())) if det else None
        t_now = first.get("fcst_temp_now") if first else None
        p_today = first.get("fcst_precip_today") if first else None
        t_max = spread["temp_spread"].get("mean")
        t_spread = spread["temp_spread"].get("spread")
        conf = spread["confidence"]

        L.append(f"  {loc_name:<22} {fmt(t_now, '°C'):>7} {fmt(p_today, 'mm'):>11} {fmt(t_max, '°C'):>7} {fmt(t_spread, '°C'):>9} {conf:>7}")

    L.append("-" * 78)
    return "\n".join(L)

# ============================================================
#  MAIN
# ============================================================

def main():
    # Setup parser per argomenti della riga di comando
    parser = argparse.ArgumentParser(description="Meteo Multimodello - Valli Cuneo")
    parser.add_argument("--auto", "-a", action="store_true",
                        help="Modalità automatica: seleziona tutte le stazioni, nessun input")
    parser.add_argument("--stations", "-s", type=str, default=None,
                        help="Numeri stazioni da selezionare (es. 1,3,5)")
    args = parser.parse_args()

    now = datetime.now()
    now_str = now.strftime("%Y%m%d_%H%M%S")
    date_folder = now.strftime("%Y_%m_%d")
    report_dt = now.strftime("%d/%m/%Y %H:%M")

    print("=" * 78)
    print("  METEO MULTIMODELLO - STAZIONI ARPA VALLE GESSO v10.2 (AUTOMATED)")
    print(f"  Esecuzione: {report_dt}")
    print("=" * 78)
    print()
    print("  Tutti i dati sono PREVISIONI dei modelli, non osservazioni")
    print("  Coordinate: stazioni ARPA Piemonte (UTM->WGS84)")
    print("  Organizzazione: cartella YYYY_MM_DD/")
    print()

    # Modalità automatica se --auto o ambiente GitHub Actions
    is_auto = args.auto or (args.stations is None and not sys.stdin.isatty())
    if args.stations:
        is_auto = False  # sta passando selezioni specifiche

    # Se siamo in ambiente GitHub Actions o --auto flag
    if args.auto:
        print("[AUTO] Modalità automatica attivata (--auto flag)")

    selected_locations = select_locations(interactive=not is_auto, selection_arg=args.stations)
    if not selected_locations:
        print("  Errore: nessuna stazione selezionata. Uscita.")
        return

    # STEP 1: Crea cartella giornaliera
    print("\n  STEP 1: Preparazione cartella...")
    folder_path = setup_daily_folder()

    print("\n  STEP 2: Download dati...")
    print("-" * 78)

    all_results = {}

    for loc_name, coords in selected_locations.items():
        print(f"\n  [{loc_name}] {coords['lat']:.4f}°N {coords['lon']:.4f}°E")
        det_results = {}
        for label, model_id in DETERMINISTIC_MODELS.items():
            print(f"    -> {label}...", end=" ")
            data = fetch_det_model(label, model_id, coords["lat"], coords["lon"])
            if data:
                metrics = extract_det_metrics(data)
                det_results[label] = metrics
                print(f"OK (T: {metrics.get('fcst_temp_now')}°C)" if metrics else "PARZIALE")
            else:
                det_results[label] = None
                print("FAIL")

        spread = compute_model_spread(det_results)

        all_results[loc_name] = {
            "deterministic": det_results,
            "spread": spread,
        }

    print("\n" + "-" * 78)
    print("  STEP 3: Generazione report...")
    print()

    full_report = []
    full_report.append("")
    full_report.append("=" * 78)
    full_report.append("  REPORT METEO MULTIMODELLO")
    full_report.append("  Stazioni ARPA Piemonte — Valle Gesso")
    full_report.append(f"  Stazioni: {', '.join(selected_locations.keys())}")
    full_report.append(f"  Eseguito: {report_dt}")
    full_report.append("  NOTA: Tutti i valori sono PREVISIONI dei modelli NWP,")
    full_report.append("        non osservazioni strumentali da stazioni reali.")
    full_report.append("=" * 78)

    for loc_name in selected_locations:
        res = all_results[loc_name]
        full_report.append(generate_report(
            loc_name, selected_locations[loc_name], res["deterministic"], res["spread"]
        ))

    if len(selected_locations) > 1:
        full_report.append(generate_summary(selected_locations, all_results))

    full_report.extend([
        "", "=" * 78, "  LEGENDA", "=" * 78,
        "  Modelli:",
        "    ECMWF   = ECMWF IFS 0.25° (~25 km, globale, 15 giorni)",
        "    ICON-D2 = DWD ICON-D2 (~2 km, Europa centrale, 2 giorni)",
        "    AROME   = Meteo-France AROME HD (~1.5 km, Francia, 4 giorni)",
        "",
        "  Stazioni ARPA Piemonte (coordinate WGS84 da UTM Zona 32N):",
        "    Valdieri (Terme)   44.2047°N  7.2681°E   1390 m",
        "    Diga La Piastra    44.2250°N  7.3894°E    950 m",
        "    Diga del Chiotas   44.1600°N  7.3329°E   2020 m",
        "    Andonno Gesso      44.2888°N  7.4366°E    712 m",
        "    Palanfrè           44.1901°N  7.4886°E   1625 m",
        "",
        "  Tutti i valori sono PREVISIONI, non misure reali.",
        "  Spread = divergenza tra i 3 modelli",
        "    Spread T < 3°C e P < 5mm  → ALTA affidabilità",
        "    Spread T < 6°C e P < 15mm → MEDIA affidabilità",
        "    Altrimenti                → BASSA affidabilità",
        "",
        "  Per osservazioni reali: www.arpa.piemonte.it",
        "",
    ])

    report_string = "\n".join(full_report)
    print(report_string)

    # Nome file
    loc_short = "_".join(n[:3].lower() for n in selected_locations) if len(selected_locations) <= 3 else "multi"
    txt_filename = f"meteo_gesso_{loc_short}_{now_str}.txt"
    json_filename = f"meteo_gesso_{loc_short}_{now_str}.json"

    txt_path = os.path.join(folder_path, txt_filename)
    json_path = os.path.join(folder_path, json_filename)

    # Salva TXT
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report_string)

    # Salva JSON
    json_data = {
        "timestamp": now.isoformat(),
        "note": "Tutti i valori sono PREVISIONI dei modelli NWP, non osservazioni strumentali.",
        "stations_source": "ARPA Piemonte - Valle Gesso",
        "fields_description": {
            "fcst_temp_now": "Temperatura a 2m prevista dal modello per l'ora corrente (°C)",
            "fcst_wind_now": "Velocità vento a 10m prevista dal modello per l'ora corrente (km/h)",
            "fcst_precip_now": "Precipitazione cumulata nell'ora precedente prevista dal modello (mm)",
            "fcst_temp_max_today": "Temperatura massima odierna prevista dal modello (°C)",
            "fcst_temp_min_today": "Temperatura minima odierna prevista dal modello (°C)",
            "fcst_precip_today": "Precipitazione totale odierna prevista dal modello (mm)",
            "fcst_precip_tomorrow": "Precipitazione totale di domani prevista dal modello (mm)",
        },
        "locations": {
            loc: {
                "coordinates": selected_locations[loc],
                "deterministic": {lbl: m for lbl, m in all_results[loc]["deterministic"].items() if m},
                "spread": all_results[loc]["spread"],
            }
            for loc in selected_locations
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)

    print("\n" + "-" * 78)
    print("  OUTPUT SALVATI:")
    print(f"    {txt_path}")
    print(f"    {json_path}")
    print("\n" + "=" * 78)
    print("  COMPLETATO")
    print("=" * 78)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrotto dall'utente.")
    except Exception as e:
        import traceback
        print(f"\n  ERRORE: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
