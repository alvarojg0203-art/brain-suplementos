# Vua Showroom — Guía de instalación (VS Code + MySQL Workbench)

## Estructura del proyecto

```
caro_boutique/
├── app.py                 → servidor Flask (conecta la web con MySQL + panel admin)
├── requirements.txt       → librerías de Python necesarias
├── .env.example           → plantilla con los datos de conexión y contraseñas
├── db/
│   └── schema.sql         → crea la base de datos y las tablas
├── index.html              → la landing page (para clientes)
├── templates/
│   ├── login.html            → login de clientes (mail/contraseña + Google/Apple)
│   ├── register.html         → alta de cuenta de cliente
│   ├── forgot_password.html  → pedir link para recuperar contraseña
│   ├── reset_password.html   → poner contraseña nueva
│   ├── cuenta.html           → "Mi cuenta": datos + historial de pedidos
│   ├── terminos.html, cambios.html, privacidad.html → páginas legales (editar antes de publicar)
│   ├── pago_resultado.html   → pantalla de vuelta de Mercado Pago (éxito/pendiente/error)
│   ├── admin_base.html
│   ├── admin_setup.html      → alta del administrador (primer ingreso)
│   ├── admin_login.html
│   ├── admin_forgot.html      → recuperar contraseña (paso 1: usuario/mail)
│   ├── admin_forgot_question.html   → paso 2: pregunta de seguridad
│   ├── admin_forgot_reset.html      → paso 3: contraseña nueva
│   ├── admin_dashboard.html
│   ├── admin_product_form.html
│   ├── admin_product_colors.html   → colores y galería de fotos de un producto
│   ├── admin_product_sizes.html    → talles de un producto
│   ├── admin_hero.html             → carrusel de imágenes de la portada
│   ├── admin_orders.html
│   ├── admin_customers.html        → clientes registrados
│   ├── admin_stock.html            → stock de todos los productos y variantes, en lista
│   ├── admin_sets.html             → lista de conjuntos/looks armados
│   ├── admin_set_form.html         → crear/editar un conjunto
│   ├── admin_stats.html            → estadísticas de ventas
│   ├── admin_payment_settings.html → qué medios de pago acepta la tienda
│   ├── admin_reviews.html          → moderar reseñas de clientes
│   ├── admin_coupons.html          → cupones de descuento
│   ├── admin_shipping_zones.html   → zonas y costos de envío
│   ├── admin_subcategories.html    → subcategorías por categoría
│   ├── admin_caja.html             → caja: abrir/cerrar, ventas y gastos del día
│   ├── admin_caja_venta.html       → cargar una venta presencial nueva
│   ├── admin_caja_historial.html   → historial de cajas abiertas/cerradas
│   ├── admin_ticket.html           → ticket imprimible de una venta presencial
│   └── admin_reportes.html         → ganancias y gastos (online + local)
└── static/
    ├── css/style.css       → estilos de la landing
    ├── js/caro.js           → catálogo, carrito y checkout
    └── img/                 → fotos de productos (se suben solas desde el panel)
```

## 0. Antes de publicarla: datos de ejemplo que hay que reemplazar

El proyecto trae algunos datos de prueba para poder verla funcionando desde el principio. Antes de mostrársela a un cliente real, conviene revisar esto:

- **Número de WhatsApp**: constante `WHATSAPP_NUMBER` en `static/js/caro.js` (ver sección 3, paso 4). Actualiza sola el botón flotante, el ícono del pie de página y los datos que lee Google.
- **Instagram**: constante `INSTAGRAM_URL`, arriba del todo en `static/js/caro.js` (junto a `WHATSAPP_NUMBER`).
- **Dirección del pie de página**: en `index.html`, buscá `Dirección de ejemplo, Ciudad, Argentina` (está comentado en el código para que sea fácil de encontrar) y poné la real, o borrá esa parte si la tienda no tiene local físico.
- **Mail de contacto**: `contacto@vuashowroom.com` aparece en `index.html` (footer) — cambialo por el mail real si es distinto.
- **Páginas legales**: `templates/terminos.html`, `cambios.html` y `privacidad.html` tienen texto genérico, hay que adaptarlo al negocio real.
- **Logo e imágenes de vista previa**: el logo está en `static/img/logo-vua.png`; las imágenes que se ven al compartir el link (WhatsApp/redes) siguen apuntando a un placeholder (`placehold.co`) en `index.html` — se puede reemplazar por una foto real de la tienda cuando haya una.
- **Productos de ejemplo**: los 12 productos que trae `db/schema.sql` son solo para probar — se borran o editan desde el panel (`/admin`) una vez que tu prima cargue el catálogo real.

## 1. Crear la base de datos en MySQL Workbench

1. Abrí MySQL Workbench y conectate a tu servidor MySQL (local o el que uses).
2. Abrí una pestaña SQL nueva (ícono de rayo/hoja arriba a la izquierda).
3. Abrí `db/schema.sql` de esta carpeta, copiá todo el contenido y pegalo en Workbench.
4. Ejecutalo (rayo amarillo, o Ctrl+Shift+Enter).
   - Esto crea la base `caro_boutique`, las tablas `products`, `customers`, `orders`, `order_items`, `admins`, y carga 12 productos de ejemplo.
5. Confirmá que se creó: en el panel izquierdo (Schemas) debería aparecer `caro_boutique` con sus tablas.

> **Si ya habías corrido `schema.sql` antes** (versión sin la tabla `admins`), no hace falta rehacer todo: solo pegá y ejecutá esto en Workbench, parado en la base `caro_boutique`:
> ```sql
> CREATE TABLE IF NOT EXISTS admins (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   name VARCHAR(150) NOT NULL,
>   email VARCHAR(150) NOT NULL UNIQUE,
>   username VARCHAR(80) NOT NULL UNIQUE,
>   password_hash VARCHAR(255) NOT NULL,
>   security_question VARCHAR(255) NOT NULL,
>   security_answer_hash VARCHAR(255) NOT NULL,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
> ) ENGINE=InnoDB;
> ```

> **Si ya tenías la tabla `customers` de antes** (sin cuentas de cliente), corré esto una vez en Workbench para poder pedir login/registro antes de comprar:
> ```sql
> ALTER TABLE customers MODIFY phone VARCHAR(30) NULL;
> ALTER TABLE customers MODIFY email VARCHAR(150) UNIQUE;
> ALTER TABLE customers ADD COLUMN password_hash VARCHAR(255) AFTER email;
> ALTER TABLE customers ADD COLUMN auth_provider ENUM('local','google','apple') NOT NULL DEFAULT 'local' AFTER password_hash;
> ALTER TABLE customers ADD COLUMN oauth_id VARCHAR(255) AFTER auth_provider;
> ALTER TABLE customers ADD UNIQUE KEY uq_customers_oauth (auth_provider, oauth_id);
> ```

