import pytest

from substrate.er.phonetics import soundex


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Robert", "R163"),
        ("Rupert", "R163"),  # classic collision pair
        ("Ashcraft", "A261"),  # H/W transparent: s→2, c skipped (same code), r6 f1
        ("Tymczak", "T522"),  # y resets, z skipped (same code as c), k added after a
        ("Pfister", "P236"),  # f skipped (same code as p), s2 t3 r6
        ("José", "J200"),  # ASCII-stripped é
        ("", ""),
        ("123", ""),
    ],
)
def test_soundex(name, expected):
    assert soundex(name) == expected


def test_soundex_is_stable_and_case_insensitive():
    assert soundex("smith") == soundex("SMITH") == soundex("Smyth")
