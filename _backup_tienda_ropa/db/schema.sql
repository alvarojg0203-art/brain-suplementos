CREATE DATABASE IF NOT EXISTS caro_boutique
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE caro_boutique;

-- ---------------------------------------------------------
-- TABLA: admins (usuarios que pueden entrar al panel /admin)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  email VARCHAR(150) NOT NULL UNIQUE,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  security_question VARCHAR(255) NOT NULL,
  security_answer_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: products (catálogo)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  category ENUM('indumentaria','calzado','accesorios') NOT NULL,
  -- subcategory: tipo de producto dentro de su categoría (ej: "remeras"
  -- dentro de indumentaria, "botas" dentro de calzado), para que el
  -- cliente pueda filtrar más puntual en vez de ver toda la categoría
  -- junta. Guarda el slug de una fila de la tabla subcategories. NULL si
  -- el producto no tiene subcategoría cargada.
  subcategory VARCHAR(50) NULL,
  price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
  discount_percent DECIMAL(5,2) NULL,    -- si tiene valor (1 a 99), es el % off sobre price. Ej: 20 = 20% de descuento
  cost_price DECIMAL(10,2) NULL,         -- precio de costo (opcional): si se carga, permite calcular ganancia real en Caja/Reportes
  barcode VARCHAR(64) NULL,               -- código de barras/SKU (opcional): para escanear con lectora en Caja
  stock INT NOT NULL DEFAULT 0,
  image_url VARCHAR(500),
  description TEXT,
  active TINYINT(1) NOT NULL DEFAULT 1,
  -- show_low_stock_badge: apagado (0) por default. Si se tilda para un
  -- producto puntual, la tienda le muestra "¡Últimas unidades!" cuando le
  -- queda poco stock. Al ser opt-in, no aparece en todo el catálogo.
  show_low_stock_badge TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_products_category (category),
  INDEX idx_products_active (active),
  UNIQUE KEY uq_products_barcode (barcode)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_colors (variantes de color de un producto)
