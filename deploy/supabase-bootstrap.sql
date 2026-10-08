-- Run once in the new QOSYU project's Supabase SQL Editor, before starting Render.
-- Existing PostGIS installations are kept in place, including the public schema.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;
CREATE SCHEMA IF NOT EXISTS qosyu;
REVOKE ALL ON SCHEMA qosyu FROM PUBLIC;

-- Application startup creates its tables in qosyu and enables RLS there.
-- Do not add qosyu to the Data API's exposed schemas.
-- QOSYU uses its own /auth endpoints and server-side SQL, not Supabase Auth.
