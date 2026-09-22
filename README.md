# SHES-Control

Sistema de control de ventas de SHES.

Aplicación comercial de escritorio: Python 3.12 + PySide6. La preventa procesada es
preliminar; no cierra premios ni números finales sin futuras liquidaciones.

## Ejecutar en Windows

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Las dependencias están fijadas a las versiones del entorno local verificado.
SQLite guarda el índice semanal fuera del repo, usando `sqlite3` de Python.
SQLAlchemy sigue instalado para una futura migración; todavía no hay sincronización.

## Flujo principal semanal

Al ejecutar `main.py` se abre el selector de semanas, sin pedir archivos. Elegir
una semana abre el centro con Resumen, Cargas, Vendedores, Artículos, Proveedores,
Liquidaciones, Premios y Archivos/Auditoría.

- Semana de lunes a domingo, determinada por **FECHA ENTREGA** del pedido.
- Subida múltiple con vista previa y selección obligatoria de sucursal para Puntos.
- Un archivo idéntico ya activo en la misma semana se ignora y muestra la carga coincidente.
- Pedidos admite varias partes de CHESS: se combinan por número; la última carga actualiza los repetidos.
- PorCliente es un único reporte por semana: la última carga reemplaza al anterior y se cruza por cliente y fecha de entrega, usando el vendedor final del pedido. Negativos separados sin descontar preventa.
- SIGO admite un semanal por sucursal y separa cada fecha: sábado anterior → lunes de reparto, lunes → martes, hasta viernes → sábado.
- Exclusiones predeterminadas editables en la interfaz y guardadas en SQLite; las revisiones confirmadas conservan sus decisiones.
- Se elige la semana, sin preguntar rangos comerciales. Eliminar una parte recalcula los pedidos restantes;
  se conservan originales y auditoría, y se puede volver a cargar un archivo histórico o eliminado.
- No trabajado por sucursal con motivo opcional y reversión. Domingo nunca pide SIGO.
- Análisis parcial disponible sin liquidaciones ni cierre. Rangos de ventas,
  artículos y preventa documental completa se muestran separadamente.
- Revisión semanal reutiliza las tarjetas y reasignaciones anteriores.
- Cierre exige semana finalizada, preventa completa, revisión actual confirmada y
  liquidaciones confirmadas por jornada. Reapertura auditada conserva cada cierre.
- Liquidaciones se adjuntan y cuentan; su estructura financiera y los premios aún
  no se interpretan/calculan. Un cierre administrativo no inventa números netos finales.

Diseño, esquema SQLite, fórmulas, límites y guía manual en [SEMANAS.md](SEMANAS.md).

Guía del flujo actual y primera prueba: [PRIMERA_CARGA.md](PRIMERA_CARGA.md).

## Reglas del flujo diario compatible

El flujo diario anterior permanece en `app/daily_window.py`; los módulos y JSON
anteriores mantienen su contrato. Las siguientes reglas describen ese flujo.

- Se requieren cuatro archivos `.xlsx`, identificados por columnas. Las tarjetas
  distinguen Corrientes/Resistencia: no hay columna geográfica inequívoca definida.
- La fecha comercial viene de `dia` de ambos archivos SIGO y debe coincidir.
- Solo se incluyen pedidos con **fecha de alta** de esa jornada. Las otras fechas
  y las inválidas quedan auditadas como excluidas y permanecen crudas. Última
  modificación nunca determina venta. Interior requiere una futura regla explícita.
- PorCliente representa **una sola jornada y no incluye anulados**, según confirmó
  el usuario. Su período puede ser la entrega siguiente. Los artículos se asocian
  por cliente/vendedor originales a pedidos de la jornada seleccionada.
- Pedido lógico: cliente + vendedor asignado + jornada. Las reasignaciones guardan
  sus componentes originales, pero el conteo une las coincidencias en el destino.
- Pendientes y retenidos suman venta válida; anulados únicamente original.
  MODIFICADO es una marca y estados físicos diferentes generan MIXTO.
- Venta, artículos, compradores y ticket siguen la asignación final. Cartera y
  visitas SIGO permanecen con su vendedor de origen.
- CodClienteEmpresa es la clave para comparar SIGO con Chess. Empresa cuenta la
  unión de códigos de clientes, sin duplicar entre vendedores.
- Hora Venta se conserva como señal separada. Sin pedido conciliado se advierte;
  no genera importes o compradores ficticios. Su tratamiento definitivo está pendiente.
- Los porcentajes pueden superar 100% por omisiones SIGO o reasignaciones. Con
  denominador cero devuelven 0.
- HUGO queda excluido inicialmente; exclusiones se aplican al vendedor final.

## Archivos y auditoría

Copias: `~/Documents/SHES-Control-Datos/HISTORIAL/AAAA-MM-DD/carga_NN`.
Cada carpeta se reserva sin sobrescribir anteriores. Las copias fallidas conservan
un marcador `carga_incompleta.json`. Los Excel nunca se editan.

`revision_preventa.json` guarda originales, asignaciones, artículos, exclusiones,
pedidos fuera de fecha, advertencias, timestamp y huella de revisión.
`preventa_procesada.json` incluye esa revisión, su huella, actividad SIGO y métricas.
Ambos usan UTF-8, serialización estricta y reemplazo atómico. Editar asignaciones
o exclusiones obliga a confirmar nuevamente, también si se procesa fuera de la UI.

Los JSON representan la última revisión/proceso de **esa carga**; no constituyen
un registro inmutable de cada edición humana ni una base multiusuario.

## Módulos

- `importers.py`: reconocimiento y validación.
- `review_data.py`: modelos, consolidación y revisión auditable.
- `processor.py`: métricas comerciales separadas de actividad SIGO.
- `history.py` y `storage.py`: copias versionadas y escritura JSON atómica.
- `main.py`: entrada semanal; `daily_window.py` conserva la ventana diaria anterior.
- `week_calendar.py`, `week_imports.py`, `week_store.py`, `week_service.py` y
  `week_window.py`: calendario, detección, persistencia, reglas y UI semanales.
- `review_window.py`, `dashboard_window.py`: pantallas compartidas.

El paquete carga pandas antes de PySide6 incluso al importar una ventana directamente,
por la incompatibilidad observada con Shiboken/dateutil/six.

## Pruebas

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q app main.py tests
.venv\Scripts\python.exe -m pip check
```

Generan Excel ficticios en carpetas temporales e incluyen el flujo completo con Qt
offscreen. No leen ni publican datos reales. Ver `AUDITORIA.md` para hallazgos y límites.
