"""Read the active Fluent Meshing transcript and enforce the production early-stop rules."""
import re
import time

NUMBER=r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
CELLS=re.compile(r"([\d,]+)\s+cells?\s+above\s+inverse[- ]orthogonal[- ]quality\s*[:=]?\s*("+NUMBER+r")",re.I)
SKEW=re.compile(r"(?:worst\s+skewness|,\s*max skew)\s*[:=]?\s*("+NUMBER+r")",re.I)
IMPROVE=re.compile(r"^\s*(?:improved [\d,]+ nodes, most improvement|smooth[- ]improve|improving (?:the )?(?:volume|cell|mesh)|smooth(?:ing)? (?:prism|poly)|remesh cells with quality)",re.I)


def scheme_histogram_population(line, total=None):
    # v252: (in_range (bin_counts...) (underflow overflow)).
    match = re.fullmatch(r"\s*\((\d+)\s+\((\d+)\)\s+\((\d+)\s+(\d+)\)\)\s*", line)
    if not match:
        return None
    reported, count, below, above = map(int, match.groups())
    if reported != count or (total is not None and below + count + above != total):
        return None
    return count + above


class MeshQualityGuard:
    def __init__(self):
        self.tail={}
        self.histogram_state={}
        self.native_node_move=set()
        self.reported_total={}
        self.improving=False
        self.bad_since=None
        self.worst_skew=None
        self.improvement_started=None
        self.last_skew_observation=None
        self.post_improvement_skew_observed=False
        self.pre_improvement_observations=[]
        self.reason=None
        self.measurement=None

    def feed(self,src,chunk,now=None):
        now=time.monotonic() if now is None else now
        full=self.tail.get(src,"")+chunk.decode("ascii",errors="replace")
        lines=full.split("\n")
        self.tail[src]=lines.pop()
        for line in lines:
            stripped = line.strip()
            mesh_count = re.search(r"^number of interior cells\s*=\s*(\d+)", stripped)
            if mesh_count:
                self.reported_total[src] = int(mesh_count[1])
            if re.match(r"^>\s*/file/read-(?:case|mesh)\b", stripped):
                self.native_node_move.discard(src)
            elif re.match(r"^>\s*/mesh/modify/auto-node-move\b", stripped):
                self.native_node_move.add(src)
            marker = re.fullmatch(r"X57-(?:(RAW|POST)-)?INVERSE-OQ-DISTRIBUTION-(BEGIN|END)", stripped)
            if marker:
                if marker[2] == "END":
                    self.histogram_state.pop(src, None)
                else:
                    post = marker[1] == "POST" or (marker[1] is None and src in self.native_node_move)
                    self.histogram_state[src] = ("opened", post)
            else:
                stage, post = self.histogram_state.get(src, (None, False))
                if stage == "opened" and "tgapi-util-get-cell-mesh-distribution" in line and "Inverse Orthogonal Quality" in line and ".9500000000000001 1.0e20" in line:
                    self.histogram_state[src] = ("awaiting_count", post)
                elif stage == "awaiting_count":
                    population = scheme_histogram_population(line, self.reported_total.get(src))
                    if population is not None:
                        self.histogram_state.pop(src, None)
                        if population > 5000:
                            observation = dict(count=population, reported_inverse_OQ_threshold=.95, line=stripped)
                            if post and self.reason is None:
                                self.reason = "More than 5000 cells still exceed inverse orthogonal quality 0.95 after mesh improvement."
                                self.measurement = dict(observation, phase="post_improvement_histogram")
                            elif not post:
                                self.pre_improvement_observations.append(observation)
            if re.search(r"cells removed for stair-step|generating dual cells|converting to poly",line,re.I):
                self.improving=False
                self.worst_skew=None
                self.bad_since=None
                self.improvement_started=None
                self.post_improvement_skew_observed=False
            if IMPROVE.search(line) and not self.improving:
                self.improving=True
                self.improvement_started=now
                if self.worst_skew is not None and self.worst_skew>=1:
                    self.bad_since=now
            count=CELLS.search(line)
            if count:
                # Record intermediate pre-dual / pre-improvement counts for diagnostics only;
                # never kill Fluent before poly-hexcore conversion and Improve Volume Mesh finish.
                affected=int(count[1].replace(",",""))
                threshold=float(count[2])
                if affected>5000 and threshold>=.95:
                    self.pre_improvement_observations.append(
                        dict(count=affected,reported_inverse_OQ_threshold=threshold,line=stripped)
                    )
            skew=SKEW.search(line)
            if skew:
                self.worst_skew=float(skew[1])
                self.last_skew_observation=dict(line=stripped,at=now)
                if self.improving:
                    self.post_improvement_skew_observed=True
                    if self.worst_skew<1:
                        self.bad_since=None
                    elif self.bad_since is None:
                        self.bad_since=now
        return self.check(now)

    def check(self,now=None):
        now=time.monotonic() if now is None else now
        if (self.reason is None and self.bad_since is not None and self.post_improvement_skew_observed
                and now-self.bad_since>=1500):
            self.reason="Worst skewness remained at or above 1.0 in mesh-improvement reports for over 25 minutes."
            self.measurement=dict(last_reported_worst_skewness=self.worst_skew,
                                  elapsed_since_high_skew_improvement_started_s=now-self.bad_since,
                                  reported_during_improvement=self.post_improvement_skew_observed,
                                  last_skew_report_line=self.last_skew_observation["line"] if self.last_skew_observation else None)
        return self.reason

