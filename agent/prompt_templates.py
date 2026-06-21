from langchain_core.prompts import PromptTemplate

initial_translation_template = PromptTemplate(
    input_variables=[
        "preferred_term",
        "hierarchy",
        "synonyms",
        "parent_concepts",
        "related_concepts",
        "en_to_ee_paired_translations",
        "style_guidelines",
    ],
    template="""
    # Task
    Translate the following SNOMED CT preferred term from English into Estonian: '{preferred_term}'.

    # Context
    - Hierarchy: {hierarchy}
    - Synonyms: {synonyms}
    - Parent concepts: {parent_concepts}
    - Related concepts: {related_concepts}

    # Paired Translation Hints
    The following paired translations from medical sources may help you translate this term:

    {en_to_ee_paired_translations}

    # Style Guidelines
    Be sure to follow these guidelines to ensure that your translation is clinically accurate.

    {style_guidelines}

    # Instructions
    Translate the SNOMED CT preferred term '{preferred_term}' into Estonian.
    Do not add quotes, additional punctuation or any other formatting around your translation.

    Your response should be a JSON dictionary that adheres to the following schema:
    {{
        "reasoning": "a brief description of which sources you relied upon (if any) and why you chose this translation.",
        "translation": "the correct Estonian translation of the term",
        "confident": "YES if you are highly confident that you have a clinically accurate translation suitable for use in a real medical record; NO otherwise",
        "changed": "YES",
        "unverified_words": "a comma-separated string of words from the Estonian translation that you have NOT been able to verify"
    }}

    DO NOT add any preamble or other text.  ONLY output the required JSON.
    Now, translate '{preferred_term}':
    """
)

reflection_template = PromptTemplate(
    input_variables=[
        "preferred_term", 
        "estonian_term", 
        "dictionary_hints", 
        "extracts",
        "style_guidelines",
        "google_scholar_search_snippets",
        "ee_to_en_paired_translations",
    ],
    template="""
    # Task
    Consider the following translation of a SNOMED CT preferred term from English into Estonian: '{preferred_term}' -> '{estonian_term}'.
    Your job is to improve the translation - if possible - based on the following additional sources.
    Use these sources as follows:
    
    1. Look for phrases or words that are similar to the translation above.
    2. Determine whether the context in which they are used seems relevant, given the translation above.
    3. If so, check whether the translation above is using the terms correctly and improve it if necessary.
    
    Note that you may need to alter the words you see in these sources to make the case, gender and plurality match proper Estonian rules of grammar.
    
    # Style Guidelines
    Be sure to follow these guidelines to ensure that your translation is clinically accurate.
    
    {style_guidelines}
    
    # Source 1: Estonican clinical dictionary
    Some terms extracted from an Estonican clinical dictionary that may be related to the translation above: 
    
    <--START OF DICTIONARY TERMS-->
    {dictionary_hints}
    <--END OF DICTIONARY TERMS-->
    
    # Source 2: Passages of clinical text from Estonian medical documents
    Some extracts taken from Estonianclinical documents.  
    Each extract begins with a title, denoted by Markdown Bold syntax (**).
    
    <--START OF EXTRACTS-->
    {extracts}
    <--END OF EXTRACTS-->
    
    # Source 3: Snippets returned by Google Scholar when searching for the Estonian translation
    Some snippets returned by Google Scholar when searching for the Estonian translation:
    
    <--START OF GOOGLE SEARCH SNIPPETS-->
    {google_scholar_search_snippets}
    <--END OF GOOGLE SEARCH SNIPPETS-->
    
    # Source 4: Paired translations from medical sources from Estonian to English
    {ee_to_en_paired_translations}
    
    In light of these definitions, can you improve the above translation?
    If you can, please return the new, improved translation.
    If there are no material improvements to take, just return the existing translation ('{estonian_term}') as is.
    Do not add quotes, additional punctuation or any other formatting around your translation.

    Your response should be a JSON dictionary that adheres to the following schema:
    {{
        "reasoning": "a brief description of which sources you relied upon (if any) and why you altered the translation (if you did).",
        "translation": "the correct Estonian translation of the term",
        "confident": "YES if you are highly confident that you have a clinically accurate translation suitable for use in a real medical record; NO otherwise"
        "changed": "YES if you have improved the translation; NO otherwise",
        "unverified_words": "a comma-separated string of words from the Estonian translation that you have NOT been able to verify"
    }}    
    
    # A note on confidence
    You should ONLY be highly confident in your translation if the following is true:
    - You have seen an EACH of the clinical terms in the Estonian translation I provided you with somewhere in the sources.
    
    DO NOT add any preamble or other text.  ONLY output the required JSON.
    Now, improve the translation of '{preferred_term}' -> '{estonian_term}':
    """
)

forced_revision_template = PromptTemplate(
    input_variables=[
        "preferred_term", 
        "estonian_term", 
        "hierarchy", 
        "synonyms", 
        "parent_concepts", 
        "related_concepts", 
        "unverified_words",
    ],
    template="""
    # Task
    Consider the following translation of a SNOMED CT preferred term from English into Estonian: '{preferred_term}' -> '{estonian_term}'.
    The following words in the translation are not clinically accurate: {unverified_words}.
    
    The following English information about the term is available:
    - {hierarchy}
    - {synonyms}
    - {parent_concepts}
    - {related_concepts}
        
    In light of this information, please suggest an alternative translation for '{preferred_term}'.
    Do not add quotes, additional punctuation or any other formatting around your translation.

    Your response should be a JSON dictionary that adheres to the following schema:
    {{
        "reasoning": "a brief description of which sources you relied upon (if any) and why you altered the translation (if you did).",
        "translation": "the correct Estonian translation of the term",
        "confident": "Just return NO in this field",
        "changed": "Just return YES in this field",
        "unverified_words": ""a comma-separated string containing all new words that you have added to the Estonian translation"
    }}    
    
    DO NOT add any preamble or other text.  ONLY output the required JSON.
    Now, improve the translation of '{preferred_term}' -> '{estonian_term}':
    """
)