> **Si ya tenías la tabla `products` de antes** (sin descuentos), corré esto una vez en Workbench para poder cargar un % de descuento desde el panel:
> ```sql
> ALTER TABLE products ADD COLUMN discount_percent DECIMAL(5,2) NULL AFTER price;
> ```
> Si en algún momento anterior llegaste a correr una versión que agregaba `discount_price` (precio fijo en vez de %), primero borrala con `ALTER TABLE products DROP COLUMN discount_price;` y después corré la línea de arriba.

> **Para poder cargar colores y varias fotos por color**, corré esto una vez en Workbench (crea las tablas nuevas y agrega las columnas de color a `order_items`; no borra ni toca nada de lo que ya tenías):
> ```sql
> CREATE TABLE IF NOT EXISTS product_colors (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   product_id INT NOT NULL,
>   color_name VARCHAR(60) NOT NULL,
>   color_hex VARCHAR(7) NOT NULL DEFAULT '#cccccc',
>   stock INT NOT NULL DEFAULT 0,
>   sort_order INT NOT NULL DEFAULT 0,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
> ) ENGINE=InnoDB;
>
> CREATE TABLE IF NOT EXISTS product_color_images (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   color_id INT NOT NULL,
>   image_url VARCHAR(500) NOT NULL,
>   sort_order INT NOT NULL DEFAULT 0,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   FOREIGN KEY (color_id) REFERENCES product_colors(id) ON DELETE CASCADE
> ) ENGINE=InnoDB;
>
> ALTER TABLE order_items ADD COLUMN product_color_id INT AFTER qty;
> ALTER TABLE order_items ADD COLUMN color_name VARCHAR(60) AFTER product_color_id;
> ALTER TABLE order_items ADD FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE SET NULL;
> ```

> **Para poder cargar talles**, corré esto una vez en Workbench:
> ```sql
> CREATE TABLE IF NOT EXISTS product_sizes (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   product_id INT NOT NULL,
>   size_name VARCHAR(20) NOT NULL,
>   stock INT NOT NULL DEFAULT 0,
>   sort_order INT NOT NULL DEFAULT 0,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
> ) ENGINE=InnoDB;
>
> ALTER TABLE order_items ADD COLUMN product_size_id INT AFTER color_name;
> ALTER TABLE order_items ADD COLUMN size_name VARCHAR(20) AFTER product_size_id;
> ALTER TABLE order_items ADD FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE SET NULL;
> ```

> **Para poder cargar el carrusel de imágenes de portada**, corré esto una vez en Workbench:
> ```sql
> CREATE TABLE IF NOT EXISTS hero_slides (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   image_url VARCHAR(500) NOT NULL,
>   title VARCHAR(150),
>   subtitle VARCHAR(255),
>   button_text VARCHAR(60),
>   button_link VARCHAR(255),
>   sort_order INT NOT NULL DEFAULT 0,
>   active TINYINT(1) NOT NULL DEFAULT 1,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
> ) ENGINE=InnoDB;
> ```

## 2. Preparar el entorno de Python (en VS Code)

Abrí una terminal en VS Code, parado en la carpeta del proyecto:

```bash
python -m venv venv
venv\Scripts\activate          # en Windows
# source venv/bin/activate     # en Mac/Linux
pip install -r requirements.txt
```

## 3. Conectar el servidor a tu MySQL

1. Copiá el archivo `.env.example` y renombralo a `.env`.
2. Completá los datos con los que usás en MySQL Workbench para conectarte (usuario, contraseña, host, puerto).

```
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=tu_contraseña
DB_NAME=caro_boutique
```

3. En el mismo `.env`, cambiá `SECRET_KEY` por cualquier texto largo al azar.
4. Buscá `WHATSAPP_NUMBER` en `static/js/caro.js` (arriba del todo) y poné el número real (código de país + número, sin espacios ni `+`. Ej: `5491123456789`). Con cambiarlo ahí alcanza: el botón flotante, el ícono del pie de página y los datos que Google lee de la tienda se actualizan solos.

## 4. Correr el proyecto

```bash
python app.py
```

Abrí **http://localhost:5000** en el navegador. Deberías ver el catálogo cargado desde MySQL. Al hacer un pedido, se guarda en las tablas `customers`, `orders` y `order_items` (lo podés revisar en Workbench) y después se abre WhatsApp con el resumen.

### 4.1 Ver la tienda desde el celular (mientras la probás en tu PC)

El servidor ya está configurado para escuchar en toda tu red local (`host="0.0.0.0"` en `app.py`), así que podés abrirlo desde tu celular sin necesidad de publicar la web todavía:

1. Conectá el celular al **mismo WiFi** que la computadora donde corre `python app.py`.
2. En la PC, abrí una terminal y buscá tu IP local:
   - Windows: `ipconfig` → mirá el número que dice **"Dirección IPv4"** (algo como `192.168.0.15`).
   - Mac/Linux: `ifconfig` o `ip addr` → buscá algo parecido bajo tu WiFi.
3. En el celular, abrí el navegador y entrá a `http://TU_IP:5000` (ej: `http://192.168.0.15:5000`). Para el panel admin es `http://TU_IP:5000/admin`.
4. Si no carga, es casi siempre el **Firewall de Windows** bloqueando la conexión entrante: la primera vez que corrés `python app.py`, Windows suele preguntar "¿Permitir acceso a Python en redes públicas/privadas?" — tildá **"Redes privadas"** y aceptar. Si ya lo cerraste sin permitir, buscá "Firewall de Windows Defender" → "Permitir una aplicación..." y habilitá Python ahí.

Esto solo funciona mientras la PC y el celular están en la misma red y `python app.py` sigue corriendo; no es todavía la web pública (para eso, ver sección 8).

## 5. Panel de administración (para tu prima, sin tocar código)

Andá a **http://localhost:5000/admin**.

**La primera vez**, como todavía no existe ningún administrador, te va a pedir crear la cuenta: nombre, email, usuario, contraseña y una pregunta de seguridad (para poder recuperarla si se olvida). Ese formulario solo aparece una vez — después de creado el primer usuario, siempre pide login normal.

Si se olvida la contraseña, en el login hay un link **"¿Olvidaste tu contraseña?"** que pide el usuario/mail, muestra la pregunta de seguridad, y si la respuesta es correcta deja poner una contraseña nueva.

