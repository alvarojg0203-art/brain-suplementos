-- Migración: subcategorías dentro de Indumentaria (remeras, pantalones,
-- buzos, camperas, vestidos, polleras, shorts, otros), para que el
-- cliente pueda filtrar por tipo de prenda puntual en vez de ver toda
-- la indumentaria junta.
-- Corré esto una sola vez en MySQL Workbench, sobre la base caro_boutique.

USE caro_boutique;

ALTER TABLE products
  ADD COLUMN subcategory VARCHAR(50) NULL AFTER category;
