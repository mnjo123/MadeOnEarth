# Cómo correr Cielo en Movimiento en Windows

Guía para abrir el visor Aladin + SPHEREx en una PC con Windows.

**Importante:** no copies la carpeta `backend\.venv`. Ese entorno es de Linux, no sirve en Windows y además provoca el error *Ruta de acceso demasiado larga* (`0x80010135`).

---

## Requisitos

- Windows 10 u 11
- Python **3.11 o 3.12** (mejor que 3.14)
- Conexión a internet (IRSA y Aladin Lite)

---

## 1. Instalar Python

1. Entra a [https://www.python.org/downloads/](https://www.python.org/downloads/).
2. Descarga Python 3.12 (o 3.11).
3. En el instalador marca **Add python.exe to PATH**.
4. Completa la instalación.
5. Abre **PowerShell** y comprueba:

```powershell
python --version
```

Debe aparecer algo como `Python 3.12.x`.

---

## 2. Copiar solo el código

Coloca el proyecto en una ruta **corta**, por ejemplo:

```text
C:\cielo
```

La carpeta debe verse así:

```text
C:\cielo\
  index.html
  config.js
  spherex-integration.js
  README.md
  assets\
    header.jpg
  demo\
    real-motion\
  docs\
    WINDOWS.md
  backend\
    server.py
    build_demo_track.py
    requirements.txt
```

- **No** copies `backend\.venv`.
- **No** copies carpetas `__pycache__`.
- Si llegó un `.venv` viejo, bórralo.

Si el proyecto está en GitHub (recomendado, evita el error de rutas largas):

```powershell
cd C:\
git clone https://github.com/USUARIO/EL-REPO.git cielo
cd C:\cielo
```

---

## 3. Crear el entorno e instalar dependencias

En PowerShell:

```powershell
cd C:\cielo\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si Windows bloquea el script de activación:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Cuando el entorno esté activo, el prompt empieza con `(.venv)`. Luego:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

La primera vez tarda varios minutos (Astropy, NumPy, reproject, Pillow).

---

## 4. Arrancar el servidor

Sigue en la misma ventana, con `(.venv)` activo:

```powershell
uvicorn server:app --reload
```

Debe aparecer:

```text
Uvicorn running on http://127.0.0.1:8000
```

---

## 5. Abrir la app

En el navegador entra a:

**http://127.0.0.1:8000**

No hace falta cambiar `config.js` para uso local (déjalo vacío).

Para probar:

1. Abre la sección **Participants**.
2. Pulsa **Search observations**.
3. Elige un resultado para ver la capa SPHEREx.

---

## 6. La próxima vez

```powershell
cd C:\cielo\backend
.\.venv\Scripts\Activate.ps1
uvicorn server:app --reload
```

Luego abre de nuevo **http://127.0.0.1:8000**.

Para detener el servidor: `Ctrl + C` en la terminal.

---

## Problemas frecuentes

| Qué ves | Qué hacer |
|---------|-----------|
| `python` no se reconoce | Reinstala Python marcando **Add to PATH**. Cierra y vuelve a abrir PowerShell. |
| Error de `ExecutionPolicy` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| *Ruta de acceso demasiado larga* (`0x80010135`) | Cancela la copia. Borra `.venv` y `__pycache__`. Copia solo el código a `C:\cielo`. |
| `pip` falla al instalar | Usa Python 3.11 o 3.12, no 3.14. |
| La página abre pero no hay datos | Comprueba internet y que el servidor siga corriendo. |

---

## Resumen rápido

```powershell
cd C:\cielo\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn server:app --reload
```

Abrir: **http://127.0.0.1:8000**
