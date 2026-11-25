"""Copy a native FTM checkpoint and relocate its saved project dependencies."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import h5py


ROOT = Path(__file__).resolve().parents[1]
PROJECT_STRING = re.compile(rb'"([DEF]:/FEA Coursework/Workspace/[^"\r\n]+)"', re.I)


def workspace_path(path, *, existing):
    path = Path(path).resolve(strict=existing)
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Expected a workspace path: {path}")
    return path


def copy_checkpoint(source, destination, size_field=None):
    source = workspace_path(source, existing=True)
    destination = workspace_path(destination, existing=False)
    field = workspace_path(size_field, existing=True) if size_field is not None else None
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError(f"A new checkpoint path in an existing directory is required: {destination}")
    mappings = {}

    def replace_path(match):
        old = match[1].decode("utf-8")
        relative = old.split("/", 3)[3]
        target = field if field is not None and relative.lower().endswith(".sf") else ROOT / relative
        target = workspace_path(target, existing=True)
        if not target.is_file():
            raise ValueError(f"Missing checkpoint dependency: {target}")
        mappings[old] = str(target)
        return b'"' + target.as_posix().encode("utf-8") + b'"'

    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".ftm-", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        shutil.copyfile(source, temp_path)
        with h5py.File(temp_path, "r+") as h:
            settings = h["settings"]
            for name in list(settings):
                old = settings[name]
                if old.shape != (1,) or old.dtype.kind != "S":
                    continue
                before = bytes(old[0])
                after = PROJECT_STRING.sub(replace_path, before)
                if after == before:
                    continue
                if len(after) >= old.dtype.itemsize:
                    # CFF stores one null-terminated string with FEM metadata attributes.
                    # Keep the HDF5 creation properties, encoding, padding and all attributes.
                    datatype = old.id.get_type().copy()
                    datatype.set_size(len(after) + 1)
                    new_id = h5py.h5d.create(settings.id, None, datatype, old.id.get_space(),
                                              dcpl=old.id.get_create_plist())
                    new = h5py.Dataset(new_id)
                    for attr in old.attrs:
                        new.attrs.create(attr, old.attrs[attr], dtype=old.attrs.get_id(attr).dtype)
                    del settings[name]
                    settings[name] = new
                settings[name][0] = after
                if bytes(settings[name][0]) != after:
                    raise ValueError(f"Fluent settings string failed lossless readback: {name}")
        if not mappings or (field is not None and str(field) not in mappings.values()):
            raise ValueError("No matching saved FTM project dependencies or size-field entry.")
        os.rename(temp_path, destination)
        return mappings
    finally:
        temp_path.unlink(missing_ok=True)



def copy_sidecars(source, destination, size_field=None):
    """Install a native workflow sidecar directory atomically for a relocated checkpoint."""
    source = workspace_path(source, existing=True)
    destination = workspace_path(destination, existing=True)
    field = workspace_path(size_field, existing=True) if size_field is not None else None
    source_stem = source.name.removesuffix(".msh.h5")
    target_stem = destination.name.removesuffix(".msh.h5")
    original = source.with_name(source_stem + "_workflow_files")
    target = destination.with_name(target_stem + "_workflow_files")
    if target.exists() or not original.is_dir():
        raise ValueError(f"Expected original sidecars and a new destination: {original}, {target}")

    def update_workflow(value):
        if isinstance(value, dict):
            return {k: update_workflow(v) for k, v in value.items()}
        if isinstance(value, list):
            return [update_workflow(x) for x in value]
        if isinstance(value, str) and PROJECT_STRING.fullmatch(b'"' + value.encode('utf-8') + b'"'):
            relative = value.split("/", 3)[3]
            dep = field if field is not None and relative.lower().endswith(".sf") else ROOT / relative
            return workspace_path(dep, existing=True).as_posix()
        return value

    with tempfile.TemporaryDirectory(prefix=".ftm-sidecars-", dir=target.parent) as stage:
        directory = Path(stage) / "workflow"
        directory.mkdir()
        for entry in original.rglob("*"):
            if entry.is_dir():
                continue
            dest = directory / entry.relative_to(original)
            if entry.name in (source_stem + ".wft", source_stem + ".fmd"):
                dest = dest.with_name(target_stem + entry.suffix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if entry.suffix == ".wft":
                data = json.loads(entry.read_text("utf-8-sig"))
                dest.write_text(json.dumps(update_workflow(data), indent=4), encoding="utf-8")
            elif entry.name.endswith(".msh.h5"):
                copy_checkpoint(entry, dest, field)
            else:
                shutil.copyfile(entry, dest)
        os.rename(directory, target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--size-field", type=Path)
    parser.add_argument("--sidecars-only", action="store_true")
    args = parser.parse_args()
    if args.sidecars_only:
        print(copy_sidecars(args.source, args.destination, args.size_field))
        raise SystemExit(0)
    for old, new in copy_checkpoint(args.source, args.destination, args.size_field).items():
        print(f"{old} -> {new}")
