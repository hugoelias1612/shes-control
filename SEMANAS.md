# Centro de control semanal

El flujo actual se explica en [PRIMERA_CARGA.md](PRIMERA_CARGA.md): SIGO semanal por sucursal, preventa sábado anterior a viernes y reparto lunes a sábado. La configuración de exclusiones se guarda en `settings` y sus cambios en `settings_history`.


## Eliminar cargas de prueba

En la semana, abrir **Archivos / Auditoría**, seleccionar una o varias filas
(Ctrl o Shift) y pulsar **Eliminar cargas seleccionadas**. La confirmación muestra
los archivos afectados. Las cargas eliminadas dejan de aportar datos y la pantalla
recalcula los resultados; no se activa automáticamente una versión anterior.
Se puede activar manualmente una versión histórica que no esté eliminada.

Los Excel originales y snapshots se conservan. Las filas quedan como ELIMINADA,
con fecha y evento de auditoría, y los mismos archivos pueden subirse nuevamente.
La revisión y las confirmaciones de liquidaciones deben confirmarse otra vez.
Las semanas cerradas requieren reapertura antes de eliminar cargas.

La migración automática a esquema 2 agrega `uploads.removed_at` sin modificar
archivos ni eliminar registros existentes. La eliminación múltiple es atómica y
verifica que la semana no haya cambiado desde que se abrió la lista.
Validación actual: 79 tests, incluyendo migración, recarga del mismo Excel,
cancelación, selección ordenada en UI, recálculo y bloqueo en semanas cerradas.

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
entrada pequeña. `build_logical_orders` acepta una columna de fecha opcional:
el flujo diario conserva alta y el semanal usa entrega.

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

## Esquema SQLite (versión 2)

| Tabla | Datos y restricciones principales |
| --- | --- |
| `schema_version` | Versión del esquema |
| `weeks` | ID ISO, inicio único, fin, estado persistente, reapertura, revisión, timestamps |
| `workdays` | Una fila por semana/fecha/sucursal, trabajó/no trabajó y motivo |
| `uploads` | Tipo, clave lógica, ruta, nombre original, hash, fechas detectadas y semana, sucursal, versión, activa, metadatos, timestamp, removed_at |
| `liquidation_day_status` | Por jornada: confirmación, fecha/hora, cantidad al confirmar y nota |
| `reviews` | Revisiones confirmadas, revisión de fuentes, JSON y ruta del snapshot |
| `snapshots` | Cada procesamiento/cierre, revisión de fuentes, ruta, hash y timestamp |
| `audit_events` | Acción, timestamp y detalles JSON |
| `legacy_loads` | Referencias a las cargas diarias anteriores, sin modificarlas |

Índice único parcial: una sola versión activa por semana/clave lógica. Claves de
Puntos: sucursal (archivo semanal); Pedidos: una por hash y semana; PorCliente: una por semana. Las liquidaciones
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
4. Pedidos y PorCliente se cargan para la semana seleccionada, sin preguntar rangos ni modos de fecha.
   La vista previa muestra las fechas detectadas. El usuario carga todas las partes que exportó de CHESS.
5. PorCliente conserva fechas por fila y se cruza por fecha de entrega.
6. Confirmar el lote: recién entonces se copian archivos y se actualiza SQLite.

Un hash ya activo en esta semana se ignora aunque cambie el nombre; se muestra su ID y nombre original.
Las cargas históricas, eliminadas o de otras semanas no bloquean una nueva carga.
El hash corresponde a los bytes del Excel: volver a guardar un workbook puede
producir otra versión aunque sus celdas parezcan iguales.

Todos los reportes de Pedidos diferentes quedan activos como partes de la semana.
Se combinan por número de pedido: la última carga actualiza importe, estado, fecha y
demás campos del número repetido. Primero se combinan y después se filtra por entrega,
para que una actualización de fecha o anulación también quite el valor anterior.
Eliminar una parte vuelve a calcular desde las restantes. PorCliente conserva una
sola versión activa y el último archivo reemplaza al anterior.

Pedidos con entrega fuera de la semana o fecha inválida/futura se conservan crudos
y se excluyen con advertencia. La última modificación nunca asigna semana.

## Domingo y días no trabajados

La semana comienza el lunes y termina el domingo inclusive. Un pedido con entrega
lunes pertenece a la semana que comienza, aunque se haya creado el domingo o el año anterior.
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

- Pedido lógico: cliente + vendedor final + fecha de entrega. Los componentes de
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

PorCliente se cruza por cliente y fecha de entrega, con el vendedor final del pedido. Los destinos ambiguos se advierten; las líneas negativas se conservan separadas sin afectar preventa ni artículos vendidos.
Sus fuentes crudas quedan conservadas. No se prorratean importes para forzar coincidencias.
Los pedidos sin vendedor se muestran como SIN ASIGNAR: requieren asignación en la revisión
y una alerta informa el importe que aún no suma. Las revisiones anteriores basadas en alta
deben confirmarse nuevamente; los cierres históricos conservan sus snapshots originales.

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
3. Seleccionar varios Puntos y partes de pedidos. Elegir sucursal para Puntos;
   guardar. Verificar todas las partes ACTIVAS en Archivos/Auditoría.
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

La suite contempla 79 pruebas: 22 anteriores y 57 semanales. Incluye los
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
