"""Per-command submodules for the Unlimited Skills CLI.

Each module holds the cmd_* implementations for one command family and
resolves shared helpers late through the ``unlimited_skills.cli`` module
object so monkeypatching ``cli.<helper>`` keeps working.
"""
