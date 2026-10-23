import hmac
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="CCD | Admin V2.0", page_icon="📍", layout="wide", initial_sidebar_state="collapsed")
st.markdown('''<style>.block-container{padding-top:1rem;max-width:1450px}h1,h2,h3{color:#084a82}div[data-testid="stMetric"]{border:1px solid #dce6ef;border-radius:12px;padding:12px;background:#f8fbff}div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px} .stButton>button[kind="primary"]{background:#00815d;border:0}@media(max-width:700px){.block-container{padding:0.7rem}.stDataFrame{font-size:12px}}</style>''', unsafe_allow_html=True)
st.title("CUSTOMER CARE DAY")
st.caption("WE CARE. YOU DRIVE. | Admin Dashboard V2.8 | Pakistan Standard Time (PKT)")

required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ADMIN_PASSWORD"]
missing = [key for key in required if not st.secrets.get(key)]
if missing:
    st.error("Missing Streamlit Secrets: " + ", ".join(missing))
    st.stop()
if not st.session_state.get("admin_ok", False):
    with st.form("login"):
        password = st.text_input("Administrator password", type="password")
        login = st.form_submit_button("Sign in", type="primary")
    if login:
        if hmac.compare_digest(password, str(st.secrets["ADMIN_PASSWORD"])):
            st.session_state.admin_ok = True
            st.rerun()
        st.error("Incorrect password")
    st.stop()

BASE = str(st.secrets["SUPABASE_URL"]).rstrip("/")
KEY = str(st.secrets["SUPABASE_SERVICE_ROLE_KEY"])
if not BASE.startswith("https://") or not BASE.endswith(".supabase.co"):
    st.error("SUPABASE_URL must be the project URL ending in .supabase.co")
    st.stop()

