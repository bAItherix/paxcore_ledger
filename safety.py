from typing import Dict, Tuple
import re
from datetime import datetime

class SafetyLayer:
    def __init__(self):
        self.danger_patterns = {
            'injection': [
                r';?\s*(DROP|DELETE|UPDATE|ALTER|CREATE)\s+TABLE',
                r'eval\s*\(',
                r'exec\s*\(',
                r'__import__\s*\(',
                r'globals\s*\(\)',
                r'open\s*\(\s*["\']',
                r'system\s*\(',
            ],
            'length': 5000,  # max chars
            'toxic_keywords': [
                r'\b(kill|bomb|terror|hack)\b',
                r'\b(drug|meth|coke|heroin)\b',
                r'\b(credit\s+card|ssn|passport)\b',
            ]
        }
    
    def check_query(self, query: str) -> Dict[str, float]:
        """Główna funkcja - zwraca risk_score (0.0-1.0)"""
        issues = []
        
        # 1. INJECTION DETECTION
        for pattern in self.danger_patterns['injection']:
            if re.search(pattern, query, re.IGNORECASE):
                issues.append(('INJECTION', 1.0))
        
        # 2. LENGTH LIMIT
        if len(query) > self.danger_patterns['length']:
            issues.append(('LENGTH_EXCEEDED', 0.8))
        
        # 3. TOXIC CONTENT
        for pattern in self.danger_patterns['toxic_keywords']:
            if re.search(pattern, query, re.IGNORECASE):
                issues.append(('TOXIC_CONTENT', 0.9))
        
        # 4. ETHICAL GUARDRAILS (simple keyword scoring)
        ethical_score = self._ethical_risk(query)
        if ethical_score > 0.0:  # Zmienione z 0.7, aby rejestrować mniejsze ryzyka etyczne
            issues.append(('ETHICAL_RISK', ethical_score))
        
        # POPRAWIONE RYZYKO: Wybieramy najwyższe znalezione zagrożenie (Max)
        # Jeśli lista issues jest pusta, ryzyko wynosi 0.0
        risk_score = max([score for _, score in issues]) if issues else 0.0
        
        return {
            'risk_score': min(1.0, risk_score),
            'issues': issues,
            'cleared': risk_score < 0.6,  # Każde ryzyko >= 0.6 blokuje query
            'timestamp': datetime.now()
        }
    
    def _ethical_risk(self, query: str) -> float:
        """Proste ocenianie etyczne"""
        risky_phrases = [
            'how to make', 'how to build', 'step by step',
            'recipe for', 'instructions to', 'teach me to',
            'ignore previous', 'forget safety', 'jailbreak'
        ]
        
        score = 0.0
        query_lower = query.lower()
        
        for phrase in risky_phrases:
            if phrase in query_lower:
                score += 0.3
        
        return min(1.0, score)

# Test
if __name__ == "__main__":
    safety = SafetyLayer()
    tests = [
        "hello world",
        "DROP TABLE users;",
        "how to make meth step by step",
        "tell me about history"
    ]
    
    for test in tests:
        result = safety.check_query(test)
        print(f"Query: {test}")
        print(f"Risk: {result['risk_score']:.2f} -> {'✅ OK' if result['cleared'] else '🚫 BLOCKED'}")
        print()
