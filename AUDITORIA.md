# Auditoría — 21/09/2026

## Actualización — 24/09/2026

- Se retiró Liquidaciones de la UI, el cierre y la carga de archivos. La migración
  v4 desactiva esos adjuntos antiguos, conserva sus archivos y elimina su tabla funcional.
- PorCliente reconoce positivos asociados a pedidos semanales y negativos como
  devoluciones. El match simple usa cliente, artículo, vendedor y la venta anterior
  más cercana; una reasignación conserva el vendedor final del pedido.
- Los negativos sin match dentro de la semana requieren APROBAR/RECHAZAR. Los
  posteriores sin venta semanal compatible se ignoran para esa semana.
- Bruto, devoluciones y neto alimentan compradores, conversión, ticket, artículos,
  proveedores, bultos, comisión y premios. Cobertura conserva la actividad SIGO.
- Validación: 107 pruebas, incluidos rangos amplios 07–16, positivos posteriores,
  devoluciones posteriores parciales/totales, persistencia, cierres y regresiones.

Se revisaron todos los módulos originales, main, dependencias y configuración Git.
Se mantuvieron Python/PySide6 y el flujo carga → revisión → confirmación → dashboard.

## Lo que ya estaba bien

- Reconocimiento por columnas, cuatro archivos obligatorios y fecha basada en SIGO.
- Separación básica de datos, procesamiento y widgets.
- Original/válida: los pendientes ya sumaban y los anulados se distinguían.
- Proveedor en Descripción.5, bultos fraccionarios, HUGO excluido y vendedor original.
- NumericItem comparaba números y las tablas se llenaban antes de habilitar orden.
- Resultados preliminares hasta el cierre semanal.

## Correcciones

1. Filtro obligatorio de jornada al construir pedidos y control defensivo al procesar.
2. Compradores por proveedor mediante unión real, reemplazando el máximo entre artículos.
3. Reasignaciones que coinciden en cliente/destino/fecha cuentan un pedido lógico.
4. Editar invalida confirmación y cierra dashboard anterior; el procesador verifica
   huellas de sesión y revisión guardada.
5. pandas antes de Qt también al importar ventanas directamente.
6. ExcelFile ahora se cierra: antes dejaba archivos bloqueados en Windows.
7. Fechas SIGO inválidas rechazadas, formatos mixtos interpretados por elemento,
   encabezados normalizados también al releer y flags numéricos 1.0 reconocidos.
8. Importes corruptos ya no se convierten silenciosamente en cero.
9. Estados físicos diferentes generan MIXTO, incluyendo facturado/pendiente.
10. JSON atómico UTF-8, sin NaN/Infinity, con artículos, estados, fechas y trazabilidad.
11. Historial sin colisiones ni reutilización de carpetas, rechazo de archivos
    repetidos y errores de escritura manejados por UI.
12. Empresa cuenta clientes únicos; mix usa pares cliente/artículo; Hora Venta y
    diferencias entre PorCliente/pedidos se muestran como señales de conciliación.
13. Dashboard incluye métricas faltantes y detalle vendedor con clientes del
    proveedor y participación del artículo; tablas de solo lectura.
14. Ignorados Excel, resultados comerciales, bases y carpetas privadas.
15. requirements conserva las versiones instaladas y se convirtió de UTF-16 a UTF-8.

## Validación

- 20 pruebas unittest aprobadas con Excel ficticios.
- Flujo completo desde MainWindow: cargar, guardar copias, revisar, confirmar,
  procesar JSON y abrir dashboard en Qt offscreen.
- Consolidación, fechas, anulados, pendientes, estados, reasignación, exclusión,
  ceros, ticket, cobertura, clientes solapados por proveedor, Hora Venta, JSON
  atómico, historial y orden numérico.
- Imports directos en procesos Python nuevos, compilación y pip check correctos.
- No se reinstaló el entorno desde cero ni se verificó el índice externo de paquetes.

## Pendientes y límites

- Falta prueba manual con una jornada real; las pruebas sintéticas no cubren todas
  las variantes de exportación.
- Interior: pedidos creados otro día se excluyen hasta definir fecha comercial
  explícita. No se infiere mediante entrega o última modificación.
- Hora Venta sin pedido: se informa discrepancia; falta decidir su posible métrica
  comercial adicional. No altera los compradores utilizados en ticket.
- Se presupone CodClienteEmpresa global entre zonas. Confirmarlo con datos reales
  antes de comparar carteras de distintas bases.
- PorCliente usa la regla confirmada: jornada única, sin anulados. No permite
  reconstruir artículos anulados originales. Diferencias monetarias y pares sin
  pedido se advierten, no se prorratean.
- Bonific conserva la suma existente. Falta confirmar si es importe, cantidad o
  porcentaje; no usar para premios hasta definirla.
- Original es TOTAL observado incluyendo anulados, no un importe histórico previo
  a modificaciones administrativas que la exportación no contiene.
- La tarjeta identifica la región; los esquemas son iguales y no se inventa una
  inferencia por nombre de archivo.
- Solo `.xlsx`: `.xls` requería un motor no instalado y antes se renombraba a
  `.xlsx` al copiar. Convertir desde Excel cuando corresponda.
- Trabajo síncrono en UI: archivos grandes pueden congelarla temporalmente.
- Sincronización multiusuario continúa pendiente. Premios y devoluciones semanales
  se guardan en SQLite; no hay ajustes retroactivos de semanas ya pagadas.
- Los JSON son instantáneas reemplazables de una carga, no historial inmutable de
  cada edición ni solución concurrente multiusuario.

## Git y privacidad

Al iniciar solo estaban versionados `.gitignore` y `.gitattributes`; los módulos
y requirements estaban sin seguimiento. Se editaron localmente, sin commit ni
publicación. No se encontraron Excel/JSON comerciales versionados en el checkout.

## Evolución semanal — 22/09/2026

El flujo principal pasó a semanas comerciales lunes–domingo. Se agregó índice SQLite
externo, carga masiva revisable, hashes/versiones activas, estados por sucursal,
métricas semanales parciales, revisión reutilizada y cierre/reapertura con snapshots.
La ventana diaria anterior se trasladó sin eliminar su lógica ni sus tests.

Validación de esta evolución: 66 tests (22 existentes + 44 semanales), compilación,
dependencias y carga temporal de los cuatro Excel reales con hashes originales intactos.
La UI semanal fue renderizada en modo offscreen para revisar navegación y checklist.
La nueva base de producción se inicializa al ejecutar la app; las pruebas usaron
carpetas temporales. Diseño, fórmulas, esquema, compatibilidad, límites y pasos
manuales se documentan en `SEMANAS.md`.
