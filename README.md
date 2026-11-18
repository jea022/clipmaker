# Clipmaker

Convierte un clip horizontal de stream en un video vertical 1080x1920: **cámara arriba, título en el centro, gameplay abajo**, con la plantilla de cada cuenta (`@wganga_clips`, `@gtaHispaClips`). Genera también el caption y los hashtags.

## Instalar (una vez)
1. Python 3.10+ (Windows: `winget install Python.Python.3.12`). En Windows ffmpeg no hace falta instalarlo: `run.bat` lo descarga solo la primera vez (~200 MB) a la carpeta `bin/`. En Mac: `brew install ffmpeg`.
2. Doble clic en `run.bat` (Windows) o `./run.sh` (Mac/Linux). Crea el entorno solo y abre http://127.0.0.1:5000.
3. Windows puede mostrar el aviso de SmartScreen: "Más información" → "Ejecutar de todas formas". Si la descarga de ffmpeg falla, instálalo a mano con `winget install Gyan.FFmpeg` y ciérrala y ábrela de nuevo.

## Instalar en Mac
1. Instala [Homebrew](https://brew.sh) si no lo tienes, y en Terminal: `brew install python@3.12 ffmpeg`.
2. Descarga el proyecto: https://github.com/jea022/clipmaker/archive/refs/heads/main.zip y descomprímelo donde quieras dejarlo.
3. En Terminal, dentro de esa carpeta: `./run.sh`. La primera vez crea el entorno y abre el navegador. **En Mac usa el puerto 5055** (el 5000 lo ocupa AirPlay Receiver); si el 5055 también está ocupado: `./run.sh 5056`.
4. Acceso directo: `./crear_acceso_directo.sh` crea `Clipmaker.command` en el escritorio.
5. Si macOS bloquea los archivos: `chmod +x run.sh crear_acceso_directo.sh` y `xattr -dr com.apple.quarantine .` dentro de la carpeta; o clic derecho → Abrir.
6. Para llevar tus ajustes desde otro equipo, copia la carpeta `data/` (y `secrets/` si subes a YouTube).
Las actualizaciones automáticas funcionan igual que en Windows.

## Acceso directo en el escritorio
Una vez, doble clic en `crear_acceso_directo.bat` (Windows) o ejecuta `./crear_acceso_directo.sh` (Mac/Linux). Aparece "Clipmaker" en el escritorio; al abrirlo arranca la app y se abre el navegador. No muevas la carpeta del proyecto después (si la mueves, vuelve a ejecutarlo).

## Usar
1. Arrastra el clip principal; debajo del cuadro verás el progreso de la subida.
2. Elige la **variación**: cámara+gameplay, gameplay+cámara, video+imagen, imagen+video, dos videos o video con fondo difuminado. Si la variación lo pide, sube la imagen o el segundo video (si dura menos que el principal, se repite; puedes elegir de cuál sale el audio).
3. Escribe el título y elige el **estilo del texto**:
   - **Franja** (clásico): una franja oscura entre los dos videos; ajustas su **alto** y el **tamaño de letra** (si el título no cabe, la letra se achica sola; la cámara y el gameplay ocupan el resto).
   - **Superpuesto** (caja blanca, negra o amarilla, o texto con contorno blanco o amarillo): los dos videos quedan **pegados** y el texto va encima, centrado en la unión. Con **Parte de arriba** repartes el alto entre ambos videos (30 a 70 %) y con **Subir / bajar el texto** lo mueves desde la unión.
   - Elige la **tipografía** (Inter, Poppins, Anton, Bebas Neue, Archivo Black, Bangers, Luckiest Guy; todas con ñ y tildes) y si va **todo en mayúsculas** o tal como lo escribes.
   - Elige la cuenta y marca quién sale.
4. En **Recortes del clip** elige si dibujas la **cámara** (rojo) o el **gameplay** (verde) y arrastra con el ratón sobre la imagen. "Gameplay completo" quita el recorte. "Guardar como valores por defecto" recuerda recortes, estilo, tipografía, franja, reparto y letra para esa cuenta; "Restablecer valores de fábrica" los borra.
5. La **vista previa** de la derecha se actualiza sola con cada cambio (puedes apagarla o pulsar "Actualizar").
6. **Crear video**, descarga y copia los textos.

Por terminal: `python clipmaker.py clip.mp4 "Título" --layout templates/wganga.json -o salida.mp4`, o `--batch carpeta` (cada `clip.mp4` con su `clip.txt` de título). Variaciones: `--preset clip_image --image foto.jpg`, `--preset clip_clip --clip-b otro.mp4 --audio b`, `--preset clip_blur`; `--list-presets` las muestra todas junto con los estilos y tipografías. Texto superpuesto: `--title-style box_white --font poppins --split 45 --offset 0 --font-size 56 --lowercase`.

## Hashtags
Cada cuenta tiene su lista recomendada (basada en una investigación de hashtags reales, ver abajo) y puedes editarla en la sección **5 · Hashtags de la cuenta**:
- **Siempre**: salen en todos los clips (por defecto `#GTA6 #GTAVI`).
- **Personas**: los hashtags de quien marques en el clip (el primero es el principal; los demás rotan).
- **Nicho, Alcance y Reserva**: rotan **por turnos**, así cada clip lleva un set distinto y todos se usan por igual. "Ver cómo se reparten" lo muestra con los próximos clips y cuántas veces sale cada uno en 30.
- **Solo clips de GTA RP**: se usan únicamente si eliges "GTA V / GTA RP" en *Juego del clip*; en un clip de GTA VI serían engañosos y no se ponen.
- **Por verificar**: no se usan nunca; es donde esperan los hashtags sin evidencia (compruébalos en la app antes de moverlos).
- Cantidad: 5 en TikTok y 3 en Shorts (más `#Shorts`). Esos topes vienen de prensa, no están confirmados por TikTok/YouTube.
Las dos cuentas comparten solo `#GTA6` y `#GTAVI`. Tus cambios se guardan en `data/hashtags.json` y las actualizaciones no los tocan. Desde la terminal: `python captions.py wganga "Título" westcol samulx`.

## Tu diseño de Canva
Exporta 1080x1920: un PNG de **fondo** y uno **transparente** de overlay. Cópialos a `templates/` y en `templates/<cuenta>.json` cambia `background_png` y `overlay_png`. Las zonas (`cam_zone`, `title_zone`, `game_zone`) se ajustan en el mismo archivo.

## Subir a YouTube Shorts (API oficial)
1. En Google Cloud Console crea un proyecto, activa **YouTube Data API v3** y crea credenciales OAuth tipo "Aplicación de escritorio". Descarga el JSON a `secrets/client_secret.json` (o `secrets/client_secret_wganga.json` por cuenta).
2. En la pantalla de consentimiento, añade como usuarios de prueba los emails de tus canales.
3. Botón "Subir a YouTube Shorts" en la web, o `python publish_youtube.py video.mp4 "Título" --account wganga --people westcol`. La primera vez inicias sesión en el navegador; el token queda en `secrets/` (nunca se guarda tu contraseña).

Importante: por defecto sube como **privado**. Google deja en privado los videos subidos por API desde proyectos sin auditar; para publicar en abierto hay que pasar su auditoría o cambiar la visibilidad a mano en YouTube Studio. Cuota: ~6 subidas/día por proyecto de Cloud.

**TikTok:** su API exige una auditoría antes de poder publicar en abierto, así que de momento copia el caption y sube el video a mano (o usa un programador como Buffer/Metricool).

## Actualizaciones automáticas
La app puede avisarte cuando hay una versión nueva y actualizarse con un clic (se reinicia sola y no toca tus ajustes, tu entorno, ffmpeg ni tus credenciales; guarda una copia de seguridad en `data/backups/`).
Se activa copiando `update.example.json` a `update.json` y poniendo la dirección del repositorio de GitHub donde se publican las versiones. Solo se aceptan descargas por https desde github.com. Con `"auto": true` se actualiza sola al abrirse, sin preguntar.
Cada versión nueva debe subir el número del archivo `VERSION`.

## Pruebas
`python test_clipmaker.py` (montaje), `python test_api.py` (web), `python test_publish.py` (YouTube), `python test_updater.py` (actualizaciones), `node test_ui.js` (navegador; necesita el servidor en marcha).
