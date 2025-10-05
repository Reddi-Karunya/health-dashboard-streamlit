import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# --- Firebase Imports ---
import firebase_admin
from firebase_admin import credentials, firestore
import os

# --- Set up the Streamlit page layout (should be at the very top) ---
st.set_page_config(layout="wide", page_title="Kerala Migrant Health Dashboard")

# --- Authentication Logic ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login to the Dashboard")
    with st.form(key='login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button(label='Log In')

    if login_button:
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.success("Logged in successfully!")
            st.rerun() # Rerun to switch to dashboard view
        else:
            st.error("Invalid username or password.")

# --- The Main Dashboard Code (Only runs if authenticated) ---
if st.session_state.authenticated:
    # --- Firebase Connection and Data Loading ---
    db = None

    try:
        if not firebase_admin._apps:
            # IMPORTANT: Replace with your actual Firebase key file
            cred = credentials.Certificate("health-project-afff3-firebase-adminsdk-fbsvc-d4407f2099.json")
            firebase_admin.initialize_app(cred)
        db = firestore.client()

        @st.cache_data(ttl=60) # Cache data for 60 seconds
        def get_firestore_data():
            patients_with_visits_data = []
            doctors_data = []

            try:
                # Fetch Patients and Visits Data from the nested structure
                patients_ref = db.collection('patients')
                for patient_doc in patients_ref.stream():
                    patient_data = patient_doc.to_dict()
                    patient_id = patient_doc.id

                    visits_ref = patient_doc.reference.collection('visits')
                    for visit_doc in visits_ref.stream():
                        visit_data = visit_doc.to_dict()
                        # Combine patient and visit data into a single record
                        combined_record = {
                            **patient_data, # Spreads patient's main info
                            **visit_data, # Spreads visit-specific info
                            'patient_id': patient_id,
                            'visit_id': visit_doc.id,
                        }
                        patients_with_visits_data.append(combined_record)
                        
                df_patients = pd.DataFrame(patients_with_visits_data)

                # Fetch Doctors Data (as before)
                doctors_ref = db.collection('doctors')
                for doc in doctors_ref.stream():
                    record = doc.to_dict()
                    record['doctor_id'] = doc.id
                    doctors_data.append(record)
                df_doctors = pd.DataFrame(doctors_data)

                # Standardize column names for consistency
                if not df_patients.empty:
                    df_patients = df_patients.rename(columns={
                        'name': 'Patient Name',
                        'location': 'Current Residence (District)',
                        'notes': 'Doctor Advice',
                        'visitDate': 'Date of Visit',
                        'symptoms': 'Reported Symptoms',
                        'currentVaccinationStatus': 'Vaccination Status',
                    })
                    # Convert date strings to datetime objects for filtering
                    df_patients['Date of Visit'] = pd.to_datetime(df_patients['Date of Visit'], format='%d-%m-%Y', errors='coerce')
                    # Ensure lat/lon for mapping, now using a new column
                    if 'lat' not in df_patients.columns: df_patients['lat'] = 0.0
                    if 'lon' not in df_patients.columns: df_patients['lon'] = 0.0

                if not df_doctors.empty:
                    df_doctors = df_doctors.rename(columns={
                        'Name': 'Doctor Name',
                        'Location': 'Doctor Location',
                        'Specialty': 'Specialty',
                        'Joining Date': 'Joining Date'
                    })
                    # Ensure lat/lon for mapping
                    if 'doctor_lat' not in df_doctors.columns: df_doctors['doctor_lat'] = 0.0
                    if 'doctor_lon' not in df_doctors.columns: df_doctors['doctor_lon'] = 0.0

                return df_patients, df_doctors

            except Exception as e:
                st.error(f"Error fetching data from Firestore: {e}")
                st.info("Please ensure your Firebase connection details are correct and your collections are populated.")
                return pd.DataFrame(), pd.DataFrame()

        df_patients, df_doctors = get_firestore_data()

        if df_patients.empty and df_doctors.empty:
            st.warning("No data available in either Firebase collection. Please ensure records are being added by the app.")

    except Exception as e:
        st.error(f"Could not connect to Firebase: {e}")
        st.info("Please check if the Firebase Admin SDK is installed (`pip install firebase-admin`) and your service account key path is correct.")
        df_patients = pd.DataFrame()
        df_doctors = pd.DataFrame()

    # --- Logout Button ---
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.rerun()

    # --- Dashboard Title and Description ---
    st.title("Kerala Migrant Health Dashboard ⚕️")
    st.markdown("### Public Health Surveillance for a Migrant Population")
    st.markdown("Use the filters on the left to analyze health and demographic data.")

    # --- Create a tabbed interface for Patients and Doctors ---
    tab1, tab2, tab3, tab4 = st.tabs(["Patients Overview", "Doctors Overview", "Combined Analysis", "Add Records"])

    with tab1:
        st.header("Migrant Patient Demographics & Visits")
        # Existing patient metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Total Patients", df_patients['patient_id'].nunique() if not df_patients.empty else 0)
        with col2: st.metric("Total Visits", len(df_patients))
        with col3: st.metric("Patient Districts", df_patients['Current Residence (District)'].nunique() if not df_patients.empty else 0)
        with col4: st.metric("Vaccination Statuses", df_patients['Vaccination Status'].nunique() if not df_patients.empty else 0)

        # Updated chart for reported symptoms by district
        st.subheader("Reported Symptoms by District")
        if not df_patients.empty:
            # Aggregate data to count symptoms per district
            symptoms_by_district = df_patients.groupby('Current Residence (District)')['Reported Symptoms'].count().reset_index()
            symptoms_by_district.columns = ['District', 'Number of Reported Symptoms']
            
            symptoms_chart = alt.Chart(symptoms_by_district).mark_bar().encode(
                x=alt.X('District', axis=alt.Axis(title='District', labelAngle=-45)),
                y='Number of Reported Symptoms',
                tooltip=['District', 'Number of Reported Symptoms']
            ).properties(title="Symptom Reports by District").interactive()
            st.altair_chart(symptoms_chart, use_container_width=True)
        else:
            st.info("No patient data available for this chart.")

        # Updated chart for vaccination status
        st.subheader("Patient Vaccination Status Distribution")
        if not df_patients.empty:
            vaccination_chart = alt.Chart(df_patients).mark_arc(outerRadius=120).encode(
                theta=alt.Theta(field="count()", type="quantitative"),
                color=alt.Color(field="Vaccination Status", type="nominal"),
                tooltip=["Vaccination Status", alt.Tooltip("count()", title="Number of Patients")]
            ).properties(title="Patient Vaccination Status").interactive()
            st.altair_chart(vaccination_chart, use_container_width=True)
        else:
            st.info("No patient data available for this chart.")

        st.subheader("All Patient Visits Table")
        if not df_patients.empty:
            st.dataframe(df_patients[[
                'patient_id',
                'Patient Name',
                'Date of Visit',
                'Reported Symptoms',
                'Current Residence (District)',
                'Vaccination Status',
                'Doctor Advice',
                'visit_id'
            ]], use_container_width=True)
        else:
            st.info("No patient visit data available.")
        
    # No changes to Tab 2 and 3 as they reference the same dataframes.
    with tab2:
        st.header("Doctor Demographics")
        col1, col2 = st.columns(2)
        with col1: st.metric("Total Doctors", len(df_doctors) if not df_doctors.empty else 0)
        with col2: st.metric("Doctor Specialties", df_doctors['Specialty'].nunique() if not df_doctors.empty and 'Specialty' in df_doctors.columns else 0)

        st.subheader("Doctor Specialty Distribution")
        if not df_doctors.empty and 'Specialty' in df_doctors.columns:
            specialty_chart = alt.Chart(df_doctors).mark_bar().encode(
                x=alt.X('Specialty', axis=alt.Axis(title='Specialty', labelAngle=-45)),
                y='count()',
                tooltip=['Specialty', 'count()']
            ).properties(title="Doctor Specialty Distribution").interactive()
            st.altair_chart(specialty_chart, use_container_width=True)
        else: st.info("No doctor data for Specialty Distribution.")

        st.subheader("Full Doctor Data Table")
        if not df_doctors.empty:
            st.dataframe(df_doctors, use_container_width=True)
        else: st.info("No doctor data available.")

    with tab3:
        st.header("Combined Analysis")
        st.markdown("Here you can build visualizations that link doctors to patients, or analyze distribution across both.")

        # Example: Patients by district
        if not df_patients.empty:
            st.subheader("Patient Density by District")
            patient_counts = df_patients['Current Residence (District)'].value_counts().reset_index()
            patient_counts.columns = ['District', 'Patient Count']

            chart = alt.Chart(patient_counts).mark_bar().encode(
                x=alt.X('District', axis=alt.Axis(labelAngle=-45)),
                y='Patient Count',
                color=alt.Color('District', legend=None),
                tooltip=['District', 'Patient Count']
            ).properties(title='Patient Count by District')
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Not enough data for combined analysis.")
            
    with tab4:
        st.header("Add New Records")

        if db:
            # Add New Migrant Record (Patient)
            st.subheader("➕ Add New Patient Record")
            with st.form(key='new_patient_form'):
                # Your form fields go here
                new_patient_id = st.text_input("Unique Patient ID (e.g., KL-123)", max_chars=10)
                new_name = st.text_input("Patient Name", max_chars=50)
                new_date = st.text_input("Date of Visit (dd-mm-yyyy)")
                new_symptoms = st.text_area("Reported Symptoms")
                new_notes = st.text_area("Additional Notes (Doctor Advice)")
                new_district = st.selectbox("Current Location (District)", options=[
                    'Alappuzha', 'Ernakulam', 'Idukki', 'Kannur', 'Kasaragod', 'Kollam',
                    'Kottayam', 'Kozhikode', 'Malappuram', 'Palakkad', 'Pathanamthitta',
                    'Thiruvananthapuram', 'Thrissur', 'Wayanad'
                ])
                new_vaccination_status = st.selectbox("Vaccination Records", options=[
                    'Fully Vaccinated', 'Partially Vaccinated', 'Not Vaccinated'
                ])

                submit_patient_button = st.form_submit_button(label='Add Patient Record to Firebase')

                if submit_patient_button:
                    try:
                        # Validation as per Flutter code
                        if not new_patient_id:
                            st.error("Unique Patient ID cannot be empty.")
                            st.stop()
                        if not new_date:
                            st.error("Date of Visit cannot be empty.")
                            st.stop()
                        
                        # Data to be written
                        patient_data = {
                            'name': new_name,
                            'currentVaccinationStatus': new_vaccination_status,
                            'createdAt': firestore.SERVER_TIMESTAMP,
                        }
                        visit_data = {
                            'visitDate': new_date,
                            'symptoms': new_symptoms,
                            'location': new_district,
                            'notes': new_notes,
                            'recordedAt': firestore.SERVER_TIMESTAMP,
                        }

                        # Check if patient already exists
                        patient_doc_ref = db.collection('patients').document(new_patient_id)
                        patient_doc = patient_doc_ref.get()

                        if not patient_doc.exists:
                            # New patient, create patient document and a new visit sub-document
                            patient_doc_ref.set(patient_data)
                            patient_doc_ref.collection('visits').add(visit_data)
                        else:
                            # Existing patient, only add a new visit sub-document and update vaccination status
                            patient_doc_ref.collection('visits').add(visit_data)
                            patient_doc_ref.update({
                                'currentVaccinationStatus': new_vaccination_status,
                            })

                        st.success(f"New patient record for {new_patient_id} added successfully! Dashboard will update shortly.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error adding patient record to Firebase: {e}")

            st.markdown("---")

            # Add New Doctor Record
            st.subheader("➕ Add New Doctor Record")
            with st.form(key='new_doctor_form'):
                specialty_options = df_doctors['Specialty'].unique().tolist() if not df_doctors.empty and 'Specialty' in df_doctors.columns else ['General Physician', 'Pediatrician', 'Cardiologist', 'Dentist', 'Orthopedic']
                location_options = df_doctors['Doctor Location'].unique().tolist() if not df_doctors.empty and 'Doctor Location' in df_doctors.columns else [
                    'Alappuzha', 'Ernakulam', 'Idukki', 'Kannur', 'Kasaragod', 'Kollam',
                    'Kottayam', 'Kozhikode', 'Malappuram', 'Palakkad', 'Pathanamthitta',
                    'Thiruvananthapuram', 'Thrissur', 'Wayanad'
                ]
                new_doctor_name = st.text_input("Doctor Name", max_chars=50)
                new_doctor_specialty = st.selectbox("Specialty", options=specialty_options)
                new_doctor_location = st.selectbox("Location", options=location_options)
                new_doctor_phone = st.text_input("Phone Number", max_chars=15)
                new_doctor_email = st.text_input("Email", max_chars=50)

                submit_doctor_button = st.form_submit_button(label='Add Doctor Record to Firebase')

                if submit_doctor_button:
                    try:
                        new_doctor_data = {
                            'Name': new_doctor_name, 'Specialty': new_doctor_specialty,
                            'Location': new_doctor_location, 'Phone': new_doctor_phone,
                            'Email': new_doctor_email, 'Joining Date': firestore.SERVER_TIMESTAMP
                        }
                        db.collection('doctors').add(new_doctor_data) # <--- Using 'doctors' collection
                        st.success("New doctor record added to Firebase successfully! Dashboard will update shortly.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error adding doctor record to Firebase: {e}")
        else:
            st.warning("Firebase connection not established. Cannot add records.")

    # --- Sidebar Filters ---
    st.sidebar.header("Patient Data Filters")

    # Filter by Current Residence (for patients)
    selected_residence = st.sidebar.multiselect(
        "Select Patient Current Residence",
        options=df_patients['Current Residence (District)'].unique().tolist() if not df_patients.empty else [],
        default=df_patients['Current Residence (District)'].unique().tolist() if not df_patients.empty else []
    )

    # Filter by Date Range (for patients)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Patient Visit Date Range")
    if not df_patients.empty and 'Date of Visit' in df_patients.columns and not df_patients['Date of Visit'].isnull().all():
        min_date_df = df_patients['Date of Visit'].min().date()
        max_date_df = df_patients['Date of Visit'].max().date()
        date_range_value = (min_date_df, max_date_df)
    else:
        min_date_df = datetime.now().date()
        max_date_df = datetime.now().date()
        date_range_value = (min_date_df, max_date_df)
        st.sidebar.info("No valid 'Date of Visit' found for patient date range filter.")


    patient_date_range = st.sidebar.date_input(
        "Select patient date range",
        value=date_range_value,
        min_value=min_date_df,
        max_value=max_date_df
    )

    # Apply filters to patient data
    filtered_df_patients_sidebar = pd.DataFrame()
    if not df_patients.empty and len(patient_date_range) == 2:
        start_date_patient, end_date_patient = patient_date_range
        filtered_df_patients_sidebar = df_patients[
            (df_patients['Current Residence (District)'].isin(selected_residence)) &
            (df_patients['Date of Visit'].dt.date >= start_date_patient) &
            (df_patients['Date of Visit'].dt.date <= end_date_patient)
        ]
    elif not df_patients.empty:
         filtered_df_patients_sidebar = df_patients[
            (df_patients['Current Residence (District)'].isin(selected_residence))
        ]
    
    # --- Interactive Location-based List (for Patients, in sidebar context) ---
    st.sidebar.header("Patient Visit Records by District")
    available_patient_locations = df_patients['Current Residence (District)'].unique().tolist() if not df_patients.empty else []
    selected_patient_location_for_list = st.sidebar.selectbox(
        '**View Patients by Current Residence:**',
        ['Select a Location'] + available_patient_locations
    )

    if selected_patient_location_for_list != 'Select a Location':
        patient_location_list_df = df_patients[df_patients['Current Residence (District)'] == selected_patient_location_for_list]
        st.sidebar.markdown(f"**Patients in {selected_patient_location_for_list}**")
        st.sidebar.dataframe(patient_location_list_df[['Patient Name', 'Date of Visit', 'Reported Symptoms']], use_container_width=True)
    else:
        st.sidebar.info("Select a location to see a list of patient visits.")