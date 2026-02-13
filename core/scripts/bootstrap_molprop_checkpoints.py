#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _state_dict_from_checkpoint(checkpoint: Any) -> dict[str, Any]:
    if isinstance(checkpoint, dict):
        if isinstance(checkpoint.get("model_state_dict"), dict):
            return checkpoint["model_state_dict"]
        if isinstance(checkpoint.get("state_dict"), dict):
            return checkpoint["state_dict"]
        if checkpoint and all(hasattr(v, "shape") for v in checkpoint.values()):
            return checkpoint
    raise ValueError("Unsupported checkpoint format")


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create additional MolProp endpoint checkpoints from local CSVs.")
    parser.add_argument("--repo-dir", required=True, help="Path to writable MolPROP repo copy.")
    parser.add_argument("--epochs", type=int, default=1, help="Epochs per endpoint.")
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size.")
    parser.add_argument("--sample-size", type=int, default=128, help="Rows sampled per endpoint.")
    parser.add_argument("--lr", type=float, default=5e-5, help="Learning rate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not repo_dir.exists():
        raise SystemExit(f"Repo dir not found: {repo_dir}")

    base_dir = repo_dir / "neurobin_models" / "bbb_martins"
    base_setup_path = base_dir / "setup.json"
    base_checkpoint_path = base_dir / "SLEF_validation.pth"
    if not base_setup_path.exists() or not base_checkpoint_path.exists():
        raise SystemExit("Base neurobin checkpoint/setup missing in neurobin_models/bbb_martins")

    endpoint_specs = [
        ("bbbp_benchmark", "data/train_bbbp.csv", "discrete"),
        ("bace_benchmark", "data/train_bace.csv", "discrete"),
        ("clintox_benchmark", "data/train_clintox.csv", "discrete"),
        ("lipo_benchmark", "data/train_lipo.csv", "continuous"),
    ]

    random.seed(args.seed)
    os.environ.setdefault("PYTHONHASHSEED", str(args.seed))

    prev_cwd = Path.cwd()
    try:
        os.chdir(repo_dir)
        sys.path.insert(0, str((repo_dir / "src").resolve()))

        import pandas as pd  # type: ignore
        import torch  # type: ignore
        from torch.nn import BCEWithLogitsLoss, MSELoss  # type: ignore
        from torch.nn.modules.utils import consume_prefix_in_state_dict_if_present  # type: ignore
        from torch.utils.data import DataLoader  # type: ignore

        from DataLoader import SuperSet_csv  # type: ignore
        from DeepNetworks.SLEF import SLEFNet  # type: ignore
        from utils import collateFunction  # type: ignore

        base_setup = _load_json(base_setup_path)
        base_ckpt = torch.load(str(base_checkpoint_path), map_location="cpu")
        base_state = _state_dict_from_checkpoint(base_ckpt)
        consume_prefix_in_state_dict_if_present(base_state, "module.")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {device}")

        for endpoint_name, csv_rel, mode in endpoint_specs:
            csv_path = repo_dir / csv_rel
            if not csv_path.exists():
                print(f"Skipping {endpoint_name}: missing {csv_rel}")
                continue

            endpoint_dir = repo_dir / "neurobin_models" / endpoint_name
            endpoint_dir.mkdir(parents=True, exist_ok=True)

            setup = copy.deepcopy(base_setup)
            setup.setdefault("network", {}).setdefault("language", {})["mode"] = mode
            setup.setdefault("training", {})["set_L"] = int(setup.get("training", {}).get("set_L") or 1)
            setup_path = endpoint_dir / "setup.json"
            setup_path.write_text(json.dumps(setup, indent=2) + "\n", encoding="utf-8")

            df = pd.read_csv(csv_path)
            if "ids" not in df.columns or "y" not in df.columns:
                print(f"Skipping {endpoint_name}: ids/y columns missing in {csv_rel}")
                continue
            if len(df) > args.sample_size:
                df = df.sample(n=args.sample_size, random_state=args.seed).reset_index(drop=True)

            dataset = SuperSet_csv(data=df[["ids", "y"]], X="ids", y="y")
            loader = DataLoader(
                dataset,
                batch_size=max(1, int(args.batch_size)),
                shuffle=True,
                num_workers=0,
                collate_fn=collateFunction(setup=setup, set_L=int(setup["training"]["set_L"])),
                pin_memory=False,
            )

            model = SLEFNet(setup["network"])
            model.load_state_dict(base_state, strict=False)
            model = model.to(device)
            model.train()

            optimizer = torch.optim.Adam(model.parameters(), lr=float(args.lr))
            loss_fn = BCEWithLogitsLoss() if mode == "discrete" else MSELoss()

            for _ in range(max(1, int(args.epochs))):
                for batch in loader:
                    optimizer.zero_grad()
                    lrs, ens_attention_masks, alphas, tokens, attention_masks = _to_device(batch, device, torch)
                    props = batch[5].reshape(-1).float().to(device)
                    output = model(
                        lrs,
                        ens_attention_masks,
                        alphas,
                        tokens,
                        attention_masks,
                        fusion_size=320,
                    ).reshape(-1)
                    loss = loss_fn(output, props)
                    loss.backward()
                    optimizer.step()

            ckpt = {"model_state_dict": model.state_dict()}
            ckpt_path = endpoint_dir / "SLEF_validation.pth"
            torch.save(ckpt, str(ckpt_path))
            print(f"Wrote {endpoint_name} checkpoint: {ckpt_path}")
    finally:
        os.chdir(prev_cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
