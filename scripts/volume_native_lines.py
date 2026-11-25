"""Track completed native transcript lines for production volume generation."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

LIMIT_SECONDS = 35 * 60

def is_volume_generation(mode,workdir,journal,workspace):
    if mode!="meshing" or journal.parent!=workdir or not workdir.is_relative_to(workspace/"02_mesh"):
        return False
    config=workdir/"mesh_config.json"
    if not config.is_file():
        return False
    settings=json.loads(config.read_text(encoding="utf-8-sig"))
    if settings.get("level") not in ("coarse","medium","fine"):
        return False
    declared=settings.get("generation_journal")
    if declared:
        return (workdir/declared).resolve()==journal
    # Older locally generated inputs precede the generation_journal property.
    if journal.name.lower()!="mesh.jou":
        return False
    text=journal.read_text(encoding="utf-8-sig",errors="replace")
    return bool(re.search(r"(?im)^\s*/mesh/auto-mesh(?:\s|$)|GenerateTheVolumeMeshFTM|fill\(workflow,\s*meshing,",text))

class VolumeLines:
    def __init__(self,run_id,journal,case,monotonic_start,wall_start):
        self.run_id=run_id
        self.case=case
        self.journal=str(journal)
        self.started=wall_start
        self.last_tick=monotonic_start
        self.last_wall=None
        self.source=None
        self.last_line=None
        self.count=0
        self.partial={}

    def feed(self,source,chunk,tick,wall):
        head,sep,tail=chunk.rpartition(b"\n")
        prior=self.partial.get(source,b"")
        if not sep:
            self.partial[source]=(prior+tail)[-2048:]
            return False
        self.partial[source]=tail[-2048:]
        # CR-only updates and incomplete bytes never reset the expiration.
        previous_line=head.rsplit(b"\n",1)[-1] if b"\n" in head else prior+head
        self.last_line=previous_line.rstrip(b"\r")[-2048:].decode("utf-8",errors="replace")
        self.source=str(source)
        self.count+=chunk.count(b"\n")
        self.last_tick=tick
        self.last_wall=wall
        return True

    def expired(self,tick):
        return tick-self.last_tick>=LIMIT_SECONDS

    def evidence(self,tick,wall):
        def stamp(epoch):
            return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="milliseconds")
        return dict(run_id=self.run_id,case=self.case,journal=self.journal,started_at=stamp(self.started),
                    observed_at=stamp(wall),native_transcript=self.source,completed_native_lines=self.count,
                    last_line=self.last_line,last_line_observed_at=stamp(self.last_wall) if self.last_wall is not None else None,
                    silent_seconds=round(max(0.,tick-self.last_tick),3),limit_seconds=LIMIT_SECONDS)
