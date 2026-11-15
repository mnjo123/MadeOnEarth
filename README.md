# Cielo en Movimiento

Explorador de la misión SPHEREx para el NASA Space Apps Challenge 2026, del equipo **Made On Earth**. El visor usa Aladin Lite v3 como mapa astronómico y consulta el archivo público de NASA/IPAC-IRSA. La comparación en el tiempo alinea recortes FITS, resta el fondo y muestra la secuencia con el mismo estiramiento por detector.

La interfaz está en inglés. Esta guía está en español.

## Qué incluye

- Mapa interactivo con Aladin Lite v3 y selector de objeto o coordenadas RA/Dec.
- Búsqueda SIA2 en las colecciones públicas `spherex_dr1` y `spherex_qr3`. También se pueden consultar las colecciones Deep.
- Descarga de un recorte FITS desde IRSA, extracción de una imagen 2D con Astropy y capa sobre el mapa.
- Comparación temporal: parpadeo, deslizador y diferencia lineal entre dos fechas del mismo detector.
- Secuencia ya procesada de WISE 0855 en `demo/real-motion/wise0855/`, para abrir la comparación sin esperar a NASA.

## Estructura

```text
index.html                  visor
config.js                   URL del API (vacía en local)
spherex-integration.js      mapa Aladin, búsqueda y comparación
assets/header.jpg           imagen de la cabecera
demo/real-motion/           secuencias SPHEREx guardadas
backend/server.py           API FastAPI
backend/build_demo_track.py regenera la secuencia de demostración
backend/requirements.txt
docs/WINDOWS.md             cómo abrirlo en Windows
render.yaml                 despliegue del API en Render
```

GitHub Pages solo publica el frontend. El API va en otro servicio, porque Pages no ejecuta Python ni procesa FITS.

No entregues `backend/.venv` ni `__pycache__`. El entorno virtual se crea en cada máquina.

## Requisitos

- Python 3.11 o 3.12 (en Windows evita 3.14)
- Conexión a internet para IRSA y Aladin Lite

## Ejecutar en local

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn server:app --reload
```

Abre [http://127.0.0.1:8000](http://127.0.0.1:8000). El API también sirve el HTML y los scripts, así que las llamadas a `/api/...` quedan en el mismo origen. Deja `config.js` con la cadena vacía.

En Windows, los pasos con PowerShell están en [docs/WINDOWS.md](docs/WINDOWS.md).

## Cómo usar el visor

1. Entra a **Participants** para el mapa en vivo.
2. El mapa abre centrado en WISE 0855. Puedes elegir otro objeto o moverte por el cielo.
3. **Use map center** copia el centro del mapa a la consulta.
4. Ajusta el radio y la colección y pulsa **Search observations**.
5. Elige un resultado para pedir el recorte FITS y verlo como capa.
6. En **Compare**, la secuencia precargada de WISE 0855 aparece al entrar. **Search sequence** descarga otras coordenadas desde IRSA; puede tardar un par de minutos.

## Notas técnicas

- La capa inicial `DSS2/color` es contexto del cielo. La imagen SPHEREx aparece al elegir un resultado de IRSA.
- Astropy se queda con una extensión 2D apta para la vista previa. El cubo espectral completo no se dibuja aquí.
- No se asume una capa HiPS de todo el cielo de SPHEREx. Cada consulta pide observaciones puntuales por SIA2.
- Las observaciones descargadas en caliente viven en memoria y en un directorio temporal. Si el servicio se reinicia, hay que buscar otra vez. La secuencia de `demo/` sí permanece en disco.
- La diferencia solo se calcula entre dos fechas del mismo detector.
- Aladin Lite necesita internet y WebGL2. Conserva su logo y la atribución en el mapa.
- El plan gratuito de Render puede tardar en despertar tras un rato inactivo.

## Publicar

### Frontend en GitHub Pages

1. Sube este repositorio. En la raíz deben quedar `index.html`, `config.js`, `spherex-integration.js`, `assets/`, `README.md` y `render.yaml`, junto con `backend/` y `demo/`.
2. En **Settings → Pages**, elige **Deploy from a branch**, rama `main` y carpeta `/ (root)`.
3. El sitio queda en una URL del estilo `https://TU-USUARIO.github.io/cielo-en-movimiento/`.

### API en Render

1. Crea un **Web Service** con este repositorio.
2. **Root Directory:** `backend`.
3. **Build Command:** `pip install -r requirements.txt`.
4. **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`.
5. Variable `CORS_ORIGINS` con el origen exacto de GitHub Pages, por ejemplo `https://TU-USUARIO.github.io`. Varios orígenes se separan con comas.
6. Comprueba `https://TU-API.onrender.com/health`. Debe responder `{"status":"ok",...}`.

`render.yaml` deja CORS en `*` para una prueba inicial. Antes de dejarlo público, sustitúyelo por el origen concreto.

En `config.js`, pega la URL del API sin barra final y vuelve a publicar el frontend:

```js
window.CEM_SPHEREX_API_BASE = "https://TU-API.onrender.com";
```

## Regenerar la demostración

Desde `backend/`, con el entorno activo y conexión a IRSA:

```bash
python build_demo_track.py
```

Guarda de nuevo los recortes de WISE 0855 en `demo/real-motion/wise0855/`.

## Fuentes

- Aladin Lite v3: https://cds-astro.github.io/aladin-lite/
- API de Aladin Lite: https://cds-astro.github.io/aladin-lite/Aladin.js.html
- Acceso a datos SPHEREx en IRSA: https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/
