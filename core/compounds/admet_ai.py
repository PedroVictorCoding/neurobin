import importlib.util
import logging
from functools import lru_cache


logger = logging.getLogger(__name__)


def is_admet_ai_available() -> bool:
    return importlib.util.find_spec("admet_ai") is not None


def get_admet_ai_version() -> str:
    try:
        import admet_ai  # type: ignore

        return str(getattr(admet_ai, "__version__", "") or "")
    except Exception:
        return ""


def _import_admet_model_class():
    try:
        from admet_ai import ADMETModel  # type: ignore

        return ADMETModel
    except Exception:
        try:
            from admet_ai.admet_model import ADMETModel  # type: ignore

            return ADMETModel
        except Exception as exc:
            raise ImportError("Could not import ADMETModel from admet_ai") from exc


@lru_cache(maxsize=1)
def _get_model():
    ADMETModel = _import_admet_model_class()
    return ADMETModel()


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]

    # pandas / numpy scalars
    for cast in (int, float, str):
        try:
            return cast(value)
        except Exception:
            continue

    return str(value)


def predict_admet(smiles: str) -> dict:
    """
    Runs ADMET-AI predictions for a single SMILES string.

    Returns a JSON-serializable dict. Raises ImportError if admet_ai is missing.
    """
    if not smiles or not isinstance(smiles, str) or not smiles.strip():
        raise ValueError("SMILES is required")

    if not is_admet_ai_available():
        raise ImportError("admet_ai is not installed")

    model = _get_model()

    last_exc = None
    call_candidates = [
        lambda: model.predict(smiles),
        lambda: model.predict([smiles]),
        lambda: model(smiles),
        lambda: model([smiles]),
    ]

    result = None
    for call in call_candidates:
        try:
            result = call()
            break
        except Exception as exc:
            last_exc = exc
            continue

    if result is None:
        raise RuntimeError("ADMET-AI prediction failed") from last_exc

    # Common return shapes
    if isinstance(result, dict):
        return _jsonable(result)
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return _jsonable(result[0])

    # pandas DataFrame-like
    if hasattr(result, "iloc") and hasattr(result, "to_dict"):
        try:
            row = result.iloc[0]
            if hasattr(row, "to_dict"):
                return _jsonable(row.to_dict())
        except Exception:
            pass
        try:
            as_dict = result.to_dict()
            if isinstance(as_dict, dict):
                return _jsonable(as_dict)
        except Exception:
            pass

    logger.warning("Unknown ADMET-AI result type: %s", type(result))
    return {"result": _jsonable(result)}

