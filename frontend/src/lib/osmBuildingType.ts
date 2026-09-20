/**
 * Rodzaje budynkow z OpenStreetMap jako etykiety dla uzytkownika.
 *
 * Etykieta jest interpretacja tagu, wiec surowa wartosc tagu zostaje widoczna obok: kto weryfikuje
 * dane w OSM albo poprawia je u zrodla, musi wiedziec, jaki tag tam naprawde stoi. Nieznanego
 * rodzaju nie tlumaczymy na sile — lepiej pokazac `barn` niz zgadywac.
 *
 * Klucze OSM sa juz angielskie, wiec przy interfejsie po angielsku czesc wpisow to to samo slowo
 * po obu stronach (`garage`, `barn`, `hotel`). Zostaja w mapie, bo znacza „ten tag widzielismy
 * w danych i nie wymaga tlumaczenia" — czego samo wpadniecie w galaz dla nieznanego tagu nie
 * odroznia od tagu, ktorego nikt nigdy nie sprawdzil. Zamiast tego `buildingTypeLabel` nie doklada
 * tagu, gdy etykieta jest z nim identyczna: „garage · garage" wygladalo jak usterka interfejsu,
 * a nie jak podane zrodlo. Przy tagu nieoczywistym (`farm_auxiliary`, `sty`, `roof`) etykieta
 * niesie tresc, ktorej w tagu nie ma, wiec tag zostaje obok niej.
 *
 * Lista pokrywa rodzaje, ktore faktycznie wystepuja w snapshocie mazowieckiego (policzone na
 * probce 120 000 budynkow); `fclass` z Geofabrik jest bezuzyteczne, bo dla wszystkich 2 585 219
 * budynkow ma wartosc `building`.
 */
const LABELS: Record<string, string> = {
  house: 'single-family house',
  detached: 'detached house',
  semidetached_house: 'semi-detached house',
  terrace: 'terraced housing',
  apartments: 'apartment building',
  residential: 'residential building',
  dormitory: 'dormitory',
  outbuilding: 'outbuilding',
  farm_auxiliary: 'farm outbuilding',
  farm: 'farmhouse',
  barn: 'barn',
  cowshed: 'cowshed',
  stable: 'stable',
  sty: 'pigsty',
  greenhouse: 'greenhouse',
  garage: 'garage',
  garages: 'garage block',
  carport: 'carport',
  shed: 'shed',
  hut: 'hut',
  cabin: 'cabin',
  bungalow: 'holiday home',
  service: 'utility building',
  transformer_tower: 'transformer tower',
  retail: 'retail building',
  commercial: 'commercial building',
  supermarket: 'supermarket',
  kiosk: 'kiosk',
  office: 'office building',
  industrial: 'industrial building',
  manufacture: 'manufacturing building',
  warehouse: 'warehouse',
  church: 'church',
  chapel: 'chapel',
  school: 'school',
  kindergarten: 'kindergarten',
  university: 'university building',
  hospital: 'hospital',
  hotel: 'hotel',
  civic: 'public building',
  government: 'government building',
  public: 'public building',
  sports_hall: 'sports hall',
  train_station: 'railway station',
  toilets: 'toilets',
  roof: 'canopy',
  construction: 'building under construction',
  ruins: 'ruin',
}

/**
 * Etykieta rodzaju albo `null`, gdy OSM go nie podaje (tak jest u ~35% budynkow).
 *
 * Rodzaj opisany inaczej niz sam tag wraca jako „etykieta · surowy tag", bo tag jest tu zrodlem,
 * ktore da sie sprawdzic w OSM. Gdy etykieta jest dokladnie tagiem, tag nie wraca drugi raz
 * (`garage`, a nie „garage · garage"), a nieznany rodzaj wraca jako sam tag.
 */
export function buildingTypeLabel(osmType: string | null | undefined): string | null {
  const raw = osmType?.trim()
  if (!raw) return null
  const label = LABELS[raw]
  if (!label) return raw
  return label === raw ? label : `${label} · ${raw}`
}

/**
 * Sama nazwa rodzaju, bez surowego tagu — do naglowka karty, gdzie liczy sie zwieziosc.
 * W wierszu danych pokazujemy pelna etykiete z tagiem, bo tam chodzi o weryfikowalnosc.
 */
export function buildingTypeName(osmType: string | null | undefined): string | null {
  const raw = osmType?.trim()
  if (!raw) return null
  return LABELS[raw] ?? raw
}
