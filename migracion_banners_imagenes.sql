-- Carga las 5 imágenes de banners motivacionales para "Comprá por objetivo"
-- (sección goal_banners). Pega esto en tu base de datos después de correr
-- migracion_banners.sql (que crea la tabla). Podés correr esto de nuevo sin
-- problema: primero borra estos 5 títulos si ya existían y los vuelve a cargar.
SET NAMES utf8mb4;

DELETE FROM goal_banners WHERE title IN (
  'Ganar masa muscular',
  'Mejorar rendimiento',
  'Bajar grasa corporal',
  'Energía y foco',
  'Recuperación y bienestar'
);

INSERT INTO goal_banners (image_url, title, button_link, sort_order, active) VALUES
('/static/img/banners/banner-ganar-masa-muscular.jpg', 'Ganar masa muscular', '/?tag=proteinas#catalogo', 1, 1),
('/static/img/banners/banner-mejorar-rendimiento.jpg', 'Mejorar rendimiento', '/?tag=pre-entreno#catalogo', 2, 1),
('/static/img/banners/banner-bajar-grasa-corporal.jpg', 'Bajar grasa corporal', '/?tag=quemadores#catalogo', 3, 1),
('/static/img/banners/banner-energia-y-foco.jpg', 'Energía y foco', '/?tag=aminoacidos#catalogo', 4, 1),
('/static/img/banners/banner-recuperacion-bienestar.jpg', 'Recuperación y bienestar', '/?tag=vitaminas-minerales#catalogo', 5, 1);

-- Los "tag" de arriba apuntan a categorías que ya tenés cargadas (proteinas,
-- pre-entreno, quemadores, aminoacidos, vitaminas-minerales). Si en tu base
-- esas categorías tienen otro slug, entrá a /admin/banners y cambiá el link
-- de cada banner desde ahí (es la misma pantalla del carrusel de portada).
