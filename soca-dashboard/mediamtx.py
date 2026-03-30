import logging
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote

logger = logging.getLogger(__name__)

try:
    from ruamel.yaml import YAML
    _yaml = YAML()
    _yaml.preserve_quotes = True
    _yaml.indent(mapping=2, sequence=4, offset=2)
    YAML_OK = True
except ImportError:
    YAML_OK = False
    _yaml = None


def _load(yml_path: Path):
    if not YAML_OK:
        raise RuntimeError("ruamel.yaml not installed")
    if not yml_path.exists():
        raise FileNotFoundError(f"mediamtx.yml not found: {yml_path}")
    with open(yml_path, "r") as f:
        data = _yaml.load(f)
    if data is None:
        data = {}
    data.setdefault("paths", {})
    return data


def _save(yml_path: Path, data):
    with yml_path.open("w") as f:
        _yaml.dump(data, f)


def _build_rtsp_url(rtsp_url: str, username: str, password: str) -> str:
    if not username:
        return rtsp_url
    parsed = urlparse(rtsp_url)
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def add_source(yml_path: str, camera_name: str, rtsp_url: str, username: str = "", password: str = "") -> bool:
    try:
        p = Path(yml_path)
        data = _load(p)
        if camera_name in data["paths"]:
            return False
        data["paths"][camera_name] = {
            "source": _build_rtsp_url(rtsp_url, username, password),
            "rtspTransport": "automatic",
            "sourceOnDemand": "yes",
        }
        _save(p, data)
        return True
    except Exception as e:
        logger.error(f"mediamtx add_source error: {e}")
        return False


def update_source(yml_path: str, old_name: str, new_name: str, rtsp_url: str, username: str = "", password: str = "") -> bool:
    try:
        p = Path(yml_path)
        data = _load(p)
        if old_name not in data["paths"]:
            return False
        entry = data["paths"].pop(old_name)
        entry["source"] = _build_rtsp_url(rtsp_url, username, password)
        data["paths"][new_name] = entry
        _save(p, data)
        return True
    except Exception as e:
        logger.error(f"mediamtx update_source error: {e}")
        return False


def remove_source(yml_path: str, camera_name: str) -> bool:
    try:
        p = Path(yml_path)
        data = _load(p)
        if camera_name not in data["paths"]:
            return False
        del data["paths"][camera_name]
        _save(p, data)
        return True
    except Exception as e:
        logger.error(f"mediamtx remove_source error: {e}")
        return False
