# Centro de control semanal

## Arquitectura y compatibilidad

La aplicación arranca en `WeeksWindow`. Las semanas se generan desde el calendario
(12 anteriores, actual y una siguiente), más las existentes en la base y el historial
diario. Se puede navegar a cualquier fecha sin crear semanas manualmente.

Se conservaron los validadores, modelos diarios, consolidación de pedidos,
agregadores de artículos/proveedores, revisión y dashboard. Los 22 tests originales
continúan ejecutándose. El flujo diario está en `app/daily_window.py` y mantiene
su alias `main.MainWindow` para compatibilidad; `main.main()` abre la UI semanal.

Nuevos módulos:

| Archivo | Responsabilidad |
| --- | --- |
| `week_calendar.py` | Lunes/domingo, identificador ISO, jornadas y calendario |
| `week_imports.py` | Inspección por columnas, candidatos de carga y validación del rango |
| `week_store.py` | SQLite, transacciones, copias, versiones, auditoría y snapshots |
| `week_service.py` | Progreso documental, revisión, métricas y cierre/reapertura |
| `week_window.py` | Selector, centro de control, carga masiva y consultas |

Adaptaciones: `review_window.py` acepta callbacks opcionales para guardar/procesar
la revisión semanal. Sus valores predeterminados preservan el flujo diario.
`dashboard_window.py` adapta el subtítulo al contexto semanal. `main.py` queda como
entrada pequeña. No se modificaron los contratos de `importers.py`, `review_data.py`
ni `processor.py`.

Se utiliza `sqlite3` de la biblioteca estándar: transacciones explícitas y SQL
acotado al repositorio de almacenamiento, sin una dependencia nueva. SQLAlchemy
permanece disponible, pero no es necesario introducir un ORM para este índice local.

## Datos fuera del repositorio

```text
Documents/SHES-Control-Datos/
    shes_index.sqlite3
    HISTORIAL/
        2026-09-18/carga_01/...           # Sin modificar
        2026-W39/
            puntos/v1_<identificador>.xlsx
            pedidos/v1_<identificador>.xlsx
            porcliente/v1_<identificador>.xlsx
            liquidacion/v1_<identificador>.xlsx
            auditoria/revision_<identificador>.json
            procesado/procesado_<identificador>.json
            procesado/cierre_<identificador>.json
```

Los nombres físicos son únicos; fecha, sucursal y versión lógica se consultan en el
índice y la UI. Una versión vieja nunca se sobrescribe. Cada archivo tiene SHA-256.
Se verifica la copia y también los archivos activos al calcular. SQLite, sus archivos
auxiliares, Excel y snapshots están ignorados en Git. WeekStore rechaza datos dentro
del repositorio. La exportación tampoco permite escribir dentro del repo o reemplazar
el historial protegido.

Para backup, cerrar la aplicación y copiar **la carpeta de datos completa**, no solo
la base. Esta versión guarda rutas absolutas: mover datos de equipo requiere una
futura herramienta de relocalización. No compartir esta SQLite como solución multi-PC.

## Esquema SQLite (versión 1)

| Tabla | Datos y restricciones principales |
| --- | --- |
| `schema_version` | Versión del esquema |
| `weeks` | ID ISO, inicio único, fin, estado persistente, reapertura, revisión, timestamps |
| `workdays` | Una fila por semana/fecha/sucursal, trabajó/no trabajó y motivo |
| `uploads` | Tipo, clave lógica, ruta, nombre original, hash, rango detectado y comercial confirmado, sucursal, versión, activa, metadatos, timestamp |
| `liquidation_day_status` | Por jornada: confirmación, fecha/hora, cantidad al confirmar y nota |
| `reviews` | Revisiones confirmadas, revisión de fuentes, JSON y ruta del snapshot |
| `snapshots` | Cada procesamiento/cierre, revisión de fuentes, ruta, hash y timestamp |
| `audit_events` | Acción, timestamp y detalles JSON |
| `legacy_loads` | Referencias a las cargas diarias anteriores, sin modificarlas |

Índice único parcial: una sola versión activa por semana/clave lógica. Claves de
Puntos: fecha+sucursal; Pedidos/PorCliente: una por tipo y semana. Las liquidaciones
son adjuntos independientes. La cantidad cargada se consulta de los adjuntos activos,
sin inventar cantidad esperada. Cambios de fuentes incrementan la revisión semanal;
una revisión humana obsoleta no puede confirmar sobre datos nuevos.

Estados derivados de jornadas y documentación: EN_CURSO, PREVENTA_COMPLETA y
LIQUIDACIONES_PENDIENTES. CERRADA y REABIERTA se persisten. No se infiere que una
semana pasada esté cerrada solamente por su fecha.

## Cargas, rangos y versiones

1. Seleccionar varios `.xlsx` en **+ SUBIR ARCHIVOS**.
2. Se detecta tipo, fecha y vendedores por columnas/contenido. El nombre no clasifica.
3. Elegir Corrientes o Resistencia para **cada Puntos**, según la decisión del usuario.
   Puede existir una sugerencia interna por columnas explícitas, pero la UI exige elegir.
