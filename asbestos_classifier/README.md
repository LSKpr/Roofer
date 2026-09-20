# Klasyfikator dachów azbestowych

Samodzielny moduł TensorFlow/Keras klasyfikujący zdjęcia dachów RGB o rozmiarze dokładnie `48×48` pikseli. Model zwraca dwie wartości Softmax, w tym estymowane prawdopodobieństwo klasy `asbestos`.

Implementacja bazuje na architekturze opisanej w pracy:

> Edwin Raczko, Małgorzata Krówczyńska, Ewa Wilk (2022), *Asbestos roofing recognition by use of convolutional neural networks and high-resolution aerial imagery. Testing different scenarios*, Building and Environment 217, 109092, DOI: 10.1016/j.buildenv.2022.109092.

Autorzy używali sygnatur `47×47 RGB`. Ten moduł używa wymaganego wejścia `48×48 RGB`; po czterech etapach poolingu końcowy tensor nadal ma prawidłowy rozmiar `2×2`.

## Zawartość folderu

```text
asbestos_classifier/
├── __init__.py
├── asbestos_model.py   # architektura, kompilacja i harmonogram learning rate
├── data.py             # odczyt folderów, kontrola duplikatów i podział danych
├── predict.py          # predykcja jednego obrazu
├── requirements.txt    # przypięte zależności
├── train.py            # trening, checkpointy i ewaluacja
└── README.md
```

Modele i wyniki treningu są domyślnie zapisywane w `asbestos_classifier/artifacts/`, który jest ignorowany przez Git.

## Architektura

Wejście modelu ma kształt `48×48×3`. Feature-wise standardization jest dopasowywana wyłącznie na zbiorze treningowym i zapisywana wewnątrz modelu.

Warstwa wejściowa:

1. Conv2D: 64 filtry, kernel `3×3`, stride 1,
2. ReLU,
3. Batch Normalization.

Następnie występują cztery bloki Inception. Każdy ma trzy równoległe gałęzie:

1. Conv `1×1`, 32 filtry → ReLU → Conv `3×3`, 64 filtry → ReLU → Batch Normalization,
2. Conv `1×1`, 32 filtry → ReLU → Conv `5×5`, 64 filtry → ReLU → Batch Normalization,
3. MaxPool `3×3` → Conv `5×5`, 64 filtry → ReLU → Batch Normalization.

Wyniki gałęzi są konkatenowane. Po każdym bloku stosowane są MaxPool i Spatial Dropout `0.55`. Pierwsze trzy poolingi mają stride 2, ostatni stride 1.

Część klasyfikacyjna:

1. Flatten,
2. Dense 1024 → Batch Normalization → ReLU → Dropout `0.50`,
3. Dense 1024 → Batch Normalization → ReLU → Dropout `0.50`,
4. Dense 2 z Softmax.

Mapowanie klas:

```text
0 = non_asbestos
1 = asbestos
```

## Parametry treningu

Domyślne wartości odwzorowują publikację:

| Parametr | Wartość |
| --- | ---: |
| Epoki | 128 |
| Batch size | 64 |
| Optimizer | Adam |
| Początkowy learning rate | 0.0015 |
| Loss | Binary cross-entropy |
| Spatial dropout | 0.55 |
| Dense dropout | 0.50 |

Learning rate jest mnożony przez `0.85` co 10 epok. Po pięciu epokach bez poprawy `val_loss` jest dodatkowo zmniejszany o `0.001`, nie niżej niż `1e-6`. Checkpoint `best.keras` zawsze odpowiada najniższemu `val_loss`.

## Przygotowanie danych

Potrzebne są dwa foldery. Mogą mieć dowolne nazwy, ponieważ ich znaczenie przekazuje się argumentami CLI:

```text
dataset/
├── asbestos/
│   ├── roof_000001.png
│   ├── roof_000002.png
│   └── ...
└── non_asbestos/
    ├── roof_000001.png
    ├── roof_000002.png
    └── ...
```

Wymagania:

- każdy plik musi przedstawiać jeden dach,
- każdy obraz musi mieć dokładnie `48×48` pikseli,
- obraz jest konwertowany do trzech kanałów RGB,
- obsługiwane rozszerzenia: `.png`, `.jpg`, `.jpeg`, `.bmp`,
- identyczne pliki nie mogą powtarzać się w zbiorze,
- ten sam dach i jego warianty nie mogą występować w różnych podziałach,
- etykieta powinna odpowiadać stanowi dachu w dniu wykonania zdjęcia.

Skrypt wykrywa identyczne pliki przez SHA-256 i przerywa pracę, jeśli znajdzie duplikat albo ten sam obraz w obu klasach.

### Skala przestrzenna

Publikacja używała ortofotomapy `25 cm/piksel`. Obraz 48×48 obejmuje wtedy około `12×12 m`. Wszystkie dane powinny mieć zbliżoną rozdzielczość terenową. Przykładowo przy `5 cm/piksel` obraz obejmie tylko `2,4×2,4 m` i może nie zawierać całego dachu.