Desde el panel puede, sin saber programar ni entrar a Workbench:
- Ver todos los productos cargados, con foto, precio y stock.
- Agregar un producto nuevo (**+ Nuevo producto**): nombre, categoría, precio, descripción y **subir la foto directamente desde su computadora o celular**. Este formulario ya no pide stock — después de crear el producto se entra directo a **Colores**, donde se cargan los colores, talles y fotos, y la cantidad de cada uno se carga después desde **Stock** (así todo el stock se maneja siempre desde un solo lugar, sin números repetidos que no coincidan).
- Editar cualquier producto (incluida la foto) desde **Editar**.
- Sacar un producto del catálogo sin borrarlo, con el botón **"Sacar del catálogo"** de cada fila (o volver a mostrarlo después con **"Reactivar"**) — útil para pausarlo temporalmente sin perder colores, talles, fotos ni el historial de pedidos. También se puede desde **Editar**, destildando "Visible en la tienda". Si en cambio se quiere borrar en serio, está el botón **Eliminar** (esto sí es definitivo).
- Ver los **pedidos** que van llegando, con el detalle de qué compró cada cliente, en la pestaña **Pedidos**.
- Ver todas las personas que se registraron en la tienda (nombre, email, teléfono, dirección, si entraron con Google/Apple o con contraseña, fecha de registro y cuántos pedidos hizo cada una) en la pestaña **Clientes**, con un buscador por nombre, email o teléfono.

Las fotos que suba quedan guardadas en `static/img/` dentro del proyecto.

MySQL Workbench sigue funcionando igual por si en algún momento necesitás vos hacer algo más avanzado directamente en la base.

## 6. Colores y galería de fotos por producto

Cada producto puede tener varios colores, y cada color puede tener varias fotos — así no hace falta cargar "Remera oversize rosa" y "Remera oversize gris" como dos productos distintos.

Desde **Editar** un producto (tiene que estar guardado primero), aparece un botón **Colores** que lleva a una pantalla donde tu prima puede, sin tocar código:
- Agregar un color nuevo: nombre (ej: "Rosa viejo"), el color del circulito, y subir una o varias fotos. El color se crea con stock 0.
- Agregar más fotos a un color que ya existe.
- Borrar una foto suelta o un color entero (con todas sus fotos).

**Importante: la cantidad de stock ya no se carga ni se edita desde Colores ni desde Talles.** Esas dos pantallas son solo para dar de alta colores/talles nuevos y editar nombre, color de circulito y fotos — la cantidad siempre se carga después desde **Stock** (sección 5), que es el único lugar donde se toca el número. Así se evita terminar con el stock cargado en varios lugares distintos sin coincidir.

Si un producto **no** tiene ningún color cargado, sigue funcionando exactamente igual que antes: una sola foto y un solo stock (cargado desde **Stock**).

De la misma manera, cada producto puede tener **talles** (S, M, L, 38, 39...), cada uno con su propio stock. Se cargan desde el botón **Talles** al lado de **Colores** (se crean con stock 0). Estos talles "sueltos" son independientes de los colores (no hay una combinación tipo "rosa talle M" con stock propio): cada dimensión tiene su stock por separado, y la tienda no deja agregar al carrito más de lo que permite el más bajo de los dos.

Si en cambio necesitás cargar **cada talle por color por separado** (por ejemplo, 2 unidades de "Rosa viejo" talle L y 1 de "Beige" talle L, cada una con su propio stock), mirá la sección **6.2** más abajo.

En la tienda, si el producto tiene colores y/o talles, al hacer click se abre una ficha con la galería de fotos, los círculos de color y los talles disponibles — al elegir cambia el stock disponible para esa combinación.

## 6.2 Talles por color (stock combinado: "2 de Rosa viejo en L, 1 de Beige en L")

Además de los talles "sueltos" de la sección 6, cada color puede tener sus **propios talles con su propio stock**, totalmente separado de los demás colores. Esto es lo que hay que usar cuando el stock real depende de la combinación color+talle (lo más común en indumentaria).

> **Para poder usar esta función**, corré esto una vez en Workbench (o usá el archivo `migracion_talles_por_color.sql` que está en la carpeta del proyecto):
> ```sql
> ALTER TABLE product_sizes
>   ADD COLUMN product_color_id INT NULL AFTER product_id,
>   ADD CONSTRAINT fk_product_sizes_color
>     FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE CASCADE;
> ```

Cómo se usa, desde **Editar producto → Colores**:
- Debajo de las fotos de cada color hay una sección **"Talles de este color"**, con un campo para agregar un talle nuevo (solo el nombre, queda con stock 0) que queda atado únicamente a ese color. La cantidad se carga después desde **Stock**.
- Una vez que un color tiene al menos un talle propio cargado, ese color pasa a venderse "por talle": el stock que se usa es el de cada talle, y el stock general del color (el de arriba) deja de tener efecto — no hace falta tocarlo ni borrarlo.
- Un color puede quedarse sin talles propios si no lo necesitás: en ese caso sigue funcionando con su stock general de siempre.
- Podés tener, en el mismo producto, un color que vende por talle (con su matriz propia) y otro color que vende con un stock único — no hace falta que todos los colores usen el mismo esquema.

En la tienda, el cliente elige primero el color y después el talle: si ese color tiene talles propios, se le muestran solo esos (con el stock real de esa combinación); si no, se le muestran los talles "sueltos" del producto (sección 6), igual que antes.

En el panel **Stock** (sección 5), cuando un color tiene talles propios, sus talles aparecen agrupados visualmente debajo del nombre de ese color, en vez de mezclarse con los demás campos de stock del producto.

## 6.1 Carrusel de imágenes en la portada

Desde el panel, en el menú **Portada**, tu prima puede cargar varias imágenes para la sección "Moda que te representa" (arriba de todo en la home), cada una con un título, texto y botón opcionales (por si quiere anunciar una promo o colección con su propio link). En la tienda cambian solas cada pocos segundos, y la persona también las puede pasar con las flechas, los puntitos de abajo, o deslizando el dedo en el celular.

Si no cargó ninguna imagen, la portada se ve exactamente igual que ahora (el texto fijo "Moda que te representa" sobre el fondo rosado).

> **Para poder recuperar la contraseña por mail**, corré esto una vez en Workbench:
> ```sql
> ALTER TABLE customers ADD COLUMN reset_token VARCHAR(100) AFTER oauth_id;
> ALTER TABLE customers ADD COLUMN reset_token_expires DATETIME AFTER reset_token;
> ```

> **Para poder cobrar con Mercado Pago**, corré esto una vez en Workbench:
> ```sql
> ALTER TABLE orders ADD COLUMN mp_preference_id VARCHAR(100) AFTER delivery_address;
> ALTER TABLE orders ADD COLUMN mp_payment_id VARCHAR(100) AFTER mp_preference_id;
> ```

