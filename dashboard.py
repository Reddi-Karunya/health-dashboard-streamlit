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
@st.cache_resource
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            if "firebase_key" in st.secrets:
                cred_dict = ast.literal_eval(st.secrets["firebase_key"]) if isinstance(st.secrets["firebase_key"], str) else dict(st.secrets["firebase_key"])
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'projectId': cred_dict['project_id']})
            else: # For local development
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

    patients_with_visits_data = []
    doctors_data = []
    try:
        # Fetch Patients and Visits
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

        # Fetch Doctors
        doctors_ref = _db.collection('doctors')
        for doc in doctors_ref.stream():
            record = doc.to_dict()
            record['doctor_id'] = doc.id
            doctors_data.append(record)
        df_doctors = pd.DataFrame(doctors_data)

        # --- Data Cleaning ---
        if not df_patients.empty:
            df_patients = df_patients.rename(columns={
                'name': 'Patient Name', 'location': 'District', 'notes': 'Doctor Advice',
                'visitDate': 'Date of Visit', 'symptoms': 'Reported Symptoms',
                'currentVaccinationStatus': 'Vaccination Status',
            })
            df_patients['Date of Visit'] = pd.to_datetime(df_patients['Date of Visit'], format='%d-%m-%Y', errors='coerce')
        if not df_doctors.empty:
            df_doctors = df_doctors.rename(columns={'Name': 'Doctor Name', 'Location': 'Doctor Location', 'Specialty': 'Specialty'})
        
        return df_patients, df_doctors
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

    _keralaDistricts = ['Alappuzha', 'Ernakulam', 'Idukki', 'Kannur', 'Kasaragod', 'Kollam', 'Kottayam', 'Kozhikode', 'Malappuram', 'Palakkad', 'Pathanamthitta', 'Thiruvananthapuram', 'Thrissur', 'Wayanad']
    
    # Sample coordinates for the map feature
    district_coords = {
        'Thiruvananthapuram': {'lat': 8.5241, 'lon': 76.9366}, 'Kollam': {'lat': 8.8932, 'lon': 76.6141},
        'Pathanamthitta': {'lat': 9.2647, 'lon': 76.7870}, 'Alappuzha': {'lat': 9.4981, 'lon': 76.3388},
        'Kottayam': {'lat': 9.5916, 'lon': 76.5222}, 'Idukki': {'lat': 9.8530, 'lon': 76.9800},
        'Ernakulam': {'lat': 9.9816, 'lon': 76.2999}, 'Thrissur': {'lat': 10.5276, 'lon': 76.2144},
        'Palakkad': {'lat': 10.7867, 'lon': 76.6548}, 'Malappuram': {'lat': 11.0514, 'lon': 76.0711},
        'Kozhikode': {'lat': 11.2588, 'lon': 75.7804}, 'Wayanad': {'lat': 11.6854, 'lon': 76.1320},
        'Kannur': {'lat': 11.8745, 'lon': 75.3704}, 'Kasaragod': {'lat': 12.5089, 'lon': 74.9880}
    }

    if db:
        with st.spinner('Loading dashboard data...'):
            df_patients, df_doctors = get_firestore_data(db)
        
        # Add coordinates to patient dataframe for the map
        if not df_patients.empty:
            df_patients['lat'] = df_patients['District'].map(lambda x: district_coords.get(x, {}).get('lat'))
            df_patients['lon'] = df_patients['District'].map(lambda x: district_coords.get(x, {}).get('lon'))

        # --- Sidebar ---
        st.sidebar.markdown("---")
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.cache_data.clear(); st.cache_resource.clear()
            st.rerun()
            
        st.sidebar.header("Patient Data Filters")
        if not df_patients.empty:
            unique_districts = sorted(df_patients['District'].unique())
            selected_districts = st.sidebar.multiselect("Filter by Patient District", options=unique_districts, default=unique_districts)
            
            min_date = df_patients['Date of Visit'].min().date()
            max_date = df_patients['Date of Visit'].max().date()
            date_range = st.sidebar.date_input("Filter by Visit Date", value=(min_date, max_date), min_value=min_date, max_value=max_date)

            # Apply filters
            start_date, end_date = date_range
            df_patients_filtered = df_patients[
                (df_patients['District'].isin(selected_districts)) &
                (df_patients['Date of Visit'].dt.date >= start_date) &
                (df_patients['Date of Visit'].dt.date <= end_date)
            ]
        else:
            st.sidebar.info("No patient data to filter.")
            df_patients_filtered = pd.DataFrame()

        # --- Main Page ---
        st.title("Kerala Migrant Health Dashboard ⚕️")
        tab1, tab2, tab3, tab4 = st.tabs(["Patients Overview", "Doctors Overview", "Combined Analysis", "Add Records"])

        with tab1:
            st.header("Migrant Patient Demographics & Visits")
            if not df_patients_filtered.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Patients", df_patients_filtered['patient_id'].nunique())
                col2.metric("Total Visits", len(df_patients_filtered))
                col3.metric("Districts Covered", df_patients_filtered['District'].nunique())
                
                st.subheader("Patient Visit Map")
                st.map(df_patients_filtered[['lat', 'lon']].dropna())

                st.subheader("Reported Symptoms by District")
                symptoms_chart = alt.Chart(df_patients_filtered).mark_bar().encode(x='District:N', y='count():Q', tooltip=['District', 'count()']).interactive()
                st.altair_chart(symptoms_chart, use_container_width=True)
                
                st.subheader("All Filtered Patient Visits")
                st.dataframe(df_patients_filtered, use_container_width=True)
            else:
                st.info("No patient data to display for the selected filters.")

        # ... (Tabs 2, 3, 4 remain the same as the full-featured version)
        with tab2:
            st.header("Doctor Demographics")
            if not df_doctors.empty:
                st.metric("Total Doctors", len(df_doctors))
                st.dataframe(df_doctors, use_container_width=True)
            else:
                st.info("No doctor data to display.")
        with tab3:
            st.header("Combined Analysis")
            if not df_patients_filtered.empty:
                st.subheader("Patient Density by District")
                patient_counts = df_patients_filtered['District'].value_counts().reset_index()
                patient_counts.columns = ['District', 'Patient Count']
                chart = alt.Chart(patient_counts).mark_bar().encode(x='District', y='Patient Count', tooltip=['District', 'Patient Count']).interactive()
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No patient data for combined analysis.")
        with tab4:
            st.header("Add New Records")
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
        st.error("Could not connect to Firebase. Please check credentials and network.")
