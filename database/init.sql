-- SQL Initialization for Supabase (PostgreSQL)

-- Table: users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    whatsapp_number TEXT UNIQUE NOT NULL,
    nome TEXT,
    carro_km_inicial FLOAT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table: apps (Delivery Platforms)
CREATE TABLE apps (
    id SERIAL PRIMARY KEY,
    nome TEXT UNIQUE NOT NULL
);

-- Insert common apps
INSERT INTO apps (nome) VALUES ('iFood'), ('Uber Eats'), ('Rappi'), ('Loggi'), ('Lalamove'), ('Correios'), ('Mercado Livre'), ('Particular');

-- Table: operacoes_dia (Daily Sessions)
CREATE TABLE operacoes_dia (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    data DATE DEFAULT CURRENT_DATE,
    hora_inicio TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    hora_fim TIMESTAMP WITH TIME ZONE,
    status TEXT DEFAULT 'ativa', -- 'ativa' or 'encerrada'
    km_inicial FLOAT,
    km_final FLOAT
);

-- Table: eventos (Events during operation)
CREATE TABLE eventos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    operacao_id UUID REFERENCES operacoes_dia(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL, -- 'corrida', 'gasto', 'pausa', 'ajuste', 'pacotes'
    valor FLOAT DEFAULT 0,
    km FLOAT DEFAULT 0,
    app_id INTEGER REFERENCES apps(id),
    pacotes INTEGER DEFAULT 0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    descricao TEXT
);

-- Enable RLS (Row Level Security) - Optional but recommended for production
-- For a personal bot, we can keep it simple or configure as needed.
