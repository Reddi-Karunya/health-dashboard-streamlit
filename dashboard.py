import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import os
import ast # ADDED: To safely parse the secret string

# --- Firebase Imports ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- Page Config (must be the first Streamlit command) ---
st.set_page_config(layout="wide", page_title="Kerala Migrant Health Dashboard")

# --- Firebase Connection ---
# FINAL, ROBUST VERSION: This function now handles if the secret is read as a string.
@st.cache_resource
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # Check if running in Streamlit Cloud and secrets are available
            if "firebase_key" in st.secrets:
                cred_info = st.secrets["firebase_key"]
                cred_dict = {}

                # Safely convert the secret from a string to a dictionary if needed
                if isinstance(cred_info, str):
                    cred_dict = ast.literal_eval(cred_info)
                else:
                    cred_dict = dict(cred_info)

                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            else:
                # Fallback for local development
                st.info("Initializing Firebase using local credentials...")
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred)
            
            return firestore.client()
            
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}", icon="🔥")
            return None
            
    return firestore.client()

# --- Data Fetching Function ---
@st.cache_data(ttl=60)
def get_firestore_data(_db):
    if _db is None:
        return pd.DataFrame()

    patients_with_visits_data = []
    try:
        patients_ref = _db.collection('patients')
        for patient_doc in patients_ref.stream():
            patient_data = patient_doc.to_dict()
            patient_id = patient_doc.id
            visits_ref = patient_doc.reference.collection('visits')
            for visit_doc in visits_ref.stream():
                visit_data = visit_doc.to_dict()
                combined_record = {**patient_data, **visit_data, 'patient_id': patient_id, 'visit_id': visit_doc.id}
                patients_with_visits_data.append(combined_record)
        
        df_patients = pd.DataFrame(patients_with_visits_data)
        
        if not df_patients.empty:
            df_patients = df_patients.rename(columns={
                'name': 'Patient Name', 'location': 'District', 'notes': 'Doctor Advice',
                'visitDate': 'Date of Visit', 'symptoms': 'Reported Symptoms',
                'currentVaccinationStatus': 'Vaccination Status',
            })
            df_patients['Date of Visit'] = pd.to_datetime(df_patients['Date of Visit'], format='%d-%m-%Y', errors='coerce')
        
        return df_patients

    except Exception as e:
        st.error(f"Error fetching patient data from Firestore: {e}", icon="📄")
        return pd.DataFrame()

# --- Authentication Logic ---
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

    if db:
        with st.spinner('Loading data from Firebase...'):
            df_patients = get_firestore_data(db)

        st.sidebar.title("Controls")
        if st.sidebar.button("Logout", key="logout_button"):
            st.session_state.authenticated = False
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
        
        st.title("Kerala Migrant Health Dashboard ⚕️")
        
        tab1, tab2 = st.tabs(["Patients Overview", "Add Records"])

        with tab1:
            st.header("Migrant Patient Visits")
            if not df_patients.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Patients", df_patients['patient_id'].nunique())
                col2.metric("Total Visits", len(df_patients))
                col3.metric("Districts Covered", df_patients['District'].nunique())
                
                st.subheader("Reported Symptoms by District")
                symptoms_by_district = df_patients.groupby('District')['Reported Symptoms'].count().reset_index()
                symptoms_chart = alt.Chart(symptoms_by_district).mark_bar().encode(
                    x=alt.X('District', sort=None, axis=alt.Axis(labelAngle=-45)),
                    y='Reported Symptoms',
                    tooltip=['District', 'Reported Symptoms']
                ).interactive()
                st.altair_chart(symptoms_chart, use_container_width=True)
                
                st.subheader("All Patient Visits")
                st.dataframe(df_patients, use_container_width=True)
            else:
                st.warning("No patient data found or failed to load.")

        with tab2:
            st.header("Add New Records")
            st.subheader("➕ Add New Patient and Visit")
            with st.form(key='new_patient_form', clear_on_submit=True):
                new_patient_id = st.text_input("Unique Patient ID (e.g., KL-123)")
                new_name = st.text_input("Patient Name")
                new_date = st.text_input("Date of Visit (dd-mm-yyyy)")
                new_symptoms = st.text_area("Reported Symptoms")
                new_notes = st.text_area("Doctor Advice")
                new_district = st.selectbox("District", options=['Alappuzha', 'Ernakulam', 'Idukki', 'Kannur', 'Kasaragod', 'Kollam', 'Kottayam', 'Kozhikode', 'Malappuram', 'Palakkad', 'Pathanamthitta', 'Thiruvananthapuram', 'Thrissur', 'Wayanad'])
                new_vaccination_status = st.selectbox("Vaccination Status", options=['Fully Vaccinated', 'Partially Vaccinated', 'Not Vaccinated'])
                submit_patient_button = st.form_submit_button(label='Add Record')

                if submit_patient_button:
                    if not all([new_patient_id, new_name, new_date]):
                        st.warning("Please fill out Patient ID, Name, and Date.")
                    else:
                        try:
                            patient_doc_ref = db.collection('patients').doc(new_patient_id)
                            patient_doc = patient_doc_ref.get()

                            visit_data = {
                                'visitDate': new_date,
                                'symptoms': new_symptoms,
                                'location': new_district,
                                'notes': new_notes,
                                'recordedAt': firestore.SERVER_TIMESTAMP,
                                'vaccinationStatus': new_vaccination_status
                            }
                            
                            if not patient_doc.exists:
                                patient_data = {
                                    'name': new_name,
                                    'createdAt': firestore.SERVER_TIMESTAMP,
                                }
                                patient_doc_ref.set(patient_data)

                            patient_doc_ref.collection('visits').add(visit_data)
                            patient_doc_ref.update({'currentVaccinationStatus': new_vaccination_status})

                            st.success(f"Record for {new_patient_id} added!")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error adding record: {e}")
