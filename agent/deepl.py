import os
import deepl
import json
from tqdm import tqdm

deepl_client = deepl.Translator(os.getenv("DEEPL_API_KEY"))

TARGET_LANGCODE = "ET" # for DeepL
DEEPL_CACHE_PATH = "../data/cache/deepl_results.json"


def translate_with_deepl(wave_df):
    
    with open(DEEPL_CACHE_PATH, "r") as f:
        deepl_results = json.load(f)
    
    for row in tqdm(wave_df.itertuples(), total=wave_df.shape[0]):
        key = str(row.sctid) + "_" + TARGET_LANGCODE
        try:
            yield deepl_results[key]
        except KeyError:
            deepl_result = deepl_client.translate_text(
                row.preferred_term, 
                target_lang=TARGET_LANGCODE
            )
            deepl_results[key] = deepl_result.text
            yield deepl_result.text
    with open(DEEPL_CACHE_PATH, "w") as f:
        json.dump(deepl_results, f)
