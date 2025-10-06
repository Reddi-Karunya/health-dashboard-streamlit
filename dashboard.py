import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import os
import ast # To safely parse the secret string

# --- Firebase Imports ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- Page Config ---
st.set_page_config(layout="wide", page_title="NDMA Training Dashboard")

# --- Firebase Connection (No changes needed here) ---
@st.cache_resource
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            if "firebase_key" in st.secrets:
                cred_dict = ast.literal_eval(st.secrets["firebase_key"]) if isinstance(st.secrets["firebase_key"], str) else dict(st.secrets["firebase_key"])
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'projectId': cred_dict['project_id']})
            else:
                st.info("Initializing Firebase using local credentials...")
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}", icon="🔥")
            return None
    return firestore.client()

# --- Data Fetching Function (Modified for new data structure) ---
@st.cache_data(ttl=60)
def get_firestore_data(_db):
    if _db is None:
        return pd.DataFrame(), pd.DataFrame()

    training_sessions_data = []
    agencies_data = []
    try:
        # CHANGED: Fetch 'training_programs' and their nested 'sessions'
        programs_ref = _db.collection('training_programs')
        for program_doc in programs_ref.stream():
            program_data = program_doc.to_dict()
            program_id = program_doc.id
            sessions_ref = program_doc.reference.collection('sessions')
            for session_doc in sessions_ref.stream():
                session_data = session_doc.to_dict()
                combined_record = {**program_data, **session_data, 'program_id': program_id, 'session_id': session_doc.id}
                training_sessions_data.append(combined_record)
        df_trainings = pd.DataFrame(training_sessions_data)

        # CHANGED: Fetch 'training_agencies'
        agencies_ref = _db.collection('training_agencies')
        for doc in agencies_ref.stream():
            record = doc.to_dict()
            record['agency_id'] = doc.id
            agencies_data.append(record)
        df_agencies = pd.DataFrame(agencies_data)

        # --- Data Cleaning ---
        if not df_trainings.empty:
            df_trainings = df_trainings.rename(columns={
                'title': 'Program Title', 'location': 'State/District', 
                'theme': 'Training Theme', 'date': 'Date of Session',
                'attendees': 'Number of Attendees', 'status': 'Training Status'
            })
            df_trainings['Date of Session'] = pd.to_datetime(df_trainings['Date of Session'], format='%d-%m-%Y', errors='coerce')

        return df_trainings, df_agencies
    except Exception as e:
        st.error(f"Error fetching data from Firestore: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Authentication (No changes needed) ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login to the Dashboard")
    # ... (login form remains the same)
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "password123"
    with st.form(key='login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button(label='Log In')
    if login_button:
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid username or password.")
else:
    # --- Main Dashboard ---
    db = initialize_firebase()
    
    states_and_uts = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"]


    if db:
        with st.spinner('Loading dashboard data...'):
            df_trainings, df_agencies = get_firestore_data(db)

        # --- Sidebar ---
        st.sidebar.markdown("---")
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.cache_data.clear(); st.cache_resource.clear()
            st.rerun()
            
        st.sidebar.header("Training Data Filters")
        if not df_trainings.empty:
            unique_locations = sorted(df_trainings['State/District'].unique())
            selected_locations = st.sidebar.multiselect("Filter by Location", options=unique_locations, default=unique_locations)
            df_trainings_filtered = df_trainings[df_trainings['State/District'].isin(selected_locations)]
        else:
            st.sidebar.info("No training data to filter.")
            df_trainings_filtered = pd.DataFrame()

        # --- Main Page ---
        st.title("NDMA Training Monitoring Dashboard 📈")
        
        tab1, tab2, tab3 = st.tabs(["Trainings Overview", "Agencies Overview", "Add Records"])

        with tab1:
            st.header("Disaster Management Training Analytics")
            if not df_trainings_filtered.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Programs", df_trainings_filtered['program_id'].nunique())
                col2.metric("Total Sessions Conducted", len(df_trainings_filtered))
                col3.metric("Total Attendees Trained", df_trainings_filtered['Number of Attendees'].sum())

                st.subheader("Training Sessions by State/District")
                location_chart = alt.Chart(df_trainings_filtered).mark_bar().encode(
                    x=alt.X('State/District', axis=alt.Axis(title='Location', labelAngle=-45)),
                    y='count():Q',
                    tooltip=['State/District', 'count()']
                ).interactive()
                st.altair_chart(location_chart, use_container_width=True)

                st.subheader("All Training Session Records")
                st.dataframe(df_trainings_filtered, use_container_width=True)
            else:
                st.info("No training data to display for the selected filters.")

        with tab2:
            st.header("Partner Agency Overview")
            if not df_agencies.empty:
                st.metric("Total Training Agencies", len(df_agencies))
                st.dataframe(df_agencies, use_container_width=True)
            else:
                st.info("No agency data to display.")

        with tab3:
            st.header("Log New Training Records")
            with st.form(key='new_training_form', clear_on_submit=True):
                program_id = st.text_input("Unique Program ID (e.g., STATE-AGENCY-001)")
                program_title = st.text_input("Program Title (e.g., 'Community First Responder Training')")
                session_date = st.text_input("Date of Session (dd-mm-yyyy)")
                attendees = st.number_input("Number of Attendees", min_value=0, step=1)
                location = st.selectbox("State/District of Training", options=sorted(states_and_uts))
                theme = st.text_input("Training Theme (e.g., 'Earthquake Preparedness')")
                submit_button = st.form_submit_button(label='Log Training Session')

                if submit_button:
                    if not all([program_id, program_title, session_date]):
                        st.warning("Program ID, Title, and Date are required.")
                    else:
                        try:
                            program_doc_ref = db.collection('training_programs').doc(program_id)
                            program_doc = program_doc_ref.get()
                            
                            session_data = {
                                'date': session_date, 
                                'attendees': attendees, 
                                'location': location, 
                                'createdAt': firestore.SERVER_TIMESTAMP
                            }
                            
                            if not program_doc.exists:
                                program_doc_ref.set({'title': program_title, 'theme': theme})
                            
                            program_doc_ref.collection('sessions').add(session_data)
                            st.success(f"New session for program {program_id} logged successfully!")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error adding record: {e}")
    else:
        st.error("Could not connect to Firebase.")