-- Si un producto no tiene filas acá, se vende con su foto y stock
-- normales (products.image_url / products.stock). Si tiene una o más
-- filas, cada color maneja su propio stock y su propia galería de fotos
-- (product_color_images).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_colors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  color_name VARCHAR(60) NOT NULL,
  color_hex VARCHAR(7) NOT NULL DEFAULT '#cccccc',   -- para pintar el circulito de color
  stock INT NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_color_images (galería de fotos de cada color)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_color_images (
  id INT AUTO_INCREMENT PRIMARY KEY,
  color_id INT NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (color_id) REFERENCES product_colors(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_images (fotos extra de un producto, ej: frente y
-- espalda de una prenda). Es independiente de los colores: sirve para
-- productos que no tienen colores cargados, o como fotos generales del
-- producto además de las de cada color. products.image_url sigue siendo
-- la que se usa de tapa en el catálogo; estas son adicionales, para la
-- galería del detalle.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_images (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_sizes (talles de un producto, ej: S, M, L, 38, 39...)
-- Igual que los colores: si un producto no tiene talles cargados, se
-- vende con su stock normal (products.stock).
--
-- product_color_id (opcional): si un talle pertenece a un color en
-- particular (ej: "Talle L" del color "Rosa viejo"), acá va el id de ese
-- color, y el stock de esa fila es el de ESA combinación color+talle
-- exacta (no se suma ni se comparte con otros colores). Si es NULL, el
-- talle es del producto en general, sin distinguir color.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_sizes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  product_color_id INT NULL,
  size_name VARCHAR(20) NOT NULL,
  stock INT NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: hero_slides (imágenes del carrusel de portada). Si no hay
-- ninguna fila activa, la portada muestra el texto fijo de siempre (sin
-- foto de fondo).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS hero_slides (
  id INT AUTO_INCREMENT PRIMARY KEY,
  image_url VARCHAR(500) NOT NULL,
  title VARCHAR(150),
  subtitle VARCHAR(255),
  button_text VARCHAR(60),
  button_link VARCHAR(255),
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: customers (clientes con cuenta propia para comprar)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  phone VARCHAR(30),
  email VARCHAR(150) UNIQUE,
  address VARCHAR(255),
  password_hash VARCHAR(255),                          -- null si se registró con Google/Apple
  auth_provider ENUM('local','google','apple') NOT NULL DEFAULT 'local',
  oauth_id VARCHAR(255),                                -- id que da Google/Apple para esa cuenta
  reset_token VARCHAR(100),                             -- token temporal para "olvidé mi contraseña"
  reset_token_expires DATETIME,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_customers_oauth (auth_provider, oauth_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: orders (pedidos)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  status ENUM('pendiente','pagado','enviado','entregado','cancelado') NOT NULL DEFAULT 'pendiente',
  total DECIMAL(10,2) NOT NULL CHECK (total >= 0),
  payment_method VARCHAR(50),
  delivery_method VARCHAR(50),
  delivery_address VARCHAR(255),
  mp_preference_id VARCHAR(100),   -- id de la preferencia de pago en Mercado Pago
  mp_payment_id VARCHAR(100),      -- id del pago ya confirmado en Mercado Pago
  coupon_code VARCHAR(40),         -- cupón usado en este pedido, si tuvo
  discount_amount DECIMAL(10,2),   -- monto descontado por el cupón
  shipping_zone VARCHAR(100),      -- nombre de la zona de envío elegida, si tuvo
  shipping_cost DECIMAL(10,2),     -- costo de envío cobrado (0 si fue gratis)
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES customers(id),
  INDEX idx_orders_created_at (created_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: order_items (detalle de cada pedido)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,  -- copia del nombre por si el producto cambia después
  unit_price DECIMAL(10,2) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  product_color_id INT,
  color_name VARCHAR(60),               -- copia del color elegido por si se borra después
  product_size_id INT,
  size_name VARCHAR(20),                -- copia del talle elegido por si se borra después
  FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE SET NULL,
  FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: payment_settings (fila única: qué medios de pago acepta la
-- tienda, prendidos/apagados desde /admin/medios-de-pago)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_settings (
  id INT PRIMARY KEY DEFAULT 1,
  efectivo TINYINT(1) NOT NULL DEFAULT 1,
  transferencia TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_credito TINYINT(1) NOT NULL DEFAULT 1,
  tarjeta_debito TINYINT(1) NOT NULL DEFAULT 1,
  mercado_pago TINYINT(1) NOT NULL DEFAULT 1,
  tarjetas_aceptadas VARCHAR(255)   -- texto libre, ej: "Visa, Mastercard, Naranja, Cabal"
) ENGINE=InnoDB;
INSERT IGNORE INTO payment_settings (id) VALUES (1);

-- ---------------------------------------------------------
-- TABLA: product_sets (conjuntos/looks armados con productos que ya
-- existen en el catálogo). Cada producto del conjunto mantiene su propio
-- precio y stock — el conjunto es solo una forma de mostrarlos juntos y
-- agregarlos todos al carrito de una. discount_price es un precio
-- especial opcional para todo el conjunto (si se vende más barato que
-- comprando cada producto por separado).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_sets (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  description VARCHAR(255),
  image_url VARCHAR(500),        -- opcional: si no se sube, se arma un collage con las fotos de los productos
  discount_price DECIMAL(10,2),  -- precio especial opcional del conjunto entero
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_set_items (qué productos forman cada conjunto)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_set_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  set_id INT NOT NULL,
  product_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  FOREIGN KEY (set_id) REFERENCES product_sets(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  UNIQUE KEY uq_set_product (set_id, product_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: product_reviews (reseñas de clientes en cada producto). Un
-- cliente puede dejar una sola reseña por producto (si vuelve a opinar,
-- se actualiza la que ya tenía en vez de duplicarse).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  customer_id INT NOT NULL,
  rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  UNIQUE KEY uq_review_customer_product (customer_id, product_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: coupons (cupones de descuento aplicables en el checkout,
-- además del % de descuento fijo que ya puede tener cada producto)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS coupons (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(40) NOT NULL UNIQUE,
  percent_off DECIMAL(5,2) NOT NULL CHECK (percent_off > 0 AND percent_off <= 100),
  active TINYINT(1) NOT NULL DEFAULT 1,
  expires_at DATE,                        -- NULL = sin vencimiento
  usage_limit INT,                        -- NULL = sin límite de usos
  used_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: stock_notify_requests ("Avisame cuando haya stock"): el cliente
-- deja su mail en un producto/color/talle agotado, y cuando vuelve a
-- tener stock se le manda un mail automático.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_notify_requests (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(150) NOT NULL,
  product_id INT NOT NULL,
  product_color_id INT,
  product_size_id INT,
  notified TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE CASCADE,
  FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: shipping_zones (costo de envío real configurable por zona, ya
-- que no tenemos credenciales de Correo Argentino/Andreani para conectar
-- una cotización automática)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipping_zones (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,           -- ej: "CABA", "GBA", "Interior"
  price DECIMAL(10,2) NOT NULL DEFAULT 0,
  free_from DECIMAL(10,2),              -- si el pedido supera este monto, el envío de esta zona sale gratis (NULL = nunca gratis)
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: cash_registers (apertura/cierre de caja del local). Mientras
-- hay una fila con status='abierta', las ventas presenciales (pos_sales)
-- y gastos (cash_expenses) del día quedan asociados a ella. Al cerrar se
-- guarda lo que se contó en la caja y la diferencia contra lo esperado
-- (apertura + ventas en efectivo - gastos en efectivo).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS cash_registers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  opening_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  closed_at TIMESTAMP NULL,
  closing_amount DECIMAL(10,2),     -- plata contada a mano al cerrar
  expected_amount DECIMAL(10,2),    -- lo que debería haber en caja según el sistema
  difference DECIMAL(10,2),         -- closing_amount - expected_amount (positivo = sobra, negativo = falta)
  notes VARCHAR(255),
  status ENUM('abierta','cerrada') NOT NULL DEFAULT 'abierta'
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: pos_sales (ventas presenciales hechas en el local, por fuera de
-- la tienda online — las de la web siguen guardándose en `orders`).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_sales (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT NOT NULL,
  total DECIMAL(10,2) NOT NULL,
  payment_method VARCHAR(50) NOT NULL DEFAULT 'Efectivo',
  customer_name VARCHAR(150),     -- opcional: venta presencial no exige cuenta de cliente
  status ENUM('completada','cancelada') NOT NULL DEFAULT 'completada',   -- al cancelar se devuelve el stock vendido
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: pos_sale_items (detalle de cada venta presencial)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_sale_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sale_id INT NOT NULL,
  product_id INT,
  product_name VARCHAR(150) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  qty INT NOT NULL CHECK (qty > 0),
  product_color_id INT,
  color_name VARCHAR(60),
  product_size_id INT,
  size_name VARCHAR(20),
  FOREIGN KEY (sale_id) REFERENCES pos_sales(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  FOREIGN KEY (product_color_id) REFERENCES product_colors(id) ON DELETE SET NULL,
  FOREIGN KEY (product_size_id) REFERENCES product_sizes(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: cash_expenses (gastos: proveedores, servicios, sueldos, etc.)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS cash_expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cash_register_id INT,    -- NULL si el gasto no se cargó con una caja abierta puntual
  category VARCHAR(60) NOT NULL DEFAULT 'Otro',
  description VARCHAR(255),
  amount DECIMAL(10,2) NOT NULL CHECK (amount >= 0),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (cash_register_id) REFERENCES cash_registers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------
-- TABLA: subcategories (tipos de producto dentro de cada categoría, ej:
-- "Remeras"/"Pantalones" dentro de Indumentaria, "Botas"/"Sandalias"
-- dentro de Calzado, etc. Se administran desde /admin/subcategorias).
-- products.subcategory guarda el "slug" (texto sin espacios/acentos) de
-- la fila elegida acá, no el id — así que borrar una subcategoría no
-- rompe productos que ya la tenían puesta, solo deja de aparecer en el
-- selector para elegirla de nuevo.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS subcategories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category ENUM('indumentaria','calzado','accesorios') NOT NULL,
  name VARCHAR(60) NOT NULL,     -- lo que ve el cliente, ej: "Remeras"
  slug VARCHAR(60) NOT NULL,     -- lo que se guarda en products.subcategory, ej: "remeras"
  sort_order INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_subcategories_category_slug (category, slug)
) ENGINE=InnoDB;

-- Subcategorías de Indumentaria con las que ya viene armada la tienda
-- (se pueden editar, pausar o borrar desde el panel una vez cargada la web).
INSERT IGNORE INTO subcategories (category, name, slug, sort_order) VALUES
('indumentaria', 'Remeras', 'remeras', 1),
('indumentaria', 'Pantalones', 'pantalones', 2),
('indumentaria', 'Buzos y hoodies', 'buzos', 3),
('indumentaria', 'Camperas', 'camperas', 4),
('indumentaria', 'Vestidos', 'vestidos', 5),
('indumentaria', 'Polleras', 'polleras', 6),
('indumentaria', 'Shorts', 'shorts', 7),
('indumentaria', 'Otros', 'otros', 8);

-- ---------------------------------------------------------
-- PRODUCTOS DE EJEMPLO (los podés editar/borrar desde Workbench o
-- después desde el panel admin de la web)
-- ---------------------------------------------------------
INSERT INTO products (name, category, price, stock, image_url, description) VALUES
('Vestido Florencia', 'indumentaria', 24999, 12, 'https://placehold.co/400x500/ecdfd0/634b3d?text=Vestido', 'Vestido liviano ideal para el dia a dia'),
('Remera oversize', 'indumentaria', 11999, 20, 'https://placehold.co/400x500/ecdfd0/634b3d?text=Remera', 'Remera de algodon corte oversize'),
('Pantalon palazzo', 'indumentaria', 19999, 15, 'https://placehold.co/400x500/ecdfd0/634b3d?text=Pantalon', 'Pantalon fluido tiro alto'),
('Campera de jean', 'indumentaria', 28999, 8, 'https://placehold.co/400x500/ecdfd0/634b3d?text=Campera', 'Campera de jean clasica'),
('Zapatillas urbanas', 'calzado', 32999, 10, 'https://placehold.co/400x500/e4d6c4/634b3d?text=Zapatillas', 'Zapatillas comodas para el dia a dia'),
('Sandalias de taco', 'calzado', 21999, 14, 'https://placehold.co/400x500/e4d6c4/634b3d?text=Sandalias', 'Sandalias elegantes de taco medio'),
('Botas cortas', 'calzado', 36999, 6, 'https://placehold.co/400x500/e4d6c4/634b3d?text=Botas', 'Botas cortas de cuero eco'),
('Zapatos chatitas', 'calzado', 18999, 18, 'https://placehold.co/400x500/e4d6c4/634b3d?text=Chatitas', 'Chatitas comodas para todo el dia'),
('Cartera de cuero eco', 'accesorios', 22999, 9, 'https://placehold.co/400x500/e8d5c4/634b3d?text=Cartera', 'Cartera amplia de cuero ecologico'),
('Cinturon trenzado', 'accesorios', 8999, 25, 'https://placehold.co/400x500/e8d5c4/634b3d?text=Cinturon', 'Cinturon trenzado unisex'),
('Collar bijou', 'accesorios', 6999, 30, 'https://placehold.co/400x500/e8d5c4/634b3d?text=Collar', 'Collar bijou dorado'),
('Anteojos de sol', 'accesorios', 14999, 16, 'https://placehold.co/400x500/e8d5c4/634b3d?text=Anteojos', 'Anteojos de sol con proteccion UV');
