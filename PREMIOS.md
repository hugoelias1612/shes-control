# Premios semanales

En la pestaña **Premios** hay tres vistas: semana seleccionada, configuración e
historial. No se crean premios de ejemplo automáticamente: Administración define
los objetivos y montos reales desde **Crear premio**, sin editar archivos JSON.

## Primera configuración

1. Crear una regla por objetivo. Elegir métrica, operador, objetivo y monto.
2. Indicar vigencia, todos los vendedores o una selección. La vigencia se evalúa
   contra el **lunes de la semana**: para incluir una semana, usar ese lunes o antes.
3. Para escalones, repetir el grupo y asignar niveles distintos. Cada monto es
   adicional: 10.000 + 5.000 + 10.000 paga 25.000 cuando cumple los tres niveles.
4. Para proveedor elegir su nombre; para artículo, su código. Las listas se
   alimentan de la semana y permiten escribir valores para reglas futuras.
5. Editar, duplicar, activar/desactivar o archivar desde la tabla de configuración.
   Archivar no borra auditoría ni cierres anteriores.

Los vendedores excluidos de la revisión semanal no participan del cálculo ni del
Excel. La selección de vendedores de una regla restringe ese conjunto.

## Bases y métricas

La venta antes de IVA de Pedidos es **NETO GRAVADO + NO GRAVADO**, excluyendo
anulados y respetando la asignación final de la revisión. La comisión base es
**3%** de esa venta, separada de los premios. No se divide el total por una tasa
de IVA supuesta. Para artículos y proveedores se usa **Importes Netos** de PorCliente.

Métricas disponibles:

- Venta semanal antes de IVA, cobertura, conversión, ticket promedio antes de IVA,
  clientes compradores, pedidos lógicos y mix promedio por cliente.
- Proveedor: venta antes de IVA, compradores únicos y penetración sobre los
  compradores del vendedor.
- Artículo: venta antes de IVA, bultos y compradores únicos.
- Clientes nuevos y reactivados: valores manuales, sin detección automática.

Cobertura, conversión, compradores, pedidos y mix reutilizan las métricas actuales.
El ticket conserva la definición existente: venta dividida por compradores únicos.
Los porcentajes se ingresan como 55 para 55%. No se juzga el objetivo elegido.
Si falta una fuente o el importe neto, la métrica queda no disponible; no se
convierte una ausencia de datos en un cero que pueda ganar un premio.
Las líneas negativas de PorCliente conservan el tratamiento existente: quedan
separadas, sin descontarse automáticamente de la preventa.

## Seguimiento y control

Abrir un vendedor con doble clic para ver sus reglas, progreso y explicación de
lo que falta. La barra llega a 100%, pero el texto conserva valores superiores.
Todas las reglas cumplidas acumulan. Los operadores disponibles son >=, >, <=, < e =.

Durante la semana se muestran PENDIENTE, CUMPLIDO_PRELIMINAR,
PENDIENTE_CONTROL_MANUAL o INVALIDADO. Para reglas manuales se carga valor
verificado, fecha, nota libre y observación desde el detalle del vendedor.

**Control final** permite verificar la venta antes de IVA y las métricas automáticas
aplicables, registrar ajustes y dejar una nota con fecha. No interpreta liquidaciones
ni aplica devoluciones automáticamente. Cambiar cargas, revisión, reglas o valores
manuales deja obsoleto el control correspondiente: hay que revisarlo otra vez.

Al cerrar, las reglas se recalculan con los valores controlados. Las cumplidas pasan
a CONFIRMADO y las restantes a NO_ALCANZADO. Un nivel preliminar que cae por debajo
del objetivo deja de sumar. Si hay reglas vigentes, el cierre exige controles válidos
y datos suficientes. Se mantienen además los requisitos documentales originales de
cierre; no se modifica el funcionamiento de la pestaña Liquidaciones.

## Invalidaciones y alerta

Se puede invalidar un premio o todos los de un vendedor en esa semana. Se exige
motivo y fecha, con nota opcional. La reversión exige motivo y queda auditada.
Invalidar premios no altera la comisión base.

La alerta global se activa si (comisión base + premios) / venta antes de IVA supera
7%. **Solo advierte: nunca recorta montos.** Si falta venta neta o el denominador
no es positivo, no se presenta un porcentaje ficticio.

## Historial y Excel

Cada cierre guarda reglas, objetivos, valores, estados, importes, controles,
invalidaciones, notas, valores manuales, comisión y total variable. Editar una
regla después no cambia ese cierre. Reabrir conserva el snapshot anterior; un
nuevo cierre genera otro. El historial permite consultar y exportar cada cierre.
Los cierres anteriores a esta función no reciben premios calculados retroactivamente.

La exportación incluye todos los vendedores participantes, independientemente del
filtro visual, en **RESUMEN** y **DETALLE PREMIOS**. Incluye columnas por regla,
comisión, totales, estados y notas. Un archivo todavía no confirmado muestra
**PRELIMINAR — NO LIQUIDAR**. Los importes son celdas numéricas. La exportación
no puede sobrescribir archivos dentro del repositorio ni del historial protegido.

## Persistencia y tablas

Se utiliza el SQLite existente. La migración aditiva a versión 3 agrega
reward_rules, reward_results, reward_manual_values, reward_invalidations,
reward_controls, reward_audit y reward_meta. Las reglas se versionan; los resultados
actuales se separan de los snapshots inmutables y de la auditoría de cambios.
Las escrituras verifican la revisión de fuentes y premios para evitar guardar
resultados obsoletos. Los respaldos siguen siendo de la carpeta de datos completa.

Las tablas principales comparten configuración: orden por encabezado, columnas
redimensionables y movibles, anchos iniciales razonables y desplazamiento horizontal
y vertical. No fuerzan todas las columnas dentro de la ventana. Las actualizaciones
semanales conservan anchos, orden, selección y desplazamiento cuando las filas siguen
disponibles. La vista previa de cargas conserva su orden para mantener asociados
los controles de cada archivo.
