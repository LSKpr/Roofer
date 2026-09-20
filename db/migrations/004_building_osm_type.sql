-- Rodzaj budynku z OSM. W snapshocie Geofabrik `fclass` ma dla WSZYSTKICH 2 585 219 budynkow
-- wartosc 'building' (warstwa splaszcza rodzaj), a prawdziwy rodzaj siedzi we wlasciwosci `type`:
-- house, apartments, outbuilding, garage, retail. Na probce 120 000 obiektow niepusty rodzaj ma
-- 65% budynkow, wiec warto go miec — garaz i dom to dla inwentaryzacji azbestu dwie rozne rzeczy.
ALTER TABLE osm_buildings ADD COLUMN osm_type text;
