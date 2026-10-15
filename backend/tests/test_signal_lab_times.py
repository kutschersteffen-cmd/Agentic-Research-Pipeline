from __future__ import annotations

import pytest

from arp.signal_lab.times import content_hash_of, month_end_time, normalise_time


def test_date_only_is_end_of_day():
    assert normalise_time("2020-01-31") == "2020-01-31T23:59:59Z"


def test_zulu_and_millis():
    assert normalise_time("2020-01-31T23:10:00.123Z") == "2020-01-31T23:10:00Z"


def test_lowercase_z():
    assert normalise_time("2020-01-31T23:10:00z") == "2020-01-31T23:10:00Z"


def test_offset_converted_to_utc():
    assert normalise_time("2020-02-01T01:30:00+02:00") == "2020-01-31T23:30:00Z"


@pytest.mark.parametrize(
    "bad", ["2020-01-31T23:10:00", "31 Jan 2020", "", "2021-02-30", "2021-02-30T10:00:00Z"]
)
def test_invalid_raises(bad):
    with pytest.raises(ValueError):
        normalise_time(bad)


def test_month_end_time():
    assert month_end_time("2020-02-01") == "2020-02-29T23:59:59Z"
    assert month_end_time("2021-02-01") == "2021-02-28T23:59:59Z"
    assert month_end_time("2021-12-15") == "2021-12-31T23:59:59Z"


def test_content_hash_stable_and_sensitive():
    base = content_hash_of("t", "b")
    assert base == content_hash_of("t", "b")
    assert base != content_hash_of("t", "b2")
    assert base != content_hash_of("t2", "b")
