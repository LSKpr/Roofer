/**
 * Rodzaje budynków z OpenStreetMap po polsku.
 *
 * Tłumaczenie jest interpretacją, więc surowa wartość tagu zostaje widoczna obok: kto weryfikuje
 * dane w OSM albo poprawia je u źródła, musi wiedzieć, jaki tag tam naprawdę stoi. Nieznanego
 * rodzaju nie tłumaczymy na siłę — lepiej pokazać `barn` niż zgadywać.
 *
 * Lista pokrywa rodzaje, które faktycznie występują w snapshocie mazowieckiego (policzone na
 * próbce 120 000 budynków); `fclass` z Geofabrik jest bezużyteczne, bo dla wszystkich 2 585 219
 * budynków ma wartość `building`.
 */
const LABELS: Record<string, string> = {
  house: 'dom jednorodzinny',
  detached: 'dom wolnostojący',
  semidetached_house: 'bliźniak',
  terrace: 'zabudowa szeregowa',
  apartments: 'budynek wielorodzinny',
  residential: 'budynek mieszkalny',
  dormitory: 'akademik',
  outbuilding: 'budynek gospodarczy',
  farm_auxiliary: 'budynek gospodarczy',
  farm: 'budynek gospodarstwa',
  barn: 'stodoła',
  cowshed: 'obora',
  stable: 'stajnia',
  sty: 'chlewnia',
  greenhouse: 'szklarnia',
  garage: 'garaż',
  garages: 'garaże',
  carport: 'zadaszenie na samochód',
  shed: 'szopa',
  hut: 'chata',
  cabin: 'domek',
  bungalow: 'domek letniskowy',
  service: 'budynek techniczny',
  transformer_tower: 'stacja transformatorowa',
  retail: 'budynek handlowy',
  commercial: 'budynek usługowy',
  supermarket: 'supermarket',
  kiosk: 'kiosk',
  office: 'biurowiec',
  industrial: 'budynek przemysłowy',
  manufacture: 'budynek produkcyjny',
  warehouse: 'magazyn',
  church: 'kościół',
  chapel: 'kaplica',
  school: 'szkoła',
  kindergarten: 'przedszkole',
  university: 'budynek uczelni',
  hospital: 'szpital',
  hotel: 'hotel',
  civic: 'budynek publiczny',
  government: 'budynek urzędu',
  public: 'budynek publiczny',
  sports_hall: 'hala sportowa',
  train_station: 'dworzec kolejowy',
  toilets: 'toaleta',
  roof: 'zadaszenie',
  construction: 'budynek w budowie',
  ruins: 'ruina',
}

/**
 * Etykieta rodzaju albo `null`, gdy OSM go nie podaje (tak jest u ~35% budynków).
 * Znany rodzaj wraca jako „polski opis · surowy tag", nieznany jako sam tag.
 */
export function buildingTypeLabel(osmType: string | null | undefined): string | null {
  const raw = osmType?.trim()
  if (!raw) return null
  const label = LABELS[raw]
  return label ? `${label} · ${raw}` : raw
}
