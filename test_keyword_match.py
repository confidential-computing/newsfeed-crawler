#!/usr/bin/env python3
"""
Unit tests for keyword_match in crawler.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import DEFAULT_KEYWORDS, keyword_match

KEYWORDS = DEFAULT_KEYWORDS.split(",")


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
        self.assertTrue(keyword_match("Intel SGX is being retired", KEYWORDS))


if __name__ == "__main__":
    unittest.main()
