from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError


_GENERIC_STEMS = {
    "model",
    "models",
    "weights",
    "checkpoint",
    "ckpt",
    "best",
    "latest",
    "slef_validation",
    "slef",
}


def _load_setup_mode(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "discrete"
    network = payload.get("network") if isinstance(payload, dict) else {}
    language = network.get("language") if isinstance(network, dict) else {}
    mode = language.get("mode") if isinstance(language, dict) else None
    mode_s = str(mode or "").strip().lower()
    return mode_s if mode_s in {"discrete", "continuous"} else "discrete"


def _sanitize_name(raw: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_")
    return out or "endpoint"


def _name_from_checkpoint(repo_dir: Path, checkpoint: Path, index: int) -> str:
    stem = checkpoint.stem.strip().lower()
    if stem and stem not in _GENERIC_STEMS:
        return _sanitize_name(checkpoint.stem)

    rel_parts = checkpoint.relative_to(repo_dir).parts[:-1]
    for part in reversed(rel_parts):
        candidate = part.strip().lower()
        if candidate and candidate not in _GENERIC_STEMS:
            return _sanitize_name(part)
    return f"endpoint_{index:03d}"


def _pair_score(checkpoint: Path, setup: Path) -> tuple[int, int]:
    checkpoint_parent = checkpoint.parent.resolve()
    setup_parent = setup.parent.resolve()
    try:
        rel = checkpoint_parent.relative_to(setup_parent)
        return (0, len(rel.parts))
    except ValueError:
        pass

    c_parts = checkpoint_parent.parts
    s_parts = setup_parent.parts
    common = 0
    for c, s in zip(c_parts, s_parts):
        if c != s:
            break
        common += 1
    divergence = (len(c_parts) - common) + (len(s_parts) - common)
    return (1, divergence)


def _find_best_setup(checkpoint: Path, setup_files: list[Path]) -> Path | None:
    if not setup_files:
        return None
    return min(setup_files, key=lambda setup: _pair_score(checkpoint, setup))


class Command(BaseCommand):
    help = "Generate core/config/molprop_bridge.json by auto-discovering setup/checkpoint files in a MolPROP repo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo-dir",
            required=True,
            help="Path to local MolPROP repo checkout.",
        )
        parser.add_argument(
            "--out",
            default="core/config/molprop_bridge.json",
            help="Output JSON path for generated bridge config.",
        )
        parser.add_argument(
            "--device",
            default="cpu",
            help="Device value to place in generated config (cpu/cuda).",
        )
        parser.add_argument(
            "--checkpoint-glob",
            default="**/*.pth",
            help="Glob pattern to find checkpoint files under repo.",
        )
        parser.add_argument(
            "--setup-glob",
            default="**/setup*.json",
            help="Glob pattern to find setup JSON files under repo.",
        )
        parser.add_argument(
            "--name-prefix",
            default="",
            help="Optional prefix for generated endpoint names.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite output file if it exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print generated JSON without writing file.",
        )

    def handle(self, *args, **options):
        repo_dir = Path(options["repo_dir"]).expanduser().resolve()
        out_path = Path(options["out"]).expanduser().resolve()
        device = str(options["device"]).strip() or "cpu"
        checkpoint_glob = str(options["checkpoint_glob"]).strip() or "**/*.pth"
        setup_glob = str(options["setup_glob"]).strip() or "**/setup*.json"
        name_prefix = _sanitize_name(str(options["name_prefix"]).strip()) if options["name_prefix"] else ""
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])

        if not repo_dir.exists() or not repo_dir.is_dir():
            raise CommandError(f"MolPROP repo not found: {repo_dir}")

        setup_files = sorted([p for p in repo_dir.glob(setup_glob) if p.is_file()])
        checkpoint_files = sorted([p for p in repo_dir.glob(checkpoint_glob) if p.is_file()])
        if not setup_files:
            raise CommandError(f"No setup files found with glob '{setup_glob}' under {repo_dir}")
        if not checkpoint_files:
            raise CommandError(f"No checkpoint files found with glob '{checkpoint_glob}' under {repo_dir}")

        used_names: set[str] = set()
        endpoints: dict[str, dict[str, Any]] = {}
        skipped = 0

        for idx, checkpoint in enumerate(checkpoint_files, start=1):
            setup_file = _find_best_setup(checkpoint, setup_files)
            if not setup_file:
                skipped += 1
                continue

            base_name = _name_from_checkpoint(repo_dir, checkpoint, idx)
            if name_prefix:
                base_name = f"{name_prefix}_{base_name}"
            name = _sanitize_name(base_name)
            while name in used_names:
                name = f"{name}_{idx}"
            used_names.add(name)

            endpoints[name] = {
                "setup_json": str(setup_file.relative_to(repo_dir)),
                "checkpoint_file": str(checkpoint.relative_to(repo_dir)),
                "mode": _load_setup_mode(setup_file),
                "source_column": "ids",
                "target_column": "y",
                "enabled": True,
            }

        if not endpoints:
            raise CommandError("Auto-discovery produced zero endpoint mappings.")

        payload = {
            "repo_dir": str(repo_dir),
            "device": device,
            "endpoints": endpoints,
            "meta": {
                "generated_by": "manage.py generate_molprop_bridge_config",
                "setup_glob": setup_glob,
                "checkpoint_glob": checkpoint_glob,
                "discovered_endpoints": len(endpoints),
                "skipped_checkpoints": skipped,
            },
        }

        rendered = json.dumps(payload, indent=2, sort_keys=True)

        if dry_run:
            self.stdout.write(rendered)
            self.stdout.write(self.style.SUCCESS(f"Dry run complete: {len(endpoints)} endpoints mapped."))
            return

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not force:
            raise CommandError(f"Output exists: {out_path}. Use --force to overwrite.")

        out_path.write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path} with {len(endpoints)} endpoint mappings."))
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped {skipped} checkpoint files."))
        self.stdout.write("Review endpoint names and positive_class_index before production use.")
