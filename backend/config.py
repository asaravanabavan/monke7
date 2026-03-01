"""
NemoCraft application settings, loaded from environment variables and .env file.

All environment variables are prefixed with ``NEMO_`` (e.g. ``NEMO_NIM_API_KEY``).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for the NemoCraft backend."""

    # NVIDIA NIM / LLM
    nim_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_model: str = "nvidia/llama-3.1-nemotron-70b-instruct"

    # Minecraft RCON
    rcon_host: str = "localhost"
    rcon_port: int = 25575
    rcon_password: str = "nemocraft"

    # Backend server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Build behaviour
    build_delay: float = 0.3
    max_rooms: int = 5

    # Auto-generation
    check_interval_minutes: int = 15
    auto_generate_threshold: float = 0.3
    auto_generate_cooldown_minutes: int = 30

    # Karma system
    karma_enable: bool = True
    karma_decay_rate: float = 0.01          # λ per hour (~69h half-life)
    karma_violence_weight: float = 0.3      # composite weight
    karma_nature_weight: float = 0.3        # composite weight
    karma_social_weight: float = 0.4        # composite weight (heaviest)

    # Villain chatbot (all default OFF)
    villain_enabled: bool = False
    villain_name: str = "Lord Netherbane"
    villain_react_probability: float = 0.3
    villain_max_history: int = 20
    villain_cooldown_seconds: int = 5

    model_config = {"env_prefix": "NEMO_", "env_file": ".env"}


settings = Settings()
