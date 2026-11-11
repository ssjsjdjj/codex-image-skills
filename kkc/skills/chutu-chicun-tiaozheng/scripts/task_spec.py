"""Fixed task parsing shared by rendering, validation and sequential review."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def load_jobs(path, *, require_size=True):
    spec = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict) or not isinstance(spec.get("defaults", {}), dict):
        raise ValueError("任务单和defaults必须为对象")
    if not isinstance(spec.get("jobs"), list) or not spec["jobs"]:
        raise ValueError("任务单jobs必须为非空列表")
    jobs = []
    for item in spec["jobs"]:
        if not isinstance(item, dict):
            raise ValueError("每项任务必须为对象")
        job = {**spec.get("defaults", {}), **item}
        if not isinstance(job.get("input"), str) or not job["input"] or (require_size and not job.get("size")):
            raise ValueError("每项任务需要input和size（可放在defaults中）")
        jobs.append(job)
    return jobs
