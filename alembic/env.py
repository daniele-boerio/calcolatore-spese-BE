import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Importa Base e modelli per permettere ad Alembic di vedere le tabelle
from database import Base
import models  # Importante per caricare tutti i modelli
from dotenv import load_dotenv

# Carica le variabili dal file .env
load_dotenv()

# Questo è l'oggetto Config di Alembic, che ha accesso ai valori nel file .ini in uso.
config = context.config

# Interpreta il file di configurazione per il logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Impostiamo i metadati dei modelli per l'autogenerazione delle migrazioni
target_metadata = Base.metadata

def get_url():
    """Compone l'URL del database usando le variabili d'ambiente."""
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    database = os.getenv("DB_NAME")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"

def run_migrations_offline() -> None:
    """Esegue le migrazioni in modalità 'offline'."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Esegue le migrazioni in modalità 'online'."""
    
    # Sovrascriviamo la configurazione dell'URL nel file .ini con quella del .env
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()