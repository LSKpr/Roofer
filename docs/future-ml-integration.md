# Future ML integration

The initial release has no model, no heuristic probability, and no orange prediction layer. The disabled UI action says that a model is not configured.

## Contract

`RoofPredictionProvider` defines asynchronous batch prediction over a list of building geometries and one `ImageryLayer` descriptor. `NoOpPredictionProvider` returns an empty list. `ModelPrediction` persists the building, imagery layer, model name/version, optional probability, uncertainty, class, explanation metadata, and timestamp.

A real provider should create predictions only after it has:

- immutable imagery evidence references and acquisition metadata;
- a documented label definition for roof material rather than parcel/whole-building material;
- uncertainty calibration and a reject/unknown state;
- model versioning, reproducible preprocessing, and audit metadata;
- access controls, retention rules, and review workflow;
- separate single-image and before/after roof-change capabilities.

## API evolution

`GET /api/v1/buildings/{id}/predictions` already provides a typed empty-result contract while no provider is configured. A future `POST /analysis-jobs/{id}/predictions` can queue a provider batch and expose `model_status` separately from registry status. Prediction results must not overwrite GeoAzbest evidence. The UI can render orange only when a configured provider returns an auditable model result and must display probability, uncertainty, version, imagery evidence, and limitations.