## 6.3 Subcategorías (remeras, pantalones, botas, carteras... una lista por categoría)

Para que el cliente no tenga que ver toda una categoría junta para encontrar, por ejemplo, una remera puntual, cada producto puede tener además una subcategoría — y a diferencia de antes, ahora **las tres categorías** (Indumentaria, Calzado, Accesorios) pueden tener su propia lista, armada y editada por tu prima desde el panel, sin tocar código.

> **Para poder usar esta función**, corré esto una vez en Workbench (o usá el archivo `migracion_subcategorias_admin.sql` de la carpeta del proyecto):
> ```sql
> CREATE TABLE IF NOT EXISTS subcategories (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   category ENUM('indumentaria','calzado','accesorios') NOT NULL,
>   name VARCHAR(60) NOT NULL,
>   slug VARCHAR(60) NOT NULL,
>   sort_order INT NOT NULL DEFAULT 0,
>   active TINYINT(1) NOT NULL DEFAULT 1,
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   UNIQUE KEY uq_subcategories_category_slug (category, slug)
> ) ENGINE=InnoDB;
> ```
> (Si ya habías corrido la migración vieja `migracion_subcategorias.sql`, no hace falta nada más: la columna `products.subcategory` es la misma de antes, esta migración solo agrega la tabla nueva con la lista editable, y de yapa carga las 8 subcategorías de Indumentaria que ya venían fijas — Remeras, Pantalones, Buzos y hoodies, Camperas, Vestidos, Polleras, Shorts, Otros — para que los productos que ya las tenían puestas no pierdan nada.)

Cómo se usa:
- **Menú "Subcategorías"** en el panel: ahí tu prima arma la lista de cada categoría (por ejemplo "Botas", "Sandalias", "Zapatillas" para Calzado, o "Carteras", "Cinturones", "Bijou" para Accesorios), y puede ocultar o eliminar las que no use.
- Desde **Editar producto** (o al crear uno nuevo), el campo **"Subcategoría"** siempre aparece, y sus opciones cambian solas según la categoría elegida (usa la lista que se cargó en el paso anterior).
- Es opcional: si lo dejás en "Sin especificar", el producto sigue apareciendo en su categoría como siempre, simplemente no aparece al filtrar por un tipo puntual.
- En la tienda, al elegir cualquiera de las tres categorías aparece una fila extra de botones con las subcategorías cargadas para esa categoría (y "Todas"), para acotar la búsqueda. Si esa categoría no tiene ninguna subcategoría cargada, esa fila no aparece.

## 6.4 Varias fotos por producto (frente, espalda, detalle)

Todas las fotos de un producto (frente, espalda, detalle) se cargan por color, desde **Colores** (sección 6): a cada color se le pueden subir varias fotos, no solo una.

Antes existía además una tarjeta aparte en **Editar producto** ("Fotos extra") para subir fotos generales sin color. Se sacó esa tarjeta del formulario para no tener dos lugares distintos donde cargar fotos — ahora todo se hace desde **Colores**. Si algún producto viejo ya tenía fotos cargadas ahí, se siguen mostrando en la tienda igual que antes (y en **Editar producto** todavía se pueden borrar si hace falta), pero ya no se pueden agregar fotos nuevas por ese lado.

En la tienda:
- En el catálogo, si un color tiene 2 o más fotos cargadas, al pasar el mouse por encima de la tarjeta del producto la foto cambia suavemente a la segunda foto de ese color (por ejemplo, mostrando la espalda de la prenda) — no hace falta nada más para que esto funcione, alcanza con cargar 2 fotos en el primer color.
- En la ficha de detalle (al hacer click en el producto), todas las fotos del color elegido aparecen en la galería para poder verlas una por una.

## 7. Cuentas de cliente (obligatorio para comprar)

Ahora, para poder finalizar una compra, la persona tiene que tener una cuenta. Si no la tiene, al tocar "Finalizar compra" la mandamos a `/login`, donde puede:
- Crear cuenta con nombre, mail y contraseña (`/register`), o
- Iniciar sesión si ya tiene cuenta (`/login`), o
- Entrar con Google o con Apple, si los configuraste (ver más abajo). Si no los configuraste, esos botones directamente no aparecen y el login por mail funciona igual.

Esto es aparte del panel de `/admin` (que sigue siendo solo para tu prima).

### Activar "Continuar con Google"

