import hmac
from datetime import datetime, timedelta, timezone
from io import BytesIO
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="CCD | Management Dashboard", page_icon="📍", layout="wide")
st.markdown("""<style>.block-container{padding-top:1.5rem}h1,h2,h3{color:#084a82}.stButton>button[kind=primary]{background:#00815d;border:0}div[data-testid=stMetric]{border:1px solid #e2e8f0;padding:12px;border-radius:10px}</style>""",unsafe_allow_html=True)
st.title("CUSTOMER CARE DAY")
st.markdown("### WE CARE. YOU DRIVE.  |  Management Dashboard")
st.caption("Read-only attendance reporting · Supabase V1.2 visit summary")

required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "ADMIN_PASSWORD"]
missing = [x for x in required if not st.secrets.get(x)]
if missing:
    st.error("Missing Streamlit secrets: " + ", ".join(missing))
    st.stop()

if not st.session_state.get("admin_ok", False):
    with st.form("admin_login"):
        pw = st.text_input("Administrator password", type="password")
        submit = st.form_submit_button("Sign in", type="primary")
    if submit:
        if hmac.compare_digest(pw, str(st.secrets["ADMIN_PASSWORD"])):
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

with st.sidebar:
    st.success("Administrator session")
    if st.button("Sign out"):
        st.session_state.admin_ok = False
        st.rerun()
    if st.button("Refresh from Supabase"):
        st.cache_data.clear()
        st.rerun()

BASE = str(st.secrets["SUPABASE_URL"]).rstrip("/")
KEY = str(st.secrets["SUPABASE_SERVICE_ROLE_KEY"])
if not BASE.startswith("https://") or not BASE.endswith(".supabase.co"):
    st.error("SUPABASE_URL must be the project base URL ending in .supabase.co")
    st.stop()

@st.cache_data(ttl=120, show_spinner="Loading visits from Supabase...")
def load_visits():
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}
    rows = []
    page_size = 1000
    for offset in range(0, 100000, page_size):
        r = requests.get(f"{BASE}/rest/v1/attendance_visit_summary", headers=headers,
            params={"select":"*", "order":"in_time.desc.nullslast", "limit":page_size, "offset":offset}, timeout=40)
        if not r.ok:
            raise RuntimeError(f"Supabase HTTP {r.status_code}: {r.text[:350]}")
        chunk = r.json()
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
    else:
        st.warning("Only the first 100,000 visits are shown. Narrow the date range or add server-side pagination for larger datasets.")
    return pd.DataFrame(rows)

try:
    data = load_visits()
except Exception as exc:
    st.error(f"Unable to retrieve visit summary: {exc}")
    st.info("Check the service role key, project URL, and that V1.2 attendance_visit_summary exists.")
    st.stop()
if data.empty:
    st.info("No attendance records found yet.")
    st.stop()

for field in ("in_time", "out_time"):
    if field in data:
        data[field] = pd.to_datetime(data[field], utc=True, errors="coerce")

now = datetime.now(timezone.utc).date()
valid_dates = data["in_time"].dropna().dt.date
start_default = valid_dates.min() if len(valid_dates) else now
end_default = now if now >= start_default else start_default
with st.sidebar:
    st.header("Filters")
    dates = st.date_input("IN date range (UTC)", value=(start_default, end_default))
    outlet_opts = sorted(data["outlet_code"].dropna().astype(str).unique())
    selected_outlets = st.multiselect("Outlet code", outlet_opts)
    statuses = sorted(data["outlet_gps_status"].dropna().astype(str).unique())
    selected_status = st.multiselect("Outlet GPS status", statuses)
    employee_search = st.text_input("Employee code or name")

filtered = data.copy()
if isinstance(dates, (list, tuple)) and len(dates) == 2:
    date_values = filtered["in_time"].dt.date
    filtered = filtered.loc[date_values.between(dates[0], dates[1])]
if selected_outlets:
    filtered = filtered[filtered["outlet_code"].astype(str).isin(selected_outlets)]
if selected_status:
    filtered = filtered[filtered["outlet_gps_status"].isin(selected_status)]
if employee_search:
    mask = filtered["employee_code"].astype(str).str.contains(employee_search, case=False, regex=False, na=False) | filtered["employee_name"].astype(str).str.contains(employee_search, case=False, regex=False, na=False)
    filtered = filtered[mask]

complete = filtered["in_time"].notna() & filtered["out_time"].notna()
mismatch = filtered["outlet_gps_status"].eq("Mismatch")
cols = st.columns(5)
for col, label, val in zip(cols, ["Visits", "Completed", "Incomplete", "GPS mismatches", "Unique employees"],
    [len(filtered), int(complete.sum()), int((~complete).sum()), int(mismatch.sum()), filtered["employee_code"].nunique()]):
    col.metric(label, val)

st.subheader("Outlet-wise visits")
if not filtered.empty:
    outlet_report = filtered.groupby(["outlet_code", "outlet_name"], dropna=False).agg(
        visits=("visit_id", "count"),
        gps_mismatches=("outlet_gps_status", lambda s: int(s.eq("Mismatch").sum())),
        avg_time_hours=("time_spent_hours", "mean")
    ).reset_index().sort_values("visits", ascending=False)
    outlet_report["avg_time_hours"] = outlet_report["avg_time_hours"].round(2)
    st.dataframe(outlet_report, use_container_width=True, hide_index=True)
    st.bar_chart(outlet_report.set_index("outlet_code")["visits"])

st.subheader("GPS mismatch exceptions")
exception_cols = ["employee_code", "employee_name", "outlet_code", "outlet_name", "in_time", "out_time", "in_outlet_distance_m", "out_outlet_distance_m", "in_out_distance_m"]
st.dataframe(filtered.loc[mismatch, exception_cols], use_container_width=True, hide_index=True)

st.subheader("All employee visits")
preferred = ["visit_id", "employee_code", "employee_name", "outlet_code", "outlet_name", "in_time", "out_time", "time_spent_hhmmss", "time_spent_hours", "in_outlet_distance_m", "out_outlet_distance_m", "in_out_distance_m", "in_out_distance_status", "outlet_gps_status", "in_accuracy_m", "out_accuracy_m"]
shown = filtered[[c for c in preferred if c in filtered.columns]].copy()
st.dataframe(shown, use_container_width=True, hide_index=True)

@st.cache_data(show_spinner=False)
def excel_bytes(visits_json, outlet_json, exceptions_json):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, js in [("Employee Visits", visits_json), ("Outlet Summary", outlet_json), ("GPS Exceptions", exceptions_json)]:
            df = pd.read_json(BytesIO(js.encode()), orient="records")
            for c in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].dt.tz_localize(None) if df[c].dt.tz is not None else df[c]
            df.to_excel(writer, sheet_name=name, index=False)
    return out.getvalue()

# Use JSON serialization to avoid caching mutable DataFrames directly.
excel = excel_bytes(shown.to_json(orient="records", date_format="iso"),
    outlet_report.to_json(orient="records") if not filtered.empty else "[]",
    filtered.loc[mismatch, [c for c in exception_cols if c in filtered]].to_json(orient="records", date_format="iso"))
st.download_button("Download Excel report", excel, file_name=f"CCD_Attendance_Report_{now.isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
st.caption("Times shown in UTC. This is a management-only app; never share its administrator password or server key.")
