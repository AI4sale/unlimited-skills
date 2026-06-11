"""Compatibility entrypoint for the E10 profile-enforcement acceptance command.

The implementation-focused tests live in ``test_mcp_tool_profile_enforcement``,
while the release task contract names this shorter file. Importing the tests
keeps both paths reproducible without weakening coverage.
"""

from test_mcp_tool_profile_enforcement import *  # noqa: F401,F403
