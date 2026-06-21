from itertools import count

from models import State


SONNET_INPUT_TOKEN_COST = 3 / 1e6
SONNET_OUTPUT_TOKEN_COST = 15 / 1e6
OPUS_INPUT_TOKEN_COST = 15 / 1e6
OPUS_OUTPUT_TOKEN_COST = 75 / 1e6


def render_paired_translations(paired_translations: list[str]) -> str:
    md = f"|English|Estonian|\n|---|---|\n"
    for p in paired_translations:
        if p != []:
            md += f"|{p['en']}|{p['ee']}|\n"
    return md


def render_as_md(state):    
    fsn = f"{state['sctid']} | {state['preferred_term']} ({state['hierarchy']})"
    synonyms = "* " + "\n* ".join(state['synonyms'])
    parents = "* " + "\n* ".join(state['parent_concepts'])
    related = "* " + "\n* ".join(state['related_concepts'])    
    initial_translation = f"**{state['initial_translation']['translation']}**\n\n{state['initial_translation']['reasoning']}\n_Confident: {state['initial_translation']['confident']}_"
    en_to_ee_paired_translations = render_paired_translations(state["en_to_ee_paired_translations"])    
    hints = [
        " | ".join([
            f"{hint['term']} -> {hint['definition']}" 
            for hint in reflection_step
        ])
        for reflection_step in state['dictionary_hints']
    ]
    extracts = [
        "\n".join([
            f"**{extract['source']}**\n\n{extract['passage']}\n" 
            for extract in reflection_step
        ])
        for reflection_step in state['extracts']
    ]    
    google_scholar_search_snippets = [
        "\n".join([
            f"**{snippet['title']}**\n\n{snippet['snippet']}\n" 
            for snippet in reflection_step
        ])
        for reflection_step in state['google_scholar_search_snippets']
    ]
    revised_translations = [
        f"**{t['translation']}**\n\n{t['reasoning']}\n_Confident: {t['confident']}_"
        for t in state["revised_translations"]
    ]
    ee_to_en_paired_translations = [
        render_paired_translations(t)
        for t in state["ee_to_en_paired_translations"]
    ]
    
    style_guidelines = state["style_guidelines"]

    # Initial Translation Details    
    md = f"""
    # **{fsn}**
    
    # Initial Translation
    
    ## Synonyms
    {synonyms}
    
    ## Parents
    {parents}
    
    ## Related Concepts
    {related}
    
    ## Paired Translation Hints
    {en_to_ee_paired_translations}
    
    ## Relevant Style Guidelines
    {style_guidelines}
    
    ## Initial Translation
    {initial_translation}
    """
    
    # Reflection rounds
    for c, h, e, g, t, p in zip(
        count(1), 
        hints, 
        extracts, 
        google_scholar_search_snippets, 
        revised_translations,
        ee_to_en_paired_translations,
    ):
        md += f"""
        # Reflection Step {c}
        
        ## Source 1: Dictionary Hints
        {h}
        
        ## Source 2: Extracts
        {e}
        
        ## Source 3: Google Scholar Search Snippets
        {g}
        
        ## Source 4: EE -> EN Paired Translations
        {p}
        
        ## Revised Translation {c}
        {t}
        """
    
    return md.replace("\t", "").replace("    ", "")


def calculate_cost(state):
    try:
        cost = 0
        ip = state["initial_translation"]["token_counts"]["input_tokens"] * SONNET_INPUT_TOKEN_COST
        op = state["initial_translation"]["token_counts"]["output_tokens"] * SONNET_OUTPUT_TOKEN_COST
        cost = ip + op
    except KeyError:
        cost = 0
    
    for t in state["revised_translations"]:
        try:
            ip = t["token_counts"]["input_tokens"] * OPUS_INPUT_TOKEN_COST
            op = t["token_counts"]["output_tokens"] * OPUS_OUTPUT_TOKEN_COST
            cost += ip + op
        except KeyError:
            pass
    return cost


def get_best_translation(state: State) -> str:
    if len(state["revised_translations"]) > 0:
        if len(state["revised_translations"]) > len(state["forced_revisions"]):
            return state["revised_translations"][-1]
        else:
            return state["forced_revisions"][-1]
    else:
        return state["initial_translation"]

    
def get_num_translation_iterations(state: State) -> int:
    return 1 + len(state["revised_translations"]) + len(state["forced_revisions"])