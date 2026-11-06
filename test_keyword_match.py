#!/usr/bin/env python3
"""
Unit tests for keyword_match in crawler.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

from crawler import DEFAULT_KEYWORDS, is_about_member, keyword_match, keywords_for_language

KEYWORDS = DEFAULT_KEYWORDS.split(",")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.yaml")) as _f:
    LANGUAGE_KEYWORDS = yaml.safe_load(_f).get("keywords") or {}


class TestEnclave(unittest.TestCase):

    def test_computing_enclaves_match(self):
        for text in [
            "Apple's Secure Enclave stores the keys",
            "Code runs inside an SGX enclave",
            "AWS Nitro Enclaves now support GPUs",
            "Attackers read enclave memory through a side channel",
            "New enclave technology promises better protection",
            "Enclaves isolate sensitive workloads from the host",
        ]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)

    def test_territorial_enclaves_do_not_match(self):
        for text in [
            "Social media rumors sparked migration surge from Morocco to Spain's Ceuta enclave",
            "Gaza building collapse shows dangers plaguing enclave since Israel-Hamas truce",
            "Russia's Baltic enclave of Kaliningrad",
            "Hamas's military arm said the enclave was under bombardment",
            "an affluent enclave of the city where tech workers live",
        ]:
            self.assertFalse(keyword_match(text, KEYWORDS), text)

    def test_territorial_enclave_does_not_hide_other_keywords(self):
        self.assertTrue(keyword_match(
            "Gaza enclave news. Separately, Intel shipped TDX updates.", KEYWORDS))

    def test_buick_enclave_does_not_match(self):
        self.assertFalse(keyword_match("The 2026 Buick Enclave review", KEYWORDS))


class TestAcronyms(unittest.TestCase):

    def test_acronyms_are_case_sensitive_words(self):
        self.assertTrue(keyword_match("Intel TDX and AMD SEV-SNP", KEYWORDS))
        self.assertFalse(keyword_match("The committee met several times", KEYWORDS))
        self.assertFalse(keyword_match("a golf tee", KEYWORDS))

    def test_plurals_match(self):
        for text in ["Two TEEs were compared", "Azure confidential VMs",
                     "confidential containers on Kubernetes"]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)

    def test_spelled_out_tee_and_confidential_ai_match(self):
        for text in ["runs in a trusted execution environment",
                     "Fortanix announces Confidential AI for Kubernetes"]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)

    def test_singapore_exchange_sgx_does_not_match(self):
        self.assertFalse(keyword_match("Shares listed on SGX rose 3%", KEYWORDS))
        self.assertFalse(keyword_match(
            "Cloud and technology stocks trading on the SGX rose", KEYWORDS))
        self.assertTrue(keyword_match("Intel SGX is being retired", KEYWORDS))

    def test_bare_exchange_sgx_does_not_match(self):
        for text in [
            "SGX hunts for new CEO as Loh Boon Chye plans 2027 exit",
            "chairman Koh Boon Hwee will help pick a successor. SGX posted record "
            "revenue of US$1.17B and US$595M adjusted net profit in FY2026.",
        ]:
            self.assertFalse(keyword_match(text, KEYWORDS), text)

    def test_computing_sgx_matches(self):
        for text in [
            "Linux 7.5 drops the SGX driver",
            "Researchers break SGX with a new side-channel",
            "Code runs inside an SGX enclave",
            "SGX attestation keys leaked",
        ]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)

    def test_package_names_do_not_match(self):
        # LWN "Security updates for Friday", 2026-11-05 edition
        for text in [
            "SUSE openSUSE-SU-2026:12161-1 TW aws-nitro-enclaves-binaryblobs-upstream 2026-10-29",
            "Fedora FEDORA-2026-1234 F45 aws-nitro-enclaves-cli 2026-11-02",
        ]:
            self.assertFalse(keyword_match(text, KEYWORDS), text)

    def test_hyphenated_prose_still_matches(self):
        for text in ["AWS Nitro Enclaves now support GPUs", "Intel SGX-enabled servers",
                     "AMD SEV-SNP guests", "TEE-based key management",
                     "the Confidential Containers project"]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)

    def test_incident_severity_sev_does_not_match(self):
        for text in [
            # InfoQ panel transcript, 2026-11-04 edition
            "Given some of the things that have happened in Amazon recently where "
            "there has been agent accelerated SEVs, is there anything that we're "
            "learning about why agents can help us to make bad choices",
            "The outage was declared a SEV1 within minutes",
            "AWS cloud teams page on-call for any SEV-2 in software they own",
            "We hold a blameless review after every SEV",
        ]:
            self.assertFalse(keyword_match(text, KEYWORDS), text)

    def test_computing_sev_matches(self):
        for text in [
            "AMD SEV protects guest memory",
            "Linux 7.6 improves SEV support in KVM",
            "SEV-encrypted VMs on EPYC",
            "a new attack on SEV guests",
            "AMD SEV-SNP lands in QEMU",
            "SEV-ES support for older processors",
        ]:
            self.assertTrue(keyword_match(text, KEYWORDS), text)


class TestSpanishPortuguese(unittest.TestCase):
    """Feeds with lang: es / pt use the keyword lists in feeds.yaml."""

    def match(self, text, lang):
        return keyword_match(text, keywords_for_language(KEYWORDS, LANGUAGE_KEYWORDS, lang), lang)

    def test_translated_terms_match(self):
        for lang, text in [
            ("es", "Microsoft amplía la computación confidencial en Azure"),
            ("es", "Los entornos de ejecución confiables llegan a la nube"),
            ("es", "Apple guarda las claves en un enclave seguro del chip"),
            ("pt", "Google lança computação confidencial para IA no Brasil"),
            ("pt", "Nova vulnerabilidade afeta o enclave SGX da Intel"),
        ]:
            self.assertTrue(self.match(text, lang), text)

    def test_acronyms_and_english_terms_still_match(self):
        self.assertTrue(self.match("Intel presenta TDX para centros de datos", "es"))
        self.assertTrue(self.match("A AMD anuncia confidential computing com SEV-SNP", "pt"))

    def test_bare_enclave_is_an_ordinary_word(self):
        for lang, text in [
            ("es", "Israel bombardea el enclave palestino de Gaza"),
            ("es", "Ceuta, el enclave español, refuerza su seguridad informática"),
            ("pt", "Cabinda, enclave angolano, recebe investimentos em tecnologia"),
        ]:
            self.assertFalse(self.match(text, lang), text)

    def test_english_feeds_unchanged(self):
        self.assertEqual(keywords_for_language(KEYWORDS, LANGUAGE_KEYWORDS, "en"), KEYWORDS)


class TestJapanese(unittest.TestCase):

    def ja(self, text):
        return keyword_match(text, keywords_for_language(KEYWORDS, LANGUAGE_KEYWORDS, "ja"), "ja")

    def test_acronyms_followed_by_japanese_match(self):
        for text in ["インテルのTDXを採用した", "AMD SEV-SNPに対応", "TEEで保護されたAI推論"]:
            self.assertTrue(self.ja(text), text)

    def test_full_width_acronyms_match(self):
        self.assertTrue(self.ja("ＴＤＸ対応のクラウド"))

    def test_japanese_terms_match_with_or_without_dots_and_spaces(self):
        for text in ["コンフィデンシャル・コンピューティングの導入",
                     "コンフィデンシャル コンピューティングの導入",
                     "コンフィデンシャルコンピューティングの導入",
                     "機密コンピューティングを提供", "信頼できる実行環境（TEE）",
                     "秘密計算サービスを開始", "ｺﾝﾌｨﾃﾞﾝｼｬﾙｺﾝﾋﾟｭｰﾃｨﾝｸﾞ"]:
            self.assertTrue(self.ja(text), text)

    def test_bare_sgx_needs_context(self):
        self.assertTrue(self.ja("インテルSGXのエンクレーブ"))
        self.assertFalse(self.ja("シンガポール取引所（SGX）に上場"))
        self.assertFalse(self.ja("SGXの決算発表"))

    def test_unrelated_japanese_text_does_not_match(self):
        self.assertFalse(self.ja("新しいスマートフォンが発売された"))

    def test_english_boundaries_unchanged(self):
        self.assertFalse(keyword_match("STEEL prices rise", KEYWORDS))
        self.assertFalse(keyword_match("SGX_TOTAL counter", KEYWORDS))
        self.assertTrue(keyword_match("Intel TDX-based VMs", KEYWORDS))


class TestMemberAliases(unittest.TestCase):

    MEMBERS = ["Intel Corporation", "Hewlett Packard Enterprise", "Fujitsu Limited",
               "Arm Limited"]

    def test_katakana_and_kanji_names(self):
        self.assertEqual(is_about_member("インテルが発表", self.MEMBERS), "Intel Corporation")
        self.assertEqual(is_about_member("富士通の秘密計算", self.MEMBERS), "Fujitsu Limited")
        self.assertEqual(is_about_member("ヒューレット パッカード エンタープライズ",
                                         self.MEMBERS), "Hewlett Packard Enterprise")

    def test_ambiguous_names_are_not_aliased(self):
        self.assertIsNone(is_about_member("ロボットアームの新製品", self.MEMBERS))


if __name__ == "__main__":
    unittest.main()
