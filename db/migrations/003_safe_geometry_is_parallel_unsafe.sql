-- Blok EXCEPTION w PL/pgSQL otwiera subtransakcje, czego nie wolno robic w zapytaniu
-- rownoleglym: "cannot start subtransactions during a parallel operation". PARALLEL SAFE
-- w migracji 002 bylo wiec bledem — parsowanie geometrii musi isc jednowatkowo.
CREATE OR REPLACE FUNCTION safe_geojson_geometry(payload text) RETURNS geometry
LANGUAGE plpgsql IMMUTABLE PARALLEL UNSAFE AS $$
BEGIN
    RETURN ST_SetSRID(ST_GeomFromGeoJSON(payload), 4326);
EXCEPTION
    WHEN others THEN RETURN NULL;
END;
$$;
