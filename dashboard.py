import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import os
import ast # To safely parse the secret string

# --- Firebase Imports ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- Page Config (must be the first Streamlit command) ---
st.set_page_config(layout="wide", page_title="NDMA Training Monitoring Dashboard")

# --- Firebase Connection ---
# FINAL, ROBUST VERSION: Handles secrets, project ID, and string parsing for deployment.
@st.cache_resource
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # For deployed app on Streamlit Cloud
            if "firebase_key" in st.secrets:
                cred_info = st.secrets["firebase_key"]
                cred_dict = {}

                if isinstance(cred_info, str):
                    cred_dict = ast.literal_eval(cred_info)
                else:
                    cred_dict = dict(cred_info)

                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {
                    'projectId': cred_dict['project_id'],
                })
            # For local development
            else:
                st.info("Initializing Firebase using local credentials...")
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred)
            
            return firestore.client()
            
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}", icon="🔥")
            return None
            
    return firestore.client()

# --- Data Fetching and Processing ---
@st.cache_data(ttl=60)
def get_firestore_data(_db):
    if _db is None:
        return pd.DataFrame(), pd.DataFrame()

    training_sessions_data = []
    agencies_data = []
    try:
        # Fetch Training Programs and their nested Sessions
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

        # Fetch Training Agencies
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
                'attendees': 'Number of Attendees', 'notes': 'Remarks'
            })
            df_trainings['Date of Session'] = pd.to_datetime(df_trainings['Date of Session'], format='%d-%m-%Y', errors='coerce')
            # Add coordinates for map feature
            # In a real app, these would come from the database or a proper lookup
            district_coords = {
                'Thiruvananthapuram': {'lat': 8.5241, 'lon': 76.9366}, 'Kollam': {'lat': 8.8932, 'lon': 76.6141},
                'Pathanamthitta': {'lat': 9.2647, 'lon': 76.7870}, 'Alappuzha': {'lat': 9.4981, 'lon': 76.3388},
                'Kottayam': {'lat': 9.5916, 'lon': 76.5222}, 'Idukki': {'lat': 9.8530, 'lon': 76.9800},
                'Ernakulam': {'lat': 9.9816, 'lon': 76.2999}, 'Thrissur': {'lat': 10.5276, 'lon': 76.2144},
                'Palakkad': {'lat': 10.7867, 'lon': 76.6548}, 'Malappuram': {'lat': 11.0514, 'lon': 76.0711},
                'Kozhikode': {'lat': 11.2588, 'lon': 75.7804}, 'Wayanad': {'lat': 11.6854, 'lon': 76.1320},
                'Kannur': {'lat': 11.8745, 'lon': 75.3704}, 'Kasaragod': {'lat': 12.5089, 'lon': 74.9880}
            }
            df_trainings['lat'] = df_trainings['State/District'].map(lambda x: district_coords.get(x, {}).get('lat'))
            df_trainings['lon'] = df_trainings['State/District'].map(lambda x: district_coords.get(x, {}).get('lon'))


        if not df_agencies.empty:
            df_agencies = df_agencies.rename(columns={'name': 'Agency Name', 'type': 'Agency Type'})

        return df_trainings, df_agencies
    except Exception as e:
        st.error(f"Error fetching data from Firestore: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Authentication ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login to the Dashboard")
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
            
        st.sidebar.header("Filter Training Data")
        if not df_trainings.empty:
            unique_locations = sorted(df_trainings['State/District'].dropna().unique())
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
                col3.metric("Total Attendees Trained", int(df_trainings_filtered['Number of Attendees'].sum()))

                st.subheader("Geographic Spread of Training Sessions")
                st.map(df_trainings_filtered[['lat', 'lon']].dropna())

                st.subheader("Training Sessions by State/District")
                location_chart = alt.Chart(df_trainings_filtered).mark_bar().encode(
                    x=alt.X('State/District:N', sort='-y', axis=alt.Axis(title='Location', labelAngle=-45)),
                    y=alt.Y('count():Q', title='Number of Sessions'),
                    tooltip=['State/District', 'count()']
                ).interactive()
                st.altair_chart(location_chart, use_container_width=True)

                st.subheader("All Training Session Records (Filtered)")
                st.dataframe(df_trainings_filtered, use_container_width=True)
            else:
                st.info("No training data to display for the selected filters.")

        with tab2:
            st.header("Partner Agency Overview")
            if not df_agencies.empty:
                st.metric("Total Training Agencies", len(df_agencies))
                st.dataframe(df_agencies, use_container_width=True)
            else:
                st.info("No agency data to display. Add some in the 'Add Records' tab.")

        with tab3:
            st.header("Log New Records")
            
            st.subheader("➕ Log a New Training Session")
            with st.form(key='new_training_form', clear_on_submit=True):
                program_id = st.text_input("Unique Program ID (e.g., KERALA-SDMA-001)")
                program_title = st.text_input("Program Title (e.g., 'Community First Responder Training')")
                session_date = st.text_input("Date of Session (dd-mm-yyyy)")
                attendees = st.number_input("Number of Attendees", min_value=0, step=1)
                location = st.selectbox("State/UT of Training", options=sorted(states_and_uts))
                theme = st.selectbox("Training Theme", options=['Earthquake Preparedness', 'Flood Response', 'Cyclone Safety', 'First Aid', 'Community Evacuation', 'Search and Rescue', 'Fire Safety'])
                notes = st.text_area("Remarks / Notes")
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
                                'notes': notes,
                                'recordedAt': firestore.SERVER_TIMESTAMP
                            }
                            
                            if not program_doc.exists:
                                program_doc_ref.set({'title': program_title, 'theme': theme})
                            
                            program_doc_ref.collection('sessions').add(session_data)
                            st.success(f"New session for program {program_id} logged successfully!")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error adding record: {e}")
            
            st.markdown("---")
            
            st.subheader("➕ Add a New Training Agency")
            with st.form(key='new_agency_form', clear_on_submit=True):
                agency_name = st.text_input("Agency Name (e.g., 'State Disaster Management Authority')")
                agency_type = st.selectbox("Agency Type", options=["SDMA", "ATI", "NGO", "CSO"])
                submit_agency_button = st.form_submit_button(label='Add Agency')

                if submit_agency_button and agency_name:
                    try:
                        db.collection('training_agencies').add({'name': agency_name, 'type': agency_type})
                        st.success(f"Agency '{agency_name}' added successfully!")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Error adding agency: {e}")
    else:
        st.error("Could not connect to Firebase. Please check your credentials and network connection.")
