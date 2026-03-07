#!/usr/bin/env python3
import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


_GIT_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_CHEMBERTA_DIRS = {
    "chemberta-77m-mlm": "ChemBERTa-77M-MLM",
    "chemberta-10m-mlm": "ChemBERTa-10M-MLM",
    "chemberta-77m-mtr": "ChemBERTa-77M-MTR",
    "chemberta-10m-mtr": "ChemBERTa-10M-MTR",
}
_CHEMBERTA_REQUIRED_FILES = (
    "config.json",
    "merges.txt",
    "pytorch_model.bin",
    "vocab.json",
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return payload


def _resolve_path(raw: str | None, *, config_dir: Path, repo_dir: Path | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if repo_dir:
        repo_candidate = (repo_dir / path).resolve()
        if repo_candidate.exists():
            return repo_candidate
    return (config_dir / path).resolve()


def _iter_endpoints(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    endpoints = config.get("endpoints")
    if isinstance(endpoints, dict):
        out = []
        for endpoint, cfg in endpoints.items():
            if isinstance(cfg, dict):
                out.append((str(endpoint), cfg))
        return out
    if isinstance(endpoints, list):
        out = []
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append((name, item))
        return out
    return []


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    max_value = max(values)
    exps = [math.exp(v - max_value) for v in values]
    total = sum(exps) or 1.0
    return [v / total for v in exps]


def _state_dict_from_checkpoint(checkpoint: Any) -> dict[str, Any]:
    if isinstance(checkpoint, dict):
        if isinstance(checkpoint.get("model_state_dict"), dict):
            return checkpoint["model_state_dict"]
        if isinstance(checkpoint.get("state_dict"), dict):
            return checkpoint["state_dict"]
        if checkpoint and all(hasattr(v, "shape") for v in checkpoint.values()):
            return checkpoint
    raise ValueError("Checkpoint does not contain a supported model state dict")


def _is_git_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(len(_GIT_LFS_POINTER_PREFIX) + 64)
    except OSError:
        return False
    return head.startswith(_GIT_LFS_POINTER_PREFIX)


def _assert_materialized_file(path: Path, *, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    if _is_git_lfs_pointer(path):
        raise RuntimeError(
            f"{label} is still a Git LFS pointer ({path}). Follow the upstream MolPROP setup first: "
            "install git-lfs, run `git lfs pull`, and create the conda env from `molprop.yml`."
        )


def _normalize_language_model(value: Any) -> str:
    model = str(value or "").strip().lower()
    if model.endswith("-only"):
        model = model[:-5]
    return model


def _validate_language_assets(*, name: str, setup: dict[str, Any], repo_dir: Path) -> None:
    network = setup.get("network") if isinstance(setup.get("network"), dict) else {}
    language = network.get("language") if isinstance(network.get("language"), dict) else {}
    model_name = _normalize_language_model(language.get("model"))
    if not model_name or model_name in {"none", "false"}:
        return

    chemberta_dir = _CHEMBERTA_DIRS.get(model_name)
    if not chemberta_dir:
        return

    asset_root = repo_dir / "config" / "chembert" / chemberta_dir
    if not asset_root.exists():
        raise FileNotFoundError(
            f"{name}: ChemBERTa assets not found for {model_name}: {asset_root}. "
            "Use a complete MolPROP checkout before running predictions."
        )

    for filename in _CHEMBERTA_REQUIRED_FILES:
        _assert_materialized_file(
            asset_root / filename,
            label=f"{name} ChemBERTa asset",
        )


def _predict_from_tensor(
    values: list[float],
    *,
    mode: str,
    positive_class_index: int | None,
) -> tuple[float, float | None]:
    if not values:
        raise ValueError("Model returned no prediction values")

    if mode == "discrete":
        if len(values) == 1:
            probability = _sigmoid(values[0])
            uncertainty = probability * (1.0 - probability)
            return probability, uncertainty
        probs = _softmax(values)
        idx = 1 if positive_class_index is None else int(positive_class_index)
        idx = max(0, min(idx, len(probs) - 1))
        probability = probs[idx]
        entropy = -sum(p * math.log(max(p, 1e-12)) for p in probs)
        normalized_entropy = entropy / math.log(len(probs))
        return probability, normalized_entropy

    value = float(values[0])
    return value, None


def _load_batch(loader):
    batch = next(iter(loader))
    if not isinstance(batch, (list, tuple)) or len(batch) < 6:
        raise ValueError("Unexpected batch format from MolPROP dataloader")
    return batch


def _to_device(batch, device, torch_module):
    lrs, ens_attention_masks, alphas, tokens, attention_masks = batch[:5]
    if isinstance(lrs, torch_module.Tensor) or lrs is None:
        if isinstance(lrs, torch_module.Tensor):
            lrs = lrs.float().to(device)
        if isinstance(ens_attention_masks, torch_module.Tensor):
            ens_attention_masks = ens_attention_masks.bool().to(device)
        if isinstance(alphas, torch_module.Tensor):
            alphas = alphas.bool().to(device)
        if isinstance(tokens, torch_module.Tensor):
            tokens = tokens.int().to(device)
        if isinstance(attention_masks, torch_module.Tensor):
            attention_masks = attention_masks.bool().to(device)
    else:
        from torch_geometric.data import Batch as GeometricBatch  # type: ignore

        lrs = GeometricBatch.from_data_list([item.to(device) for item in lrs]).to(device)
        if isinstance(tokens, torch_module.Tensor):
            tokens = tokens.int().to(device)
        if isinstance(attention_masks, torch_module.Tensor):
            attention_masks = attention_masks.bool().to(device)
    return lrs, ens_attention_masks, alphas, tokens, attention_masks


def _predict_endpoint(
    *,
    smiles: str,
    name: str,
    cfg: dict[str, Any],
    config_dir: Path,
    repo_dir: Path,
    device_name: str,
) -> tuple[float, float | None]:
    import pandas as pd  # type: ignore
    import torch  # type: ignore
    from torch.nn.modules.utils import consume_prefix_in_state_dict_if_present  # type: ignore
    from torch.utils.data import DataLoader  # type: ignore

    setup_path = _resolve_path(str(cfg.get("setup_json") or ""), config_dir=config_dir, repo_dir=repo_dir)
    checkpoint_path = _resolve_path(
        str(cfg.get("checkpoint_file") or ""),
        config_dir=config_dir,
        repo_dir=repo_dir,
    )
    if setup_path is None:
        raise FileNotFoundError(f"{name}: setup_json not found")
    if checkpoint_path is None:
        raise FileNotFoundError(f"{name}: checkpoint_file not found")

    _assert_materialized_file(setup_path, label=f"{name} setup_json")
    _assert_materialized_file(checkpoint_path, label=f"{name} checkpoint_file")

    setup = _load_json(setup_path)
    _validate_language_assets(name=name, setup=setup, repo_dir=repo_dir)
    training = setup.get("training") if isinstance(setup.get("training"), dict) else {}
    mode = str(cfg.get("mode") or setup.get("network", {}).get("language", {}).get("mode") or "discrete").strip().lower()
    positive_class_index = cfg.get("positive_class_index")

    source_column = str(cfg.get("source_column") or "ids")
    target_column = str(cfg.get("target_column") or "y")
    set_l = int(cfg.get("set_L") or training.get("set_L") or 1)
    fusion_size = int(cfg.get("fusion_size") or 320)

    prev_cwd = Path.cwd()
    try:
        os.chdir(repo_dir)
        sys.path.insert(0, str((repo_dir / "src").resolve()))
        from DataLoader import SuperSet_csv  # type: ignore
        from DeepNetworks.SLEF import SLEFNet  # type: ignore
        from utils import collateFunction  # type: ignore

        model = SLEFNet(setup["network"])
        checkpoint = torch.load(str(checkpoint_path), map_location=device_name)
        state_dict = _state_dict_from_checkpoint(checkpoint)
        consume_prefix_in_state_dict_if_present(state_dict, "module.")
        model.load_state_dict(state_dict, strict=False)
        model = model.to(device_name)
        model.eval()

        rows = [{source_column: smiles, target_column: 0.0}]
        data = pd.DataFrame(rows)
        dataset = SuperSet_csv(data=data, X=source_column, y=target_column)
        loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=0,
            collate_fn=collateFunction(setup=setup, set_L=set_l),
            pin_memory=False,
        )

        batch = _load_batch(loader)
        lrs, ens_attention_masks, alphas, tokens, attention_masks = _to_device(batch, device_name, torch)
        with torch.no_grad():
            output = model(
                lrs,
                ens_attention_masks,
                alphas,
                tokens,
                attention_masks,
                fusion_size=fusion_size,
            )
        values = output.detach().cpu().numpy().reshape(-1).tolist()
        return _predict_from_tensor(values, mode=mode, positive_class_index=positive_class_index)
    finally:
        try:
            os.chdir(prev_cwd)
        except Exception:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MolPROP bridge command for Neurobin")
    parser.add_argument("--smiles", required=True, help="SMILES string")
    parser.add_argument(
        "--config",
        default=os.getenv("MOLPROP_BRIDGE_CONFIG", ""),
        help="Path to MolPROP bridge config JSON",
    )
    parser.add_argument(
        "--endpoint",
        default="",
        help="Optional endpoint name filter",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    smiles = str(args.smiles or "").strip()
    if not smiles:
        print("Missing SMILES", file=sys.stderr)
        return 2

    script_root = Path(__file__).resolve().parents[1]
    default_config = script_root / "config" / "molprop_bridge.json"
    config_path = Path(args.config).expanduser() if args.config else default_config
    if not config_path.exists():
        print(f"MolPROP bridge config not found: {config_path}", file=sys.stderr)
        return 2

    config = _load_json(config_path)
    config_dir = config_path.parent
    repo_dir = _resolve_path(
        str(config.get("repo_dir") or os.getenv("MOLPROP_REPO_DIR") or ""),
        config_dir=config_dir,
        repo_dir=None,
    )
    if repo_dir is None or not repo_dir.exists():
        print("MolPROP repo directory not found. Set repo_dir in config or MOLPROP_REPO_DIR.", file=sys.stderr)
        return 2

    endpoint_filter = str(args.endpoint or "").strip()
    endpoints = _iter_endpoints(config)
    if endpoint_filter:
        endpoints = [item for item in endpoints if item[0] == endpoint_filter]
    if not endpoints:
        print("No endpoints configured for MolPROP bridge", file=sys.stderr)
        return 2

    device_name = str(config.get("device") or os.getenv("MOLPROP_DEVICE") or "cpu")
    predictions: dict[str, float] = {}
    uncertainty: dict[str, float] = {}
    errors: dict[str, str] = {}

    for endpoint_name, endpoint_cfg in endpoints:
        enabled = endpoint_cfg.get("enabled", True)
        if enabled is False:
            continue
        try:
            pred, unc = _predict_endpoint(
                smiles=smiles,
                name=endpoint_name,
                cfg=endpoint_cfg,
                config_dir=config_dir,
                repo_dir=repo_dir,
                device_name=device_name,
            )
            predictions[endpoint_name] = float(pred)
            if unc is not None:
                uncertainty[endpoint_name] = float(unc)
        except Exception as exc:
            errors[endpoint_name] = str(exc)

    if not predictions:
        if errors:
            print("MolPROP bridge failed: " + "; ".join(f"{k}: {v}" for k, v in errors.items()), file=sys.stderr)
        else:
            print("MolPROP bridge produced no predictions", file=sys.stderr)
        return 2

    payload = {
        "predictions": predictions,
        "uncertainty": uncertainty,
        "meta": {
            "backend": "molprop-bridge",
            "device": device_name,
            "endpoint_count": len(predictions),
            "error_count": len(errors),
        },
    }
    if errors:
        payload["errors"] = errors
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