1. Andá a [Google Cloud Console](https://console.cloud.google.com/) → creá un proyecto (o usá uno existente).
2. **APIs y servicios → Pantalla de consentimiento OAuth**: completá los datos básicos (nombre de la app, mail de soporte) y publicala.
3. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**, tipo **Aplicación web**.
4. En **URIs de redireccionamiento autorizados** agregá:
   - `http://localhost:5000/auth/google/callback` (para probar en tu compu)
   - `https://tu-dominio.com/auth/google/callback` (cuando publiques la web)
5. Te da un **Client ID** y un **Client secret**: pegalos en `.env` como `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.
6. Reiniciá `python app.py`. El botón de Google va a aparecer solo en `/login` y `/register`.

### Activar "Continuar con Apple"

Esto requiere que tu prima (o quien publique la app) tenga una cuenta de **Apple Developer Program** (u$s99/año) — es un requisito de Apple, no algo que se pueda evitar desde el código.

1. En [developer.apple.com](https://developer.apple.com/account) → **Certificates, Identifiers & Profiles**.
2. Creá un **App ID** (si no tenés uno) y activale la capacidad **Sign in with Apple**.
3. Creá un **Services ID** (ej: `com.caroboutique.web`) — ese valor va en `APPLE_CLIENT_ID`. Ahí mismo configurá los dominios y el **Return URL**: `https://tu-dominio.com/auth/apple/callback` (Apple no acepta `localhost`, para probar necesitás un dominio real o un túnel tipo ngrok).
4. Anotá tu **Team ID** (arriba a la derecha en el portal) → `APPLE_TEAM_ID`.
5. **Keys → Crear una key** con "Sign in with Apple" habilitado. Descargá el archivo `.p8` (**solo se puede descargar una vez**) y anotá el **Key ID** → `APPLE_KEY_ID`.
6. Abrí el archivo `.p8` con un editor de texto y pegá todo su contenido (con los `-----BEGIN PRIVATE KEY-----` y `-----END PRIVATE KEY-----`) en `APPLE_PRIVATE_KEY` dentro de `.env`, reemplazando los saltos de línea por `\n` si tu `.env` no admite líneas múltiples.
7. Reiniciá `python app.py`. El botón de Apple aparece solo si las 4 variables están completas.

Si en algún momento estas variables faltan o están mal, ese botón de login simplemente no se muestra (o avisa "no está configurado" si se llega a tocar el link directo) — nunca rompe el resto de la web.

### Activar "Olvidé mi contraseña" (recuperar por mail)

Si un cliente se olvida la contraseña, en `/login` hay un link **"¿Olvidaste tu contraseña?"** que le manda un mail con un link para poner una nueva (vale por 1 hora). Para que esto funcione hace falta una cuenta de mail que pueda mandar correos por SMTP — lo más simple es usar un Gmail:

1. Andá a tu cuenta de Google → **Seguridad** → activá la **verificación en dos pasos** (es requisito para el paso siguiente).
2. Buscá **Contraseñas de aplicaciones** (o entrá directo a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)) y generá una para "Correo".
3. En `.env` completá:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=tu-cuenta@gmail.com
   SMTP_PASSWORD=la-contraseña-de-aplicación-de-16-letras
   SMTP_FROM=tu-cuenta@gmail.com
   ```
4. Reiniciá `python app.py`.

Si no completás estas variables, al tocar "¿Olvidaste tu contraseña?" el sistema avisa que el envío de mails no está configurado todavía (en vez de romperse) — mientras tanto, si un cliente queda trabado, se puede contactar por WhatsApp para resolverlo a mano.

## 8. Publicar la web en internet

Cuando esté probada localmente, hay que subirla a un hosting que soporte Python + MySQL. Opciones típicas:
- **PythonAnywhere**: tiene plan gratis, soporta Flask y MySQL, fácil para arrancar.
- **Railway** o **Render**: gratis/económico, corren Flask y ofrecen MySQL o Postgres administrado.
- Hosting compartido con cPanel (muy común en Argentina): soporta MySQL, pero Flask requiere que el hosting permita Python (no todos lo hacen — conviene confirmar antes).

Podemos ver el paso a paso de despliegue cuando lleguemos a esa etapa.

## 9. Cobro online con Mercado Pago

Cuando el cliente elige **Mercado Pago** como método de pago en el checkout, si esta función está configurada, en vez de derivarlo a WhatsApp lo mandamos directo al checkout alojado por Mercado Pago (Checkout Pro) para que pague con tarjeta, dinero en cuenta, etc. Cuando el pago se aprueba, el pedido pasa solo a estado **"pagado"** en el panel — no hace falta que tu prima lo cambie a mano.

Si Mercado Pago **no** está configurado, "Mercado Pago" sigue apareciendo como opción, pero el pedido se avisa por WhatsApp igual que con transferencia o efectivo — nada se rompe.

### Conseguir el access token

1. Entrá a [mercadopago.com.ar](https://www.mercadopago.com.ar/) con la cuenta de tu prima (o creá una).
2. Andá a **Tu negocio → Configuración → Credenciales** (o directo a [mercadopago.com.ar/developers/panel](https://www.mercadopago.com.ar/developers/panel)).
3. Copiá el **Access Token de producción** (para probar sin cobrar de verdad, usá el de **prueba**, que aparece en la misma pantalla junto con usuarios de prueba compradores/vendedores).
4. Pegalo en `.env`:
   ```
   MP_ACCESS_TOKEN=el-access-token-que-copiaste
   ```
5. Reiniciá `python app.py`.

### Sobre las notificaciones (webhook)

Mercado Pago avisa que un pago se acreditó llamando a `https://tu-dominio.com/webhooks/mercadopago`. Esa URL tiene que ser accesible desde internet, así que:
- **En tu compu local no va a llegar sola** — Mercado Pago no puede llamar a `localhost`. Para probar el webhook en tu compu podés usar una herramienta como [ngrok](https://ngrok.com/) para exponerla temporalmente.
- **Una vez publicada la web** (ver sección 8), el webhook funciona solo, sin nada más que configurar.
- Aunque el webhook no llegue a andar (por ejemplo mientras probás en local), el pago igual se procesa en Mercado Pago y el cliente ve la pantalla de éxito/pendiente/error al volver — lo único que no se actualiza solo es el estado del pedido en el panel, que tu prima puede cambiar a mano igual que antes.

### Qué pasa si el pago falla o queda pendiente

El pedido siempre queda guardado (con el stock ya descontado) apenas el cliente confirma el checkout. Si el pago se rechaza, el pedido pasa a "cancelado" automáticamente (y convendría reponer el stock a mano desde el panel); si queda pendiente (por ejemplo, pago en efectivo tipo Rapipago), sigue en "pendiente" hasta que se acredite.

## 10. Elegir qué medios de pago acepta la tienda

Desde el panel, en **Medios de pago**, tu prima puede prender o apagar cada opción que aparece en el checkout: Efectivo contra entrega, Transferencia bancaria, Tarjeta de crédito, Tarjeta de débito, y Mercado Pago (dinero en cuenta). También puede escribir qué tarjetas acepta (ej: "Visa, Mastercard, Naranja, Cabal") para que se muestre como cartel informativo antes de pagar — ese texto es solo para que el cliente lo vea, no cambia qué tarjetas funcionan de verdad (eso lo define Mercado Pago según la cuenta de tu prima).

> **Para poder elegir los medios de pago**, corré esto una vez en Workbench:
> ```sql
> CREATE TABLE IF NOT EXISTS payment_settings (
>   id INT PRIMARY KEY DEFAULT 1,
>   efectivo TINYINT(1) NOT NULL DEFAULT 1,
>   transferencia TINYINT(1) NOT NULL DEFAULT 1,
>   tarjeta_credito TINYINT(1) NOT NULL DEFAULT 1,
>   tarjeta_debito TINYINT(1) NOT NULL DEFAULT 1,
>   mercado_pago TINYINT(1) NOT NULL DEFAULT 1,
>   tarjetas_aceptadas VARCHAR(255)
> ) ENGINE=InnoDB;
> INSERT IGNORE INTO payment_settings (id) VALUES (1);
> ```

### Cómo funciona cada medio de pago

- **Efectivo** (sirve tanto para pagar al recibir el envío como al retirar en el local) y **Transferencia bancaria**: igual que siempre, el pedido se guarda y se avisa por WhatsApp para que tu prima coordine el pago a mano (le pasa el CBU/alias por ese medio si es transferencia).
- **Mercado Pago (dinero en cuenta)**: va al checkout alojado por Mercado Pago (el mismo de la sección 9) — se lleva al cliente a mercadopago.com.ar a pagar con su saldo o sus tarjetas guardadas.
- **Tarjeta de crédito / débito**: si configuraste `MP_PUBLIC_KEY` (ver 10.1), el formulario de tarjeta (número, titular, vencimiento, código de seguridad) aparece **integrado en la misma página del checkout**, sin redirigir a ningún lado — igual que en Tiendanube, Mercado Libre, etc. Si todavía no configuraste esa clave, esta opción cae al mismo checkout redirigido de Mercado Pago mientras tanto.
- **Esta web nunca ve ni guarda el número de tarjeta ni el código de seguridad**, ni siquiera con el formulario integrado: esos campos los renderiza directamente el código de Mercado Pago dentro de la página, y el número se convierte en un token seguro en el navegador del cliente antes de llegarnos — nuestro servidor solo recibe ese token, nunca la tarjeta real. Es importante que sea así: una tienda armada a medida como esta no cumple (ni puede cumplir fácilmente) con las normas de seguridad que exigen las tarjetas para manejar esos datos directamente (se llama PCI-DSS), así que pedirlos en un formulario propio sin este mecanismo sería un riesgo real de robo de datos para tus clientes y de estafas para la tienda.
- Cuando el pago por tarjeta o Mercado Pago se acredita, el cliente recibe un mail con el comprobante de la compra, y tu prima recibe otro mail avisándole que se vendió algo (con los datos del cliente para contactarlo por mail o WhatsApp). Estos mails necesitan que el SMTP esté configurado (ver sección 7, "Olvidé mi contraseña") — si no está configurado, no se manda el mail pero el pago se procesa igual.
- El mail de aviso de venta le llega a la cuenta de mail con la que tu prima creó su usuario de administrador (la que completó en `/admin/setup`).

### 10.1 Formulario de tarjeta integrado (sin redirigir a Mercado Pago)

1. Entrá a [mercadopago.com.ar/developers/panel](https://www.mercadopago.com.ar/developers/panel/credentials) (misma pantalla de la sección 9).
2. Copiá la **Public Key** (no el Access Token, es la otra clave de esa misma pantalla — esta sí es segura de exponer en el navegador).
3. Pegala en `.env`:
   ```
   MP_PUBLIC_KEY=la-public-key-que-copiaste
   ```
4. Reiniciá `python app.py`. La próxima vez que un cliente elija "Tarjeta de crédito o débito", los campos van a aparecer ahí mismo en el checkout.

Si no la configurás, no pasa nada malo: esa opción sigue funcionando, solo que redirige a Mercado Pago en vez de mostrar el formulario integrado.

## 11. Conjuntos (looks armados con productos que ya tenés cargados)

Permite agrupar 2 o más productos que ya existen en el catálogo (por ejemplo una remera + un pantalón) para mostrarlos juntos en la tienda, en la sección **"Armá tu look"** (aparece automáticamente arriba del catálogo, y se oculta sola si no hay ningún conjunto cargado).

**Importante:** cada producto del conjunto mantiene su propio precio y su propio stock — el conjunto no es un producto nuevo ni tiene su propio stock. Es solo una forma de mostrarlos combinados y agregarlos todos al carrito de una.

1. Corré la migración una sola vez en Workbench: abrí `migracion_conjuntos.sql` (en la carpeta del proyecto) y ejecutalo sobre la base `caro_boutique`.
2. En el panel admin, entrá a **Conjuntos → + Nuevo conjunto**.
3. Ponele un nombre (ej: "Look de oficina"), una descripción opcional, y elegí 2 o más productos activos de la lista.
4. Opcional: subí una foto propia para el conjunto. Si no subís ninguna, en la tienda se usa la foto del primer producto.
5. Guardá. El conjunto aparece enseguida en la tienda (si está tildado "Visible").

En la tienda, el cliente ve cada conjunto con las fotos de sus productos, el precio total, y un botón **"Agregar conjunto al carrito"**:
- Los productos que **no** tienen colores ni talles cargados se agregan directo al carrito.
- Los que **sí** tienen colores o talles (hay que elegir cuál) se abren automáticamente en su ficha (como si el cliente hubiera tocado ese producto en el catálogo) para que elija color/talle ahí mismo; si hay más de uno pendiente, después de elegir el primero se abre el siguiente solo, hasta terminar con todos.

Si un producto de un conjunto se pausa o se borra, el conjunto deja de mostrar ese producto; si quedan menos de 2 productos activos, el conjunto entero se oculta solo (no hace falta borrarlo a mano).

### 11.1 Precio especial para el conjunto

Si querés vender el look más barato que comprando cada prenda por separado, podés cargarle un precio especial al conjunto entero.

1. Corré `migracion_precio_conjunto.sql` una sola vez en Workbench (agrega la columna `discount_price` a `product_sets`).
2. En **Conjuntos → Editar** (o al crear uno nuevo), completá "Precio especial del conjunto" con el precio final que querés cobrar. Dejalo vacío para que se cobre la suma normal de los productos, sin ningún descuento.
3. En la tienda, el conjunto se muestra con la suma normal tachada y el precio especial al lado.
4. Al agregar el conjunto al carrito, el descuento se reparte proporcionalmente entre todos sus productos (según el precio de catálogo de cada uno), así la suma de lo que queda en el carrito da exactamente el precio especial — tanto para los productos que se agregan directo como para los que necesitan elegir color/talle.

## 12. Reseñas de clientes

Los clientes que compraron (o no) pueden dejar una calificación de 1 a 5 estrellas y un comentario opcional en la ficha de cada producto. Solo se puede dejar una reseña por cliente y por producto — si vuelve a puntuar, se actualiza la que ya tenía en vez de crear otra.

1. Corré `migracion_funciones_nuevas.sql` una sola vez en Workbench (crea, entre otras, la tabla `product_reviews`).
2. Listo, no hay nada más que configurar. En la ficha del producto aparece el promedio de estrellas, la cantidad de reseñas, y el formulario para dejar la propia (pide haber iniciado sesión).
3. Si el cliente que reseñó tiene un pedido con ese producto, se le muestra el sello **"Compra verificada"**.
4. En el panel admin, **Reseñas** lista todas las reseñas de todos los productos con un botón para borrar la que haga falta (comentarios inapropiados, spam, etc.).

## 13. Cupones de descuento

Códigos que el cliente carga en el checkout para un % extra de descuento sobre el total de la compra (además del descuento que ya pueda tener cada producto).

1. Corré `migracion_funciones_nuevas.sql` una sola vez en Workbench (crea la tabla `coupons` y agrega `coupon_code`/`discount_amount` a `orders`).
2. En el panel admin, **Cupones → + Nuevo cupón**: código (ej: `BIENVENIDA10`), % de descuento, vencimiento opcional y límite de usos opcional.
3. En el checkout, el cliente escribe el código antes de confirmar el pedido; si es válido, ve el descuento aplicado al total antes de pagar.
4. El cupón se valida también en el servidor al confirmar el pedido (no solo al mostrarlo), así nadie puede aplicar un cupón vencido o agotado editando la página. El total con descuento es el que efectivamente se cobra, tanto por WhatsApp/transferencia como por Mercado Pago o tarjeta.
5. Desde **Cupones** podés desactivar o eliminar un código en cualquier momento.

## 14. Avisame cuando haya stock

Cuando un producto (o una combinación de color/talle puntual) está agotado, en vez del botón "Agregar al carrito" aparece un formulario para dejar el mail. Apenas la dueña carga stock de nuevo para esa combinación puntual, se le manda un mail automático al cliente avisándole (una sola vez).

1. Corré `migracion_funciones_nuevas.sql` una sola vez en Workbench (crea la tabla `stock_notify_requests`).
2. Necesita el envío de mails configurado (ver sección de recuperar contraseña / `.env`: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`). Si no está configurado, el cliente puede dejar igual su mail, pero no se manda el aviso hasta que actives el SMTP.
3. No hay nada que configurar en el panel: funciona automáticamente cada vez que se actualiza el stock de un producto, color o talle desde **Stock**, **Colores**, **Talles** o el formulario de edición del producto.

## 15. Alerta de stock bajo a la dueña

Cada vez que una venta hace que el stock de un producto (o de una combinación color/talle) baje a 3 unidades o menos, se le manda un mail automático a la cuenta de administrador avisando qué se está por agotar. El aviso se manda una sola vez por cada vez que cruza ese umbral (no en cada venta mientras se mantiene bajo). Este mail interno es automático para todos los productos, no depende del aviso visual de abajo.

- Necesita el envío de mails configurado (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` en `.env`). Sin eso, no se manda el mail pero tampoco rompe nada.
- El umbral (3 unidades) se puede cambiar editando `LOW_STOCK_THRESHOLD` en `app.py`.

**Aviso "¡Últimas unidades!" al cliente (opcional, producto por producto).** A diferencia del mail interno de arriba, este aviso visual en la tienda es opt-in: viene destildado por default en todos los productos, para no mostrarlo en toda la vidriera con negocios que suelen manejar poco stock. Se activa desde **Editar producto** (o al crear uno nuevo), tildando la casilla "Mostrar aviso '¡Últimas unidades!'...". Solo en los productos donde esté tildada aparece el cartelito cuando el stock baja al umbral de `LOW_STOCK_THRESHOLD` (mismo valor de arriba, también ajustable en `static/js/caro.js`).

> **Para poder usar esta casilla**, corré esto una vez en Workbench (o usá el archivo `migracion_aviso_stock_bajo.sql` de la carpeta del proyecto):
> ```sql
> ALTER TABLE products ADD COLUMN show_low_stock_badge TINYINT(1) NOT NULL DEFAULT 0 AFTER active;
> ```

## 16. Exportar a PDF (Pedidos, Stock, Caja, Reportes, Estadísticas)

En varias secciones del panel admin hay un botón **"⬇ Exportar a PDF"** que descarga un archivo `.pdf` prolijo (sin fotos de productos) con los datos que se están viendo en pantalla:

- **Pedidos**: después de elegir un período, exporta el detalle de cada pedido y sus productos (color, talle, cantidad, entrega, medio de pago, estado y total).
- **Stock**: después de elegir una categoría o buscar, exporta una tabla con el nombre del producto, categoría, color, talle y cantidad de cada variante — sin las fotos.
- **Caja**: con la caja abierta, exporta los totales del turno (monto inicial, ventas en efectivo, ventas con otro medio, gastos, efectivo esperado) más el detalle de ventas y gastos de esa caja.
- **Reportes (Ganancias y gastos)**: después de elegir un período, exporta ventas online, ventas presenciales, gastos, costo de mercadería y resultado.
- **Estadísticas**: exporta ingresos totales, pedidos por estado, top 5 productos más vendidos y ventas por mes.

- Necesita la librería `reportlab` instalada (ya está en `requirements.txt` — si el entorno es viejo, correr `pip install -r requirements.txt` de nuevo).
- No requiere ninguna migración de base de datos.

## 17. Costo de envío real (zonas configurables)

Reemplaza la vista previa de "Transportista" (que no cobraba nada real) por zonas de envío con un precio de verdad, que se le cobra al cliente en el checkout.

1. Corré `migracion_envios.sql` una sola vez en Workbench (crea la tabla `shipping_zones` si todavía no existe, y agrega `shipping_zone`/`shipping_cost` a `orders`).
2. En el panel admin, entrá a **Envíos → + Nueva zona**: nombre (ej: "CABA", "GBA", "Interior del país"), precio, y opcionalmente un monto de "envío gratis a partir de" (dejalo vacío si esa zona nunca es gratis).
3. En el checkout, cuando el cliente elige "Envío a domicilio", ve las zonas activas con su precio real (o "Gratis" si ya llegó al mínimo de esa zona) y elige una antes de confirmar.
4. El costo de envío se suma al total que se cobra de verdad (WhatsApp, transferencia, Mercado Pago y tarjeta), validado siempre en el servidor — nunca se confía en un precio que mande el navegador.
5. Mientras no haya ninguna zona activa cargada, el checkout no muestra ninguna opción de envío y se sigue coordinando el costo por WhatsApp como antes (no rompe nada si todavía no cargaste zonas).

## 18. Seguinos en Instagram

En la tienda aparece una sección **"Seguinos en Instagram"** (arriba del pie de página) y el ícono de Instagram del pie de página, ambos apuntando al perfil de Instagram real.

- Para cambiar el link, editá la constante `INSTAGRAM_URL` al principio de `static/js/caro.js` (junto a `WHATSAPP_NUMBER`) y poné la URL de tu perfil real (ej: `https://instagram.com/tu_usuario`).
- No trae publicaciones automáticamente (eso requeriría conectar una cuenta de Instagram Business con la API de Meta, que no está disponible sin esas credenciales) — es un link directo al perfil para que el cliente entre a verlo.

## 19. Caja — ventas presenciales en el local

Además de la tienda online, el panel ahora tiene un sistema de gestión simple para cuando tu prima vende en persona (en el local o donde sea), en el menú **Caja**.

> **Para poder usar esta función**, corré esto una vez en Workbench (o usá el archivo `migracion_caja.sql` de la carpeta del proyecto):
> ```sql
> ALTER TABLE products ADD COLUMN cost_price DECIMAL(10,2) NULL AFTER discount_percent;
>
> CREATE TABLE IF NOT EXISTS cash_registers (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   opening_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
>   closed_at TIMESTAMP NULL,
>   closing_amount DECIMAL(10,2),
>   expected_amount DECIMAL(10,2),
>   difference DECIMAL(10,2),
>   notes VARCHAR(255),
>   status ENUM('abierta','cerrada') NOT NULL DEFAULT 'abierta'
> ) ENGINE=InnoDB;
>
> CREATE TABLE IF NOT EXISTS pos_sales (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   cash_register_id INT NOT NULL,
>   total DECIMAL(10,2) NOT NULL,
>   payment_method VARCHAR(50) NOT NULL DEFAULT 'Efectivo',
>   customer_name VARCHAR(150),
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id)
> ) ENGINE=InnoDB;
>
> CREATE TABLE IF NOT EXISTS pos_sale_items (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   sale_id INT NOT NULL,
>   product_id INT,
>   product_name VARCHAR(150) NOT NULL,
>   unit_price DECIMAL(10,2) NOT NULL,
>   qty INT NOT NULL CHECK (qty > 0),
>   product_color_id INT,
>   color_name VARCHAR(60),
>   product_size_id INT,
>   size_name VARCHAR(20),
>   FOREIGN KEY (sale_id) REFERENCES pos_sales(id) ON DELETE CASCADE,
>   FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
>   FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE SET NULL,
>   FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE SET NULL
> ) ENGINE=InnoDB;
>
> CREATE TABLE IF NOT EXISTS cash_expenses (
>   id INT AUTO_INCREMENT PRIMARY KEY,
>   cash_register_id INT,
>   category VARCHAR(60) NOT NULL DEFAULT 'Otro',
>   description VARCHAR(255),
>   amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
>   created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
>   FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id) ON DELETE SET NULL
> ) ENGINE=InnoDB;
> ```
>
> Y para el código de barras (o usá `migracion_codigo_barras.sql`):
> ```sql
> ALTER TABLE products ADD COLUMN barcode VARCHAR(64) NULL AFTER cost_price;
> ALTER TABLE products ADD UNIQUE KEY uq_products_barcode (barcode);
> ```
>
> Y para poder cancelar ventas (o usá `migracion_cancelar_venta.sql`):
> ```sql
> ALTER TABLE pos_sales ADD COLUMN status ENUM('completada','cancelada') NOT NULL DEFAULT 'completada' AFTER customer_name;
> ```

Cómo funciona:

- **Abrir caja**: antes de cargar cualquier venta presencial hay que abrir la caja con el monto inicial (el efectivo con el que arranca el día). Mientras esté abierta, todas las ventas y gastos que se carguen quedan asociados a ella.
- **Nueva venta**: al entrar ya se ven todos los productos activos en una lista (no hace falta escribir nada), y arriba hay un buscador para filtrar por nombre. Elegís color/talle si el producto tiene, y se arma una lista con los productos de esa venta (como un carrito). El stock se descuenta exactamente igual que en una compra online — un producto que se vende en el local ya no aparece disponible en la web, y viceversa, porque ambos usan el mismo stock. Al confirmar, se genera un **ticket** (comprobante no fiscal) que se puede imprimir con el botón "Imprimir (cliente + local)" — funciona con cualquier impresora conectada a la computadora a través del diálogo de impresión del navegador (no hace falta un driver especial, pero si tu prima tiene una impresora térmica de tickets, anda probando el ancho de papel en la vista previa de impresión).
- **Dos copias por venta**: cada vez que se imprime un ticket salen dos copias iguales, una atrás de la otra, cada una en su propia hoja: la primera es para el cliente y la segunda para tu prima (control interno). Es así para cualquier medio de pago (efectivo, transferencia, Mercado Pago o tarjeta).
- **Pago con tarjeta**: como no hay una integración con un posnet real, si el medio de pago elegido es "Tarjeta de débito" o "Tarjeta de crédito", solo la segunda copia (la del local) agrega al final un espacio para completar a mano **Firma, Aclaración y DNI** — a modo de cupón manual, para tener respaldo de esa venta. La copia del cliente nunca pide firma.
- El diseño del ticket es todavía una versión de prueba (solo el nombre "Vua Showroom" arriba) — en cuanto tu prima me pase el CUIT, la dirección y el teléfono del local, se los agrego para que quede como un comprobante más completo.
- **Código de barras / lectora**: en **Editar producto** hay un campo opcional "Código de barras / SKU". Si lo cargás, en "Nueva venta" alcanza con escanearlo con una lectora de código de barras (o escribirlo a mano y apretar Enter): si hay un solo producto con ese código, se agrega directo a la venta (o se abre el selector de color/talle si tiene). Requiere correr `migracion_codigo_barras.sql` una vez (ver abajo).
- **Cancelar una venta**: si se cargó una venta por error, en la lista "Ventas de esta caja" cada venta tiene un botón **"Cancelar"** (pide confirmación). Al cancelarla, el stock que se había descontado se devuelve automáticamente (al producto, color o talle exacto que correspondía) y la venta pasa a figurar tachada con la etiqueta "Cancelada" — no se borra, para que quede el rastro de que existió y se anuló. Las ventas canceladas no suman en los totales de la caja (efectivo esperado) ni en Reportes. El ticket de una venta cancelada también muestra el aviso "VENTA CANCELADA" si se lo vuelve a abrir. Requiere correr `migracion_cancelar_venta.sql` una vez (ver arriba).
- **Gastos**: se pueden registrar gastos (proveedores, servicios, sueldos, alquiler, otros) en cualquier momento, estén o no con la caja abierta.
- **Cerrar caja**: al final del día (o del turno), se cuenta el efectivo real y se carga en "Cerrar caja". El sistema calcula solo cuánto debería haber (monto inicial + ventas en efectivo - gastos) y muestra la diferencia contra lo contado, para detectar rápido si falta o sobra plata.
- **Historial de caja**: lista de todas las cajas abiertas y cerradas, con sus montos y diferencias.
- **Reportes**: en el menú **Reportes**, junta las ventas online y las presenciales de un período (hoy/semana/mes/rango de fechas) y les resta los gastos, mostrando un resultado final. Si además se carga el **"Precio de costo"** de cada producto (campo opcional en Editar producto, no lo ve el cliente), el reporte también descuenta el costo de la mercadería vendida para mostrar una ganancia real, no solo lo facturado — si falta cargar el costo de algún producto, el reporte avisa que el número es una estimación incompleta.
- **Facturación fiscal**: esto no emite factura válida ante AFIP (eso requiere un facturador electrónico habilitado, que es un trámite aparte) — es solo un comprobante interno para el cliente y para el control del negocio.
