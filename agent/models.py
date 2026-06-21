from typing import Annotated
from typing_extensions import TypedDict


def append(list_, new):
    assert(isinstance(list_, list))
    list_.append(new)
    return list_

def concat(cur_list, new_list):
    assert(isinstance(cur_list, list))
    assert(isinstance(new_list, list))
    cur_list = cur_list + new_list
    return cur_list

def add_key(dict_, item_):
    key_, value_ = item_
    dict_[key_] = value_
    return dict_

class State(TypedDict):
    max_reflection_steps: int
    max_extracts: int
    max_search_results: int
    min_extract_relevancy_score: float
    sctid: int
    preferred_term: str = ""
    hierarchy: str = ""
    synonyms: list = list()
    parent_concepts: list = list()
    related_concepts: list = list()
    en_to_ee_paired_translations: list = list()
    ee_to_en_paired_translations: Annotated[list, append] = list()
    initial_translation: dict = dict()
    revised_translations: Annotated[list, append] = list()
    forced_revisions: Annotated[list, append] = list()
    dictionary_hints: Annotated[list, append] = list()
    google_scholar_search_snippets: Annotated[list, append] = list()
    token_counts: Annotated[list, append] = list()
    extracts: Annotated[list, append] = list()
    style_guidelines: str = ""