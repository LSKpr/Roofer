from app.config import Settings


def test_allowed_origins_splits_a_comma_separated_list() -> None:
    settings = Settings(cors_origins="http://localhost:5173, https://roofer.example ,")

    assert settings.allowed_origins == ["http://localhost:5173", "https://roofer.example"]
