"""Runs inside Fluent 25.2 solver (via %py-exec) after the meshing-mode volume mesh is read.

Fluent-native mesh repair: repair() fixes handedness/node-order problems flagged by
/mesh/check, improve_quality() smooths interior nodes of the worst cells. Boundary
nodes are NOT moved, so the CAD surface and all named zones are preserved.
This worker never raises: any API problem is recorded and the journal continues.
"""
import json
import os
import sys
import traceback
from pathlib import Path

record = {"steps": [], "errors": []}
try:
    sys.path.insert(0, str(Path(os.environ["FLUENT_PROD_DIR"]) / "cortex/pylib"))
    import flsetup
    flsetup.insert_pyfluent_module_path()
    from flapi.flproxy import Proxy
    from flapi.generated.solver.settings_252 import root

    s = root()
    s.set_flproxy(Proxy)
    cfg = json.loads((Path.cwd() / "repair_config.json").read_text(encoding="utf-8"))
    passes = int(cfg.get("improve_passes", 2))
    ri = s.mesh.repair_improve
    for name, value in (("allow_repair_at_boundaries", False),
                        ("include_local_polyhedra_conversion_in_repair", False)):
        try:
            setattr(ri, name, value)
            record["steps"].append(f"{name}={value}")
        except Exception as exc:  # option absent in this build
            record["errors"].append(f"{name}: {exc}")
    try:
        ri.repair()
        record["steps"].append("repair")
    except Exception as exc:
        record["errors"].append(f"repair: {exc}")
    for i in range(passes):
        try:
            ri.improve_quality()
            record["steps"].append(f"improve_quality_{i + 1}")
        except Exception as exc:
            record["errors"].append(f"improve_quality_{i + 1}: {exc}")
            break
except Exception:
    record["errors"].append(traceback.format_exc()[-2000:])
try:
    (Path.cwd() / "repair_record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
except Exception:
    pass
print("X57-FASTTRACK-REPAIR", json.dumps(record)[:600], flush=True)
