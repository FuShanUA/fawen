from urllib.parse import urljoin


def resolve_image_url(url, base_url):
    """Return an absolute remote image URL, or None for non-remote inputs."""
    url = str(url or "").strip()
    if url.startswith(("http://", "https://")):
        return url

    if url.startswith("/"):
        base_url = str(base_url or "").strip()
        if not base_url.startswith(("http://", "https://")):
            return None
        return urljoin(base_url, url)

    return None
