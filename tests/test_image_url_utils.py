import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agents"))

from image_url_utils import resolve_image_url


def test_absolute_http_url_is_unchanged():
    url = "https://example.com/image.png"

    assert resolve_image_url(url, "https://example.com/post") == url


def test_site_relative_url_resolves_against_source_url():
    url = "/img/medium/700/1*example.png"
    base = "https://freedium-mirror.cfd/https://medium.com/example"

    assert resolve_image_url(url, base) == "https://freedium-mirror.cfd/img/medium/700/1*example.png"


def test_site_relative_url_requires_http_base():
    assert resolve_image_url("/img/a.png", "") is None
    assert resolve_image_url("/img/a.png", "not-a-url") is None


def test_local_relative_path_is_not_remote():
    assert resolve_image_url("../assets/original/a.png", "https://example.com") is None
