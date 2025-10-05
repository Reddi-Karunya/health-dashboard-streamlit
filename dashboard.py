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
st.set_page_config(layout="wide", page_title="Kerala Migrant Health Dashboard")

# --- Firebase Connection ---
# FINAL, ROBUST VERSION: Handles secrets, project ID, and string parsing.
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

# --- Data Fetching Function ---
@st.cache_data(ttl=60)
def get_firestore_data(_db):
    if _db is None:
        return pd.DataFrame(), pd.DataFrame()

    patients_with_visits_data = []
    doctors_data = []

    try:
        # Fetch Patients and Visits Data
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

        # Fetch Doctors Data
        doctors_ref = _db.collection('doctors')
        for doc in doctors_ref.stream():
            record = doc.to_dict()
            record['doctor_id'] = doc.id
            doctors_data.append(record)
        df_doctors = pd.DataFrame(doctors_data)

        # --- Data Cleaning and Formatting ---
        if not df_patients.empty:
            df_patients = df_patients.rename(columns={
                'name': 'Patient Name', 'location': 'Current Residence (District)',
                'notes': 'Doctor Advice', 'visitDate': 'Date of Visit',
                'symptoms': 'Reported Symptoms', 'currentVaccinationStatus': 'Vaccination Status',
            })
            df_patients['Date of Visit'] = pd.to_datetime(df_patients['Date of Visit'], format='%d-%m-%Y', errors='coerce')

        if not df_doctors.empty:
            df_doctors = df_doctors.rename(columns={
                'Name': 'Doctor Name', 'Location': 'Doctor Location', 'Specialty': 'Specialty'
            })

        return df_patients, df_doctors
    except Exception as e:
        st.error(f"Error fetching data from Firestore: {e}")
        return pd.DataFrame(), pd.DataFrame()

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
        with st.spinner('Loading dashboard data...'):
            df_patients, df_doctors = get_firestore_data(db)

        # --- Sidebar ---
        st.sidebar.markdown("---")
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
            
        st.sidebar.header("Patient Data Filters")
        if not df_patients.empty:
            selected_residence = st.sidebar.multiselect(
                "Filter by Patient District",
                options=sorted(df_patients['Current Residence (District)'].unique()),
                default=sorted(df_patients['Current Residence (District)'].unique())
            )
            df_patients = df_patients[df_patients['Current Residence (District)'].isin(selected_residence)]
        else:
            st.sidebar.info("No patient data to filter.")

        # --- Main Page ---
        st.title("Kerala Migrant Health Dashboard ⚕️")
        
        tab1, tab2, tab3, tab4 = st.tabs(["Patients Overview", "Doctors Overview", "Combined Analysis", "Add Records"])

        with tab1: # All Patient Features Restored
            st.header("Migrant Patient Demographics & Visits")
            if not df_patients.empty:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Patients", df_patients['patient_id'].nunique())
                col2.metric("Total Visits", len(df_patients))
                col3.metric("Patient Districts", df_patients['Current Residence (District)'].nunique())
                col4.metric("Vaccination Statuses", df_patients['Vaccination Status'].nunique())

                st.subheader("Reported Symptoms by District")
                symptoms_by_district = df_patients.groupby('Current Residence (District)')['Reported Symptoms'].count().reset_index()
                symptoms_by_district.columns = ['District', 'Number of Reported Symptoms']
                symptoms_chart = alt.Chart(symptoms_by_district).mark_bar().encode(
                    x=alt.X('District', axis=alt.Axis(title='District', labelAngle=-45)),
                    y='Number of Reported Symptoms',
                    tooltip=['District', 'Number of Reported Symptoms']
                ).interactive()
                st.altair_chart(symptoms_chart, use_container_width=True)

                st.subheader("Patient Vaccination Status Distribution")
                vaccination_chart = alt.Chart(df_patients).mark_arc(outerRadius=120).encode(
                    theta=alt.Theta(field="count()", type="quantitative"),
                    color=alt.Color(field="Vaccination Status", type="nominal"),
                    tooltip=["Vaccination Status", alt.Tooltip("count()", title="Number of Patients")]
                ).interactive()
                st.altair_chart(vaccination_chart, use_container_width=True)

                st.subheader("All Patient Visits Table")
                st.dataframe(df_patients[['patient_id', 'Patient Name', 'Date of Visit', 'Reported Symptoms', 'Current Residence (District)', 'Vaccination Status']], use_container_width=True)
            else:
                st.info("No patient data to display.")

        with tab2: # All Doctor Features Restored
            st.header("Doctor Demographics")
            if not df_doctors.empty:
                col1, col2 = st.columns(2)
                col1.metric("Total Doctors", len(df_doctors))
                col2.metric("Doctor Specialties", df_doctors['Specialty'].nunique() if 'Specialty' in df_doctors.columns else 0)
                st.subheader("Full Doctor Data Table")
                st.dataframe(df_doctors, use_container_width=True)
            else:
                st.info("No doctor data to display.")

        with tab3: # All Combined Features Restored
            st.header("Combined Analysis")
            if not df_patients.empty:
                st.subheader("Patient Density by District")
                patient_counts = df_patients['Current Residence (District)'].value_counts().reset_index()
                patient_counts.columns = ['District', 'Patient Count']
                chart = alt.Chart(patient_counts).mark_bar().encode(
                    x=alt.X('District', axis=alt.Axis(labelAngle=-45)),
                    y='Patient Count',
                    tooltip=['District', 'Patient Count']
                ).interactive()
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No patient data for combined analysis.")

        with tab4: # All "Add Records" Features Restored and Fixed
            st.header("Add New Records")
            st.subheader("➕ Add New Patient Record")
            with st.form(key='new_patient_form', clear_on_submit=True):
                new_patient_id = st.text_input("Unique Patient ID (e.g., KL-123)")
                new_name = st.text_input("Patient Name")
                new_date = st.text_input("Date of Visit (dd-mm-yyyy)")
                new_symptoms = st.text_area("Reported Symptoms")
                new_notes = st.text_area("Additional Notes")
                new_district = st.selectbox("District", options=sorted(_keralaDistricts))
                new_vaccination_status = st.selectbox("Vaccination Status", options=['Fully Vaccinated', 'Partially Vaccinated', 'Not Vaccinated'])
                submit_patient_button = st.form_submit_button(label='Add Patient Record')

                if submit_patient_button:
                    if not all([new_patient_id, new_date]):
                        st.warning("Patient ID and Date of Visit are required.")
                    else:
                        try:
                            # BUG FIX: Using .doc() instead of .document()
                            patient_doc_ref = db.collection('patients').doc(new_patient_id)
                            patient_doc = patient_doc_ref.get()

                            visit_data = {'visitDate': new_date, 'symptoms': new_symptoms, 'location': new_district, 'notes': new_notes, 'recordedAt': firestore.SERVER_TIMESTAMP}
                            
                            if not patient_doc.exists:
                                patient_doc_ref.set({'name': new_name, 'createdAt': firestore.SERVER_TIMESTAMP})
                            
                            patient_doc_ref.collection('visits').add(visit_data)
                            patient_doc_ref.update({'currentVaccinationStatus': new_vaccination_status})
                            st.success(f"Record for {new_patient_id} added!")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error adding record: {e}")

            st.markdown("---")
            st.subheader("➕ Add New Doctor Record")
            with st.form(key='new_doctor_form', clear_on_submit=True):
                new_doctor_name = st.text_input("Doctor Name")
                new_doctor_specialty = st.text_input("Specialty")
                submit_doctor_button = st.form_submit_button(label='Add Doctor Record')
                if submit_doctor_button and new_doctor_name:
                    try:
                        db.collection('doctors').add({'Name': new_doctor_name, 'Specialty': new_doctor_specialty})
                        st.success(f"Doctor {new_doctor_name} added!")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Error adding doctor: {e}")

    else:
        st.error("Could not connect to Firebase. Please check your credentials and network connection.")
