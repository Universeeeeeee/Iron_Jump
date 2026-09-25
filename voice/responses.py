"""Speak only validated report claims and retain their evidence limitations."""


def analysis_speech(analysis: dict) -> str:
    parts = []
    for claim in analysis.get("claims", [])[:3]:
        text = str(claim.get("text", "")).strip()
        if text:
            parts.append(text)
            parts.extend(str(item) for item in claim.get("limitations", []))
    parts.extend(str(item) for item in analysis.get("overall_limitations", []))
    return "。".join(parts) if parts else "报告分析已完成，请查看报告页面的详细结果。"
