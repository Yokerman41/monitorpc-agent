# monitorPC Agent - Versión 1.0.1 🚀

Este directorio contiene el instalador oficial de la versión **1.0.1** de **monitorPC Agent** para Windows.

---

## 📦 Descarga del Instalador
Puedes descargar directamente el instalador desde el repositorio:
👉 **[Instalador-monitorPC-Agent.exe (v1.0.1)](Instalador-monitorPC-Agent.exe)**

---

## 🛡️ Verificación de Integridad y Seguridad (VirusTotal)

Para garantizar la seguridad de tu descarga, puedes validar la integridad del instalador mediante su hash criptográfico.

*   **Archivo**: `Instalador-monitorPC-Agent.exe`
*   **Algoritmo**: SHA-256
*   **Hash**: `A5FAD09235A1BDA15DCD09A83FDF68D4FF2B3DBDBF1E7FBAB37D3F07D496ACC4`
*   **Reporte de Análisis**: 🔍 [Ver análisis en VirusTotal](https://www.virustotal.com/gui/file/a5fad09235a1bda15dcd09a83fdf68d4ff2b3dbdbf1e7fbab37d3f07d496acc4)

> [!NOTE]  
> Al compilar programas hechos en Python en un ejecutable único `.exe` utilizando PyInstaller, algunos antivirus con firmas heurísticas genéricas pueden arrojar falsos positivos temporales. El hash SHA-256 provisto arriba permite verificar que el archivo es idéntico al compilado originalmente de manera limpia.

---

## 🛠️ Novedades de la Versión 1.0.1
*   **Solución a Bloqueos por Permisos (`Errno 13`)**: Corregido el problema crítico que impedía iniciar el agente si se ejecutaba automáticamente al inicio del sistema o desde terminales en carpetas protegidas. Ahora el agente utiliza rutas de persistencia absolutas resueltas dinámicamente sobre la carpeta de instalación local del usuario (`AppData\Local\Programs\monitorPC-Agent`).
*   **Optimización de Landing Page**: Ajustado el layout y responsividad de la página de destino local del agente para visualizaciones de escritorio, móvil y tablet.
*   **Corrección de Iconografía**: Corregido el renderizado de la métrica de CPU en el dashboard simulado de la landing page usando la clase estándar `fa-microchip` de FontAwesome.
*   **Control de Sockets**: Validación inteligente de puertos en uso (8765 and 8766) al iniciar la aplicación para evitar colisiones.

---

## 🖥️ Características Principales
*   **Métricas del Sistema**: Reporte detallado y consumo en tiempo real de CPU (uso general, temperatura por núcleo, velocidad de reloj), GPU (temperatura, uso de VRAM, encoders/decoders) y memoria RAM.
*   **Almacenamiento e Historial**: Diagnóstico S.M.A.R.T. detallado y monitoreo de espacio en discos (SSD, NVMe, HDD).
*   **Red de Baja Latencia**: Sincronización a través de WebSockets de alta velocidad con latencia de respuesta instantánea.
*   **Control Remoto Seguro**:
    *   Cierre de sesión, bloqueo de PC y suspensión del sistema de forma segura.
    *   Inspección de procesos y capacidad de finalizar tareas del sistema de forma remota.
    *   Lanzamiento rápido de scripts de macros preconfigurados (`scripts.json`).
*   **Mirroring de Pantalla**: Transmisión fluida de la pantalla de tu PC a la app móvil por WebSocket para un control visual rápido.
*   **NSD/mDNS**: Descubrimiento automático de equipos en la misma red local sin necesidad de ingresar IPs de forma manual.

---

## 🚀 Instrucciones de Instalación
1.  Descarga el archivo [Instalador-monitorPC-Agent.exe](Instalador-monitorPC-Agent.exe).
2.  Ejecuta el instalador en tu sistema operativo Windows.
3.  Elige el directorio de instalación deseado (por defecto se instala en el directorio de aplicaciones locales del usuario: `AppData\Local\Programs\monitorPC-Agent`).
4.  Selecciona si deseas crear accesos directos e iniciar el agente con Windows.
5.  El agente se ejecutará en la bandeja del sistema (System Tray). Desde allí puedes:
    *   **Ver Información de Conexión**: IP y puerto para emparejar con la app de Android.
    *   **Generar PIN**: PIN seguro de 6 dígitos para vincular dispositivos móviles.
    *   **Desvincular**: Eliminar dispositivos vinculados en la base de datos local.
