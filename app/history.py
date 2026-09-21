"""Copias crudas versionadas; nunca reutilizar una carpeta de carga."""
import shutil
from pathlib import Path

from app.storage import write_json

FILENAMES = {"ctes": "puntos_ctes.xlsx", "resis": "puntos_resistencia.xlsx",
             "pedidos": "reporte_pedidos.xlsx", "porcliente": "porcliente.xlsx"}


def save_raw_load(history_root, day, files):
    if set(files) != set(FILENAMES) or not all(files.values()):
        raise ValueError("Debe cargar los cuatro archivos")
    paths = [Path(files[key]).resolve() for key in FILENAMES]
    if len(set(paths)) != 4:
        raise ValueError("Los cuatro archivos deben ser distintos")
    if any(p.suffix.lower() != ".xlsx" for p in paths):
        raise ValueError("Use archivos .xlsx; convierta los .xls antes de cargar")
    day_folder = Path(history_root) / day.isoformat()
    day_folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        destination = day_folder / f"carga_{number:02d}"
        try:
            destination.mkdir()
            break
        except FileExistsError:
            number += 1
    try:
        for key, filename in FILENAMES.items():
            shutil.copy2(files[key], destination / filename)
    except Exception as error:
        # Conservar evidencia de una copia fallida, nunca presentarla como completa.
        write_json(destination / "carga_incompleta.json", {"error": str(error)})
        raise
    return destination