4. Para Pedidos/PorCliente, confirmar el rango comercial realmente exportado, incluyendo
   días sin movimientos. Las fechas mínimas/máximas de filas por sí solas no prueban
   cobertura documental de los días vacíos.
5. PorCliente conserva fechas por fila según confirmó el usuario. Indicar si el período
   es fecha de entrega (caso de los archivos actuales) o fecha comercial.
6. Confirmar el lote: recién entonces se copian archivos y se actualiza SQLite.

Un hash ya cargado se ignora aunque cambie el nombre; se registra el rechazo.
El hash corresponde a los bytes del Excel: volver a guardar un workbook puede
producir otra versión aunque sus celdas parezcan iguales.

Si el nuevo reporte cubre el mismo rango o lo amplía, queda activo. Un rango menor
o diferente se conserva como histórico. En Archivos/Auditoría se puede hacer activa
otra versión mediante acción explícita; recalcular usa **solo esa versión**, incluso
si reduce la cobertura. Dos reportes disjuntos tampoco se suman automáticamente:
exportar un acumulado que cubra el rango deseado o elegir uno como activo.

Pedidos fuera del rango confirmado/semana o con fecha inválida se conservan crudos
y se excluyen con advertencia. La última modificación nunca asigna semana.

## Domingo y días no trabajados

La semana comienza el lunes y termina el domingo inclusive. Alta domingo con entrega
lunes pertenece a la semana que termina. Alta lunes pertenece a la siguiente.
Domingo no espera Puntos ni genera visitas/cobertura. Sí suma pedidos, compradores,
venta y artículos semanales. La cobertura de Pedidos/PorCliente debe incluirlo para
declarar que la preventa semanal está completa, aunque no tenga movimientos.

No trabajado puede marcarse/revertirse para una o ambas sucursales de lunes a sábado.
Cada sucursal conserva su motivo y eventos. Sus Puntos históricos siguen guardados
pero no aportan actividad. No se exige un Excel vacío. Si las dos no trabajaron,
la jornada no exige reportes ni confirmación de liquidaciones. Si existen pedidos
excepcionales en esa fecha, su venta sigue conservada; no convierte el día en jornada
operativa ni cambia por sí sola la marca administrativa.

El día actual muestra EN_CURSO y los posteriores FUTURA: no se consideran faltantes
hasta el día siguiente (fecha local de Windows). El usuario actualiza desde la UI.

## Métricas parciales

Se reconstruyen desde filas de las **versiones activas**, no sumando JSON diarios:

- Pedido lógico: cliente + vendedor final + fecha comercial. Los componentes de
  origen quedan auditados; reasignar al mismo destino no infla conteos.
- Venta válida excluye anulados, conserva pendientes y retenidos; original incluye
  lo observado en la exportación, también anulados. Excluidos no aportan métricas.
- Compradores: códigos únicos de cliente en toda la semana. Ticket semanal:
  venta semanal / compradores únicos.
- Cobertura: pares cliente/jornada visitados / asignados. Puntos de domingos,
  sucursales no trabajadas, días futuros y fechas fuera del rango activo de Pedidos
  no entran. Un cliente visitado dos días participa en dos jornadas, no dos compradores.
- Conversión: pares cliente/jornada con venta asignada / pares visitados, dentro
  de las fechas con actividad SIGO del vendedor. Domingo no cambia esta conversión.
  Las visitas no se trasladan al reasignar pedidos. Con denominador cero se devuelve 0.
- Promedio operativo: venta de jornadas completas con actividad / cantidad de esas
  jornadas. Excluye tanto del numerador como del divisor el domingo y días no trabajados;
  sus ventas excepcionales siguen incluidas en venta semanal. Puede haber venta
  semanal sin un promedio operativo disponible (divisor 0).
- Artículos/proveedores: sets reales de clientes, todos los artículos, bultos sin
  convertir a unidades. Mix: pares cliente/artículo / compradores semanales.

Se muestra por separado **ventas hasta**, **artículos hasta** y **preventa completa hasta**.
Las fechas primeras son coberturas declaradas de reportes activos; la última es el
avance documental continuo desde el lunes. Una semana incompleta permite analizar.

PorCliente se cruza por cliente/vendedor original y fecha elegida:
si es comercial, con alta; si es entrega, con entrega del pedido sin alterar su semana.
Si varios pedidos lógicos de distintas fechas comparten período/cliente y tienen el
mismo vendedor final, los artículos se contabilizan una vez a nivel semanal, sin
inventar reparto por día. Si tienen destinos diferentes, se deja una advertencia y
esas líneas no se atribuyen comercialmente hasta contar con detalle suficiente.
Sus fuentes crudas quedan conservadas. No se prorratean importes para forzar coincidencias.
También se evita atribuir un período de entrega cuando comparte cliente/vendedor
con pedidos detectados fuera del rango comercial: sin detalle adicional no es posible
separar con certeza esos artículos entre semanas.

