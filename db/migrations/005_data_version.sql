-- Znacznik wersji danych: jeden token, ktory zmienia sie przy kazdym imporcie.
--
-- Powod: kafle wektorowe niosa identyfikatory budynkow z bazy, a ponowny import je zmienia,
-- bo TRUNCATE nie zeruje sekwencji (pulapka 21 w AGENTS.md). Przy `Cache-Control: max-age=3600`
-- przegladarka przez godzine rysowala kafle ze starymi identyfikatorami i klik w budynek konczyl
-- sie odpowiedzia 404. Token z tej tabeli wchodzi do ETagu kafla, wiec zaraz po imporcie warunkowy
-- GET nie moze juz dostac 304 na stary kafel.
--
-- Tabela jest singletonem: klucz glowny typu boolean z CHECK (only_row) dopuszcza dokladnie jeden
-- wiersz. Drugi wiersz albo ma te sama wartosc klucza (konflikt klucza glownego), albo false
-- (odrzucone przez CHECK), wiec „dwie wersje danych naraz" jest niewyrazalne w schemacie.
CREATE TABLE data_version (
    only_row   boolean PRIMARY KEY DEFAULT true CHECK (only_row),
    token      text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Wiersz zasiany od razu, zeby po `migrate` zawsze istnial: trasa kafli ma go tylko czytac,
-- a brak wiersza traktuje jako awarie (kafel bez ETagu i bez cache'a), nie jako sytuacje normalna.
INSERT INTO data_version (token) VALUES (md5(random()::text || clock_timestamp()::text));

COMMENT ON TABLE data_version IS 'Token wersji danych do walidacji cache kafli (ETag). Podbijany przez import.';
