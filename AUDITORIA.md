# Auditoría — 21/09/2026

Se revisaron todos los módulos originales, main, dependencias y configuración Git.
Se mantuvieron Python/PySide6 y el flujo carga → revisión → confirmación → dashboard.

## Lo que ya estaba bien

- Reconocimiento por columnas, cuatro archivos obligatorios y fecha basada en SIGO.
- Separación básica de datos, procesamiento y widgets.
- Original/válida: los pendientes ya sumaban y los anulados se distinguían.
- Proveedor en Descripción.5, bultos fraccionarios, HUGO excluido y vendedor original.
- NumericItem comparaba números y las tablas se llenaban antes de habilitar orden.
- Resultados marcados preliminares, con liquidaciones pendientes.

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
- Liquidaciones, premios, objetivos, SQL y sincronización continúan pendientes.
- Los JSON son instantáneas reemplazables de una carga, no historial inmutable de
  cada edición ni solución concurrente multiusuario.

## Git y privacidad

Al iniciar solo estaban versionados `.gitignore` y `.gitattributes`; los módulos
y requirements estaban sin seguimiento. Se editaron localmente, sin commit ni
publicación. No se encontraron Excel/JSON comerciales versionados en el checkout.
