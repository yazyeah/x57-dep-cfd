"""Inspect native Fluent HDF5 files and match data with its recorded case."""
from pathlib import Path
import h5py


def check_mesh_file(path, deep=False):
    try:
        with h5py.File(path, "r") as f:
            surface = "meshes/1/faces/nodes" in f
            volume = "meshes/1/cells/zoneTopology/maxId" in f and len(f["meshes/1/cells/zoneTopology/maxId"]) > 0
            if volume:
                zone = f["meshes/1/cells/zoneTopology"]
                volume = any(int(a) >= 1 and int(b) >= int(a) for a,b in zip(zone["minId"][:],zone["maxId"][:]))
            if deep and surface:
                readable_blocks(f)
            return surface, volume
    except (OSError, KeyError, ValueError):
        return False, False


def readable_blocks(file):
    """Read every allocated numerical payload in bounded slabs during a resume scan."""
    def visit(_, ds):
        if isinstance(ds,h5py.Dataset):
            if not ds.shape:
                ds[()]
            elif ds.shape[0]:
                row_bytes = max(1, ds.size // ds.shape[0] * ds.dtype.itemsize)
                step = max(1,(8 << 20) // row_bytes)
                for i in range(0,ds.shape[0],step):
                    ds[i:i+step]
    file.visititems(visit)


def case_for_data(data, deep=False):
    """Resolve the native Case File reference and verify complete matching pressure IDs."""
    with h5py.File(data, "r") as d:
        ref = d["settings/Case File"][0].decode("utf-8").rstrip("\0")
        case_name = Path(ref.replace("\\","/")).name
        if not case_name.endswith(".cas.h5"):
            raise ValueError("missing native case file reference")
        case = data.parent / case_name
        with h5py.File(case, "r") as c:
            topology = c["meshes/1/cells/zoneTopology"]
            def merge(intervals):
                united = []
                for lo, hi in sorted(intervals):
                    if lo < 1 or hi < lo or (united and lo <= united[-1][1]):
                        raise ValueError("invalid or overlapping cell ID ranges")
                    if united and lo == united[-1][1] + 1:
                        united[-1] = (united[-1][0], hi)
                    else:
                        united.append((lo, hi))
                return united
            zones = merge([(int(i),int(j)) for i,j in zip(topology["minId"][:],topology["maxId"][:])])
            blocks = []
            for block in d["results/1/phase-1/cells/SV_P"].values():
                lo = int(block.attrs["minId"].item())
                hi = int(block.attrs["maxId"].item())
                if len(block) != hi-lo+1:
                    raise ValueError("incomplete pressure block")
                blocks.append((lo,hi))
            if not zones or merge(blocks) != zones:
                raise ValueError("case and pressure cell ID intervals differ")
            if deep:
                readable_blocks(c)
                readable_blocks(d)
            return case


def latest_pair(folder, deep=False):
    failures = []
    for data in sorted(folder.glob("*.dat.h5"), key=lambda p:p.stat().st_mtime_ns, reverse=True):
        try:
            return case_for_data(data, deep), data, failures
        except (KeyError, OSError, ValueError, TypeError, IndexError) as e:
            failures.append({"data":data.name, "reason":str(e)})
    return None,None,failures
