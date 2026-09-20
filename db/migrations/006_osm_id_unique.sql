-- Trwaly adres budynku: unikalny indeks na osm_buildings (osm_id).
--
-- Powod: `id` pochodzi z sekwencji, a TRUNCATE jej nie zeruje, wiec ponowny import przenumerowal
-- wszystkie budynki (bylo ponizej 2 585 220, jest 2 585 326 - 5 170 544; pulapka 21 w AGENTS.md).
-- Zapisane adresy budynkow przestaly dzialac, a kafle lezace w cache przegladarki nadal nosily
-- stare numery, wiec klik w budynek konczyl sie 404 "Nie ma budynku o tym identyfikatorze"
-- (pulapka 22). `osm_id` przychodzi z OpenStreetMap i import go nie rusza: sprawdzone zapytaniem,
-- ze wszystkie 2 585 219 budynkow ma go wypelniony i unikalny, calkowity i dodatni
-- (63 662 ... 1 560 241 187) - czyli miesci sie zarowno w uint64 identyfikatora obiektu MVT,
-- jak i w bezpiecznym zakresie liczb calkowitych JavaScriptu (2^53 - 1).
--
-- Indeks jest UNIKALNY swiadomie, a nie zwykly: gdyby przyszly snapshot mial dwa budynki o tym
-- samym `osm_id`, import ma przerwac sie GLOSNO na bledzie klucza. Zwykly indeks przepuscilby taki
-- snapshot i zostawilby dwa rozne budynki pod jednym adresem w API - karta budynku pokazywalaby
-- wtedy losowy z nich, a skan obszaru dwa wiersze o tym samym identyfikatorze. Halas przy imporcie
-- jest tanszy niz cicho niejednoznaczne dane. Uwaga: unikalnosc nie zabrania NULL-a, a budynek bez
-- `osm_id` byloby po prostu nieadresowalny (trasy szczegolow oddalyby 404) - dzis takiego nie ma.
--
-- Kolumna zostaje `text`, a klucz glowny sie nie zmienia. `id` z sekwencji pozostaje wewnetrznym
-- kluczem, po ktorym lacza sie tabele (building_registry_match.building_id -> osm_buildings.id),
-- wiec przerabianie kolumny na bigint albo przestawianie klucza glownego przepisywaloby 55 MB
-- dopasowan bez zadnego zysku. Publicznym adresem budynku jest `osm_id`, wewnetrznym `id`.
--
-- Zapytania szczegolow budynku porownuja kolumne z parametrem rzutowanym na text
-- (`osm_id = %(id)s::text`), a nie odwrotnie: rzutowanie KOLUMNY na bigint uczyniloby warunek
-- nieindeksowalnym i wrocilby Seq Scan po 1,2 GB tabeli.
CREATE UNIQUE INDEX osm_buildings_osm_id_key ON osm_buildings (osm_id);

COMMENT ON INDEX osm_buildings_osm_id_key IS
    'Trwaly adres budynku w API (osm_id). Unikalny, zeby snapshot z duplikatem przerwal import, '
    'a nie dal dwoch budynkow pod jednym adresem.';
