-- Carga las categorías y subcategorías nuevas que pasó tu amigo.
-- Es seguro correrlo: usa INSERT IGNORE, así que si una categoría o
-- subcategoría ya existe (por nombre/slug) no la duplica ni toca nada
-- de lo que ya tenés cargado (productos, fotos, etc.). Las categorías
-- viejas que ya no quieran usar las pueden desactivar o borrar
-- después, a mano, desde Admin → Categorías (una vez que hayan movido
-- los productos que tengan asignados a las categorías nuevas).

-- Importante: esta línea asegura que los acentos y la "ñ" se guarden
-- bien sin importar cómo esté configurado el cliente de MySQL con el
-- que lo corras.
SET NAMES utf8mb4;

-- Creatinas
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Creatinas','creatinas', 1000, 1);
SET @cat_creatinas = (SELECT id FROM categories WHERE slug='creatinas');
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order, active) VALUES
  (@cat_creatinas, 'Saborizada', 'saborizada', 0, 1),
  (@cat_creatinas, 'Gomitas', 'gomitas', 1, 1);

-- Proteínas
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Proteínas','proteinas', 1001, 1);
SET @cat_proteinas = (SELECT id FROM categories WHERE slug='proteinas');
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order, active) VALUES
  (@cat_proteinas, 'Suero de leche', 'suero-de-leche', 0, 1),
  (@cat_proteinas, 'Vegetal', 'vegetal', 1, 1);

-- Aminoácidos
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Aminoácidos','aminoacidos', 1002, 1);
SET @cat_aminoacidos = (SELECT id FROM categories WHERE slug='aminoacidos');
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order, active) VALUES
  (@cat_aminoacidos, 'Zma', 'zma', 0, 1),
  (@cat_aminoacidos, 'Bcaas', 'bcaas', 1, 1),
  (@cat_aminoacidos, 'Beta alanina', 'beta-alanina', 2, 1),
  (@cat_aminoacidos, 'Arginina', 'arginina', 3, 1),
  (@cat_aminoacidos, 'Glutamina', 'glutamina', 4, 1);

-- Pre entreno (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Pre entreno','pre-entreno', 1003, 1);

-- Multivitamínico (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Multivitamínico','multivitaminico', 1004, 1);

-- Magnesio (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Magnesio','magnesio', 1005, 1);

-- Omega 3 (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Omega 3','omega-3', 1006, 1);

-- Colágenos (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Colágenos','colagenos', 1007, 1);

-- Resveratrol (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Resveratrol','resveratrol', 1008, 1);

-- Comestibles
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Comestibles','comestibles', 1009, 1);
SET @cat_comestibles = (SELECT id FROM categories WHERE slug='comestibles');
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order, active) VALUES
  (@cat_comestibles, 'Pancakes', 'pancakes', 0, 1),
  (@cat_comestibles, 'Pastas de maní', 'pastas-de-mani', 1, 1),
  (@cat_comestibles, 'Barras proteicas', 'barras-proteicas', 2, 1);

-- Bebidas isotónicas
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Bebidas isotónicas','bebidas-isotonicas', 1010, 1);
SET @cat_isotonicas = (SELECT id FROM categories WHERE slug='bebidas-isotonicas');
INSERT IGNORE INTO subcategories (category_id, name, slug, sort_order, active) VALUES
  (@cat_isotonicas, 'Pastillas de sal', 'pastillas-de-sal', 0, 1),
  (@cat_isotonicas, 'Geles energéticos', 'geles-energeticos', 1, 1),
  (@cat_isotonicas, 'Con cafeína', 'con-cafeina', 2, 1),
  (@cat_isotonicas, 'Sin cafeína', 'sin-cafeina', 3, 1);

-- Ganadores de peso (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Ganadores de peso','ganadores-de-peso', 1011, 1);

-- Quemadores (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Quemadores','quemadores', 1012, 1);

-- Shakers (sin subcategorías)
INSERT IGNORE INTO categories (name, slug, sort_order, active) VALUES ('Shakers','shakers', 1013, 1);
