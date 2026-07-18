# Оценочный коэффициент: кг CO₂, сэкономленных на кг переработанного сырья.
# Будет уточнён после первых реальных выездов (см. слайд «Ожидаемый эффект»).
CO2_PER_KG = 0.5


def calculate_co2_saved(weight_kg: float) -> float:
    return weight_kg * CO2_PER_KG
