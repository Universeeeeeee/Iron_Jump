"""Brief spoken replies; the original on-screen answers stay unchanged."""

import re


def concise_reply(text: str) -> str:
    """Keep complete sentences and numbers, avoiding mid-metric truncation."""
    if len(text) <= 160:
        return text
    sentences = re.findall(r"[^。！？\n]+[。！？]?", text)
    selected = []
    for sentence in sentences:
        sentence = sentence.strip()
        if selected and (len(selected) >= 2 or len("".join(selected)) + len(sentence) > 160):
            break
        selected.append(sentence)
    return "".join(selected) + "其余详情见页面。"
