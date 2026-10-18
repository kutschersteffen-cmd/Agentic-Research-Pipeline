from arp.discovery.names import names_match


def test_names_match_ignores_legal_suffix_and_case():
    assert names_match("Testwerke AG", "TESTWERKE")
    assert names_match("Testwerke AG", "Testwerke")


def test_names_match_rejects_other_company():
    assert not names_match("Testwerke AG", "Otherco plc")


def test_names_match_accents():
    assert names_match("Société Générale S.A.", "Societe Generale")


def test_names_match_short_names_need_exact():
    assert names_match("3M Company", "3M")
    assert not names_match("AB Foods", "ABB")


def test_names_match_blank_never_matches():
    assert not names_match("", "")
    assert not names_match("Testwerke AG", "")
