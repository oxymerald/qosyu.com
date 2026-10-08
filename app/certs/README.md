# Supabase certificate authority

`supabase-ca.crt` is the public CA certificate downloaded from the project's
Supabase Dashboard → Database Settings → SSL configuration on 2026-10-08.
It contains no private key. The Render deployment explicitly trusts this CA
for its PostgreSQL connection while retaining certificate and hostname checks.

If Supabase rotates this CA, download its replacement from the dashboard,
verify a TLS connection using it, and redeploy. Do not disable verification.