Hora Venta sigue siendo señal SIGO; sin pedido conciliado se advierte. No genera
importes o compradores ficticios. Puntos solo permiten calcular métricas sobre lo
cargado: resultados parciales no representan carteras todavía no exportadas.

## Revisión, liquidaciones, cierre y reapertura

REVISAR ASIGNACIONES abre las tarjetas existentes. Las decisiones confirmadas se
guardan como JSON nuevo; ante otra versión se proponen las asignaciones por ID lógico,
pero hay que revisar y confirmar nuevamente. Cambiar fuentes, activa, no trabajado
o revisión invalida las confirmaciones administrativas para no cerrar con datos obsoletos.

Liquidaciones se adjuntan manualmente a una jornada comercial. En esta etapa son
evidencia documental: **no se interpretan importes, cuentas corrientes ni devoluciones**.
La confirmación guarda timestamp, cantidad cargada y nota. Con cero archivos se exige
una nota explicativa (por ejemplo, sin repartos). No existe denominador de camiones.

Cerrar exige:

1. Semana terminada.
2. Jornadas comerciales completas salvo no trabajadas; domingo sin SIGO.
3. Revisión confirmada sobre versiones actuales.
4. Liquidaciones completas confirmadas en las jornadas aplicables.

Se guarda un snapshot de cierre con revisión, métricas, atribución de artículos,
actividad, IDs de versiones y confirmaciones. `administrative_closed=true`, pero
`final_numbers=false`: falta el futuro motor de conciliación financiera y premios.
`awards=null` evita presentar premios inventados.

Cerrada permite filtrar, ordenar, abrir vendedor/artículo/proveedor, ver snapshots
y exportar. Las mutaciones también se bloquean en almacenamiento, no solo en botones.
REABRIR SEMANA exige motivo, registra evento y conserva todos los snapshots/revisiones
anteriores. Un nuevo cierre tiene otra ruta; el original nunca se reemplaza.

## Historial anterior

Al abrir, se indexan las carpetas `AAAA-MM-DD/carga_NN` sin mover ni alterar archivos.
Se agrupan por semana en Archivos/Auditoría, con explorador de archivos/hashes y
consulta de JSON. Los dashboards ya procesados pueden abrirse en solo lectura.
No se suman varias cargas de un mismo día ni se convierten automáticamente en
reportes activos semanales. Para incorporar datos a un cálculo nuevo, seleccionarlos
desde + SUBIR ARCHIVOS y confirmar sus rangos/sucursales. Las decisiones antiguas
siguen en sus JSON originales y pueden consultarse, pero no se importan implícitamente
como una nueva revisión semanal.

## Prueba manual

1. Ejecutar `.venv\Scripts\python.exe main.py`: aparece Semanas, sin diálogo de Excel.
2. Entrar a la semana de los datos y revisar Cargas / ¿QUÉ ME FALTA?.
3. Seleccionar varios Puntos y reportes acumulados. Elegir sucursal, rangos y tipo de
   período de PorCliente; confirmar. Verificar ACTIVA en Archivos/Auditoría.
4. Subir un Excel idéntico renombrado: se ignora. Subir un acumulado ampliado:
   aparece otra versión y la venta no se duplica.
5. Marcar una sucursal no trabajada y revertir. Revisar explicación y actividad.
6. Abrir revisión, reasignar un pedido y confirmar. Procesar/ver dashboard. Comparar
   ventas del destino con visitas del vendedor original.
7. Adjuntar liquidaciones, confirmar por jornada (nota si no hubo repartos).
8. En una semana finalizada y completa, cerrar. Comprobar navegación/exportación
   habilitadas y botones de modificación bloqueados.
9. Reabrir con motivo, corregir y cerrar otra vez. Abrir el snapshot original y el
   nuevo desde Archivos/Auditoría: ambos siguen disponibles.

## Validación y pendientes

La suite tiene 66 pruebas aprobadas: 22 anteriores y 44 semanales. Incluye los
30 casos solicitados y regresiones adicionales de rangos,
reapertura, persistencia al reiniciar, manipulación de archivos, reasignación y UI.
Se ejecutó además una carga semanal con copias temporales de los cuatro Excel
reales del 18/09; sus hashes originales permanecieron iguales. La base de producción
no se creó ni migró durante esa prueba: se inicializa al abrir la aplicación.

Pendientes: parser financiero de liquidaciones, premios/pagos, sincronización,
relocalización de datos entre equipos, detección normalizada de contenido Excel,
atribución ambigua de artículos a varias fechas/destinos y automatización de la
adopción de revisiones diarias antiguas. La UI sigue procesando Excel de forma
síncrona; archivos grandes pueden pausarla durante la lectura. No hay reescritura
del stack ni integración de premios prematura.

Las escrituras SQLite se serializan con transacciones. Si falla el índice después
de copiar un archivo puede quedar una copia huérfana; nunca se utiliza sin una fila
activa en SQLite. Una herramienta futura puede detectar y recuperar esos archivos.
