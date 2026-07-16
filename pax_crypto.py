import hashlib
import json

import os
from dotenv import load_dotenv

load_dotenv()  # Wczytuje zmienne z pliku .env

# Pobieramy z systemu, a jak nie ma, to dajemy bezpieczny fallback (choć na prodzie musi być!)
GENESIS_SALT = os.getenv("GENESIS_SALT", "default_fallback_salt_for_dev")


from typing import Dict, Any, List, Tuple, Optional
# Wymaga: pip install cryptography
from cryptography.fernet import Fernet

# --- KOTWICA GENESIS (Genesis Anchoring) ---
# Unikalny, tajny klucz serwera. Zabezpiecza przed sytuacją, w której ktoś 
# podmienia całą bazę danych i generuje od nowa "poprawny" łańcuch.
GENESIS_SALT = "PaxCore_Super_Secret_Anchor_2026_!!!_KeepItSafe"


# --- 1. SZYFROWANIE I DESZYFROWANIE (Crypto-shredding) ---

def generate_user_key() -> str:
    """
    Generuje unikalny klucz symetryczny dla użytkownika.
    Zapisz go w bezpiecznym miejscu (np. osobna tabela w DB lub klucz u użytkownika).
    """
    return Fernet.generate_key().decode()


def encrypt_state(state: Dict[str, Any], key_str: str) -> str:
    """
    Szyfruje stan użytkownika przed zapisem do bazy.
    """
    f = Fernet(key_str.encode())
    state_canon = canon_json(state)
    return f.encrypt(state_canon.encode()).decode()


def decrypt_state(encrypted_state_str: str, key_str: str) -> Dict[str, Any]:
    """
    Deszyfruje stan użytkownika po odczycie z bazy.
    """
    f = Fernet(key_str.encode())
    decrypted_bytes = f.decrypt(encrypted_state_str.encode())
    return json.loads(decrypted_bytes.decode())


# --- 2. LOGIKA BLOCKCHAINowa ---

def canon_json(obj: Dict[str, Any]) -> str:
    """
    Konwertuje słownik na deterministyczny ciąg znaków JSON.
    Gwarantuje, że klucze są zawsze w tej samej kolejności.
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))


def calculate_hash(sequence: int, state: Dict[str, Any], prev_hash: str) -> str:
    """
    Oblicza hash SHA-256 dla bieżącego bloku.
    Używa JAWNEGO stanu (state), dzięki czemu weryfikacja bazy jest możliwa
    nawet bez deszyfrowania (lub gdy klucz użytkownika zostanie zniszczony).
    """
    state_canon = canon_json(state)
    
    # Jeśli to pierwszy blok, mieszamy go z solą serwera (Genesis Anchoring)
    actual_prev_hash = f"{prev_hash}_{GENESIS_SALT}" if prev_hash == "genesis" else prev_hash
    
    payload = f"{sequence}:{state_canon}{actual_prev_hash}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# --- 3. WERYFIKACJA SPÓJNOŚCI I LOGIKI PRZEJŚĆ (State Transition Proof) ---

def check_transition_rules(prev_state: Dict[str, Any], next_state: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Weryfikuje, czy przejście między stanem A i stanem B było logiczne i bezpieczne.
    Zapobiega anomalion i manipulacjom przy parametrach (np. nagły skok zaufania o 100%).
    """
    # Sprawdzamy zaufanie (trust) - np. zaufanie nie może wzrosnąć jednorazowo o więcej niż 0.5
    prev_trust = prev_state.get("trust", 0.5)
    next_trust = next_state.get("trust", 0.5)
    
    if (next_trust - prev_trust) > 0.5:
        return False, f"Abnormal trust jump: from {prev_trust} to {next_trust} (max allowed increase is 0.5)"
        
    # Sprawdzamy ryzyko (risk) - np. nagły wzrost ryzyka o ponad 0.8 bez flagi w kontekście
    prev_risk = prev_state.get("risk", 0.0)
    next_risk = next_state.get("risk", 0.0)
    
    if (next_risk - prev_risk) > 0.8:
        # Pozwalamy na taki skok tylko jeśli w kontekście jest flaga 'override'
        context = next_state.get("context", {})
        if not context.get("allow_high_risk_transition", False):
            return False, f"Risk spiked dangerously: from {prev_risk} to {next_risk} without auth override!"

    return True, "OK"


def verify_history(history: List[Tuple[int, Dict[str, Any], str]]) -> Tuple[bool, str]:
    """
    Weryfikuje cały łańcuch pod kątem spójności matematycznej (hashe)
    oraz logiki biznesowej (reguły przejść).
    
    Wejście: Lista krotek [(sequence, jawny_state_dict, hash)]
    """
    if not history:
        return True, "OK"
    
    prev_hash = "genesis"
    prev_state: Optional[Dict[str, Any]] = None
    
    for i, (sequence, state, current_hash) in enumerate(history):
        expected_seq = i + 1
        
        # 1. Ciągłość sekwencji
        if sequence != expected_seq:
            return False, f"BROKEN_SEQUENCE: Expected sequence {expected_seq}, but got {sequence}"
            
        # 2. Weryfikacja matematyczna (Integrity Check)
        expected_hash = calculate_hash(sequence, state, prev_hash)
        if current_hash != expected_hash:
            return False, f"CORRUPTED: State altered at sequence {sequence}!"
            
        # 3. Reguły Przejścia Stanu (Transition Proof)
        if prev_state is not None:
            is_valid_transition, reason = check_transition_rules(prev_state, state)
            if not is_valid_transition:
                return False, f"INVALID_TRANSITION at sequence {sequence}: {reason}"
                
        prev_hash = current_hash
        prev_state = state
        
    return True, "OK"