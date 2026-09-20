from pathlib import Path

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

IMAGE_SIZE = (48, 48)
CLASS_NAMES = ("non_asbestos", "asbestos")
INITIAL_LEARNING_RATE = 0.0015


def feature_extraction_block(inputs, index):
    branch_1 = layers.Conv2D(32, 1, strides=1, padding="same", name=f"inception_{index}_b1_reduce")(inputs)
    branch_1 = layers.ReLU(name=f"inception_{index}_b1_relu_1")(branch_1)
    branch_1 = layers.Conv2D(64, 3, strides=1, padding="same", name=f"inception_{index}_b1_conv")(branch_1)
    branch_1 = layers.ReLU(name=f"inception_{index}_b1_relu_2")(branch_1)
    branch_1 = layers.BatchNormalization(name=f"inception_{index}_b1_bn")(branch_1)

    branch_2 = layers.Conv2D(32, 1, strides=1, padding="same", name=f"inception_{index}_b2_reduce")(inputs)
    branch_2 = layers.ReLU(name=f"inception_{index}_b2_relu_1")(branch_2)
    branch_2 = layers.Conv2D(64, 5, strides=1, padding="same", name=f"inception_{index}_b2_conv")(branch_2)
    branch_2 = layers.ReLU(name=f"inception_{index}_b2_relu_2")(branch_2)
    branch_2 = layers.BatchNormalization(name=f"inception_{index}_b2_bn")(branch_2)

    branch_3 = layers.MaxPool2D(3, strides=1, padding="same", name=f"inception_{index}_b3_pool")(inputs)
    branch_3 = layers.Conv2D(64, 5, strides=1, padding="same", name=f"inception_{index}_b3_conv")(branch_3)
    branch_3 = layers.ReLU(name=f"inception_{index}_b3_relu")(branch_3)
    branch_3 = layers.BatchNormalization(name=f"inception_{index}_b3_bn")(branch_3)

    return layers.Concatenate(name=f"inception_{index}_concat")([branch_1, branch_2, branch_3])


def dense_block(inputs, index):
    x = layers.Dense(1024, name=f"dense_{index}")(inputs)
    x = layers.BatchNormalization(name=f"dense_{index}_bn")(x)
    x = layers.ReLU(name=f"dense_{index}_relu")(x)
    return layers.Dropout(0.50, name=f"dense_{index}_dropout")(x)


def build_model(normalization):
    inputs = keras.Input(shape=(*IMAGE_SIZE, 3), name="rgb_image")
    x = normalization(inputs)
    x = layers.Conv2D(64, 3, strides=1, padding="valid", name="stem_conv")(x)
    x = layers.ReLU(name="stem_relu")(x)
    x = layers.BatchNormalization(name="stem_bn")(x)

    for index in range(1, 5):
        x = feature_extraction_block(x, index)
        stride = 1 if index == 4 else 2
        x = layers.MaxPool2D(3, strides=stride, padding="valid", name=f"block_{index}_pool")(x)
        x = layers.SpatialDropout2D(0.55, name=f"block_{index}_spatial_dropout")(x)

    x = layers.Flatten(name="flatten")(x)
    x = dense_block(x, 1)
    x = dense_block(x, 2)
    outputs = layers.Dense(2, activation="softmax", name="roof_probabilities")(x)
    return keras.Model(inputs, outputs, name="asbestos_inception_cnn")


def compile_model(model):
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=INITIAL_LEARNING_RATE),
        loss=keras.losses.BinaryCrossentropy(),
        metrics=[
            keras.metrics.CategoricalAccuracy(name="accuracy"),
            keras.metrics.Precision(name="precision_asbestos", class_id=1),
            keras.metrics.Recall(name="recall_asbestos", class_id=1),
            keras.metrics.AUC(name="auc"),
        ],
    )
    return model


class SubtractLearningRateOnPlateau(keras.callbacks.Callback):
    def __init__(self, monitor="val_loss", patience=5, decrement=0.001, min_lr=1e-6, min_delta=1e-4):
        super().__init__()
        self.monitor = monitor
        self.patience = patience
        self.decrement = decrement
        self.min_lr = min_lr
        self.min_delta = min_delta
        self.best = float("inf")
        self.wait = 0

    def on_epoch_end(self, epoch, logs=None):
        current = (logs or {}).get(self.monitor)
        if current is None:
            return
        if current < self.best - self.min_delta:
            self.best = current
            self.wait = 0
            return
        self.wait += 1
        if self.wait < self.patience:
            return
        learning_rate = self.model.optimizer.learning_rate
        current_rate = float(keras.backend.get_value(learning_rate))
        new_rate = max(current_rate - self.decrement, self.min_lr)
        learning_rate.assign(new_rate)
        self.wait = 0


def paper_learning_rate_schedule(epoch, learning_rate):
    if epoch > 0 and epoch % 10 == 0:
        return learning_rate * 0.85
    return learning_rate


def training_callbacks(output_dir):
    output_dir = Path(output_dir)
    return [
        keras.callbacks.ModelCheckpoint(
            output_dir / "best.keras",
            monitor="val_loss",
            mode="min",
            save_best_only=True,
        ),
        keras.callbacks.LearningRateScheduler(paper_learning_rate_schedule),
        SubtractLearningRateOnPlateau(),
        keras.callbacks.CSVLogger(output_dir / "training.csv"),
        keras.callbacks.TerminateOnNaN(),
    ]


def load_trained_model(path):
    return keras.models.load_model(path, compile=False)


def probability_from_batch(model, images):
    probabilities = model.predict(images, verbose=0)
    return probabilities[:, 1]
