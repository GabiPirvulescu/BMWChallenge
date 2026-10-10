from __future__ import annotations

import unittest

from services.evidence import (
    EvidenceProviderError,
    EvidenceScope,
    Neo4jEvidenceProvider,
)


class _Record:
    def __init__(self, value):
        self.value = value

    def data(self):
        return self.value


class _Transaction:
    def __init__(self, records, error=None):
        self.records = records
        self.error = error

    def run(self, query, **params):
        if self.error:
            raise self.error
        return iter(_Record(record) for record in self.records)


class _Session:
    def __init__(self, transaction):
        self.transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_read(self, work):
        return work(self.transaction)


class _Driver:
    def __init__(self, transaction):
        self.transaction = transaction

    def session(self):
        return _Session(self.transaction)


class EvidenceProviderTests(unittest.TestCase):
    def test_scope_normalization_is_explicit_and_scoped(self) -> None:
        params = EvidenceScope(model="G70", market="United States", powertrain="BEVE").query_params()
        self.assertEqual(params["model"], "G70")
        self.assertEqual(params["region"], "US")
        self.assertEqual(params["powertrain"], "BEV")

    def test_source_record_decodes_locator_and_payload(self) -> None:
        provider = Neo4jEvidenceProvider(_Driver(_Transaction([{
            "record": {
                "id": "SR-1",
                "locator_json": '{"filename":"G70.xlsx","sheet":"Feedback_Explorer","row":9}',
                "raw_payload_json": '{"text":"original"}',
            },
            "source_file": {"id": "SRC-1", "sha256": "abc"},
        }])))

        record = provider.get_source_record("SR-1")

        self.assertEqual(record["locator"]["row"], 9)
        self.assertEqual(record["raw_payload"]["text"], "original")
        self.assertEqual(record["source_file"]["sha256"], "abc")

    def test_query_failures_are_not_returned_as_empty_evidence(self) -> None:
        provider = Neo4jEvidenceProvider(_Driver(_Transaction([], RuntimeError("database unavailable"))))

        with self.assertRaisesRegex(EvidenceProviderError, "database unavailable"):
            provider.get_source_record("SR-1")


if __name__ == "__main__":
    unittest.main()