with st.sidebar:
    st.success("Administrator signed in")
    if st.button("Sign out", use_container_width=True):
        st.session_state.admin_ok = False
        st.rerun()
    if st.button("Refresh from Supabase", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# V2.0 — authorized administrator master upload. The database remains the
# source of truth. No upload is committed until preview and confirmation.
st.subheader("📍 Outlet GPS Master")
st.caption("Upload an Excel (.xlsx) or CSV master with Code, Name, Latitude and Longitude. "
           "Existing outlet codes are updated; new codes are added. Missing codes are never deleted.")

@st.cache_data(ttl=120, show_spinner=False)
def load_outlet_master():
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    result = []
    for offset in range(0, 100000, 1000):
        response = requests.get(f"{BASE}/rest/v1/outlets", headers=headers,
            params={"select":"code,name,latitude,longitude",
                    "order":"code.asc", "limit":1000, "offset":offset}, timeout=30)
        response.raise_for_status()
        page = response.json()
        result.extend(page)
        if len(page) < 1000:
            return pd.DataFrame(result)
    raise RuntimeError("Outlet Master exceeds 100,000 rows; upload disabled until pagination is extended.")

def normalize_outlet_master(upload):
    if upload.name.lower().endswith(".csv"):
        raw = pd.read_csv(upload, dtype=str, keep_default_na=False)
    else:
        raw = pd.read_excel(upload, dtype=str, engine="openpyxl", keep_default_na=False)
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    aliases = {"outlet_code":"code", "outlet_name":"name", "lat":"latitude",
               "lattitude":"latitude", "lon":"longitude", "long":"longitude",
               "lng":"longitude", "langitude":"longitude"}
    raw = raw.rename(columns={c:aliases.get(c,c) for c in raw.columns})
    required_cols = ["code","name","latitude","longitude"]
    if any(list(raw.columns).count(c) != 1 for c in required_cols):
        raise ValueError("File must have exactly one column each for Code, Name, Latitude, Longitude.")
    master = raw[required_cols].copy()
    master["code"] = master["code"].astype(str).str.strip()
    master["name"] = master["name"].astype(str).str.strip()
    # Avoid accepting numeric codes accidentally converted to 114723.0
    master["code"] = master["code"].str.replace(r"\\.0$", "", regex=True)
    master["latitude"] = pd.to_numeric(master["latitude"], errors="coerce")
    master["longitude"] = pd.to_numeric(master["longitude"], errors="coerce")
    issues = []
    for idx, r in master.iterrows():
        errors = []
        if not r["code"] or not r["code"].isdigit():
            errors.append("Code must contain digits")
        if not r["name"] or len(r["name"]) > 200:
            errors.append("Name is blank or too long")
        if pd.isna(r["latitude"]) or not -90 <= r["latitude"] <= 90:
            errors.append("Invalid latitude")
        if pd.isna(r["longitude"]) or not -180 <= r["longitude"] <= 180:
            errors.append("Invalid longitude")
        if errors:
            issues.append({"Excel row": idx+2, "Code": r["code"], "Issue": "; ".join(errors)})
    duplicated = master["code"].duplicated(keep=False)
    for idx, r in master.loc[duplicated].iterrows():
        issues.append({"Excel row":idx+2, "Code":r["code"], "Issue":"Duplicate code in upload"})
    return master, pd.DataFrame(issues)

with st.expander("📤 Upload / update Outlet Master", expanded=False):
    try:
        current_master = load_outlet_master()
        st.caption(f"Current registered outlets: {len(current_master):,}")
        st.dataframe(current_master, use_container_width=True, hide_index=True)
        current_excel = BytesIO()
        with pd.ExcelWriter(current_excel, engine="openpyxl") as writer:
            current_master.to_excel(writer, sheet_name="Outlet Master", index=False)
        st.download_button("⬇️ Download current master", current_excel.getvalue(),
            file_name="CCD_Outlet_Master_Current.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        master_available = True
    except Exception as exc:
        st.error(f"Cannot retrieve Outlet Master: {exc}")
        master_available = False
        current_master = pd.DataFrame(columns=["code","name","latitude","longitude"])

    template = BytesIO()
    with pd.ExcelWriter(template, engine="openpyxl") as writer:
        pd.DataFrame([{"Code":"114723", "Name":"Test Outlet 114723",
                       "Latitude":24.8912, "Longitude":67.07735}]).to_excel(
                           writer, sheet_name="Outlet Master", index=False)
    st.download_button("⬇️ Download Excel master template", template.getvalue(),
        file_name="CCD_Outlet_Master_Template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upload = st.file_uploader("Select master file", type=["xlsx","csv"], key="outlet_master_v20")
    if upload is not None and master_available:
        if upload.size > 5_000_000:
            st.error("File exceeds 5 MB. Split it into smaller uploads.")
        else:
            try:
                proposed, issues = normalize_outlet_master(upload)
                st.write(f"**Rows received:** {len(proposed):,}")
                if proposed.empty:
                    st.error("The uploaded file contains no outlet records.")
                elif not issues.empty:
                    st.error("Upload blocked. Correct the following errors and upload again.")
                    st.dataframe(issues, use_container_width=True, hide_index=True)
                else:
                    existing_codes = set(current_master["code"].astype(str))
                    proposed["Action"] = proposed["code"].map(
                        lambda c: "Update existing" if c in existing_codes else "Add new")
                    st.metric("New outlets", int((proposed["Action"]=="Add new").sum()))
                    st.metric("Existing outlets to update", int((proposed["Action"]=="Update existing").sum()))
                    st.dataframe(proposed, use_container_width=True, hide_index=True)
                    st.warning("Confirming will overwrite the name and GPS coordinates of matching outlet codes. "
                               "Existing attendance records are not deleted. Historical distance calculations "
                               "may change because the reporting view joins the current outlet master.")
                    confirm = st.checkbox("I have reviewed the master and approve these changes",
                                          key="confirm_outlet_master_v20")
                    if st.button("Apply outlet master to Supabase", type="primary",
                                 disabled=not confirm, key="apply_outlet_master_v20"):
                        payload = proposed[["code","name","latitude","longitude"]].to_dict("records")
                        headers = {"apikey":KEY, "Authorization":f"Bearer {KEY}",
                                   "Content-Type":"application/json",
                                   "Prefer":"resolution=merge-duplicates,return=minimal"}
                        # Small batches prevent oversized requests; report partial failures explicitly.
                        succeeded = 0
                        for begin in range(0,len(payload),100):
                            batch = payload[begin:begin+100]
                            response = requests.post(f"{BASE}/rest/v1/outlets",
                                headers=headers, params={"on_conflict":"code"},
                                json=batch, timeout=40)
                            if not response.ok:
                                st.error(f"Upload stopped after {succeeded} records. "
                                         f"Supabase HTTP {response.status_code}: {response.text[:300]}")
                                break
                            succeeded += len(batch)
                        if succeeded == len(payload):
                            st.success(f"Outlet Master synchronized successfully: {succeeded} records.")
                        if succeeded:
                            st.cache_data.clear()
            except Exception as exc:
                st.error(f"Could not process master file: {exc}")

@st.cache_data(ttl=120, show_spinner="Loading attendance visits...")
def load_visits():
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    rows, size = [], 1000
    for offset in range(0, 100000, size):
        response = requests.get(f"{BASE}/rest/v1/attendance_visit_summary", headers=headers,
            params={"select":"*", "order":"in_time.desc.nullslast", "limit":size, "offset":offset}, timeout=40)
        if not response.ok:
            raise RuntimeError(f"Supabase HTTP {response.status_code}: {response.text[:300]}")
        chunk = response.json()
        rows.extend(chunk)
        if len(chunk) < size:
            return pd.DataFrame(rows), False
    return pd.DataFrame(rows), True

try:
    data, truncated = load_visits()
except Exception as exc:
    st.error(f"Could not load Supabase attendance summary: {exc}")
    st.stop()
if truncated:
    st.warning("First 100,000 visits loaded. Server-side pagination is needed for a larger dataset.")
if data.empty:
    st.info("No attendance visits have been recorded yet. The Outlet Master section above is still available.")
    st.stop()

# V2.8 device audit: retrieve event-level identifiers with admin-only service key.
# The visit summary view is unchanged; join by visit_id, not employee code.
@st.cache_data(ttl=120, show_spinner=False)
def load_device_audit():
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
    events = []
    for offset in range(0, 100000, 1000):
        response = requests.get(f"{BASE}/rest/v1/attendance_events", headers=headers,
            params={"select":"visit_id,event_type,employee_code,device_id,android_id_hash,device_manufacturer,device_model", "order":"received_at.asc",
                    "limit":1000, "offset":offset}, timeout=40)
        response.raise_for_status()
        chunk = response.json()
        events.extend(chunk)
        if len(chunk) < 1000:
            return pd.DataFrame(events), False
    return pd.DataFrame(events), True

try:
    audit_events, audit_truncated = load_device_audit()
except Exception as exc:
    st.error(f"Device audit unavailable. Apply V2.8 migration first: {exc}")
    st.stop()
if audit_truncated:
    st.warning("Device audit truncated at 100,000 events; device counts may be incomplete.")
if "visit_id" not in data.columns:
    st.error("The attendance visit summary must expose visit_id for device audit. No inferred joins will be made.")
    st.stop()
if audit_events.empty:
    audit_events = pd.DataFrame(columns=["visit_id", "event_type", "employee_code", "device_id", "android_id_hash", "device_manufacturer", "device_model"])
for col in ("visit_id", "event_type", "employee_code", "device_id", "android_id_hash", "device_manufacturer", "device_model"):
    if col not in audit_events.columns:
        audit_events[col] = ""
audit_events["device_id"] = audit_events["device_id"].fillna("").astype(str)
valid_events = audit_events.loc[audit_events["device_id"].str.startswith("CCD-")].copy()
# Across the fetched dataset, not only currently filtered visits.
device_employee_counts = valid_events.groupby("device_id")["employee_code"].nunique().to_dict()
visit_devices = valid_events.groupby("visit_id")["device_id"].agg(lambda ids: sorted(set(ids))).to_dict()
data["Device ID"] = data["visit_id"].map(lambda vid: ", ".join(visit_devices.get(vid, [])) or "Not recorded (older app)")
data["Distinct Employees on Device"] = data["visit_id"].map(
    lambda vid: max((device_employee_counts.get(dev, 0) for dev in visit_devices.get(vid, [])), default=0))
data["Device Audit Status"] = data["visit_id"].map(
    lambda vid: "IN/OUT device mismatch" if len(visit_devices.get(vid, [])) > 1
    else "Review — shared device" if any(device_employee_counts.get(dev, 0) > 1 for dev in visit_devices.get(vid, []))
    else "Normal" if visit_devices.get(vid, []) else "Not available")

# Additional device metadata (pseudonymous Android ID hash, manufacturer, model).
for field in ("android_id_hash", "device_manufacturer", "device_model"):
    audit_events[field] = audit_events[field].fillna("").astype(str)

def visit_metadata(field):
    return audit_events.groupby("visit_id")[field].agg(
        lambda vals: ", ".join(sorted({v for v in vals if v}))
    ).to_dict()

for source, target in (("android_id_hash", "Android ID Hash"),
                       ("device_manufacturer", "Device Manufacturer"),
                       ("device_model", "Device Model")):
    mapping = visit_metadata(source)
    data[target] = data["visit_id"].map(lambda vid: mapping.get(vid, "") or "Not recorded")
# Correlate reinstallations cautiously: Android ID may change on factory reset/signing-key changes.
valid_hash = audit_events.loc[audit_events["android_id_hash"].str.fullmatch(r"[0-9a-f]{64}")].copy()
hash_employee_counts = valid_hash.groupby("android_id_hash")["employee_code"].nunique().to_dict()
visit_hashes = valid_hash.groupby("visit_id")["android_id_hash"].agg(lambda vals: sorted(set(vals))).to_dict()
data["Distinct Employees on Android ID"] = data["visit_id"].map(
    lambda vid: max((hash_employee_counts.get(h, 0) for h in visit_hashes.get(vid, [])), default=0))
data["Device Audit Status"] = data.apply(
    lambda r: "Review — shared Android ID" if r["Distinct Employees on Android ID"] > 1
    and r["Device Audit Status"] in ("Normal", "Not available") else r["Device Audit Status"], axis=1)

# The V1.2 summary is the source of truth. Do not fabricate unavailable GPS coordinates.
for field in ("in_time", "out_time"):
    if field not in data.columns:
        data[field] = pd.NaT
    data[field] = pd.to_datetime(data[field], utc=True, errors="coerce")
    data[field + "_pkt"] = data[field].dt.tz_convert(ZoneInfo("Asia/Karachi"))
for field in ("employee_code", "employee_name", "outlet_code", "outlet_name", "outlet_gps_status", "in_out_distance_status"):
    if field not in data:
        data[field] = ""
for field in ("in_outlet_distance_m", "out_outlet_distance_m", "in_out_distance_m", "time_spent_hours"):
    if field not in data:
        data[field] = float("nan")
    data[field] = pd.to_numeric(data[field], errors="coerce")

now_pkt = datetime.now(ZoneInfo("Asia/Karachi")).date()
all_dates = data["in_time_pkt"].dropna().dt.date
start_date = all_dates.min() if len(all_dates) else now_pkt
end_date = max(now_pkt, start_date)

with st.expander("🔎 Filters", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        dates = st.date_input("IN date range (Pakistan time)", value=(start_date, end_date))
        employee_search = st.text_input("Employee code or name", placeholder="Search employee")
    with c2:
        outlet_options = sorted(data["outlet_code"].dropna().astype(str).unique())
        selected_outlets = st.multiselect("Outlets", outlet_options)
        status_options = sorted(data["outlet_gps_status"].dropna().astype(str).unique())
        selected_status = st.multiselect("GPS status", status_options)
    only_incomplete = st.checkbox("Show incomplete visits only")

filtered = data.copy()
if isinstance(dates, (list, tuple)) and len(dates) == 2:
    filtered = filtered.loc[filtered["in_time_pkt"].dt.date.between(dates[0], dates[1])]
if employee_search.strip():
    search = employee_search.strip()
    mask = (filtered["employee_code"].astype(str).str.contains(search, case=False, regex=False, na=False)
            | filtered["employee_name"].astype(str).str.contains(search, case=False, regex=False, na=False))
    filtered = filtered.loc[mask]
if selected_outlets:
    filtered = filtered.loc[filtered["outlet_code"].astype(str).isin(selected_outlets)]
if selected_status:
    filtered = filtered.loc[filtered["outlet_gps_status"].astype(str).isin(selected_status)]
complete = filtered["in_time"].notna() & filtered["out_time"].notna()
if only_incomplete:
    filtered = filtered.loc[~complete].copy()
    complete = filtered["in_time"].notna() & filtered["out_time"].notna()
mismatch = filtered["outlet_gps_status"].astype(str).str.casefold().eq("mismatch")

metrics = [
    ("Visits", len(filtered)), ("Completed", int(complete.sum())),
    ("Incomplete", int((~complete).sum())), ("GPS mismatches", int(mismatch.sum())),
    ("Unique employees", filtered["employee_code"].nunique())]
for row_start in (0, 3):
    items = metrics[row_start:row_start+3]
    cols = st.columns(len(items))
    for col, (name, value) in zip(cols, items):
        col.metric(name, value)

# PKT-readable copy, including all fields returned by the database view.
report = filtered.copy()
for field in ("in_time_pkt", "out_time_pkt"):
    report[field] = report[field].dt.strftime("%d %b %Y, %I:%M:%S %p").fillna("—")
report["visit_status"] = complete.map({True:"Completed", False:"Incomplete"})
preferred = ["employee_code", "employee_name", "outlet_code", "outlet_name", "visit_status",
             "in_time_pkt", "out_time_pkt", "time_spent_hhmmss", "time_spent_hours",
             "in_outlet_distance_m", "out_outlet_distance_m", "in_out_distance_m",
             "in_out_distance_status", "outlet_gps_status", "in_accuracy_m", "out_accuracy_m", "visit_id"]
# Include any latitude/longitude fields if present in the V1.2 SQL view.
geo_fields = [c for c in report.columns if any(word in c.lower() for word in ("latitude", "longitude", "_lat", "_lon", "_lng"))]
preferred += [c for c in geo_fields if c not in preferred]
shown = report[[c for c in preferred if c in report.columns]].copy()
rename = {"employee_code":"Employee code", "employee_name":"Employee name", "outlet_code":"Outlet code",
          "outlet_name":"Outlet name", "visit_status":"Visit status", "in_time_pkt":"IN (PKT)",
          "out_time_pkt":"OUT (PKT)", "time_spent_hhmmss":"Time spent (HH:MM:SS)",
          "time_spent_hours":"Time spent (hours)", "in_outlet_distance_m":"IN → outlet (m)",
          "out_outlet_distance_m":"OUT → outlet (m)", "in_out_distance_m":"IN → OUT (m)",
          "in_out_distance_status":"IN/OUT GPS status", "outlet_gps_status":"Outlet GPS status",
          "in_accuracy_m":"IN accuracy (m)", "out_accuracy_m":"OUT accuracy (m)", "visit_id":"Visit ID"}
shown = shown.rename(columns=rename)

st.subheader("📊 Management performance summary — V2.0")
st.caption("Compliance is based on recorded GPS distances. Missing GPS distances are shown separately, "
           "not assumed compliant. All figures respect the attendance filters.")
if not filtered.empty:
    overview = filtered.copy()
    overview["completed_visit"] = overview["in_time"].notna() & overview["out_time"].notna()
    overview["in_distance_value"] = pd.to_numeric(overview["in_outlet_distance_m"], errors="coerce")
    overview["out_distance_value"] = pd.to_numeric(overview["out_outlet_distance_m"], errors="coerce")
    overview["gps_violation"] = ((overview["in_distance_value"] > 1500) |
                                  (overview["out_distance_value"] > 1500))
    overview["gps_unverified"] = overview["in_distance_value"].isna() | overview["out_distance_value"].isna()
    overview["gps_compliant"] = (~overview["gps_violation"]) & (~overview["gps_unverified"])
    mg1,mg2,mg3 = st.columns(3)
    mg1.metric("GPS compliant visits", int(overview["gps_compliant"].sum()))
    mg2.metric("GPS violations", int(overview["gps_violation"].sum()))
    mg3.metric("GPS unverified", int(overview["gps_unverified"].sum()))
    grouped = overview.groupby(["outlet_code","outlet_name"], dropna=False).agg(
        visits=("employee_code","size"),
        completed=("completed_visit","sum"),
        incomplete=("completed_visit",lambda a:int((~a).sum())),
        gps_compliant=("gps_compliant","sum"),
        gps_violations=("gps_violation","sum"),
        gps_unverified=("gps_unverified","sum"),
        unique_employees=("employee_code","nunique")
    ).reset_index()
    grouped["GPS compliance (%)"] = (100*grouped["gps_compliant"]/grouped["visits"]).round(1)
    grouped["Completion (%)"] = (100*grouped["completed"]/grouped["visits"]).round(1)
    grouped = grouped.sort_values(["gps_violations","incomplete","visits"],ascending=[False,False,False])
    st.dataframe(grouped, use_container_width=True, hide_index=True)
    summary_buffer = BytesIO()
    with pd.ExcelWriter(summary_buffer, engine="openpyxl") as writer:
        grouped.to_excel(writer, sheet_name="Outlet Management", index=False)
        writer.sheets["Outlet Management"].freeze_panes="A2"
    st.download_button("⬇️ Download management summary (Excel)",summary_buffer.getvalue(),
        file_name=f"CCD_Management_Summary_{now_pkt.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("No visits match the filters.")

st.subheader("👤 Employee-wise attendance")
if filtered.empty:
    st.info("No visits match the selected filters.")
else:
    employee_summary = filtered.groupby(["employee_code", "employee_name"], dropna=False).agg(
        visits=("outlet_code", "size"), completed=("out_time", lambda s: int(s.notna().sum())),
        total_hours=("time_spent_hours", "sum"), gps_mismatches=("outlet_gps_status", lambda s: int(s.astype(str).str.casefold().eq("mismatch").sum()))
    ).reset_index().sort_values("visits", ascending=False)
    employee_summary["total_hours"] = employee_summary["total_hours"].round(2)
    st.dataframe(employee_summary, use_container_width=True, hide_index=True)

st.subheader("📋 Visit details")
st.caption("All times shown in PKT (UTC+05:00); distances in metres. Scroll tables horizontally on mobile.")
st.dataframe(shown, use_container_width=True, hide_index=True)
if not filtered.empty:
    st.markdown("**Mobile visit cards**")
    max_cards = st.select_slider("Cards to show", options=[5,10,20,50], value=10)
    for _, r in report.head(max_cards).iterrows():
        with st.container(border=True):
            st.markdown(f"**{str(r.get('employee_name',''))}** · `{str(r.get('employee_code',''))}`")
            st.caption(f"Outlet {r.get('outlet_code','')} — {r.get('outlet_name','')} | {r.get('visit_status','')}")
            st.write(f"**IN:** {r.get('in_time_pkt','—')}  |  **OUT:** {r.get('out_time_pkt','—')}")
            st.write(f"**Time spent:** {r.get('time_spent_hhmmss','—')}  |  **GPS:** {r.get('outlet_gps_status','—')}")
            st.write(f"**Outlet distance (IN / OUT):** {r.get('in_outlet_distance_m',float('nan'))} m / {r.get('out_outlet_distance_m',float('nan'))} m")
            st.write(f"**IN → OUT distance:** {r.get('in_out_distance_m',float('nan'))} m")

# V1.5: selected employee history, using exactly the same filtered data as the main report.
st.subheader("🕘 Employee attendance history")
if filtered.empty:
    st.info("No employee visits available for the selected filters.")
else:
    people = (filtered[["employee_code", "employee_name"]].drop_duplicates()
              .fillna("").astype(str).sort_values(["employee_name", "employee_code"]))
    person_labels = {f"{r.employee_code} — {r.employee_name}": (r.employee_code, r.employee_name)
                     for r in people.itertuples(index=False)}
    chosen_label = st.selectbox("Select an employee to view attendance history", list(person_labels))
    chosen_code, chosen_name = person_labels[chosen_label]
    history_mask = (filtered["employee_code"].astype(str).eq(chosen_code) &
                    filtered["employee_name"].astype(str).eq(chosen_name))
    history = shown.loc[history_mask].copy()
    st.metric("Visits for selected employee", len(history))
    st.dataframe(history, use_container_width=True, hide_index=True)
    history_buf = BytesIO()
    with pd.ExcelWriter(history_buf, engine="openpyxl") as writer:
        history.to_excel(writer, sheet_name="Employee History", index=False)
    st.download_button("⬇️ Download selected employee history", history_buf.getvalue(),
        file_name=f"CCD_Employee_{chosen_code}_History.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True)

st.subheader("🗺️ Visit GPS map — V2.0")
st.caption("Select one visit to compare its actual outlet, GPS IN and GPS OUT coordinates. Lines connect available recorded points only; they do not represent travel routes.")

def find_geo_pair(columns, prefixes):
    names = {str(c).lower(): c for c in columns}
    for prefix in prefixes:
        for lat_suffix, lon_suffix in (("lat", "lon"), ("latitude", "longitude"),
                                       ("lat", "lng"), ("latitude", "lng")):
            a, b = prefix + lat_suffix, prefix + lon_suffix
            if a in names and b in names:
                return names[a], names[b]
    return None

geo_roles = [
    ("Registered outlet", ["outlet_", "station_", "site_"], [0, 150, 95]),
    ("GPS IN", ["in_", "gps_in_", "in_gps_"], [30, 105, 225]),
    ("GPS OUT", ["out_", "gps_out_", "out_gps_"], [225, 55, 65]),
]
geo_pairs = [(label, find_geo_pair(filtered.columns, prefixes), rgb)
             for label, prefixes, rgb in geo_roles]
if filtered.empty:
    st.info("No visits match the filters. Expand the date range or clear filters to see the map.")
elif not any(pair for _, pair, _ in geo_pairs):
    st.info("Map unavailable: the Supabase attendance_visit_summary view does not expose outlet/IN/OUT coordinate pairs. The rest of the dashboard is unaffected.")
else:
    # Keep each visit independent: never connect different employees' points.
    candidates = filtered.reset_index(drop=True).copy()
    def visit_label(i):
        r = candidates.iloc[i]
        t = r.get("in_time_pkt")
        when = t.strftime("%d %b %Y %I:%M %p") if pd.notna(t) else "No IN time"
        return f"{i+1}. {r.get('employee_name','')} ({r.get('employee_code','')}) · Outlet {r.get('outlet_code','')} · {when}"
    selected_idx = st.selectbox("Select visit to map", list(range(len(candidates))),
                                format_func=visit_label, key="gps_map_visit")
    visit = candidates.iloc[selected_idx]
    # V1.2 reporting view exposes IN/OUT coordinates, but may omit outlet coordinates.
    # Retrieve the registered outlet location from the outlet master (read-only, server-side).
    @st.cache_data(ttl=300, show_spinner=False)
    def registered_outlet_coordinates(outlet_code):
        headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
        response = requests.get(
            f"{BASE}/rest/v1/outlets",
            headers=headers,
            params={"select": "code,name,latitude,longitude",
                    "code": f"eq.{outlet_code}", "limit": 1},
            timeout=20)
        response.raise_for_status()
        records = response.json()
        return records[0] if records else None

    pts = []
    for label, pair, rgb in geo_pairs:
        if not pair:
            continue
        lat = pd.to_numeric(visit.get(pair[0]), errors="coerce")
        lon = pd.to_numeric(visit.get(pair[1]), errors="coerce")
        if pd.notna(lat) and pd.notna(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            pts.append({"lat":float(lat), "lon":float(lon), "role":label, "color":rgb,
                        "coordinates":f"{float(lat):.6f}, {float(lon):.6f}",
                        "employee":str(visit.get("employee_name", "")),
                        "outlet":str(visit.get("outlet_code", ""))})

    # Fill the outlet marker from the authoritative outlets table when the view omits it.
    if not any(p["role"] == "Registered outlet" for p in pts):
        try:
            master = registered_outlet_coordinates(str(visit.get("outlet_code", "")).strip())
            if master:
                lat = pd.to_numeric(master.get("latitude"), errors="coerce")
                lon = pd.to_numeric(master.get("longitude"), errors="coerce")
                if pd.notna(lat) and pd.notna(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    pts.insert(0, {"lat":float(lat), "lon":float(lon),
                                   "role":"Registered outlet", "color":[0,150,95],
                                   "coordinates":f"{float(lat):.6f}, {float(lon):.6f}",
                                   "employee":str(visit.get("employee_name","")),
                                   "outlet":str(visit.get("outlet_code",""))})
        except Exception as exc:
            st.warning(f"Could not retrieve registered outlet coordinates from Outlet Master: {exc}")

    if not pts:
        st.warning("No valid GPS coordinates are available for this visit.")
    else:
        from math import log2, cos, radians, asin, sqrt
        by_role = {p["role"]: p for p in pts}
        focus_choices = ["Show all locations"]
        if "Registered outlet" in by_role:
            focus_choices.append("Focus on outlet")
        if "GPS IN" in by_role or "GPS OUT" in by_role:
            focus_choices.append("Focus on employee")
        mode = st.radio("Map view", focus_choices, horizontal=True, key="gps_focus_v20")

        # Zoom-to-fit uses longitude corrected for latitude, with conservative
        # padding for narrow mobile screens. Do not infer missing locations.
        def fit_view(points):
            lats = [p["lat"] for p in points]
            lons = [p["lon"] for p in points]
            midlat = (min(lats) + max(lats)) / 2
            midlon = (min(lons) + max(lons)) / 2
            lat_extent = max(lats) - min(lats)
            lon_extent = (max(lons) - min(lons)) * max(0.15, cos(radians(midlat)))
            extent = max(lat_extent, lon_extent)
            # ~300 px usable map width on narrow mobile screens.
            zoom = max(3.0, min(16.5, log2(0.25 / max(extent, 0.00025)) + 8.0))
            return pdk.ViewState(latitude=midlat, longitude=midlon, zoom=zoom, pitch=0)

        if mode == "Focus on outlet":
            visible = [by_role["Registered outlet"]]
            view = pdk.ViewState(latitude=visible[0]["lat"], longitude=visible[0]["lon"], zoom=15, pitch=0)
        elif mode == "Focus on employee":
            visible = [by_role[x] for x in ("GPS IN","GPS OUT") if x in by_role]
            view = fit_view(visible)
        else:
            visible = pts
            view = fit_view(pts)

        links = []
        for first, second, color in [
            ("Registered outlet", "GPS IN", [30,105,225]),
            ("Registered outlet", "GPS OUT", [225,55,65]),
            ("GPS IN", "GPS OUT", [100,100,100])]:
            if first in by_role and second in by_role:
                p, q = by_role[first], by_role[second]
                links.append({"source":[p["lon"],p["lat"]],
                              "target":[q["lon"],q["lat"]], "color":color})
        # V2.0: visually group nearby IN/OUT points at wide-area zoom.
        # The grouped marker is a display-only midpoint, never a replacement
        # for the true GPS coordinates stored in Supabase.
        from math import sin
        def gps_distance_m(a, b):
            dlat = radians(b["lat"] - a["lat"])
            dlon = radians(b["lon"] - a["lon"])
            h = sin(dlat / 2)**2 + cos(radians(a["lat"])) * cos(radians(b["lat"])) * sin(dlon / 2)**2
            return 6371000 * 2 * asin(min(1.0, sqrt(max(0.0, h))))

        close_pair = ("GPS IN" in by_role and "GPS OUT" in by_role and
                      gps_distance_m(by_role["GPS IN"], by_role["GPS OUT"]) <= 100)
        group_on_wide = close_pair and mode == "Show all locations"
        show_cluster = st.checkbox(
            "Group nearby IN/OUT markers on overview map",
            value=True, disabled=not group_on_wide,
            help="Groups IN and OUT only in Show all locations when they are within 100 m. "
                 "Focus on employee always shows the true separate GPS points.",
            key="gps_cluster_v20"
        ) if group_on_wide else False

        if show_cluster:
            in_pt, out_pt = by_role["GPS IN"], by_role["GPS OUT"]
            midpoint = {"lat": (in_pt["lat"] + out_pt["lat"]) / 2,
                        "lon": (in_pt["lon"] + out_pt["lon"]) / 2,
                        "role": "GPS IN + OUT (grouped)",
                        "color": [130, 75, 190],
                        "coordinates": "Tap Focus on employee to see both actual GPS positions",
                        "employee": in_pt["employee"], "outlet": in_pt["outlet"]}
            display_points = [p for p in pts if p["role"] not in ("GPS IN", "GPS OUT")] + [midpoint]
            display_links = []
            if "Registered outlet" in by_role:
                outlet = by_role["Registered outlet"]
                display_links.append({
                    "source": [outlet["lon"], outlet["lat"]],
                    "target": [midpoint["lon"], midpoint["lat"]],
                    "color": [130, 75, 190]})
            st.info("IN and OUT are grouped on this overview because they are close together. "
                    "Choose **Focus on employee** to inspect both actual GPS positions.")
        else:
            display_points = pts
            display_links = links

        layers = []
        if display_links:
            layers.append(pdk.Layer("LineLayer", data=pd.DataFrame(display_links),
                get_source_position="source", get_target_position="target",
                get_color="color", get_width=3, width_min_pixels=2))
        layers.append(pdk.Layer("ScatterplotLayer", data=pd.DataFrame(display_points),
            get_position="[lon, lat]", get_fill_color="color",
            get_radius=65, radius_min_pixels=8, radius_max_pixels=18,
            pickable=True, stroked=True, get_line_color=[255,255,255], line_width_min_pixels=2))
        st.pydeck_chart(pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            initial_view_state=view, layers=layers,
            tooltip={"html":"<b>{role}</b><br/>{coordinates}<br/>Employee: {employee}<br/>Outlet: {outlet}"}),
            use_container_width=True, key=f"ccd_gps_map_v20_{mode.replace(' ','_')}_{int(show_cluster)}")
        st.markdown("🟢 **Registered outlet** · 🔵 **GPS IN** · 🔴 **GPS OUT**" + (" · 🟣 **Grouped IN/OUT**" if show_cluster else ""))
        for p in pts:
            st.write(f"**{p['role']}:** `{p['coordinates']}`")

        def haversine(a, b):
            dlat = radians(b["lat"] - a["lat"])
            dlon = radians(b["lon"] - a["lon"])
            z = sin_half(dlat)**2 + cos(radians(a["lat"])) * cos(radians(b["lat"])) * sin_half(dlon)**2
            return 6371000 * 2 * asin(min(1.0, sqrt(max(0.0, z))))
        def sin_half(x):
            from math import sin
            return sin(x / 2)

        if "Registered outlet" in by_role:
            for role in ("GPS IN", "GPS OUT"):
                if role in by_role:
                    st.caption(f"Outlet → {role}: {haversine(by_role['Registered outlet'], by_role[role]):,.1f} m (straight-line GPS distance)")
        else:
            st.warning("Registered outlet GPS not available in reporting view or Outlet Master. Verify its master coordinates.")

        def distance_text(name):
            v = pd.to_numeric(visit.get(name), errors="coerce")
            return f"{v:,.1f} m" if pd.notna(v) else "Unavailable"
        st.write(f"**IN → outlet:** {distance_text('in_outlet_distance_m')}  |  **OUT → outlet:** {distance_text('out_outlet_distance_m')}")
        st.write(f"**IN → OUT:** {distance_text('in_out_distance_m')}  |  **GPS status:** {visit.get('outlet_gps_status','—')}")
        st.caption("Connecting lines are straight-line comparisons, not travel routes. Switch map view to inspect distant locations.")
st.subheader("🏪 Outlet-wise visits")
if not filtered.empty:
    outlet_report = filtered.groupby(["outlet_code", "outlet_name"], dropna=False).agg(
        visits=("employee_code", "size"), gps_mismatches=("outlet_gps_status", lambda s: int(s.astype(str).str.casefold().eq("mismatch").sum())),
        avg_time_hours=("time_spent_hours", "mean")
    ).reset_index().sort_values("visits", ascending=False)
    outlet_report["avg_time_hours"] = outlet_report["avg_time_hours"].round(2)
    st.dataframe(outlet_report, use_container_width=True, hide_index=True)
    st.bar_chart(outlet_report.set_index("outlet_code")["visits"])
else:
    outlet_report = pd.DataFrame(columns=["outlet_code", "outlet_name", "visits", "gps_mismatches", "avg_time_hours"])

st.subheader("🚨 GPS exception monitoring — V2.0")
st.caption("An exception occurs when the recorded IN or OUT location is more than 1,500 metres from the registered outlet. "
           "Distances are straight-line GPS measurements, not road distances. Uses the selected date, employee and outlet filters.")
threshold_m = 1500.0
in_distance = pd.to_numeric(filtered["in_outlet_distance_m"], errors="coerce")
out_distance = pd.to_numeric(filtered["out_outlet_distance_m"], errors="coerce")
in_exceeds = in_distance > threshold_m
out_exceeds = out_distance > threshold_m
exception_mask = in_exceeds | out_exceeds
missing_distances = in_distance.isna() & out_distance.isna()
exception_frame = filtered.loc[exception_mask].copy()
exception_frame["IN exception"] = in_exceeds.loc[exception_mask].map({True: "Yes", False: "No"})
exception_frame["OUT exception"] = out_exceeds.loc[exception_mask].map({True: "Yes", False: "No"})
exception_frame["Maximum deviation (m)"] = pd.concat(
    [in_distance.loc[exception_mask], out_distance.loc[exception_mask]], axis=1
).max(axis=1).round(1)
exception_frame["Deviation (km)"] = (exception_frame["Maximum deviation (m)"] / 1000).round(2)
exception_frame["Exception type"] = [
    "IN and OUT" if both_in and both_out else ("IN only" if both_in else "OUT only")
    for both_in, both_out in zip(in_exceeds.loc[exception_mask], out_exceeds.loc[exception_mask])
]
exception_frame["IN time (PKT)"] = exception_frame["in_time_pkt"].dt.strftime("%d %b %Y %I:%M:%S %p").fillna("—")
exception_frame["OUT time (PKT)"] = exception_frame["out_time_pkt"].dt.strftime("%d %b %Y %I:%M:%S %p").fillna("—")
exception_frame = exception_frame.sort_values("Maximum deviation (m)", ascending=False)

c1, c2, c3 = st.columns(3)
c1.metric("Exception visits", len(exception_frame))
c2.metric("IN violations", int(in_exceeds.sum()))
c3.metric("OUT violations", int(out_exceeds.sum()))
if missing_distances.any():
    st.warning(f"{int(missing_distances.sum())} visit(s) have neither IN nor OUT outlet-distance data; "
               "these cannot be classified as compliant or non-compliant.")
if not exception_frame.empty:
    types = st.multiselect("Exception type", ["IN only", "OUT only", "IN and OUT"],
                           default=["IN only", "OUT only", "IN and OUT"], key="exception_types_v20")
    minimum_km = st.number_input("Minimum deviation to display (km)", min_value=1.5,
                                 max_value=10000.0, value=1.5, step=0.5,
                                 key="exception_minimum_v20")
    visible_exceptions = exception_frame.loc[
        exception_frame["Exception type"].isin(types)
        & (exception_frame["Maximum deviation (m)"] > minimum_km * 1000 - 0.00001)
    ].copy()
    exception_columns = {
        "employee_code": "Employee code", "employee_name": "Employee name",
        "outlet_code": "Outlet code", "outlet_name": "Outlet name",
        "IN time (PKT)": "IN (PKT)", "OUT time (PKT)": "OUT (PKT)",
        "in_outlet_distance_m": "IN → outlet (m)",
        "out_outlet_distance_m": "OUT → outlet (m)",
        "Exception type": "Exception type",
        "Maximum deviation (m)": "Maximum deviation (m)",
        "Deviation (km)": "Deviation (km)",
        "outlet_gps_status": "Reported GPS status", "visit_id": "Visit ID"
    }
    exceptions = visible_exceptions[
        [col for col in exception_columns if col in visible_exceptions.columns]
    ].rename(columns=exception_columns)
    st.dataframe(exceptions, use_container_width=True, hide_index=True)
    if not exceptions.empty:
        exception_buffer = BytesIO()
        with pd.ExcelWriter(exception_buffer, engine="openpyxl") as writer:
            exceptions.to_excel(writer, sheet_name="GPS Exceptions", index=False)
            worksheet = writer.sheets["GPS Exceptions"]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
        st.download_button("⬇️ Download GPS exceptions (Excel)",
                           data=exception_buffer.getvalue(),
                           file_name=f"CCD_GPS_Exceptions_{now_pkt.isoformat()}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
else:
    exceptions = pd.DataFrame(columns=[
        "Employee code", "Employee name", "Outlet code", "Outlet name",
        "IN (PKT)", "OUT (PKT)", "IN → outlet (m)", "OUT → outlet (m)",
        "Exception type", "Maximum deviation (m)", "Deviation (km)",
        "Reported GPS status", "Visit ID"
    ])
    st.success("No GPS exceptions above 1.5 km in the selected visits.")

st.subheader("📱 Shared Device Attendance Audit")
st.caption("Device ID and hashed Android ID are audit signals, not IMEI or proof of impersonation. Reinstalling, resetting, or signing changes can alter identifiers. Restrict report access.")
shared_visits = filtered.loc[filtered["Device Audit Status"].isin(["Review — shared device", "Review — shared Android ID", "IN/OUT device mismatch"])].copy()
st.metric("Visits requiring device review (selected filters)", len(shared_visits))
if not shared_visits.empty:
    audit_cols = [c for c in ["employee_code", "employee_name", "outlet_code", "visit_id", "Device ID", "Android ID Hash", "Device Manufacturer", "Device Model", "Distinct Employees on Device", "Distinct Employees on Android ID", "Device Audit Status", "in_time_pkt", "out_time_pkt"] if c in shared_visits.columns]
    st.dataframe(shared_visits[audit_cols], use_container_width=True, hide_index=True)
else:
    st.info("No shared-device flags among selected visits. Older-app records without a Device ID cannot be assessed.")

@st.cache_data(show_spinner=False)
def build_excel(visits_json, outlet_json, employee_json, exception_json, audit_json):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, content in [("Employee Visits", visits_json), ("Outlet Summary", outlet_json),
                              ("Employee Summary", employee_json), ("GPS Exceptions", exception_json), ("Device Audit", audit_json)]:
            frame = pd.read_json(BytesIO(content.encode()), orient="records")
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for col in sheet.columns:
                letter = col[0].column_letter
                sheet.column_dimensions[letter].width = min(36, max(13, max(len(str(cell.value or "")) for cell in list(col)[:150]) + 2))
    return buf.getvalue()

employee_export = employee_summary if not filtered.empty else pd.DataFrame(columns=["employee_code","employee_name","visits","completed","total_hours","gps_mismatches"])
excel = build_excel(shown.to_json(orient="records"), outlet_report.to_json(orient="records"),
                    employee_export.to_json(orient="records"), exceptions.to_json(orient="records"),
                    shared_visits.to_json(orient="records", date_format="iso"))
st.download_button("⬇️ Download Excel (5 sheets)", excel, file_name=f"CCD_Attendance_Device_Audit_V2_8_{now_pkt.isoformat()}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
st.caption("Attendance reporting is read-only. Outlet Master edits require administrator confirmation. Never put server secrets in GitHub.")
