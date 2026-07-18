# Simple CO₂ calculation helper
def calculate_co2_saved(weight_kg: float) -> float:
    # 0.5 kg CO₂ saved per kg waste recycled (example factor)
    return weight_kg * 0.5
