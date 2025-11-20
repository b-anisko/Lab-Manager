import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from streamlit_calendar import calendar

# --- KONFIGURACJA ---
st.set_page_config(page_title="Lab Manager", layout="wide")

# --- POŁĄCZENIE Z GOOGLE SHEETS (ZAAWANSOWANE) ---
@st.cache_resource
def get_google_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # 1. Próba wczytania z sekretów chmurowych (Streamlit Cloud)
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"]) # Konwersja na zwykły słownik
            
            # Naprawa klucza prywatnego (częsty problem w Streamlit Cloud)
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        # 2. Próba wczytania z pliku lokalnego (Twój komputer)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
            
        client = gspread.authorize(creds)
        return client

    except Exception as e:
        st.error(f"🔥 Błąd połączenia z bazą danych: {e}")
        st.info("Wskazówka: Sprawdź format klucza prywatnego w Secrets (czy znaki \\n są poprawne).")
        return None

# --- POBIERANIE DANYCH (CACHE TTL=60s) ---
@st.cache_data(ttl=60)
def load_data():
    client = get_google_client()
    if not client: return None, None, None, None, None
    
    try:
        sh = client.open("Lab_Manager")
    except Exception as e:
        st.error(f"Nie znaleziono arkusza 'Lab_Manager'. Sprawdź nazwę w Google Sheets. ({e})")
        return None, None, None, None

    # Pobieranie zakładek (z obsługą błędów braku arkusza)
    try:
        ws_sprzet = sh.worksheet("Sprzet")
        df_sprzet = pd.DataFrame(ws_sprzet.get_all_records())
        if not df_sprzet.empty and 'ID' in df_sprzet.columns:
            df_sprzet['ID'] = df_sprzet['ID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    except: df_sprzet = pd.DataFrame()

    try: ws_rez = sh.worksheet("Rezerwacje"); df_rez = pd.DataFrame(ws_rez.get_all_records())
    except: df_rez = pd.DataFrame()
    
    try: ws_prop = sh.worksheet("Propozycje"); df_prop = pd.DataFrame(ws_prop.get_all_records())
    except: df_prop = pd.DataFrame()

    return sh, df_sprzet, df_rez, df_prop

# --- FUNKCJE POMOCNICZE ---
def przygotuj_eventy(df_rez, df_sprzet):
    events = []
    # Rezerwacje
    if not df_rez.empty and 'Data_Od' in df_rez.columns:
        for _, row in df_rez.iterrows():
            color = "#3788d8"
            title = f"{row.get('Nazwa', '?')} ({row.get('Uzytkownik', '?')})"
            if row.get('ID_Sprzetu') == 'CALE_LAB':
                color = "#ff9f89"; title = f"⛔ LAB ZAJĘTY: {row.get('Typ', '')}"
            
            try:
                events.append({
                    "title": title,
                    "start": row['Data_Od'],
                    "end": (datetime.strptime(str(row['Data_Do']), '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'),
                    "color": color,
                })
            except: continue

    # Wypożyczenia
    if not df_sprzet.empty and 'Status' in df_sprzet.columns:
        wyp = df_sprzet[df_sprzet['Status'] == 'Wypożyczony']
        for _, row in wyp.iterrows():
            if row.get('Data_Zwrotu'):
                start_date = row.get('Data_Wypozyczenia') if row.get('Data_Wypozyczenia') else datetime.now().strftime('%Y-%m-%d')
                events.append({
                    "title": f"WYPOŻYCZONE: {row.get('Nazwa')} ({row.get('Uzytkownik')})",
                    "start": start_date,
                    "end": row['Data_Zwrotu'],
                    "color": "#d83737"
                })
    return events

def sprawdz_dostepnosc(id_sprzetu, data_start, data_koniec, df_rezerwacje):
    if df_rezerwacje.empty: return True, ""
    
    # Sprawdź blokadę globalną
    if 'ID_Sprzetu' in df_rezerwacje.columns:
        lab_rez = df_rezerwacje[df_rezerwacje['ID_Sprzetu'] == 'CALE_LAB']
        for _, row in lab_rez.iterrows():
            try:
                r_s = datetime.strptime(str(row['Data_Od']), '%Y-%m-%d').date()
                r_e = datetime.strptime(str(row['Data_Do']), '%Y-%m-%d').date()
                if data_start <= r_e and data_koniec >= r_s: return False, f"CAŁE LABO: {row.get('Uzytkownik')}"
            except: continue

        # Sprawdź konkretny sprzęt
        if id_sprzetu != 'CALE_LAB':
            sprz = df_rezerwacje[df_rezerwacje['ID_Sprzetu'].astype(str) == str(id_sprzetu)]
            for _, row in sprz.iterrows():
                try:
                    r_s = datetime.strptime(str(row['Data_Od']), '%Y-%m-%d').date()
                    r_e = datetime.strptime(str(row['Data_Do']), '%Y-%m-%d').date()
                    if data_start <= r_e and data_koniec >= r_s: return False, f"{row.get('Uzytkownik')} ({row.get('Typ')})"
                except: continue
    return True, ""

# --- GŁÓWNA APLIKACJA ---
def main():
    st.title("🔬 System kontroli laboratorium")
    
    if st.sidebar.button("🔄 Odśwież dane"):
        st.cache_data.clear(); st.rerun()

    menu = st.sidebar.radio("Menu", [
        "Kalendarz", "Aktualny status urządzeń", "Rezerwacja laboratorium", 
        "Planowanie zajęć dydaktycznych", "Wypożycz urządzenie", 
        "Zwróć urządzenie", "Zgłoś usterkę", "Propozycja zakupu", "Uwagi i skargi"
    ])

    sh_obj, df_sprzet, df_rez, df_propozycje = load_data()
    
    # Jeśli nie udało się połączyć, zatrzymaj program
    if sh_obj is None: 
        st.warning("Brak połączenia z bazą danych. Sprawdź konfigurację Secrets.")
        st.stop()

    # --- 1. KALENDARZ ---
    if menu == "Kalendarz":
        st.header("🗓️ Kalendarz")
        events = przygotuj_eventy(df_rez, df_sprzet)
        calendar(events=events, options={
            "initialView": "dayGridMonth", "locale": "pl",
            "buttonText": {"today": "Dzisiaj", "month": "Miesiąc", "list": "Lista"}
        })

    # --- 2. STATUS ---
    elif menu == "Aktualny status urządzeń":
        st.header("📦 Aktualny status urządzeń")
        dzis = datetime.now().date()
        wolne, info = sprawdz_dostepnosc('CALE_LAB', dzis, dzis, df_rez)
        if not wolne: st.error(f"🚨 Dziś laboratorium niedostępne! ({info})")

        def color_status(val):
            if val == 'Dostępny': return 'background-color: #1f7a1f; color: white'
            if val == 'Wypożyczony': return 'background-color: #8b0000; color: white'
            if val == 'W naprawie': return 'background-color: #ff8c00; color: white; font-weight: bold'
            return ''
        
        if not df_sprzet.empty and 'Status' in df_sprzet.columns:
            st.dataframe(df_sprzet.style.applymap(color_status, subset=['Status']), use_container_width=True)
        else:
            st.info("Brak danych o sprzęcie.")

    # --- 3. REZERWACJA LABU ---
    elif menu == "Rezerwacja laboratorium":
        st.header("🏢 Rezerwacja całego laboratorium")
        with st.form("lab_block"):
            c1, c2 = st.columns(2); d1 = c1.date_input("Od"); d2 = c2.date_input("Do")
            typ = st.selectbox("Cel", ["Badania", "Zajęcia", "Inne"]); user = st.text_input("Osoba odpowiedzialna")
            if st.form_submit_button("Zablokuj"):
                wolne, info = sprawdz_dostepnosc('CALE_LAB', d1, d2, df_rez)
                if wolne:
                    ws_rez = sh_obj.worksheet("Rezerwacje")
                    ws_rez.append_row(['CALE_LAB', 'CAŁE LABO', user, str(d1), str(d2), typ])
                    st.cache_data.clear(); st.success("Zapisano!"); st.rerun()
                else: st.error(f"Konflikt: {info}")

    # --- 4. PLANOWANIE ---
    elif menu == "Planowanie zajęć dydaktycznych":
        st.header("📅 Planowanie zajęć dydaktycznych")
        if not df_sprzet.empty:
            with st.form("plan_multi"):
                opcje = df_sprzet['Nazwa'].astype(str) + " (ID: " + df_sprzet['ID'].astype(str) + ")"
                wybor = st.multiselect("Wybierz urządzenia", opcje)
                c1, c2 = st.columns(2); d1 = c1.date_input("Od"); d2 = c2.date_input("Do")
                typ = st.selectbox("Typ", ["Zajęcia", "Badania"]); user = st.text_input("Osoba prowadząca")
                if st.form_submit_button("Rezerwuj"):
                    ws_rez = sh_obj.worksheet("Rezerwacje")
                    for w in wybor:
                        ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                        nazwa = str(w.split(" (ID:")[0])
                        wolne, info = sprawdz_dostepnosc(ids, d1, d2, df_rez)
                        if wolne: ws_rez.append_row([ids, nazwa, user, str(d1), str(d2), typ])
                    st.cache_data.clear(); st.success("Gotowe!"); st.rerun()
        else: st.error("Brak sprzętu w bazie.")

    # --- 5. WYPOŻYCZ ---
    elif menu == "Wypożycz urządzenie":
        st.header("⚡ Wypożycz urządzenie")
        if not df_sprzet.empty:
            dostepne = df_sprzet[df_sprzet['Status'] == 'Dostępny']
            with st.form("wyp_dev"):
                opcje = dostepne['Nazwa'].astype(str) + " (ID: " + dostepne['ID'].astype(str) + ")"
                wybor = st.multiselect("Wybierz urządzenia", opcje)
                user = st.text_input("Kto")
                c1, c2 = st.columns(2)
                d_wyp = c1.date_input("Data wypożyczenia", value=datetime.now())
                d_zwrot = c2.date_input("Planowany zwrot")
                
                if st.form_submit_button("Zatwierdź"):
                    ws_sprzet = sh_obj.worksheet("Sprzet")
                    for w in wybor:
                        ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                        wolne, info = sprawdz_dostepnosc(ids, d_wyp, d_zwrot, df_rez)
                        if wolne:
                            try:
                                cell = ws_sprzet.find(ids, in_column=1)
                                ws_sprzet.update_cell(cell.row, 4, "Wypożyczony")
                                ws_sprzet.update_cell(cell.row, 5, user)
                                ws_sprzet.update_cell(cell.row, 6, str(d_zwrot))
                                # Zapisz datę wypożyczenia w kolumnie 7 (G)
                                ws_sprzet.update_cell(cell.row, 7, str(d_wyp))
                            except Exception as e: st.error(f"Błąd zapisu dla ID {ids}: {e}")
                    st.cache_data.clear(); st.rerun()
        else: st.error("Brak sprzętu.")

    # --- 6. ZWRÓĆ ---
    elif menu == "Zwróć urządzenie":
        st.header("↩️ Zwróć urządzenie")
        if not df_sprzet.empty:
            wyp = df_sprzet[df_sprzet['Status'] == 'Wypożyczony']
            if not wyp.empty:
                opcje = wyp['Nazwa'].astype(str) + " (ID: " + wyp['ID'].astype(str) + ")"
                wybor = st.multiselect("Wybierz zwracane", opcje)
                if st.button("Zwróć zaznaczone"):
                    ws_sprzet = sh_obj.worksheet("Sprzet")
                    for w in wybor:
                        ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                        cell = ws_sprzet.find(ids, in_column=1)
                        ws_sprzet.update_cell(cell.row, 4, "Dostępny")
                        ws_sprzet.update_cell(cell.row, 5, "")
                        ws_sprzet.update_cell(cell.row, 6, "")
                        ws_sprzet.update_cell(cell.row, 7, "")
                    st.cache_data.clear(); st.success("Zwrócono!"); st.rerun()
            else: st.info("Brak wypożyczonych urządzeń.")

    # --- 7. USTERKI ---
    elif menu == "Zgłoś usterkę":
        st.header("⚠️ Zgłoś usterkę")
        if not df_sprzet.empty:
            with st.form("usterka"):
                opcje = df_sprzet['Nazwa'].astype(str) + " (ID: " + df_sprzet['ID'].astype(str) + ")"
                wybor = st.selectbox("Sprzęt", opcje)
                opis = st.text_area("Opis"); zglaszajacy = st.text_input("Kto")
                if st.form_submit_button("Zgłoś"):
                    ws_usterki = sh_obj.worksheet("Usterki")
                    ws_sprzet = sh_obj.worksheet("Sprzet")
                    ids = str(wybor.split("ID: ")[1].replace(")", "")).strip()
                    nazwa = str(wybor.split(" (ID:")[0])
                    ws_usterki.append_row([ids, nazwa, zglaszajacy, opis, str(datetime.now().date()), "Otwarte"])
                    cell = ws_sprzet.find(ids, in_column=1)
                    ws_sprzet.update_cell(cell.row, 4, "W naprawie")
                    st.cache_data.clear(); st.rerun()

    # --- 8. PROPOZYCJE ---
    elif menu == "Propozycja zakupu":
        st.header("💡 Lista Życzeń")
        if not df_propozycje.empty and 'Status' in df_propozycje.columns:
            def color_prop(val):
                if val == 'Oczekuje': return 'background-color: #ffd700; color: black'
                if val == 'Zaakceptowana': return 'background-color: #1f7a1f; color: white'
                if val == 'Odrzucona': return 'background-color: #8b0000; color: white'
                if val == 'Zakupione': return 'background-color: #3788d8; color: white'
                return ''
            st.dataframe(df_propozycje.style.applymap(color_prop, subset=['Status']), use_container_width=True)
        
        st.divider(); c1, c2 = st.columns(2)
        with c1:
            st.subheader("➕ Dodaj")
            with st.form("prop_add"):
                n = st.text_input("Co?"); c = st.text_input("Cena"); u = st.text_area("Po co?"); k = st.text_input("Kto")
                if st.form_submit_button("Wyślij"):
                    ws_prop = sh_obj.worksheet("Propozycje")
                    new_id = len(df_propozycje) + 1
                    ws_prop.append_row([new_id, n, k, c, u, str(datetime.now().date()), "Oczekuje", ""])
                    st.cache_data.clear(); st.success("Wysłano!"); st.rerun()
        with c2:
            st.subheader("Panel Kierownika")
            if not df_propozycje.empty:
                l = df_propozycje['Nazwa_Sprzetu'].astype(str) + " (ID: " + df_propozycje['ID'].astype(str) + ")"
                w = st.selectbox("Wniosek", l); s = st.selectbox("Status", ["Oczekuje", "Zaakceptowana", "Odrzucona", "Zakupione"]); o = st.text_area("Komentarz")
                if st.button("Aktualizuj"):
                    ws_prop = sh_obj.worksheet("Propozycje")
                    id_p = str(w.split("ID: ")[1].replace(")", "")).strip()
                    cell = ws_prop.find(id_p, in_column=1)
                    ws_prop.update_cell(cell.row, 7, s); ws_prop.update_cell(cell.row, 8, o)
                    st.cache_data.clear(); st.rerun()

    # --- 9. UWAGI ---
    elif menu == "Uwagi i skargi":
        st.header("📢 Skrzynka uwag")
        with st.form("uwagi_form"):
            k = st.text_input("Kto"); t = st.selectbox("Typ", ["Brak materiałów", "Inne"]); tr = st.text_area("Treść")
            if st.form_submit_button("Wyślij"):
                ws_uw = sh_obj.worksheet("Uwagi")
                ws_uw.append_row([str(datetime.now().date()), k, tr, t])
                st.success("Wysłano!")

if __name__ == "__main__":
    main()
