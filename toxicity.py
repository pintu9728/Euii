import re
from typing import Optional

class ToxicityDetector:
    def __init__(self):
        self.pipeline = None
        self._load_model()

    def _load_model(self):
        try:
            from transformers import pipeline
            self.pipeline = pipeline(
                "text-classification",
                model="unitary/toxic-bert",
                device=-1,
                truncation=True,
                max_length=512,
            )
            print("[Toxicity] Loaded AI model (unitary/toxic-bert)")
        except Exception as e:
            print(f"[Toxicity] AI model not available ({e}), using heuristic fallback")
            self.pipeline = None

    async def detect(self, text: str) -> dict:
        if not text or len(text.strip()) < 2:
            return {"toxic": False, "score": 0.0, "method": "none"}

        if self.pipeline:
            try:
                result = self.pipeline(text[:512])[0]
                score = result["score"] if result["label"] == "toxic" else 1 - result["score"]
                return {
                    "toxic": result["label"] == "toxic" and score > 0.5,
                    "score": score,
                    "method": "ai",
                }
            except Exception as e:
                print(f"[Toxicity] AI inference failed: {e}")

        score = self._heuristic_score(text)
        return {
            "toxic": score > 0.75,
            "score": score,
            "method": "heuristic",
        }

    def _heuristic_score(self, text: str) -> float:
        text_lower = text.lower()
        score = 0.0

        caps = sum(1 for c in text if c.isupper())
        if len(text) > 5 and caps / len(text) > 0.7:
            score += 0.2

        if re.search(r'[!?]{3,}', text):
            score += 0.15

        aggressive_patterns = [
            r'(kill|die|death|stupid|idiot|moron|dumb|loser|hate you|shut up)',
            r'(f+u+c+k+|s+h+i+t+|a+s+s+h+o+l+e+|b+i+t+c+h+)',
            r'(d+i+e+|k+i+l+l+|r+a+p+e+|r+a+c+i+s+t+|n+a+z+i+)',
        ]
        for pattern in aggressive_patterns:
            if re.search(pattern, text_lower):
                score += 0.35

        if re.search(r'(.){6,}', text_lower):
            score += 0.1

        return min(1.0, score)
