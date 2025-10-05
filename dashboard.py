import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os

st.set_page_config(layout="wide", page_title="Kerala Migrant Health Dashboard")

# --- Authentication ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Login to the Dashboard")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Log In")

    if login_button:
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.success("Login successful!")
            st.rerun()
        else:
            st.error("Invalid credentials")

if st.session_state.authenticated:

    # --- Firebase Initialization ---
    @st.cache_resource
    def init_firebase():
        try:
            # Read secrets from Streamlit Cloud
            firebase_config = st.secrets["firebase"]
            json_key = json.loads(firebase_config["service_account_key"])
            cred = credentials.Certificate(json_key)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            st.error(f"Firebase initialization failed: {e}")
            return None

    db = init_firebase()

    @st.cache_data(ttl=60)
    def get_data():
        patients_data, doctors_data = [], []
        try:
            # --- Patients Collection ---
            patients_ref = db.collection("patients")
            for patient_doc in patients_ref.stream():
                patient = patient_doc.to_dict()
                patient_id = patient_doc.id
                visits_ref = patient_doc.reference.collection("visits")
                for visit_doc in visits_ref.stream():
                    visit = visit_doc.to_dict()
                    patients_data.append({
                        **patient,
                        **visit,
                        "patient_id": patient_id,
                        "visit_id": visit_doc.id
                    })
            df_patients = pd.DataFrame(patients_data)

            # --- Doctors Collection ---
            doctors_ref = db.collection("doctors")
            for doc in doctors_ref.stream():
                record = doc.to_dict()
                record["doctor_id"] = doc.id
                doctors_data.append(record)
            df_doctors = pd.DataFrame(doctors_data)

            return df_patients, df_doctors
        except Exception as e:
            st.error(f"Error fetching Firestore data: {e}")
            return pd.DataFrame(), pd.DataFrame()

    if db:
        df_patients, df_doctors = get_data()
    else:
        st.stop()

    # --- Sidebar: Logout ---
    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.rerun()

    st.title("⚕️ Kerala Migrant Health Dashboard")
    st.markdown("### Public Health Surveillance for Migrant Populations")

    tab1, tab2, tab3, tab4 = st.tabs(["Patients Overview", "Doctors Overview", "Combined Analysis", "Add Records"])

    # ---------------------- TAB 1: PATIENTS ----------------------
    with tab1:
        st.header("🧍‍♂️ Patient Overview")
        if not df_patients.empty:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Patients", df_patients["patient_id"].nunique())
            col2.metric("Total Visits", len(df_patients))
            col3.metric("Districts Covered", df_patients["location"].nunique())

            st.subheader("Reported Symptoms by District")
            symptoms_chart = alt.Chart(df_patients).mark_bar().encode(
                x=alt.X("location:N", title="District"),
                y=alt.Y("count():Q", title="Number of Reports"),
                tooltip=["location", "count()"]
            ).interactive()
            st.altair_chart(symptoms_chart, use_container_width=True)

            st.subheader("Full Patient Visits Data")
            st.dataframe(df_patients, use_container_width=True)
        else:
            st.info("No patient data found.")

    # ---------------------- TAB 2: DOCTORS ----------------------
    with tab2:
        st.header("👩‍⚕️ Doctors Overview")
        if not df_doctors.empty:
            st.metric("Total Doctors", len(df_doctors))
            st.metric("Unique Specialties", df_doctors["Specialty"].nunique() if "Specialty" in df_doctors.columns else 0)

            st.subheader("Doctor Specialty Distribution")
            if "Specialty" in df_doctors.columns:
                chart = alt.Chart(df_doctors).mark_bar().encode(
                    x="Specialty:N", y="count():Q", tooltip=["Specialty", "count()"]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)

            st.subheader("Full Doctor Records")
            st.dataframe(df_doctors, use_container_width=True)
        else:
            st.info("No doctor records found.")

    # ---------------------- TAB 3: COMBINED ----------------------
    with tab3:
        st.header("📊 Combined Analysis")
        if not df_patients.empty:
            chart = alt.Chart(df_patients).mark_bar().encode(
                x="location:N", y="count():Q", tooltip=["location", "count()"]
            ).properties(title="Patient Distribution by District")
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Not enough data for combined view.")

    # ---------------------- TAB 4: ADD RECORDS ----------------------
    with tab4:
        st.header("➕ Add New Records")

        if db:
            st.subheader("Add New Patient")
            with st.form("add_patient_form"):
                pid = st.text_input("Patient ID (e.g., KL-001)")
                name = st.text_input("Patient Name")
                date = st.text_input("Visit Date (dd-mm-yyyy)")
                symptoms = st.text_area("Symptoms")
                location = st.text_input("District")
                vaccination = st.selectbox("Vaccination Status", ["Fully Vaccinated", "Partially Vaccinated", "Not Vaccinated"])
                submit = st.form_submit_button("Add Patient Record")

                if submit and pid:
                    try:
                        patient_ref = db.collection("patients").document(pid)
                        patient_ref.set({"name": name, "currentVaccinationStatus": vaccination}, merge=True)
                        patient_ref.collection("visits").add({
                            "visitDate": date, "symptoms": symptoms, "location": location,
                            "createdAt": firestore.SERVER_TIMESTAMP
                        })
                        st.success(f"Patient {pid} record added.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error adding patient: {e}")

            st.subheader("Add New Doctor")
            with st.form("add_doctor_form"):
                name = st.text_input("Doctor Name")
                specialty = st.text_input("Specialty")
                location = st.text_input("Location")
                phone = st.text_input("Phone Number")
                email = st.text_input("Email")
                submit_doc = st.form_submit_button("Add Doctor Record")

                if submit_doc:
                    try:
                        db.collection("doctors").add({
                            "Name": name, "Specialty": specialty, "Location": location,
                            "Phone": phone, "Email": email, "CreatedAt": firestore.SERVER_TIMESTAMP
                        })
                        st.success("Doctor record added.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error adding doctor: {e}")