## Liczba danych

Publikacja wykorzystywała 7448 unikalnych dachów:

| Klasa | Liczba |
| --- | ---: |
| Asbestos | 3200 |
| Non-asbestos | 4248 |

Praktyczne zalecenia:

- minimum do eksperymentu: około 1000 unikalnych dachów na klasę,
- rozsądny cel: 3000–5000 dachów na klasę,
- model obejmujący różnorodne Mazowsze: co najmniej 10 000 dachów na klasę z wielu powiatów, dat i warunków oświetleniowych.

Różnorodność i poprawność etykiet są ważniejsze niż sama liczba plików. Zbiór testowy powinien zawierać dachy z innych lokalizacji niż trening.

## Instalacja

Polecenia należy wykonać z katalogu głównego repozytorium:

```bash
python3 -m venv .venv-asbestos
source .venv-asbestos/bin/activate
python -m pip install --upgrade pip
pip install -r asbestos_classifier/requirements.txt
```

Na Windows aktywacja środowiska wygląda tak:

```powershell
.venv-asbestos\Scripts\activate
```

## Trening

```bash
python3 asbestos_classifier/train.py \
  --asbestos-dir /sciezka/dataset/asbestos \
  --non-asbestos-dir /sciezka/dataset/non_asbestos
```

Domyślny podział:

```text
63,2% trening
18,4% walidacja
18,4% test
```

Publikacja używała `63,2%` treningu i `36,8%` walidacji. Tutaj udział treningu pozostał taki sam, ale część ewaluacyjną podzielono na walidację i niezależny test.

Własny katalog wyników:

```bash
python3 asbestos_classifier/train.py \
  --asbestos-dir /sciezka/dataset/asbestos \
  --non-asbestos-dir /sciezka/dataset/non_asbestos \
  --output-dir /sciezka/do/wynikow
```

Konserwatywna augmentacja treningowa:

```bash
python3 asbestos_classifier/train.py \
  --asbestos-dir /sciezka/dataset/asbestos \
  --non-asbestos-dir /sciezka/dataset/non_asbestos \
  --augment
```

Augmentacja wykonuje wyłącznie obroty o wielokrotność 90° oraz odbicia. Jest domyślnie wyłączona, ponieważ publikacja nie opisywała jej jako elementu procedury treningowej.

Jeżeli katalog wynikowy nie jest pusty, skrypt nie nadpisze go bez jawnego parametru:

```bash
python3 asbestos_classifier/train.py \
  --asbestos-dir /sciezka/dataset/asbestos \
  --non-asbestos-dir /sciezka/dataset/non_asbestos \
  --overwrite
```

## Wyniki treningu

Domyślny katalog:

```text
asbestos_classifier/artifacts/asbestos-inception/
```

Zawartość:

```text
best.keras       # model o najniższym val_loss
final.keras      # model z ostatniej epoki
config.json      # parametry uruchomienia i liczności klas
history.json     # historia metryk
metrics.json     # końcowe metryki validation/test
splits.json      # dokładny podział plików
training.csv     # przebieg epok
```

Do predykcji należy używać `best.keras`, nie `final.keras`.

Raportowane metryki:

- accuracy,
- precision dla klasy asbestos,
- recall dla klasy asbestos,
- AUC,
- binary cross-entropy.

W zastosowaniu do wyszukiwania potencjalnych dachów azbestowych szczególnie istotny jest recall klasy `asbestos`, ponieważ niski recall oznacza pomijanie rzeczywistych dachów azbestowych.

## Predykcja jednego obrazu

```bash
python3 asbestos_classifier/predict.py \
  --model asbestos_classifier/artifacts/asbestos-inception/best.keras \
  --image /sciezka/roof_48x48.png
```

Przykładowy wynik:

```json
{
  "asbestos_probability": 0.87,
  "non_asbestos_probability": 0.13,
  "predicted_class": "asbestos"
}
```

Obraz o innym rozmiarze zostanie odrzucony; predykcja nie wykonuje automatycznego skalowania.

## Użycie z kodu Python

```python
from asbestos_classifier.asbestos_model import load_trained_model
from asbestos_classifier.predict import predict_probability

model = load_trained_model("asbestos_classifier/artifacts/asbestos-inception/best.keras")
result = predict_probability(model, "roof_48x48.png")
print(result["asbestos_probability"])
```

## Interpretacja prawdopodobieństwa

Softmax zwraca estymację pewności modelu, ale nie gwarantuje statystycznie skalibrowanego prawdopodobieństwa. Po treningu należy sprawdzić kalibrację na niezależnym zbiorze testowym i dobrać próg decyzji zgodnie z kosztem false negative i false positive. Próg `0.5` w `predict.py` jest wyłącznie wartością początkową.

Model powinien służyć do wskazywania obiektów wymagających weryfikacji, a nie jako samodzielny dowód obecności azbestu.

## Status

Kod został sprawdzony statycznie, ale model nie został jeszcze wytrenowany ani uruchomiony, ponieważ dataset nie jest dostępny.
