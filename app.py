import hmac
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="CCD | Admin V1.6", page_icon="📍", layout="wide", initial_sidebar_state="collapsed")
st.markdown('''<style>.block-container{padding-top:1rem;max-width:1450px}h1,h2,h3{color:#084a82}div[data-testid="stMetric"]{border:1px solid #dce6ef;border-radius:12px;padding:12px;background:#f8fbff}div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px} .stButton>button[kind="primary"]{background:#00815d;border:0}@media(max-width:700px){.block-container{padding:0.7rem}.stDataFrame{font-size:12px}}</style>''', unsafe_allow_html=True)
st.title("CUSTOMER CARE DAY")
st.caption("WE CARE. YOU DRIVE. | Admin Dashboard V1.6 | Pakistan Standard Time (PKT)")

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
    st.info("No attendance visits have been recorded yet.")
    st.stop()

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

st.subheader("🗺️ Visit GPS map — V1.6")
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
    if not pts:
        st.warning("No valid coordinates are available for this visit. Choose another visit.")
    else:
        pt_df = pd.DataFrame(pts)
        links = []
        by_role = {p["role"]:p for p in pts}
        for first, second, color in [
            ("Registered outlet", "GPS IN", [30,105,225]),
            ("Registered outlet", "GPS OUT", [225,55,65]),
            ("GPS IN", "GPS OUT", [100,100,100])]:
            if first in by_role and second in by_role:
                p, q = by_role[first], by_role[second]
                links.append({"source":[p["lon"],p["lat"]],
                              "target":[q["lon"],q["lat"]], "color":color})
        layers = []
        if links:
            layers.append(pdk.Layer("LineLayer", data=pd.DataFrame(links),
                get_source_position="source", get_target_position="target",
                get_color="color", get_width=4, width_min_pixels=2))
        layers.append(pdk.Layer("ScatterplotLayer", data=pt_df,
            get_position="[lon, lat]", get_fill_color="color",
            get_radius=65, radius_min_pixels=9, radius_max_pixels=20,
            pickable=True, stroked=True, get_line_color=[255,255,255], line_width_min_pixels=2))
        # Center and zoom to include all available points, including large GPS mismatches.
        lat_span = float(pt_df.lat.max() - pt_df.lat.min())
        lon_span = float(pt_df.lon.max() - pt_df.lon.min())
        span = max(lat_span, lon_span)
        zoom = max(3, min(16, 12 - __import__("math").log2(max(span, 0.003)/0.02)))
        st.pydeck_chart(pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
            initial_view_state=pdk.ViewState(latitude=float(pt_df.lat.mean()),
                longitude=float(pt_df.lon.mean()), zoom=zoom, pitch=0),
            layers=layers,
            tooltip={"html":"<b>{role}</b><br/>{coordinates}<br/>Employee: {employee}<br/>Outlet: {outlet}"}),
            use_container_width=True)
        st.markdown("🟢 **Registered outlet** · 🔵 **GPS IN** · 🔴 **GPS OUT**")
        for p in pts:
            st.write(f"**{p['role']}:** `{p['coordinates']}`")
        def distance_text(name):
            v = pd.to_numeric(visit.get(name), errors="coerce")
            return f"{v:,.1f} m" if pd.notna(v) else "Unavailable"
        st.write(f"**IN → outlet:** {distance_text('in_outlet_distance_m')}  |  **OUT → outlet:** {distance_text('out_outlet_distance_m')}")
        st.write(f"**IN → OUT:** {distance_text('in_out_distance_m')}  |  **GPS status:** {visit.get('outlet_gps_status','—')}")
        if len(pts) < 3:
            st.caption("Some markers are missing because their coordinates are not available in the reporting view.")
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

st.subheader("📍 GPS mismatch exceptions")
exception_cols = ["Employee code", "Employee name", "Outlet code", "Outlet name", "IN (PKT)", "OUT (PKT)", "IN → outlet (m)", "OUT → outlet (m)", "IN → OUT (m)", "Outlet GPS status"]
exceptions = shown.loc[mismatch, [c for c in exception_cols if c in shown.columns]]
st.dataframe(exceptions, use_container_width=True, hide_index=True)

@st.cache_data(show_spinner=False)
def build_excel(visits_json, outlet_json, employee_json, exception_json):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, content in [("Employee Visits", visits_json), ("Outlet Summary", outlet_json),
                              ("Employee Summary", employee_json), ("GPS Exceptions", exception_json)]:
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
                    employee_export.to_json(orient="records"), exceptions.to_json(orient="records"))
st.download_button("⬇️ Download Excel (4 sheets)", excel, file_name=f"CCD_Attendance_V1_6_{now_pkt.isoformat()}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
st.caption("Read-only dashboard. GPS coordinates appear only if included in the Supabase attendance_visit_summary view. Never put server secrets in GitHub.")
