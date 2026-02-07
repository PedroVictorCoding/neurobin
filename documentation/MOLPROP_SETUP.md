# MolProp Setup (Bridge Mode)

Neurobin can run MolProp predictions through a command bridge.

## 1) Create a MolProp environment

MolPROP is not pip-installable as a normal package. Use its own repo and environment.

Example:

```bash
git clone https://github.com/Merck/MolPROP.git /opt/MolPROP
conda env create --name molprop --file /opt/MolPROP/molprop.yml
```

## 2) Create bridge config

Copy the example config and edit paths:

```bash
cp core/config/molprop_bridge.example.json core/config/molprop_bridge.json
```

Set `repo_dir`, `setup_json`, and `checkpoint_file` for each endpoint model.

## 3) Enable bridge for Django

Set environment variables before running Django:

```bash
export MOLPROP_BRIDGE_ENABLED=1
export MOLPROP_PYTHON_BIN=/path/to/conda/envs/molprop/bin/python
export MOLPROP_BRIDGE_CONFIG=/home/main/Dev/neurobin/core/config/molprop_bridge.json
```

Optional:

```bash
export MOLPROP_ENDPOINT=BBB_Martins
```

## 4) Start app and refresh

- Open a compound page with SMILES.
- Click `MolProp`.
- Predictions are cached in `CompoundMolPropPrediction`.

## Notes

- The bridge command is `core/scripts/molprop_bridge.py`.
- If `MOLPROP_PREDICT_CMD` is set, it takes priority over bridge mode.
