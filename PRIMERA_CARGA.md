# Primera carga en SHES-Control

1. Abrí la aplicación y elegí la semana de **reparto**. Para estos archivos: 7 al 13 de septiembre.
2. Pulsá **Subir archivos**. Seleccioná los dos Excel semanales de SIGO y elegí Corrientes para uno y Resistencia para el otro. Se pueden seleccionar también los reportes de los pasos siguientes en el mismo lote.
3. Cargá todas las partes de **Pedidos** que exportaste de CHESS. El límite de 1.000 filas no es un problema: quedan todas activas. Un número repetido se actualiza con la última carga, sin duplicar la venta.
4. Cargá el **PorCliente completo**, exportado por entrega de esa semana. Una nueva carga reemplaza al PorCliente anterior.
5. Abrí **Cargas**: arriba se ven las fechas de reparto y preventa; abajo, cartera, visitados y vendidos SIGO por día y vendedor, más el total de empresa. El filtro permite buscar un vendedor.
6. En **Revisar asignaciones**, resolvé pedidos SIN ASIGNAR, reasignaciones e inclusiones de vendedores. Confirmá y consultá Resumen, Vendedores, Artículos y Proveedores.

## Fechas que se usan

| Preventa SIGO | Reparto |
| --- | --- |
| Sábado 5 | Lunes 7 |
| Lunes 7 | Martes 8 |
| Martes 8 | Miércoles 9 |
| Miércoles 9 | Jueves 10 |
| Jueves 10 | Viernes 11 |
| Viernes 11 | Sábado 12 |

No es necesario separar SIGO en archivos diarios: se usa la fecha de cada fila.
Un nuevo SIGO de la misma sucursal reemplaza al anterior: subí el semanal completo.
La fecha de entrega del pedido sigue siendo la real; los casos que no coinciden con SIGO se advierten, sin cambiar fechas ni inventar ventas.

## Exclusiones y diferencias

**Vendedores excluidos por defecto…** permite editar la lista guardada en la configuración local. Inicialmente incluye HUGO, ROLON BRAIAN y OJEDA DIEGO. Borrá un nombre para incluirlo; no hace falta cambiar código. Las semanas con revisión confirmada conservan su elección: se cambia desde Revisión.

Pedidos determina ventas y vendedores. PorCliente aporta artículos por cliente y fecha de entrega, respetando las reasignaciones. Si hay varios destinos posibles, se muestra una alerta desplegable y esos artículos quedan sin atribuir.

**Devoluciones** muestra los importes netos negativos de PorCliente. Si encuentran una
venta positiva semanal anterior compatible, descuentan automáticamente. Los casos sin
match de la semana requieren aprobar o rechazar; una decisión se reconoce por huella
estable al reemplazar PorCliente.
Los negativos sin match anteriores o posteriores a la semana quedan ignorados. Para
los pendientes se pueden seleccionar varias filas con Ctrl/Shift o usar los botones
**APROBAR/RECHAZAR TODAS LAS PENDIENTES**.

Los resultados son de preventa, no venta neta después de devoluciones. SIGO vendido significa cliente con Hora Venta; no crea importes. Las alertas se abren cuando necesitás consultar el detalle.

## Repetir una prueba

En **Archivos / Auditoría**, seleccioná las cargas y pulsá **Eliminar cargas seleccionadas**. Se recalcula usando lo que queda. Podés volver a cargar esos Excel y se conservan los originales y el historial. Las semanas cerradas requieren reapertura para cambiar cargas.

Los archivos cargados con versiones anteriores siguen conservados. Para adoptar el nuevo SIGO semanal, subí los dos archivos completos; revisá y confirmá nuevamente si tenías una revisión anterior.
