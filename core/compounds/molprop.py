import importlib.util
import json
import logging
import os
import shlex
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


logger = logging.getLogger(__name__)


def _env_truthy(name: str) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _bridge_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "molprop_bridge.py"


def _default_bridge_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "molprop_bridge.json"


def _resolve_command_template() -> str:
    explicit = (os.getenv("MOLPROP_PREDICT_CMD") or "").strip()
    if explicit:
        return explicit

    script_path = _bridge_script_path()
    if not script_path.exists():
        return ""

    configured = _env_truthy("MOLPROP_BRIDGE_ENABLED")
    config_path = (os.getenv("MOLPROP_BRIDGE_CONFIG") or "").strip()
    if not configured and not config_path and not _default_bridge_config_path().exists():
        return ""

    python_bin = (os.getenv("MOLPROP_PYTHON_BIN") or "").strip() or sys.executable
    command = f"{shlex.quote(python_bin)} {shlex.quote(str(script_path))} --smiles {{smiles}}"
    if config_path:
        command += f" --config {shlex.quote(config_path)}"
    endpoint = (os.getenv("MOLPROP_ENDPOINT") or "").strip()
    if endpoint:
        command += f" --endpoint {shlex.quote(endpoint)}"
    return command


def is_molprop_available() -> bool:
    if importlib.util.find_spec("molprop") is not None:
        return True
    return bool(_resolve_command_template())


def get_molprop_unavailable_reason() -> str:
    if importlib.util.find_spec("molprop") is not None:
        return ""
    if _resolve_command_template():
        return ""
    return (
        "MolProp not configured. Copy core/config/molprop_bridge.example.json to "
        "core/config/molprop_bridge.json (or run `manage.py generate_molprop_bridge_config`) "
        "and set MOLPROP_BRIDGE_ENABLED=1, "
        "or set MOLPROP_PREDICT_CMD."
    )


def get_molprop_version() -> str:
    try:
        import molprop  # type: ignore

        return str(getattr(molprop, "__version__", "") or "")
    except Exception:
        if _resolve_command_template():
            return "external-cmd"
        return ""


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]

    for cast in (int, float, str):
        try:
            return cast(value)
        except Exception:
            continue
    return str(value)


def _parse_predict_output(result):
    if isinstance(result, dict):
        preds = result.get("predictions") if isinstance(result.get("predictions"), dict) else None
        uncertainty = result.get("uncertainty") if isinstance(result.get("uncertainty"), dict) else None
        if preds is None:
            preds = {k: v for k, v in result.items() if k not in ("uncertainty", "uncertainties", "errors")}
        if uncertainty is None:
            maybe = result.get("uncertainties")
            uncertainty = maybe if isinstance(maybe, dict) else {}
        return _jsonable(preds or {}), _jsonable(uncertainty or {})

    if isinstance(result, list) and result and isinstance(result[0], dict):
        return _parse_predict_output(result[0])

    if hasattr(result, "iloc") and hasattr(result, "to_dict"):
        try:
            row = result.iloc[0]
            if hasattr(row, "to_dict"):
                return _parse_predict_output(row.to_dict())
        except Exception:
            pass
        try:
            as_dict = result.to_dict()
            return _parse_predict_output(as_dict)
        except Exception:
            pass

    return {"result": _jsonable(result)}, {}


@lru_cache(maxsize=1)
def _resolve_module_predictor():
    if importlib.util.find_spec("molprop") is None:
        return None
    import molprop  # type: ignore

    if hasattr(molprop, "predict"):
        return getattr(molprop, "predict")

    for attr in ("MolPropPredictor", "Predictor", "Model"):
        cls = getattr(molprop, attr, None)
        if cls:
            try:
                obj = cls()
                if hasattr(obj, "predict"):
                    return obj.predict
            except Exception:
                continue
    return None


def _predict_with_module(smiles: str):
    predictor = _resolve_module_predictor()
    if predictor is None:
        raise RuntimeError("No usable MolProp python predictor found")

    last_exc = None
    call_candidates = [
        lambda: predictor(smiles),
        lambda: predictor([smiles]),
    ]
    for call in call_candidates:
        try:
            return _parse_predict_output(call())
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError("MolProp module prediction failed") from last_exc


def _predict_with_command(smiles: str):
    template = _resolve_command_template()
    if not template:
        raise RuntimeError(get_molprop_unavailable_reason())

    cmd = template.replace("{smiles}", smiles)
    args = shlex.split(cmd)
    if not args:
        raise RuntimeError("Invalid MOLPROP command template")

    completed = subprocess.run(args, capture_output=True, text=True, check=False, timeout=120)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        parsed_error = ""
        if stdout:
            try:
                payload = json.loads(stdout)
                if isinstance(payload, dict):
                    parsed_error = str(payload.get("error") or payload.get("detail") or "").strip()
            except Exception:
                pass
        message = parsed_error or stderr
        raise RuntimeError(f"MolProp command failed ({completed.returncode}): {message[:400]}")

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError("MolProp command produced no output")

    try:
        payload = json.loads(stdout)
    except Exception as exc:
        raise RuntimeError("MolProp command did not output valid JSON") from exc

    return _parse_predict_output(payload)


def predict_molprop(smiles: str) -> tuple[dict, dict]:
    """
    Run MolProp predictions and return (predictions, uncertainty).

    Integration modes:
      1) Python module `molprop` if available
      2) External command via `MOLPROP_PREDICT_CMD`, where output is JSON
         and `{smiles}` placeholder is replaced with the molecule SMILES
      3) Built-in bridge command if `MOLPROP_BRIDGE_CONFIG`/bridge config is set
    """
    if not smiles or not isinstance(smiles, str) or not smiles.strip():
        raise ValueError("SMILES is required")

    if importlib.util.find_spec("molprop") is not None:
        try:
            return _predict_with_module(smiles.strip())
        except Exception as exc:
            logger.warning("MolProp module prediction failed; falling back to command mode: %s", exc)

    if _resolve_command_template():
        return _predict_with_command(smiles.strip())

    raise ImportError(get_molprop_unavailable_reason())
