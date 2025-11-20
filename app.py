import streamlit as st
import pandas as pd
import gspread
import time
from datetime import datetime, timedelta
from streamlit_calendar import calendar

# --- KONFIGURACJA ---
st.set_page_config(page_title="Lab Manager", layout="wide")

# --- POŁĄCZENIE Z RETRY (PONAWIANIE PRÓB) ---
def connect_with_retry(max_retries=3):
    for i in range(max_retries):
        try:
            if "gcp_service_account" in st.secrets:
                creds = dict(st.secrets["gcp_service_account"])
                if "private_key" in creds:
                    creds["private_key"] = creds["private_key"].replace("\\n", "\n")
                
                # Nowa metoda autoryzacji (bez oauth2client)
                gc = gspread.service_account_from_dict(creds)
                return gc
            else:
                # Lokalnie
                gc = gspread.service_account(filename="secrets.json")
                return gc
        except Exception as e:
            if i == max_retries - 1:
                st.error(f"🔥 Błąd połączenia po {max_retries} próbach: {e}")
                return None
            time.sleep(2) # Czekaj 2 sekundy i spróbuj znowu
    return None

# --- POBIERANIE DANYCH (CACHE DANYCH) ---
@st.cache_data(ttl=60)
def get_dataframes():
    client = connect_with_retry()
    if not client: return None, None, None
    
    try:
        sh = client.open("Lab_Manager")
        # Pobieramy wszystkie zakładki z obsługą błędów
        try: 
            df_s = pd.DataFrame(sh.worksheet("Sprzet").get_all_records())
            if not df_s.empty and 'ID' in df_s.columns:
                df_s['ID'] = df_s['ID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        except: df_s = pd.DataFrame()

        try: df_r = pd.DataFrame(sh.worksheet("Rezerwacje").get_all_records())
        except: df_r = pd.DataFrame()
        
        try: df_p = pd.DataFrame(sh.worksheet("Propozycje").get_all_records())
        except: df_p = pd.DataFrame()
        
        return df_s, df_r, df_p
    except Exception as e:
        st.warning(f"Problem z pobraniem danych: {e}")
        return None, None, None

# --- FUNKCJE POMOCNICZE ---
def przygotuj_eventy(df_rez, df_sprzet):
    events = []
    if df_rez is not None and not df_rez.empty and 'Data_Od' in df_rez.columns:
        for _, row in df_rez.iterrows():
            try:
                events.append({
                    "title": f"{row.get('Nazwa', '?')} ({row.get('Uzytkownik', '?')})",
                    "start": row['Data_Od'],
                    "end": (datetime.strptime(str(row['Data_Do']), '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'),
                    "color": "#ff9f89" if row.get('ID_Sprzetu') == 'CALE_LAB' else "#3788d8",
                })
            except: continue
    if df_sprzet is not None and not df_sprzet.empty and 'Status' in df_sprzet.columns:
        for _, row in df_sprzet[df_sprzet['Status'] == 'Wypożyczony'].iterrows():
            if row.get('Data_Zwrotu'):
                start = row.get('Data_Wypozyczenia') if row.get('Data_Wypozyczenia') else datetime.now().strftime('%Y-%m-%d')
                events.append({
                    "title": f"WYPOŻYCZONE: {row.get('Nazwa')} ({row.get('Uzytkownik')})",
                    "start": start, "end": row['Data_Zwrotu'], "color": "#d83737"
                })
    return events

def sprawdz_dostepnosc(id_sprzetu, data_start, data_koniec, df_rezerwacje):
    if df_rezerwacje is None or df_rezerwacje.empty: return True, ""
    if 'ID_Sprzetu' not in df_rezerwacje.columns: return True, ""
    
    lab_rez = df_rezerwacje[df_rezerwacje['ID_Sprzetu'] == 'CALE_LAB']
    for _, row in lab_rez.iterrows():
        try:
            if data_start <= datetime.strptime(str(row['Data_Do']), '%Y-%m-%d').date() and data_koniec >= datetime.strptime(str(row['Data_Od']), '%Y-%m-%d').date():
                return False, f"CAŁE LABO: {row.get('Uzytkownik')}"
        except: continue

    if id_sprzetu != 'CALE_LAB':
        sprz = df_rezerwacje[df_rezerwacje['ID_Sprzetu'].astype(str) == str(id_sprzetu)]
        for _, row in sprz.iterrows():
            try:
                if data_start <= datetime.strptime(str(row['Data_Do']), '%Y-%m-%d').date() and data_koniec >= datetime.strptime(str(row['Data_Od']), '%Y-%m-%d').date():
                    return False, f"{row.get('Uzytkownik')}"
            except: continue
    return True, ""

# --- GŁÓWNA APLIKACJA ---
def main():
    st.title("🔬 System kontroli laboratorium")
    if st.sidebar.button("🔄 Odśwież dane"): st.cache_data.clear(); st.rerun()

    menu = st.sidebar.radio("Menu", ["Kalendarz", "Aktualny status urządzeń", "Rezerwacja laboratorium", "Planowanie zajęć dydaktycznych", "Wypożycz urządzenie", "Zwróć urządzenie", "Zgłoś usterkę", "Propozycja zakupu", "Uwagi i skargi"])

    df_sprzet, df_rez, df_propozycje = get_dataframes()

    if menu == "Kalendarz":
        st.header("🗓️ Kalendarz")
        events = przygotuj_eventy(df_rez, df_sprzet)
        calendar(events=events, options={"initialView": "dayGridMonth", "locale": "pl", "buttonText": {"today": "Dzisiaj", "month": "Miesiąc", "list": "Lista"}})

    elif menu == "Aktualny status urządzeń":
        st.header("📦 Aktualny status urządzeń")
        dzis = datetime.now().date()
        wolne, info = sprawdz_dostepnosc('CALE_LAB', dzis, dzis, df_rez)
        if not wolne: st.error(f"🚨 Dziś laboratorium niedostępne! ({info})")
        if df_sprzet is not None and not df_sprzet.empty and 'Status' in df_sprzet.columns:
            def color(val):
                if val == 'Dostępny': return 'background-color: #1f7a1f; color: white'
                if val == 'Wypożyczony': return 'background-color: #8b0000; color: white'
                if val == 'W naprawie': return 'background-color: #ff8c00; color: white; font-weight: bold'
                return ''
            st.dataframe(df_sprzet.style.applymap(color, subset=['Status']), use_container_width=True)

    elif menu == "Wypożycz urządzenie":
        st.header("⚡ Wypożycz urządzenie")
        if df_sprzet is not None and not df_sprzet.empty:
            dostepne = df_sprzet[df_sprzet['Status'] == 'Dostępny']
            with st.form("wyp_dev"):
                opcje = dostepne['Nazwa'].astype(str) + " (ID: " + dostepne['ID'].astype(str) + ")"
                wybor = st.multiselect("Wybierz urządzenia", opcje)
                user = st.text_input("Kto"); c1, c2 = st.columns(2); d_wyp = c1.date_input("Data wypożyczenia"); d_zwrot = c2.date_input("Zwrot")
                if st.form_submit_button("Zatwierdź"):
                    client = connect_with_retry() # Łączymy się świeżo
                    if client:
                        ws = client.open("Lab_Manager").worksheet("Sprzet")
                        for w in wybor:
                            ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                            wolne, info = sprawdz_dostepnosc(ids, d_wyp, d_zwrot, df_rez)
                            if wolne:
                                cell = ws.find(ids, in_column=1)
                                ws.update_cell(cell.row, 4, "Wypożyczony")
                                ws.update_cell(cell.row, 5, user)
                                ws.update_cell(cell.row, 6, str(d_zwrot))
                                ws.update_cell(cell.row, 7, str(d_wyp))
                        st.cache_data.clear(); st.success("Wypożyczono!"); st.rerun()
    
    elif menu == "Rezerwacja laboratorium":
        st.header("🏢 Rezerwacja całego laboratorium")
        with st.form("lab_block"):
            c1, c2 = st.columns(2); d1 = c1.date_input("Od"); d2 = c2.date_input("Do")
            typ = st.selectbox("Cel", ["Badania", "Zajęcia", "Inne"]); user = st.text_input("Kto")
            if st.form_submit_button("Zablokuj"):
                wolne, info = sprawdz_dostepnosc('CALE_LAB', d1, d2, df_rez)
                if wolne:
                    client = connect_with_retry()
                    if client:
                        client.open("Lab_Manager").worksheet("Rezerwacje").append_row(['CALE_LAB', 'CAŁE LABO', user, str(d1), str(d2), typ])
                        st.cache_data.clear(); st.success("Zablokowano!"); st.rerun()
                else: st.error(f"Konflikt: {info}")

    elif menu == "Planowanie zajęć dydaktycznych":
        st.header("📅 Planowanie zajęć dydaktycznych")
        if df_sprzet is not None and not df_sprzet.empty:
            with st.form("plan"):
                opcje = df_sprzet['Nazwa'].astype(str) + " (ID: " + df_sprzet['ID'].astype(str) + ")"
                wybor = st.multiselect("Urządzenia", opcje)
                c1, c2 = st.columns(2); d1 = c1.date_input("Od"); d2 = c2.date_input("Do")
                typ = st.selectbox("Typ", ["Zajęcia", "Badania"]); user = st.text_input("Prowadzący")
                if st.form_submit_button("Rezerwuj"):
                    client = connect_with_retry()
                    if client:
                        ws = client.open("Lab_Manager").worksheet("Rezerwacje")
                        for w in wybor:
                            ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                            wolne, info = sprawdz_dostepnosc(ids, d1, d2, df_rez)
                            if wolne: ws.append_row([ids, str(w.split(" (ID:")[0]), user, str(d1), str(d2), typ])
                        st.cache_data.clear(); st.success("Gotowe!"); st.rerun()

    elif menu == "Zwróć urządzenie":
        st.header("↩️ Zwrot")
        if df_sprzet is not None:
            wyp = df_sprzet[df_sprzet['Status'] == 'Wypożyczony']
            if not wyp.empty:
                opcje = wyp['Nazwa'].astype(str) + " (ID: " + wyp['ID'].astype(str) + ")"
                wybor = st.multiselect("Zwracane", opcje)
                if st.button("Zwróć"):
                    client = connect_with_retry()
                    if client:
                        ws = client.open("Lab_Manager").worksheet("Sprzet")
                        for w in wybor:
                            ids = str(w.split("ID: ")[1].replace(")", "")).strip()
                            cell = ws.find(ids, in_column=1)
                            ws.update_cell(cell.row, 4, "Dostępny")
                            ws.update_cell(cell.row, 5, ""); ws.update_cell(cell.row, 6, ""); ws.update_cell(cell.row, 7, "")
                        st.cache_data.clear(); st.success("Zwrócono!"); st.rerun()

    elif menu == "Zgłoś usterkę":
        st.header("⚠️ Usterka")
        if df_sprzet is not None:
            with st.form("ust"):
                opcje = df_sprzet['Nazwa'].astype(str) + " (ID: " + df_sprzet['ID'].astype(str) + ")"
                wybor = st.selectbox("Sprzęt", opcje); opis = st.text_area("Opis"); k = st.text_input("Kto")
                if st.form_submit_button("Zgłoś"):
                    client = connect_with_retry()
                    if client:
                        ids = str(wybor.split("ID: ")[1].replace(")", "")).strip()
                        client.open("Lab_Manager").worksheet("Usterki").append_row([ids, str(wybor.split(" (ID:")[0]), k, opis, str(datetime.now().date()), "Otwarte"])
                        ws_s = client.open("Lab_Manager").worksheet("Sprzet")
                        cell = ws_s.find(ids, in_column=1)
                        ws_s.update_cell(cell.row, 4, "W naprawie")
                        st.cache_data.clear(); st.rerun()

    elif menu == "Propozycja zakupu":
        st.header("💡 Propozycje")
        if df_propozycje is not None and not df_propozycje.empty and 'Status' in df_propozycje.columns:
            def color_prop(val):
                if val == 'Oczekuje': return 'background-color: #ffd700; color: black'
                if val == 'Zaakceptowana': return 'background-color: #1f7a1f; color: white'
                if val == 'Odrzucona': return 'background-color: #8b0000; color: white'
                if val == 'Zakupione': return 'background-color: #3788d8; color: white'
                return ''
            st.dataframe(df_propozycje.style.applymap(color_prop, subset=['Status']), use_container_width=True)
        st.divider(); c1, c2 = st.columns(2)
        with c1:
            with st.form("p_add"):
                n = st.text_input("Co"); c = st.text_input("Cena"); u = st.text_area("Po co"); k = st.text_input("Kto")
                if st.form_submit_button("Wyślij"):
                    client = connect_with_retry()
                    if client:
                        client.open("Lab_Manager").worksheet("Propozycje").append_row([len(df_propozycje)+1, n, k, c, u, str(datetime.now().date()), "Oczekuje", ""])
                        st.cache_data.clear(); st.success("Wysłano!"); st.rerun()
        with c2:
            st.subheader("Panel Kierownika")
            if df_propozycje is not None and not df_propozycje.empty:
                l = df_propozycje['Nazwa_Sprzetu'].astype(str) + " (ID: " + df_propozycje['ID'].astype(str) + ")"
                w = st.selectbox("Wniosek", l); s = st.selectbox("Status", ["Oczekuje", "Zaakceptowana", "Odrzucona", "Zakupione"]); o = st.text_area("Komentarz")
                if st.button("Aktualizuj"):
                    client = connect_with_retry()
                    if client:
                        ws = client.open("Lab_Manager").worksheet("Propozycje")
                        id_p = str(w.split("ID: ")[1].replace(")", "")).strip()
                        cell = ws.find(id_p, in_column=1)
                        ws.update_cell(cell.row, 7, s); ws.update_cell(cell.row, 8, o)
                        st.cache_data.clear(); st.rerun()
    
    elif menu == "Uwagi i skargi":
        st.header("📢 Uwagi")
        with st.form("uw"):
            k = st.text_input("Kto"); t = st.selectbox("Typ", ["Brak", "Inne"]); tr = st.text_area("Treść")
            if st.form_submit_button("Wyślij"):
                client = connect_with_retry()
                if client:
                    client.open("Lab_Manager").worksheet("Uwagi").append_row([str(datetime.now().date()), k, tr, t])
                    st.success("Wysłano!")

if __name__ == "__main__":
    main()
