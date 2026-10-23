# Customer Care Day V1.3 — Admin Dashboard

A separate **read-only** management dashboard for your existing Android V1.1 + Supabase V1.2 test system. **No APK changes** and **no new SQL** required.

## What it shows
- Total/completed/incomplete visits, unique employees, GPS mismatches
- Date, outlet, employee, mismatch filters
- Outlet summary and visit count chart
- Employee-wise visits and GPS exception list
- Excel workbook download (three sheets)

## Deploy in Streamlit Community Cloud
1. Create a new **private GitHub repository** for this dashboard (do not use the Android repository unless you want to keep both projects together).
2. Upload `app.py`, `requirements.txt`, `.gitignore` to repository root. You may upload `README.md`. **Do not upload real secrets.**
3. In Streamlit Community Cloud create an app from the repository, main branch, entrypoint `app.py`.
4. Open app settings > Secrets. Enter the following, replacing placeholders:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SERVER_ONLY_SERVICE_ROLE_KEY"
ADMIN_PASSWORD = "YOUR_STRONG_UNIQUE_PASSWORD"
```

5. Save secrets and reboot the dashboard. Sign in with your chosen administrator password.
6. Export Excel and verify test visit 114723 shows time spent and GPS distances.

### Finding the key
Supabase > Project Settings > API Keys > **Legacy anon, service_role** > `service_role` key. This key is highly privileged. Put it **only** in Streamlit server-side Secrets. Never put it in Android, GitHub source, chat messages, browser JavaScript, or downloadable files. Do not confuse it with the publishable key already used in the Android app.

### Important security and operational notes
- The dashboard uses a shared administrator password. Suitable for **controlled testing**, not a final production authentication system. For production use, implement individual admin login, MFA, and role-based access.
- Deploy the dashboard with restricted access where available. A publicly reachable URL with a single shared password is not ideal. Password attempts are not rate-limited in this prototype.
- The service role key bypasses Supabase RLS. It is used server-side for read-only GET requests here, but the key itself has broader powers. Rotate it if exposed.
- The V1.2 reporting view was created without `security_invoker=true`, so it may run with view-owner permissions. This package does **not** grant it to authenticated or anonymous users. Keep its grants restricted.
- The date filter is **UTC**. App displays timestamps in UTC; Pakistan time is UTC+05.
- Loads up to 100,000 visits in 1,000-row pages with 2-minute caching. For large long-term datasets, implement server-side filtering/pagination.
- Existing Android anonymous authentication is **not verified employee identity**; do not rely on it for payroll or official compliance without hardening.
- This does not change the existing Streamlit employee app, Supabase tables, RLS policies, or Android APK.
