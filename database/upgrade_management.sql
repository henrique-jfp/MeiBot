-- Upgrade for Management Features

-- Table: entregadores
CREATE TABLE entregadores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    valor_diaria FLOAT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Update Table: apps
ALTER TABLE apps ADD COLUMN valor_base FLOAT DEFAULT 0;
ALTER TABLE apps ADD COLUMN tipo_remuneracao TEXT; -- 'pacote' or 'rota'
ALTER TABLE apps ADD COLUMN entregador_padrao_id UUID REFERENCES entregadores(id);

-- Update Table: eventos
ALTER TABLE eventos ADD COLUMN hora_inicio TIMESTAMP WITH TIME ZONE;
ALTER TABLE eventos ADD COLUMN hora_fim TIMESTAMP WITH TIME ZONE;
ALTER TABLE eventos ADD COLUMN sub_tipo TEXT; -- 'espera_galpao', 'rota', 'deslocamento'

-- Update initial apps data
UPDATE apps SET valor_base = 2.0, tipo_remuneracao = 'pacote' WHERE nome = 'Correios';
UPDATE apps SET valor_base = 320.0, tipo_remuneracao = 'rota' WHERE nome = 'Shopee';
