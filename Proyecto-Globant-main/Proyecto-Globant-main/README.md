# NÁUFRAGO

Prototipo roguelite de supervivencia 2D desarrollado en Python y Pygame. El jugador recorre un mundo continuo de cuatro biomas, reúne doblones, elige mejoras durante la partida y se enfrenta a jefes regionales antes del combate final contra Barbanegra al minuto 20.

## Integrantes

- Ramiro Prioletta
- Lionel Garcia
- Francesca Laportilla
- Facundo Valencia
- Tatiana Pebay Vulcano

## Instalación y ejecución en Windows

El lanzador `jugar.bat` busca Python 3.12 de 64 bits. El código funciona con Python 3.10 o superior, pero se recomienda Python 3.12 para seguir estos pasos.

### 1. Instalar Python 3.12

Opción recomendada, con WinGet:

```powershell
winget install --id Python.PythonInstallManager
```

Cuando termine, cierra y vuelve a abrir PowerShell. Instala Python 3.12 y verifica la versión:

```powershell
py install 3.12
py -3.12 --version
```

La verificación debe mostrar `Python 3.12.x`.

Si no tienes WinGet, descarga el instalador de Python 3.12 para Windows desde [python.org](https://www.python.org/downloads/windows/). Elige el instalador de 64 bits y, durante la instalación, asegúrate de incluir `pip`. `jugar.bat` reconoce tanto la ruta habitual del instalador oficial como la del Python Install Manager.

### 2. Instalar las dependencias

Abre PowerShell en la carpeta del proyecto, donde están `requirements.txt` y `main.py`. Instala las dependencias con Python 3.12 explícitamente:

```powershell
py -3.12 -m pip install -r requirements.txt
```

El archivo `requirements.txt` instala Pygame. Para confirmar que quedó instalado en Python 3.12:

```powershell
py -3.12 -c "import pygame; print(pygame.version.ver)"
```

### 3. Iniciar el juego

Desde la carpeta del proyecto, ejecuta:

```powershell
.\jugar.bat
```

También puedes iniciarlo directamente:

```powershell
py -3.12 main.py
```

Si `py -3.12` no encuentra el intérprete instalado por Python Install Manager, usa su ruta explícita:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.12-64\python.exe" -m pip install -r requirements.txt
& "$env:LOCALAPPDATA\Python\pythoncore-3.12-64\python.exe" main.py
```

Si se cierra desde la terminal con **Ctrl+C**, la partida termina limpiamente y guarda los doblones reunidos.

### Ejecutar las pruebas

```powershell
py -3.12 -m unittest discover -s tests -v
```

## Controles

- **WASD** o **flechas**: moverse.
- **ESPACIO** o **SHIFT**: dash evasivo, con 0,2 s de invulnerabilidad y 3,5 s de recarga.
- **E**: activar un altar cuando estés a su lado.
- **ESC**: pausar o reanudar.
- **Ratón**: elegir las cartas de nivel, navegar los menús y ajustar el volumen.
- El mazo lanza cartas automáticamente al objetivo más cercano; las mejoras pueden multiplicarlas, acelerarlas, perforar enemigos o incendiarlos.

## Bucle de juego

Las partidas comienzan en la playa central con nivel 1. Al conseguir experiencia, el juego se pausa y presenta tres mejoras aleatorias para elegir entre cinco rarezas; vida, regeneración, armadura, curación y habilidades de cartas solo cambian durante esa partida. Cofres y barriles se destruyen con los ataques, y pueden soltar experiencia, doblones o curación. Los altares opcionales inician un desafío de supervivencia de 30 segundos y entregan un artefacto de la partida.

Al vencer enemigos se consiguen doblones. En el armario del menú se pueden desbloquear personajes y armas iniciales, además de comprar sombreros. El Capitán atrae más recursos, la Corsaria empieza con dagas perforantes y el Viejo Marinero resiste más y repele a sus atacantes. Los desbloqueos se guardan en `%USERPROFILE%\.naufrago\profile.json`.

## Mundo y amenazas

El mundo continuo ocupa 6400 × 6400 unidades y termina en una costa circular irregular, con espuma animada sobre el agua. El jugador, los eventos y los enemigos quedan dentro de la isla. Los biomas usan fronteras orgánicas con terreno mezclado y decoración ponderada durante las transiciones:

- **Centro, playa y bosque costero**: cangrejos, esqueletos y el Kraken de la Orilla.
- **Este, Desierto de Calaveras**: serpientes, escorpiones, gaviotas y el Gólem de Arena. El calor reduce la regeneración al quedarse quieto.
- **Oeste, Tundra Helada**: osos mutantes y espectros; el hielo altera la inercia del movimiento.
- **Norte, Volcán Sombrío**: demonios de ceniza, espectros de fuego y meteoritos señalizados antes del impacto.

Los jefes regionales tienen dos fases y ataques telegrafiados. A los 20 minutos aparece Barbanegra; derrotarlo completa la partida. Los enemigos adaptan su salud y daño al tiempo sobrevivido y algunos aparecen como élites.

## Personajes y armas iniciales

El mazo de cartas es el ataque principal automático. El armario también permite desbloquear personajes, armas secundarias iniciales y sombreros con doblones; las armas secundarias que no se hayan elegido al comenzar pueden aparecer como mejoras:

- **Dagas arrojadizas**: proyectiles rápidos y penetrantes.
- **Bombas de pólvora**: explosión de área.
- **Bumerán de concha**: protección orbital.
- **Llama de ron**: deja fuego dañino al moverse.

## Estructura

- `main.py`: bucle principal, estados, interacción, combate y renderizado.
- `settings.py`: dimensiones, límites, biomas y catálogo de mejoras.
- `game_state.py`: validación y administración del estado activo.
- `player.py`, `enemy.py`, `boss.py`: entidades y estadísticas de personajes.
- `world.py`: costa circular, contención del movimiento y pesos orgánicos de bioma.
- `ui.py`: colores de rareza y selección de rareza de cartas.
- `vfx.py`: partículas recicladas, destellos, pausa breve de impacto y vibración mínima de cámara.
- `profile.py`: persistencia y migración segura de cosméticos y desbloqueos.
- `tests/`: pruebas del juego y del perfil persistente.

El límite de partículas es de 60 elementos simultáneos; partículas, proyectiles, orbes y enemigos se reciclan para reducir asignaciones. Los efectos se recortan al área visible y el HUD suaviza la actualización de sus barras. La simulación usa pasos fijos de 1/60 s y limita el trabajo de recuperación tras una caída de frames; esto reduce picos, pero los FPS reales dependen del hardware.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

## Audio opcional

El juego no necesita recursos externos para iniciarse. Para añadir sonido, coloca archivos OGG en `assets/audio/`: `music.ogg`, `shot.ogg`, `damage.ogg`, `enemy.ogg`, `level.ogg` y `game_over.ogg`. La configuración permite ajustar los volúmenes general, de efectos y música.

## Prompts usados con IA

Los siguientes prompts resumen los pedidos principales realizados durante el desarrollo; están redactados para que se puedan reutilizar y no son transcripciones literales.

1. **Actualizar el mundo y los biomas:** «Transforma el mapa cuadrado en una isla circular con una costa integrada visualmente al terreno. Haz que los biomas tengan límites irregulares y transiciones graduales, mezclando progresivamente terreno, colores y decoración. Mantén al jugador y los eventos dentro de la isla».
2. **Diferenciar a los jefes:** «Mejora el diseño de los jefes para que cada uno tenga una silueta, apariencia, animaciones y ataques propios. Añade efectos visibles para sus habilidades, una barra de vida clara y señales que anticipen sus ataques fuertes».
3. **Añadir cartas como arma:** «Incorpora una habilidad principal basada en cartas que el personaje lance como proyectiles contra los enemigos. Las cartas deben causar daño al impactar y tener animación y efectos visuales propios; deja abierta la posibilidad de mejorarlas».
4. **Crear progresión por niveles:** «Cuando el jugador suba de nivel, pausa la partida y presenta tres mejoras aleatorias para elegir una. Incluye opciones de vida, regeneración, armadura, daño, velocidad, movimiento y habilidades de cartas; aplica la elección y reanuda la partida».
5. **Incluir rarezas y variedad de partidas:** «Organiza las mejoras en rarezas común, poco común, rara, épica y legendaria, con efectos de distinta potencia. Haz que las elecciones cambien entre partidas y que una mejora legendaria pueda añadir efectos especiales a las cartas».
6. **Integrar los sistemas al juego existente:** «Integra exploración, biomas, enemigos, jefes, experiencia y mejoras en el juego actual, con una estructura modular que permita agregar contenido sin duplicar sistemas ni modificar todo el proyecto».
7. **Corregir el borde circular:** «El borde del mapa todavía se ve cuadrado; quiero que el límite y el terreno visible sean circulares, no cuadrados. Corrige el renderizado para que no queden esquinas fuera de la isla».
8. **Documentar la instalación:** «Actualiza el README con todo lo necesario para instalar Python 3.12 en Windows, instalar las dependencias, ejecutar el juego y correr las pruebas».
