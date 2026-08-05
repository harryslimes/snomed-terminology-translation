from snomed_translation.batch_selection import modality, topic_tokens


def test_modality_recognizes_ultrasound_word_and_nuclear_venography():
    assert modality("Ultrasound Doppler flow mapping of vein") == "ultrasound"
    assert modality("Radionuclide venography of upper limb") == "nuclear"


def test_topic_tokens_drop_laterality_and_modality_but_keep_clinical_topic():
    result = topic_tokens(
        "Computed tomography venography of vein of right upper limb with contrast"
    )

    assert "upper" not in result
    assert "computed" not in result
    assert "contrast" not in result
    assert {"vein", "limb"} <= result
