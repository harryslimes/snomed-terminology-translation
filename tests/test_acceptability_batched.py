from snomed_translation.acceptability_batched import _parse_batch


def test_parse_batch_accepts_wrapped_json_and_indexes_items():
    text = '''Result:\n{"items":[
      {"i":0,"label":"acceptable","score":0.94,"reason":"good"},
      {"i":1,"label":"PARTIAL","score":0.61,"reason":"modifier"}
    ]}'''

    parsed = _parse_batch(text, 2)

    assert parsed[0]["label"] == "ACCEPTABLE"
    assert parsed[1]["score"] == 0.61


def test_parse_batch_ignores_invalid_duplicate_or_out_of_range_items():
    text = '''{"items":[
      {"i":0,"label":"WRONG","score":0.1,"reason":"wrong"},
      {"i":3,"label":"ACCEPTABLE","score":0.9,"reason":"outside"},
      {"i":1,"label":"UNKNOWN","score":0.5,"reason":"invalid"}
    ]}'''

    assert _parse_batch(text, 2) == {
        0: {"label": "WRONG", "score": 0.1, "reason": "wrong"}
    }
