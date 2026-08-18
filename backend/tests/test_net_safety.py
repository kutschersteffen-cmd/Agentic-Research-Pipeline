import pytest

from arp.net_safety import UnsafeURLError, assert_safe_fetch_target


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",  # cloud metadata (link-local)
        "http://127.0.0.1:8000/api/health",  # loopback
        "http://localhost/",  # loopback
        "http://10.0.0.5/",  # private
        "http://192.168.1.1/",  # private
        "http://0.0.0.0/",  # unspecified
        "ftp://169.254.169.254/",  # disallowed scheme
        "file:///etc/passwd",  # disallowed scheme
    ],
)
def test_rejects_unsafe_targets(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_fetch_target(url)


def test_accepts_public_ip_literal():
    # 8.8.8.8 is a real public address (Google DNS) -- not
    # private/loopback/link-local/reserved/multicast, so it should pass
    # the IP-range check itself (no DNS resolution needed for a literal).
    assert_safe_fetch_target("https://8.8.8.8/")
