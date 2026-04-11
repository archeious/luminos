"""Cache management for Luminos investigations."""

import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone

CACHE_ROOT = "/tmp/luminos"
INVESTIGATIONS_PATH = os.path.join(CACHE_ROOT, "investigations.json")


def clear_cache():
    """Remove all investigation caches under CACHE_ROOT."""
    if os.path.isdir(CACHE_ROOT):
        shutil.rmtree(CACHE_ROOT)
        print(f"Cleared cache: {CACHE_ROOT}", file=sys.stderr)
    else:
        print(f"No cache to clear ({CACHE_ROOT} does not exist).",
              file=sys.stderr)


def _sha256_path(path):
    """Return a hex SHA-256 of a path string, used as cache key."""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Investigation ID persistence
# ---------------------------------------------------------------------------

def _load_investigations():
    try:
        with open(INVESTIGATIONS_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_investigations(data):
    os.makedirs(CACHE_ROOT, exist_ok=True)
    with open(INVESTIGATIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _get_investigation_id(target, fresh=False):
    target_real = os.path.realpath(target)
    investigations = _load_investigations()
    if not fresh and target_real in investigations:
        inv_id = investigations[target_real]
        cache_dir = os.path.join(CACHE_ROOT, inv_id)
        if os.path.isdir(cache_dir):
            return inv_id, False
    inv_id = str(uuid.uuid4())
    investigations[target_real] = inv_id
    _save_investigations(investigations)
    return inv_id, True


# ---------------------------------------------------------------------------
# Cache manager
# ---------------------------------------------------------------------------

class _CacheManager:
    """Manages the /tmp/luminos/{investigation_id}/ cache tree."""

    def __init__(self, investigation_id, target):
        self.investigation_id = investigation_id
        self.target = os.path.realpath(target)
        self.root = os.path.join(CACHE_ROOT, investigation_id)
        self.files_dir = os.path.join(self.root, "files")
        self.dirs_dir = os.path.join(self.root, "dirs")
        self.log_path = os.path.join(self.root, "investigation.log")
        self.meta_path = os.path.join(self.root, "meta.json")
        os.makedirs(self.files_dir, exist_ok=True)
        os.makedirs(self.dirs_dir, exist_ok=True)

    def write_meta(self, model, start_time):
        data = {
            "investigation_id": self.investigation_id,
            "target": self.target,
            "start_time": start_time,
            "model": model,
            "directories_investigated": 0,
            "total_turns": 0,
        }
        with open(self.meta_path, "w") as f:
            json.dump(data, f, indent=2)

    def update_meta(self, **kwargs):
        try:
            with open(self.meta_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        data.update(kwargs)
        with open(self.meta_path, "w") as f:
            json.dump(data, f, indent=2)

    def log_turn(self, directory, turn, tool_name, tool_args, result_len):
        entry = {
            "directory": directory,
            "turn": turn,
            "timestamp": _now_iso(),
            "tool": tool_name,
            "args": tool_args,
            "result_length": result_len,
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _cache_path(self, cache_type, path):
        subdir = self.files_dir if cache_type == "file" else self.dirs_dir
        return os.path.join(subdir, _sha256_path(path) + ".json")

    def _cache_safe(self, cache_file):
        real = os.path.realpath(cache_file)
        root_real = os.path.realpath(self.root)
        return real.startswith(root_real + os.sep)

    def write_entry(self, cache_type, path, data):
        cache_file = self._cache_path(cache_type, path)
        if not self._cache_safe(cache_file):
            return "Error: cache path escapes cache root."
        required = {"path", "summary", "cached_at"}
        if cache_type == "file":
            required |= {"relative_path", "size_bytes", "category"}
        elif cache_type == "dir":
            required |= {"relative_path", "child_count", "dominant_category"}
        missing = required - set(data.keys())
        if missing:
            return f"Error: missing required fields: {', '.join(sorted(missing))}"
        if "content" in data or "contents" in data or "raw" in data:
            return "Error: cache entries must not contain raw file contents."
        if "confidence" in data:
            c = data["confidence"]
            if not isinstance(c, (int, float)) or not (0.0 <= c <= 1.0):
                return "Error: confidence must be a float between 0.0 and 1.0"
        if "confidence_reason" in data and not isinstance(data["confidence_reason"], str):
            return "Error: confidence_reason must be a string"
        try:
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
            return "ok"
        except OSError as e:
            return f"Error writing cache: {e}"

    def read_entry(self, cache_type, path):
        cache_file = self._cache_path(cache_type, path)
        if not self._cache_safe(cache_file):
            return None
        try:
            with open(cache_file) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def has_entry(self, cache_type, path):
        cache_file = self._cache_path(cache_type, path)
        return os.path.exists(cache_file)

    def list_entries(self, cache_type):
        subdir = self.files_dir if cache_type == "file" else self.dirs_dir
        result = []
        try:
            for name in sorted(os.listdir(subdir)):
                if not name.endswith(".json"):
                    continue
                fpath = os.path.join(subdir, name)
                try:
                    with open(fpath) as f:
                        data = json.load(f)
                    result.append(data.get("relative_path", data.get("path", name)))
                except (OSError, json.JSONDecodeError):
                    continue
        except OSError:
            pass
        return result

    def read_all_entries(self, cache_type):
        subdir = self.files_dir if cache_type == "file" else self.dirs_dir
        result = []
        try:
            for name in sorted(os.listdir(subdir)):
                if not name.endswith(".json"):
                    continue
                fpath = os.path.join(subdir, name)
                try:
                    with open(fpath) as f:
                        result.append(json.load(f))
                except (OSError, json.JSONDecodeError):
                    continue
        except OSError:
            pass
        return result

    def low_confidence_entries(self, threshold=0.7):
        """Return all file and dir cache entries with confidence below threshold.

        Entries missing a confidence field are included — they are unrated and
        therefore untrusted. Results are sorted ascending by confidence so the
        least-confident entries come first.
        """
        entries = self.read_all_entries("file") + self.read_all_entries("dir")
        low = [e for e in entries if e.get("confidence", 0.0) < threshold]
        low.sort(key=lambda e: e.get("confidence", 0.0))
        return low
