class BotError(RuntimeError):
    """Base application error."""


class ConfigError(BotError):
    """Raised when the bot configuration is invalid."""


class StateError(BotError):
    """Raised when persisted state cannot be loaded or validated."""
